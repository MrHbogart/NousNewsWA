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
from articles.services import describe_price_moves, tracked_series
from articles.slugging import build_article_slug

from .base import _utc_now

CHILD_TIMEFRAME = {
    Card.TIMEFRAME_DAY: Card.TIMEFRAME_INTRADAY,
    Card.TIMEFRAME_WEEK: Card.TIMEFRAME_DAY,
    Card.TIMEFRAME_MONTH: Card.TIMEFRAME_WEEK,
}

_FORMAT_RULES = (
    "Plain text with light structure: a section starts with a line '## Heading'; paragraphs are separated by a "
    "blank line; a list is consecutive lines starting with '- '. No other markdown, no HTML, no tables. "
    "Do not write timestamps or phrases like 'in this time window'."
)
ARTICLE_FORMATS = {
    Card.TIMEFRAME_INTRADAY: (
        "250-450 words. Open with a 2-3 sentence lead paragraph (no heading), then 2-4 short sections such as "
        "'## Central banks', '## Markets' or '## Commodities', using only sections the records support. "
        + _FORMAT_RULES
    ),
    Card.TIMEFRAME_DAY: (
        "600-900 words: the day's definitive market story. Open with a 2-3 sentence lead paragraph (no heading), "
        "then sections: '## The big picture', 2-4 topical sections, '## Market moves' (cite the price data), and "
        "'## What to watch next' (scheduled events or open questions named in the records). " + _FORMAT_RULES
    ),
    Card.TIMEFRAME_WEEK: (
        "700-1000 words reviewing the week. Open with a lead paragraph, then '## The week in brief' (a '- ' list of "
        "the 4-6 biggest stories), topical sections, '## Market moves' (cite the price data), and "
        "'## The week ahead'. " + _FORMAT_RULES
    ),
    Card.TIMEFRAME_MONTH: (
        "800-1200 words reviewing the month. Open with a lead paragraph, then '## The month in brief' (a '- ' list), "
        "topical sections on the main themes, '## Market moves' (cite the price data), and '## Looking ahead'. "
        + _FORMAT_RULES
    ),
}


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
        price_moves = describe_price_moves(tracked_series(), period_start, min(period_end, _utc_now()))
        fallback = self._compose_fallback_payload(records, timeframe, period_start, period_end, price_moves=price_moves)
        context = self._build_context_from_records(
            records, timeframe=timeframe, period_start=period_start, period_end=period_end, price_moves=price_moves
        )

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
        price_moves: str = "",
    ) -> dict:
        ranked = self._rank_records(records)

        title = self._ensure_informative_title("", ranked, timeframe, period_start)
        sources = {item.get("source_name") for item in ranked if item.get("source_name")}
        intro = (
            f"{len(ranked)} market-moving stories crossed the wires in this window, from {len(sources) or 'several'} "
            f"source{'' if len(sources) == 1 else 's'}. Here is what traders were watching."
        )

        detail_sentences = []
        for item in ranked[:4]:
            headline = self._compact_text(item.get("title") or item.get("summary") or item.get("content") or "", 180)
            if not headline:
                continue
            source_name = item.get("source_name") or "newswire"
            detail_sentences.append(
                f"{headline.rstrip('.')} ({source_name}). {self._impact_sentence(item)}"
            )

        if not detail_sentences:
            detail_sentences.append(
                "A quiet stretch: nothing in this window cleared the bar for market-moving news."
            )

        closing = (
            "The thread to follow: how these stories shift rate expectations, risk appetite and "
            "currency flows over the next few sessions."
        )

        sections = [intro] + detail_sentences + [closing]
        if price_moves:
            sections.append("## Market moves\n" + "\n".join(f"- {line}" for line in price_moves.splitlines()))
        body = "\n\n".join(sections)
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

    def _rank_records(self, records: list[dict]) -> list[dict]:
        """Most market-relevant first, newest first among equals: picks the no-LLM headline and side stories."""
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(
            records,
            key=lambda item: (
                self._relevance_score(item.get("cleaned_text") or item.get("summary") or "", item.get("title") or ""),
                item.get("published_at") or oldest,
            ),
            reverse=True,
        )

    def _impact_sentence(self, record: dict) -> str:
        text = (record.get("title") or "") + " " + (record.get("summary") or "") + " " + (record.get("content") or "")
        low = text.lower()
        if any(token in low for token in ["interest rate", "fed", "ecb", "inflation", "cpi", "ppi", "gdp"]):
            return "Watch rates and the dollar: this is the kind of news that moves policy bets."
        if any(token in low for token in ["earnings", "guidance", "revenue", "profit", "m&a", "merger", "acquisition"]):
            return "Equity investors will be re-running their valuations on this one."
        if any(token in low for token in ["oil", "gas", "commodity", "energy", "supply chain", "tariff", "sanction"]):
            return "Energy and commodity prices, and the inflation outlook with them, can swing fast on news like this."
        if any(token in low for token in ["bond", "yield", "treasury", "credit", "default", "rating"]):
            return "Bond markets are in the firing line: yields and credit spreads may reprice."
        return "One for the risk radar as markets digest it."

    def _derive_impacts(self, records: list[dict]) -> list[str]:
        low = " ".join(
            [
                (item.get("title") or "") + " " + (item.get("summary") or "") + " " + (item.get("content") or "")
                for item in records
            ]
        ).lower()

        impacts = []
        if any(token in low for token in ["interest rate", "fed", "ecb", "inflation", "cpi", "ppi", "gdp"]):
            impacts.append("Rates and FX: shifting policy bets can move bond yields and the major currency pairs.")
        if any(token in low for token in ["earnings", "guidance", "revenue", "profit", "m&a", "merger", "acquisition"]):
            impacts.append("Equities: earnings and deals are reshaping valuations, so expect money to rotate between sectors.")
        if any(token in low for token in ["oil", "gas", "commodity", "energy", "supply chain", "tariff", "sanction"]):
            impacts.append("Commodities: supply worries and geopolitics can make energy and raw materials jumpy.")
        if any(token in low for token in ["bond", "yield", "treasury", "credit", "default", "rating"]):
            impacts.append("Credit: wider spreads would squeeze heavily indebted companies and riskier assets first.")
        if not impacts:
            impacts.append("Risk sentiment: markets are still pricing in the new information, so moves may not be done.")
        return impacts[:6]

    def _build_context_from_records(
        self,
        records: list[dict],
        *,
        timeframe: str,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        price_moves: str = "",
    ) -> str:
        sections = []
        if price_moves:
            sections.append(f"Price data for this period (UTC):\n{price_moves}")
        if period_start and period_end:
            briefs = self._child_briefs_context(timeframe, period_start, period_end)
            if briefs:
                sections.append(f"Briefs already published within this period, oldest first:\n\n{briefs}")
        # Short briefs get each record's detail; longer periods have their
        # child briefs above, so a headline and teaser per record leaves room for more of them.
        detail_chars = 1500 if timeframe == Card.TIMEFRAME_INTRADAY else 300
        chunks = []
        for item in records:
            title = (item.get("title") or "").strip()
            summary = self._compact_text(item.get("summary") or "", 400)
            content = self._compact_text(item.get("cleaned_text") or item.get("content") or "", detail_chars)
            source = (item.get("source_name") or "unknown").strip()
            url = (item.get("url") or "").strip()
            details = f"\nDetails: {content}" if content and content != summary else ""
            chunks.append(f"({source}) {title}\nSummary: {summary}{details}\nURL: {url}")
        if chunks:
            sections.append("News records, newest first:\n\n" + "\n\n".join(chunks))
        combined = "\n\n".join(sections)
        # Every timeframe is capped: an uncapped busy period overflowed the
        # model context, so the call failed and still spent budget.
        max_chars = int(self.config.max_context_chars or 0)
        if max_chars > 0:
            combined = combined[:max_chars]
        return combined

    def _child_briefs_context(self, timeframe: str, period_start: datetime, period_end: datetime) -> str:
        """A day is written from its 4-hour briefs, a week from its days, a month from its weeks."""
        child = CHILD_TIMEFRAME.get(timeframe)
        if child is None:
            return ""
        articles = (
            CardArticle.objects.filter(
                kind=CardArticle.KIND_MAIN,
                card__timeframe=child,
                card__status=Card.STATUS_FINAL,
                card__period_start__gte=period_start,
                card__period_start__lt=period_end,
            )
            .select_related("card")
            .order_by("card__period_start")
        )
        return "\n\n".join(
            f"[{article.card.period_start:%a %d %b %H:%M} UTC] {article.title}\n"
            f"{article.summary}\n{self._compact_text(article.body, 1800)}"
            for article in articles
        )

    def _build_side_articles(self, records: list[dict]) -> list[dict]:
        ranked = self._rank_records(records)
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

        # Spaces/tabs only: collapsing all whitespace merged every paragraph into one.
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
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

        ranked = self._rank_records(records)

        for item in ranked:
            headline = self._compact_text(item.get("title") or item.get("summary") or "", 120)
            if headline and not self._is_generic_title(headline):
                return headline

        if timeframe == Card.TIMEFRAME_INTRADAY:
            period_end = period_start + timedelta(hours=4)
            return (
                f"Financial Market Impact Update, {period_start:%Y-%m-%d %H:00}–{period_end:%H:00} UTC"
            )
        if timeframe == Card.TIMEFRAME_DAY:
            return f"Daily Financial Market Impact Summary for {period_start:%A, %B %d, %Y}"
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
            # Placeholder URLs for link-less items (see _synthetic_url) aren't real pages.
            if trimmed.startswith("https://synthetic.local/"):
                continue
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
        body = template.replace("{context}", context)
        return f"{body}\n\nFormat instructions for article_text:\n{ARTICLE_FORMATS.get(timeframe, ARTICLE_FORMATS[Card.TIMEFRAME_INTRADAY])}"

    def _describe_price_moves(self, card: Card, window_end: datetime) -> str:
        """Factual open/last/range summary per tracked asset since card.period_end. Empty string if no candle data yet."""
        assets = [
            (asset.series, asset.label or asset.series.label or asset.series.symbol)
            for asset in card.assets.select_related("series").order_by("series__symbol")
        ]
        return describe_price_moves(assets, card.period_end, window_end)

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
