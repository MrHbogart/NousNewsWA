from __future__ import annotations

from typing import Optional

from agent.models import AgentLogEvent, AgentRun

from .base import _safe_json_value


class BudgetMixin:
    """AgentLogEvent writing and the per-run LLM request budget."""

    def _log_event(
        self,
        *,
        run: Optional[AgentRun],
        step: str,
        message: str,
        content: str = "",
        metadata: Optional[dict] = None,
        level: str = AgentLogEvent.LEVEL_INFO,
        seed_url: str = "",
        url: str = "",
    ) -> None:
        clipped_content, clip_meta = self._clip_log(content)
        meta = self._safe_json(dict(metadata or {}))
        if clip_meta:
            meta.update(clip_meta)
        AgentLogEvent.objects.create(
            run=run,
            seed_url=seed_url or "",
            url=url or "",
            step=step,
            level=level,
            message=message[:255],
            content=clipped_content,
            metadata=meta,
        )

    def _clip_log(self, text: str) -> tuple[str, dict]:
        if not text:
            return "", {}
        max_chars = max(0, int(self.log_max_chars))
        if max_chars <= 0 or len(text) <= max_chars:
            return text, {}
        head = int(max_chars * 0.7)
        tail = max_chars - head
        clipped = text[:head] + "\n...\n" + text[-tail:]
        return clipped, {"clipped": True, "original_chars": len(text), "stored_chars": len(clipped)}

    def _llm_budget_remaining(self) -> int:
        return max(0, int(self.llm_request_budget) - int(self.llm_requests_used))

    def _consume_llm_budget(
        self,
        *,
        run: Optional[AgentRun],
        purpose: str,
        reserve: int = 0,
    ) -> bool:
        remaining = self._llm_budget_remaining()
        required_remaining = max(0, int(reserve))
        if remaining <= required_remaining:
            if not self._llm_budget_exhausted_logged:
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_NEXT_STEP,
                    level=AgentLogEvent.LEVEL_WARN,
                    message="llm_budget_exhausted",
                    metadata={
                        "purpose": purpose,
                        "llm_requests_used": self.llm_requests_used,
                        "llm_request_budget": self.llm_request_budget,
                        "llm_reserved_for_articles": required_remaining,
                    },
                )
                self._llm_budget_exhausted_logged = True
            return False
        self.llm_requests_used += 1
        return True

    def _budgeted_generate_json(
        self,
        prompt: str,
        *,
        run: Optional[AgentRun],
        purpose: str,
        reserve: int = 0,
    ) -> Optional[dict]:
        if not self._consume_llm_budget(run=run, purpose=purpose, reserve=reserve):
            return None
        return self.llm.generate_json(prompt)

    @classmethod
    def _safe_json(cls, value: object):
        return _safe_json_value(value)
