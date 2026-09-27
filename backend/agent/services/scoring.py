from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from dateutil import parser as dtparser

from agent.models import AgentLogEvent, AgentRun


class ScoringMixin:
    """Heuristic + LLM-assisted relevance/importance scoring used to decide what gets written up."""

    def _should_apply_llm_filter(self, run: Optional[AgentRun], heuristic_score: int) -> bool:
        if run is None or not bool(getattr(run, "use_llm_filtering", False)):
            return False
        if not self.llm.enabled:
            return False
        if not (self.config.filter_prompt_template or "").strip():
            return False
        if self._llm_budget_remaining() <= self.llm_reserved_for_articles:
            return False
        return heuristic_score >= (self._MIN_RELEVANCE_SCORE - self._LLM_FILTER_SCORE_BUFFER)

    def _llm_filter_decision(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        heuristic_score: int,
        run: Optional[AgentRun],
        source_name: str,
        source_url: str,
        item_url: str,
    ) -> Optional[dict]:
        template = (self.config.filter_prompt_template or "").strip()
        if not template:
            return None

        prompt = (
            template.replace("{title}", self._compact_text(title, 260))
            .replace("{summary}", self._compact_text(summary, 380))
            .replace("{content}", self._compact_text(content, self._LLM_FILTER_CONTEXT_CHARS))
            .replace("{heuristic_score}", str(int(heuristic_score)))
        )
        output = self._budgeted_generate_json(
            prompt,
            run=run,
            purpose="filter_decision",
            reserve=self.llm_reserved_for_articles,
        )
        if not isinstance(output, dict):
            return None

        decision = str(output.get("decision") or "").strip().lower()
        accepted_values = {"accept", "accepted", "include", "relevant", "yes", "allow"}
        rejected_values = {"reject", "rejected", "exclude", "irrelevant", "no", "drop"}
        if decision in accepted_values:
            accepted = True
        elif decision in rejected_values:
            accepted = False
        else:
            return None

        importance_score = self._normalize_importance_score(output.get("importance_score")) or 1
        reason = self._compact_text(str(output.get("reason") or ""), 220)
        confidence_raw = output.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        if not accepted:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_NEXT_STEP,
                message="llm_filter_rejected_item",
                metadata={
                    "source": source_name,
                    "source_url": source_url,
                    "url": item_url,
                    "heuristic_score": heuristic_score,
                    "importance_score": importance_score,
                    "confidence": confidence,
                    "reason": reason,
                },
            )

        return {
            "accepted": accepted,
            "importance_score": importance_score,
            "confidence": confidence,
            "reason": reason,
        }

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

        if any(token in combined for token in high_impact_tokens):
            score = 3
        elif any(token in combined for token in medium_impact_tokens):
            score = 2
        else:
            score = 1

        if len(records or []) >= 10 and score < 3:
            score += 1

        channels = []
        if any(token in combined for token in ["rate", "yield", "bond", "treasury", "inflation", "central bank"]):
            channels.append("rates and monetary policy")
        if any(token in combined for token in ["currency", "forex", "fx", "dollar", "euro", "yen"]):
            channels.append("FX positioning")
        if any(token in combined for token in ["oil", "gas", "commodity", "energy", "metal"]):
            channels.append("commodity pricing")
        if any(token in combined for token in ["equity", "stock", "earnings", "valuation", "sector"]):
            channels.append("equity risk appetite")
        if any(token in combined for token in ["credit", "default", "spread", "bank"]):
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
            if kw in combined:
                score += 2

        title_lower = (title or "").lower()
        for high in ["central bank", "fed", "interest rate", "inflation", "gdp", "default", "bankruptcy", "sanction"]:
            if high in title_lower:
                score += 4

        for kw in reject_keywords:
            if kw in combined:
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
            if any(term in low for term in financial_terms):
                picks.append(sentence.strip())
        return " ".join(picks).strip()
