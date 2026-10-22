from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from dateutil import parser as dtparser

from agent.models import AgentLogEvent, AgentRun


_ACCEPT = {"accept", "accepted", "include", "relevant", "yes", "allow"}
_REJECT = {"reject", "rejected", "exclude", "irrelevant", "no", "drop"}


def _mentions(text: str, term: str) -> bool:
    # Whole words (plus plural), so "pet" doesn't hit "competition" or "fed" "offered".
    return re.search(rf"\b{re.escape(term)}(?:s|es)?\b", text) is not None


class ScoringMixin:
    """Heuristic + LLM-assisted relevance/importance scoring used to decide what gets written up."""

    def _llm_filter_available(self, run: Optional[AgentRun]) -> bool:
        if run is None or not bool(getattr(run, "use_llm_filtering", False)):
            return False
        if not self.llm.enabled:
            return False
        if not (self.config.filter_prompt_template or "").strip():
            return False
        return self._llm_budget_remaining() > self.llm_reserved_for_articles

    def _llm_filter_batch(self, run: Optional[AgentRun], candidates: list[dict]) -> dict[int, bool]:
        """Accept/reject by LLM, many items per request; index -> accepted.

        Items left without a decision (cap reached, budget spent, bad output)
        fall back to the heuristic score at the call site.
        """
        decisions: dict[int, bool] = {}
        if not candidates or not self._llm_filter_available(run):
            return decisions
        template = (self.config.filter_prompt_template or "").strip()
        size = self._LLM_FILTER_BATCH_SIZE
        for calls, offset in enumerate(range(0, len(candidates), size)):
            if calls >= self._LLM_FILTER_MAX_CALLS_PER_RUN:
                break
            chunk = candidates[offset : offset + size]
            block = "\n".join(
                f"[{i}] ({c['source_name']}) {self._compact_text(c['title'], 220)}\n"
                f"    {self._compact_text(c['summary'] or c['cleaned'], 320)}"
                for i, c in enumerate(chunk, 1)
            )
            # A custom template without {items} still gets the list appended.
            prompt = template.replace("{items}", block) if "{items}" in template else f"{template}\n\nItems:\n{block}"
            output = self._budgeted_generate_json(
                prompt, run=run, purpose="filter_batch", reserve=self.llm_reserved_for_articles
            )
            if not isinstance(output, dict):
                break  # budget spent or the LLM is failing: the rest uses the heuristic
            rejected = []
            for row in output.get("decisions") or []:
                if not isinstance(row, dict):
                    continue
                try:
                    index = int(row.get("id")) - 1
                except (TypeError, ValueError):
                    continue
                decision = str(row.get("decision") or "").strip().lower()
                if not 0 <= index < len(chunk) or decision not in _ACCEPT | _REJECT:
                    continue
                decisions[offset + index] = decision in _ACCEPT
                if decision in _REJECT:
                    rejected.append(chunk[index]["title"][:160])
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_NEXT_STEP,
                message="llm_filter_batch_completed",
                metadata={
                    "items": len(chunk),
                    "decided": sum(1 for i in range(offset, offset + len(chunk)) if i in decisions),
                    "rejected": rejected,
                },
            )
        return decisions

    @staticmethod
    def _normalize_importance_score(value: object) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip().lower()
            if not text:
                return None
            alias_map = {
                "low": 1,
                "minor": 1,
                "localized": 1,
                "medium": 2,
                "moderate": 2,
                "regional": 2,
                "high": 3,
                "severe": 3,
                "global": 3,
                "systemic": 3,
            }
            if text in alias_map:
                return alias_map[text]
            try:
                value = int(float(text))
            except (TypeError, ValueError):
                return None

        if isinstance(value, (int, float)):
            score = int(round(float(value)))
            return max(1, min(3, score))
        return None

    def _infer_importance_from_records(
        self,
        records: list[dict],
        *,
        title: str,
        summary: str,
        body: str,
    ) -> tuple[int, str]:
        combined = " ".join(
            [
                title or "",
                summary or "",
                body or "",
                *[
                    f"{item.get('title') or ''} {item.get('summary') or ''} {item.get('content') or ''}"
                    for item in (records or [])
                ],
            ]
        ).lower()

        high_impact_tokens = [
            "central bank",
            "interest rate",
            "rate hike",
            "rate cut",
            "inflation",
            "cpi",
            "gdp",
            "recession",
            "banking crisis",
            "default",
            "sanction",
            "tariff",
            "war",
            "oil shock",
            "energy disruption",
            "sovereign debt",
        ]
        medium_impact_tokens = [
            "earnings",
            "guidance",
            "merger",
            "acquisition",
            "treasury",
            "yield",
            "credit spread",
            "commodity",
            "supply chain",
            "regulation",
            "antitrust",
            "pmi",
            "jobs report",
            "unemployment",
            "housing",
        ]

        if any(_mentions(combined, token) for token in high_impact_tokens):
            score = 3
        elif any(_mentions(combined, token) for token in medium_impact_tokens):
            score = 2
        else:
            score = 1

        if len(records or []) >= 10 and score < 3:
            score += 1

        channels = []
        if any(_mentions(combined, token) for token in ["rate", "yield", "bond", "treasury", "inflation", "central bank"]):
            channels.append("rates and monetary policy")
        if any(_mentions(combined, token) for token in ["currency", "forex", "fx", "dollar", "euro", "yen"]):
            channels.append("FX positioning")
        if any(_mentions(combined, token) for token in ["oil", "gas", "commodity", "energy", "metal"]):
            channels.append("commodity pricing")
        if any(_mentions(combined, token) for token in ["equity", "stock", "earnings", "valuation", "sector"]):
            channels.append("equity risk appetite")
        if any(_mentions(combined, token) for token in ["credit", "default", "spread", "bank"]):
            channels.append("credit conditions")
        if not channels:
            channels.append("broad macro sentiment")

        scope = {1: "localized", 2: "regional or sector-wide", 3: "global cross-asset"}[score]
        reason = f"{scope.capitalize()} market impact expected via {channels[0]}."
        if score >= 2 and len(channels) > 1:
            reason = f"{scope.capitalize()} market impact expected via {channels[0]} and {channels[1]}."
        return score, self._compact_text(reason, 280)

    @staticmethod
    def _parse_datetime(value: object) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = dtparser.parse(str(value))
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @classmethod
    def _relevance_score(cls, text: str, title: str = "") -> int:
        combined = (text + " " + title).lower()

        financial_keywords = [
            "fed",
            "federal reserve",
            "central bank",
            "ecb",
            "bank of england",
            "pboc",
            "boj",
            "interest rate",
            "rate hike",
            "rate cut",
            "monetary policy",
            "qe",
            "quantitative easing",
            "inflation",
            "cpi",
            "ppi",
            "gdp",
            "recession",
            "unemployment",
            "jobs report",
            "stock market",
            "equity",
            "nasdaq",
            "s&p",
            "dow jones",
            "bond",
            "yield",
            "treasury",
            "dollar",
            "euro",
            "currency",
            "forex",
            "fx",
            "commodity",
            "oil",
            "gas",
            "gold",
            "earnings",
            "revenue",
            "profit",
            "eps",
            "guidance",
            "m&a",
            "merger",
            "acquisition",
            "ipo",
            "bankruptcy",
            "default",
            "tariff",
            "trade",
            "supply chain",
            "logistics",
            "regulation",
            "sec",
            "antitrust",
            "credit rating",
            "moody",
            "fitch",
            "sanction",
            "geopolitical",
            "energy",
            "oil price",
            "natural gas",
            "commodity shock",
            "yield curve",
            "credit spread",
            "mortgage",
            "housing",
            "pmi",
            "manufacturing",
            "volatility",
            "vix",
            "liquidity",
            "leverage",
            "derivative",
            "hedge",
            "bank",
        ]

        reject_keywords = [
            "celebrity",
            "actor",
            "actress",
            "sports",
            "football",
            "basketball",
            "soccer",
            "award",
            "oscar",
            "emmy",
            "grammy",
            "concert",
            "album",
            "band",
            "wedding",
            "divorce",
            "relationship",
            "celebrity gossip",
            "influencer",
            "tiktok",
            "instagram",
            "movie",
            "film",
            "netflix",
            "fashion",
            "beauty",
            "restaurant",
            "travel",
            "vacation",
            "hotel",
            "resort",
            "pet",
            "dog",
            "cat",
            "game",
            "esports",
        ]

        score = 0

        for kw in financial_keywords:
            if _mentions(combined, kw):
                score += 2

        title_lower = (title or "").lower()
        for high in ["central bank", "fed", "interest rate", "inflation", "gdp", "default", "bankruptcy", "sanction"]:
            if _mentions(title_lower, high):
                score += 4

        for kw in reject_keywords:
            if _mentions(combined, kw):
                score -= 3

        relevant_sentences = cls._extract_relevant_sentences(text)
        if relevant_sentences:
            score += 3

        if len(combined) < 200 and score > 0:
            score += 1

        return score

    @staticmethod
    def _extract_relevant_sentences(text: str) -> str:
        if not text:
            return ""
        sentences = re.split(r"(?<=[\.\?!])\s+", text)
        financial_terms = [
            "fed",
            "central bank",
            "interest rate",
            "inflation",
            "gdp",
            "unemployment",
            "earnings",
            "revenue",
            "m&a",
            "merger",
            "acquisition",
            "ipo",
            "bankruptcy",
            "bond",
            "yield",
            "treasury",
            "currency",
            "forex",
            "oil",
            "gas",
            "commodity",
            "tariff",
            "trade",
            "sanction",
            "credit",
            "rating",
            "regulation",
            "sec",
        ]
        picks = []
        for sentence in sentences:
            low = sentence.lower()
            if any(_mentions(low, term) for term in financial_terms):
                picks.append(sentence.strip())
        return " ".join(picks).strip()
