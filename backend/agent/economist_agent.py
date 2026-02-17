from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from django.utils import timezone

from agent.llm import LLMClient
from agent.models import AgentConfig, MemoryState


class EconomistAgent:
    def __init__(
        self,
        llm: LLMClient,
        generate_json_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ):
        self.llm = llm
        self._generate_json = generate_json_fn or self.llm.generate_json
        self.config = AgentConfig.objects.first()
        if self.config is None:
            self.config = AgentConfig.objects.create()
        self.trace: Dict[str, str] = {
            "signals_prompt": "",
            "signals_output": "",
            "writing_prompt": "",
            "writing_output": "",
        }

    def run(self, cleaned_text: str) -> Optional[Dict[str, Any]]:
        if not self.config or not self.config.llm_enabled:
            return None
        if not cleaned_text:
            return None
        memory_text = self._load_memory_text()
        signals = self._select_signals(cleaned_text, memory_text)
        if signals is None:
            return None
        writing = self._write_outputs(signals, memory_text)
        if writing is None:
            return None
        memory_payload = self._memory_update(signals, writing, memory_text)
        self._store_memory_state(writing, memory_payload)
        return {
            "signals": signals,
            "writing": writing,
            "memory": memory_payload,
            "trace": dict(self.trace),
        }

    def _select_signals(self, text: str, memory_text: str) -> Optional[Dict[str, Any]]:
        template = (self.config.signals_prompt_template or "").strip()
        if not template:
            return None
        prompt = template.replace("{context}", text).replace("{memory}", memory_text)
        self.trace["signals_prompt"] = prompt
        output = self._generate_json(prompt)
        self.trace["signals_output"] = self.llm.last_output_text or ""
        return output

    def _write_outputs(self, signals: Dict[str, Any], memory_text: str) -> Optional[Dict[str, Any]]:
        template = (self.config.writing_prompt_template or "").strip()
        if not template:
            return None
        prompt = template.replace("{signals}", json.dumps(signals)).replace("{memory}", memory_text)
        self.trace["writing_prompt"] = prompt
        output = self._generate_json(prompt)
        self.trace["writing_output"] = self.llm.last_output_text or ""
        return output

    def _memory_update(
        self,
        signals: Dict[str, Any],
        writing: Dict[str, Any],
        memory_text: str,
    ) -> Optional[Dict[str, Any]]:
        return None

    def _load_memory_text(self) -> str:
        state = MemoryState.objects.order_by("-updated_at").first()
        text = state.content if state else ""
        if not self.config or not self.config.memory_enabled:
            return ""
        limit = int(self.config.memory_token_limit or 0)
        if limit <= 0:
            return text
        return self._truncate_to_limit(text, limit)

    def _store_memory_state(self, writing: Dict[str, Any], memory_payload: Optional[Dict[str, Any]]) -> None:
        if self.config and not self.config.memory_enabled:
            return
        updated = ""
        if isinstance(writing, dict):
            updated = writing.get("summary") or writing.get("article_text") or ""
        if not updated:
            return
        existing = MemoryState.objects.order_by("-updated_at").first()
        stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        combined = f"{existing.content}\n\n[{stamp}] {updated}".strip() if existing else f"[{stamp}] {updated}"
        if existing:
            existing.content = self._truncate_to_limit(combined, self._memory_limit())
            existing.save(update_fields=["content", "updated_at"])
        else:
            MemoryState.objects.create(content=self._truncate_to_limit(combined, self._memory_limit()))

    def _memory_limit(self) -> int:
        if not self.config:
            return 20000
        return int(self.config.memory_token_limit or 20000)

    @staticmethod
    def _truncate_to_limit(text: str, token_limit: int) -> str:
        if token_limit <= 0:
            return text
        char_limit = token_limit * 4
        if len(text) <= char_limit:
            return text
        return text[-char_limit:]
