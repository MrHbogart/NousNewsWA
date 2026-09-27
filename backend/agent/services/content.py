from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from bs4 import BeautifulSoup
from django.utils.text import slugify

from agent.economist_agent import EconomistAgent
from agent.models import AgentLogEvent, AgentRun
from articles.models import Card, CardArticle
from articles.services import aggregate_candles, resolve_timeframe
from articles.slugging import build_article_slug


class ContentMixin:
    """LLM article/brief composition: prompt building, payload assembly, and text cleanup."""

    def _build_main_payload(
        self,
        *,
        records: list[dict],
        timeframe: str,
        period_start: datetime,
        period_end: datetime,
        run: Optional[AgentRun],
    ) -> dict:
        fallback = self._compose_fallback_payload(records, timeframe, period_start, period_end)
        context = self._build_context_from_records(records, timeframe=timeframe)

        generated_title = ""
        generated_summary = ""
        generated_body = ""
        generated_impacts = []
        generated_references: list[str] = []
        generated_importance_score: Optional[int] = None
        generated_importance_reason = ""

        if self.config.use_llm_summaries and self.llm.enabled and context:
            prompt = self._build_article_prompt(context, timeframe, period_start, period_end)
            result = None
            if self._consume_llm_budget(run=run, purpose="article_generation", reserve=0):
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_LLM_PROMPT,
                    message="article_prompt_prepared",
                    content=prompt,
                    metadata={
                        "timeframe": timeframe,
                        "period_start": period_start,
                        "period_end": period_end,
                        "records": len(records),
                        "prompt_chars": len(prompt),
                    },
                )

                result = self.llm.generate_article(prompt)
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_LLM_OUTPUT,
                    message="article_prompt_completed",
                    content=self.llm.last_output_text or "",
                    metadata={
                        "status_code": self.llm.last_status_code,
                        "error": self.llm.last_error,
                        "model": self.llm.last_model,
                        "output_chars": len(self.llm.last_output_text or ""),
                        "parsed": bool(result),
                    },
                )
            else:
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_NEXT_STEP,
                    level=AgentLogEvent.LEVEL_WARN,
                    message="article_prompt_skipped_budget",
                    metadata={
                        "timeframe": timeframe,
                        "period_start": period_start,
                        "period_end": period_end,
                        "records": len(records),
                        "llm_requests_used": self.llm_requests_used,
                        "llm_request_budget": self.llm_request_budget,
                    },
                )

            if result:
                generated_title = result.title or ""
                generated_summary = result.summary or ""
                generated_body = result.article_text or ""
                generated_impacts = result.impacts or []
                generated_references = self._normalize_references(result.references)
                generated_importance_score = self._normalize_importance_score(result.importance_score)
                generated_importance_reason = (result.importance_reason or "").strip()

            economist_output = None
            if self.economist_agent_enabled and self._llm_budget_remaining() > 0:
                economist_output = EconomistAgent(
                    self.llm,
                    generate_json_fn=lambda p: self._budgeted_generate_json(
                        p,
                        run=run,
                        purpose="economist_rewrite",
                    ),
                ).run(context)
            writing = (economist_output or {}).get("writing") if economist_output else None
            trace = (economist_output or {}).get("trace") if economist_output else None
            if trace:
                if trace.get("signals_prompt"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_PROMPT,
                        message="economist_signals_prompt_prepared",
                        content=trace.get("signals_prompt") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
                if trace.get("signals_output"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_OUTPUT,
                        message="economist_signals_prompt_completed",
                        content=trace.get("signals_output") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
                if trace.get("writing_prompt"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_PROMPT,
                        message="economist_writing_prompt_prepared",
                        content=trace.get("writing_prompt") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
                if trace.get("writing_output"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_OUTPUT,
                        message="economist_writing_prompt_completed",
                        content=trace.get("writing_output") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
            if writing:
                generated_title = writing.get("article_title") or generated_title
                generated_summary = writing.get("summary") or generated_summary
                generated_body = writing.get("article_text") or generated_body
                generated_references = self._normalize_references(writing.get("references") or generated_references)
                generated_importance_score = (
                    self._normalize_importance_score(writing.get("importance_score"))
                    or generated_importance_score
                )
                generated_importance_reason = (
                    (writing.get("importance_reason") or "").strip()
                    or generated_importance_reason
                )

        clean_generated_title = self._sanitize_generated_text(generated_title, keep_paragraphs=False)
        clean_generated_summary = self._sanitize_generated_text(generated_summary, keep_paragraphs=False)
        clean_generated_body = self._sanitize_generated_text(generated_body, keep_paragraphs=True)

        title = self._ensure_informative_title(clean_generated_title, records, timeframe, period_start)
        if self._is_generic_title(title):
            title = fallback["title"]

        summary = self._strip_time_window_phrasing(clean_generated_summary) or fallback["summary"]
        if len(summary) > 600:
            summary = summary[:597].rstrip() + "..."

        cleaned_generated_body = self._strip_time_window_phrasing(clean_generated_body)
        body = self._ensure_complete_article(cleaned_generated_body, fallback["body"])
        impacts = generated_impacts if isinstance(generated_impacts, list) and generated_impacts else fallback["impacts"]
        references = self._normalize_references(generated_references or fallback["references"])
        importance_score = generated_importance_score or fallback["importance_score"]
        importance_reason = self._compact_text(generated_importance_reason, 280) or fallback["importance_reason"]

        slug = build_article_slug(
            title=title,
            period_start=period_start,
            article_uuid=uuid4(),
            kind=CardArticle.KIND_MAIN,
        )

        return {
            "title": title,
            "summary": summary,
            "body": body,
            "references": references,
            "impacts": impacts,
            "importance_score": importance_score,
            "importance_reason": importance_reason,
            "slug": slug,
        }

    def _compose_fallback_payload(
        self,
        records: list[dict],
        timeframe: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        ranked = sorted(
            records,
            key=lambda item: item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        title = self._ensure_informative_title("", ranked, timeframe, period_start)
        intro = (
            f"{len(ranked)} financially relevant developments were identified across tracked market sources, "
            "with clear implications for cross-asset positioning."
        )

        detail_sentences = []
        for item in ranked[:4]:
            headline = self._compact_text(item.get("title") or item.get("summary") or item.get("content") or "", 180)
            if not headline:
                continue
            source_name = item.get("source_name") or "newswire"
            detail_sentences.append(
                f"{source_name} reported {headline}. {self._impact_sentence(item)}"
            )

        if not detail_sentences:
            detail_sentences.append(
                "No lower-impact or off-topic items were included; this brief is restricted to market-moving records only."
            )

        closing = (
            "Taken together, these signals can influence rate expectations, risk appetite, "
            "currency positioning, and sector-level equity rotation in the next trading sessions."
        )

        body = "\n\n".join([intro] + detail_sentences + [closing])
        summary = " ".join([intro] + detail_sentences[:2])
        summary = self._compact_text(summary, 600)

        impacts = self._derive_impacts(ranked)
        references = self._normalize_references([item.get("url") for item in ranked if item.get("url")])
        importance_score, importance_reason = self._infer_importance_from_records(
            ranked,
            title=title,
            summary=summary,
            body=body,
        )

        return {
            "title": title,
            "summary": summary,
            "body": body,
            "impacts": impacts,
            "references": references,
            "importance_score": importance_score,
            "importance_reason": importance_reason,
        }

    def _impact_sentence(self, record: dict) -> str:
        text = (record.get("title") or "") + " " + (record.get("summary") or "") + " " + (record.get("content") or "")
        low = text.lower()
        if any(token in low for token in ["interest rate", "fed", "ecb", "inflation", "cpi", "ppi", "gdp"]):
            return "This type of catalyst typically reprices rates markets and policy-sensitive FX pairs."
        if any(token in low for token in ["earnings", "guidance", "revenue", "profit", "m&a", "merger", "acquisition"]):
            return "This development is likely to affect equity valuation multiples and sector positioning."
        if any(token in low for token in ["oil", "gas", "commodity", "energy", "supply chain", "tariff", "sanction"]):
            return "Commodity-linked inflation expectations and regional risk premia could adjust quickly."
        if any(token in low for token in ["bond", "yield", "treasury", "credit", "default", "rating"]):
            return "Credit spreads and sovereign yield curves may react as investors reprice risk."
        return "Cross-asset positioning may adjust as participants incorporate the new information into risk scenarios."

    def _derive_impacts(self, records: list[dict]) -> list[str]:
        low = " ".join(
            [
                (item.get("title") or "") + " " + (item.get("summary") or "") + " " + (item.get("content") or "")
                for item in records
            ]
        ).lower()

        impacts = []
        if any(token in low for token in ["interest rate", "fed", "ecb", "inflation", "cpi", "ppi", "gdp"]):
            impacts.append("Rates and FX: policy expectations can reprice sovereign yields and major currency pairs.")
        if any(token in low for token in ["earnings", "guidance", "revenue", "profit", "m&a", "merger", "acquisition"]):
            impacts.append("Equities: sector rotation risk rises as earnings and corporate actions reshape valuation assumptions.")
        if any(token in low for token in ["oil", "gas", "commodity", "energy", "supply chain", "tariff", "sanction"]):
            impacts.append("Commodities: supply and geopolitics can amplify volatility in energy and input-sensitive sectors.")
        if any(token in low for token in ["bond", "yield", "treasury", "credit", "default", "rating"]):
            impacts.append("Credit: spread widening risk can pressure leveraged balance sheets and higher-beta assets.")
        if not impacts:
            impacts.append("Risk sentiment: cross-asset positioning may shift as new macro information is priced in.")
        return impacts[:6]

    def _build_context_from_records(self, records: list[dict], *, timeframe: str) -> str:
        chunks = []
        for item in records:
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()
            content = (item.get("cleaned_text") or item.get("content") or "").strip()
            source = (item.get("source_name") or "unknown").strip()
            url = (item.get("url") or "").strip()
            piece = f"({source}) {title}\nSummary: {summary}\nDetails: {content}\nURL: {url}"
            chunks.append(piece)
        combined = "\n\n".join(chunks)
        if timeframe in (Card.TIMEFRAME_HOUR, Card.TIMEFRAME_DAY):
            return combined
        max_chars = int(self.config.max_context_chars or 0)
        if max_chars > 0:
            combined = combined[:max_chars]
        return combined

    def _build_side_articles(self, records: list[dict]) -> list[dict]:
        ranked = sorted(
            records,
            key=lambda item: item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        payloads = []
        for entry in ranked[1:3]:
            title = self._compact_text(
                self._sanitize_generated_text(entry.get("title") or entry.get("summary") or "Market update"),
                120,
            )
            summary = self._compact_text(
                self._sanitize_generated_text(entry.get("summary") or entry.get("content") or ""),
                420,
            )
            body = self._compact_text(
                self._sanitize_generated_text(entry.get("content") or summary, keep_paragraphs=True),
                1300,
            )
            payloads.append(
                {
                    "title": title,
                    "summary": summary,
                    "body": body,
                    "references": self._normalize_references([entry.get("url")]),
                    "published_at": entry.get("published_at"),
                }
            )
        return payloads

    def _sanitize_generated_text(self, text: str, *, keep_paragraphs: bool = False) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""

        # Some models wrap text in markdown code fences when formatting drifts.
        raw = re.sub(r"^\s*```(?:json|markdown|md|text|html)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.IGNORECASE)

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
            tag.decompose()
        for node in soup.select("blockquote.twitter-tweet, blockquote.instagram-media, blockquote.tiktok-embed"):
            node.decompose()

        extracted = soup.get_text("\n" if keep_paragraphs else " ")
        if keep_paragraphs:
            extracted = extracted.replace("\xa0", " ")
            extracted = extracted.replace("\r\n", "\n").replace("\r", "\n")
            extracted = "\n".join(line.strip() for line in extracted.split("\n"))
            extracted = re.sub(r"\n{3,}", "\n\n", extracted)
            return extracted.strip()

        extracted = extracted.replace("\xa0", " ")
        return re.sub(r"\s+", " ", extracted).strip()

    def _ensure_complete_article(self, candidate: str, fallback: str) -> str:
        text = self._sanitize_generated_text(candidate or "", keep_paragraphs=True)
        fallback_clean = self._sanitize_generated_text(fallback or "", keep_paragraphs=True)
        if text:
            sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
            word_count = len(text.split())
            if sentence_count >= 4 and word_count >= 80:
                return text
        return fallback_clean

    def _strip_time_window_phrasing(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        replacements = [
            (r"\b(in|during)\s+this\s+(time\s+window|window|period|hour)\b[:,]?\s*", ""),
            (r"\bat\s+this\s+time\b[:,]?\s*", ""),
            (r"\bfor\s+the\s+current\s+time\s+window\b[:,]?\s*", ""),
            (r"\bwithin\s+this\s+(time\s+window|period)\b[:,]?\s*", ""),
            (r"\bthese\s+news\s+were\s+published\b[:,]?\s*", ""),
        ]
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _ensure_informative_title(
        self,
        candidate: str,
        records: list[dict],
        timeframe: str,
        period_start: datetime,
    ) -> str:
        value = self._compact_text(candidate or "", 140)
        if value and not self._is_generic_title(value):
            return value

        ranked = sorted(
            records,
            key=lambda item: item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        for item in ranked:
            headline = self._compact_text(item.get("title") or item.get("summary") or "", 120)
            if headline and not self._is_generic_title(headline):
                return headline

        if timeframe == Card.TIMEFRAME_HOUR:
            return f"Financial Market Impact Update for {period_start.strftime('%Y-%m-%d %H:00 UTC')}"
        if timeframe == Card.TIMEFRAME_DAY:
            period_end = period_start + timedelta(hours=24)
            return (
                "24-Hour Financial Market Impact Summary ending "
                f"{period_end.strftime('%Y-%m-%d %H:00 UTC')}"
            )
        if timeframe == Card.TIMEFRAME_WEEK:
            return f"Weekly Financial Market Impact Summary for Week of {period_start.strftime('%Y-%m-%d')}"
        return f"Monthly Financial Market Impact Summary for {period_start.strftime('%B %Y')}"

    def _is_generic_title(self, value: str) -> bool:
        slug = slugify((value or "").strip())
        if not slug:
            return True
        if slug in self._GENERIC_TITLE_SLUGS:
            return True
        if slug.startswith("market-brief") or slug.endswith("market-brief"):
            return True
        if slug.startswith("market-update") or slug.endswith("market-update"):
            return True
        return False

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        value = re.sub(r"\s+", " ", (text or "").strip())
        if len(value) <= limit:
            return value
        clipped = value[:limit].rstrip()
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        return clipped.rstrip(".,;: ") + "..."

    def _normalize_references(self, references: object) -> list[str]:
        if not references:
            return []
        urls: list[str] = []
        if isinstance(references, str):
            urls.extend(re.findall(r"https?://\S+", references))
        elif isinstance(references, (list, tuple)):
            for item in references:
                if isinstance(item, str):
                    urls.extend(re.findall(r"https?://\S+", item))
        cleaned = []
        for url in urls:
            trimmed = url.strip().rstrip(").,;")
            if trimmed and trimmed not in cleaned:
                cleaned.append(trimmed)
        return cleaned[:10]

    def _build_article_prompt(
        self,
        context: str,
        timeframe: str,
        period_start: datetime,
        period_end: datetime,
    ) -> str:
        template = self.config.article_prompt_template or "{context}"
        guardrails = (
            "You are an institutional financial journalist. "
            "Write as a human market reporter, not as a template or machine-generated bulletin. "
            "Write in clear, professional English and keep explanations straightforward. "
            "Include only events with direct or indirect impact on financial markets. "
            "Reject sports, entertainment, celebrity, lifestyle, and unrelated local stories. "
            "Do NOT write explicit timestamps or phrases like 'in this time window' in the article body. "
            "Return plain text only; do not output HTML tags, markdown formatting, social embeds, or XML fragments. "
            "Focus on what happened, why it matters, and likely market implications. "
            "Return JSON with keys: title, summary, article_text, impacts, importance_score, importance_reason, references."
        )
        body = template.replace("{context}", context)
        return f"{guardrails}\n\nSource records:\n{body}"

    def _describe_price_moves(self, card: Card, window_end: datetime) -> str:
        """Factual open/close/range summary per tracked asset since card.period_end. Empty string if no candle data yet."""
        interval_minutes, _, _ = resolve_timeframe(card.timeframe)
        span_minutes = max(1, int((window_end - card.period_end).total_seconds() // 60))
        max_buckets = max(1, -(-span_minutes // max(1, interval_minutes)))

        lines: list[str] = []
        for asset in card.assets.select_related("series").order_by("series__symbol"):
            candles = aggregate_candles(
                series=asset.series,
                start=card.period_end,
                end=window_end,
                interval_minutes=interval_minutes,
                max_buckets=max_buckets,
            )
            if not candles:
                continue
            label = asset.label or asset.series.label or asset.series.symbol
            open_price = candles[0]["open"]
            close_price = candles[-1]["close"]
            high = max(c["high"] for c in candles)
            low = min(c["low"] for c in candles)
            pct_change = ((close_price - open_price) / open_price * 100) if open_price else 0.0
            lines.append(
                f"{label}: opened at {open_price:.2f}, closed at {close_price:.2f} "
                f"({pct_change:+.2f}%), range {low:.2f}-{high:.2f}."
            )
        return "\n".join(lines)

    def _build_aftermath_payload(
        self,
        *,
        card: Card,
        main_article: CardArticle,
        price_window_end: datetime,
        run: Optional[AgentRun],
    ) -> Optional[dict]:
        price_moves = self._describe_price_moves(card, price_window_end)
        if not price_moves:
            # No candle data recorded for this window yet — try again next loop tick.
            return None

        fallback = {
            "title": self._compact_text(f"Price check: {main_article.title}", 120) if main_article.title else "Post-brief price check",
            "summary": self._compact_text(price_moves.replace("\n", " "), 400),
            "body": f"Observed price action since the brief closed:\n\n{price_moves}",
            "references": [],
        }

        if not (self.config.use_llm_summaries and self.llm.enabled):
            return fallback

        template = self.config.aftermath_prompt_template or "{price_moves}"
        prompt = (
            template.replace("{article_title}", main_article.title or "")
            .replace("{article_summary}", main_article.summary or "")
            .replace("{article_body}", main_article.body or "")
            .replace("{price_moves}", price_moves)
        )

        if not self._consume_llm_budget(run=run, purpose="aftermath_generation", reserve=0):
            return fallback

        self._log_event(
            run=run,
            step=AgentLogEvent.STEP_LLM_PROMPT,
            message="aftermath_prompt_prepared",
            content=prompt,
            metadata={"card_slug": card.slug, "prompt_chars": len(prompt)},
        )
        result = self.llm.generate_article(prompt)
        self._log_event(
            run=run,
            step=AgentLogEvent.STEP_LLM_OUTPUT,
            message="aftermath_prompt_completed",
            content=self.llm.last_output_text or "",
            metadata={
                "status_code": self.llm.last_status_code,
                "error": self.llm.last_error,
                "parsed": bool(result),
            },
        )
        if not result:
            return fallback

        return {
            "title": self._compact_text(result.title, 120) if result.title else fallback["title"],
            "summary": self._compact_text(result.summary, 400) if result.summary else fallback["summary"],
            "body": result.article_text or fallback["body"],
            "references": self._normalize_references(result.references),
        }
