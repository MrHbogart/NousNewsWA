from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from django.conf import settings

from agent.models import AgentConfig


@dataclass(frozen=True)
class ArticleResult:
    title: str
    summary: str
    article_text: str
    impacts: List[str]
    references: List[str]
    importance_score: int = 1
    importance_reason: str = ""


class LLMClient:
    def __init__(self, config: AgentConfig):
        self._config = config
        self._api_key = config.llm_api_key or ""
        self._base_url = self._normalize_base_url(config.llm_base_url or "https://api.openai.com/v1")
        self.last_output_text = ""
        self.last_error = ""
        self.last_status_code: Optional[int] = None
        self.last_model = self._config.llm_model
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _reset_trace(self) -> None:
        self.last_output_text = ""
        self.last_error = ""
        self.last_status_code = None
        self.last_model = self._config.llm_model

    @property
    def enabled(self) -> bool:
        return bool(self._config.llm_enabled and self._api_key)

    def _complete(self, prompt: str, system: str) -> Optional[str]:
        self._reset_trace()
        if not self.enabled:
            self.last_error = "llm_disabled"
            return None
        payload = {
            "model": self._config.llm_model,
            "temperature": self._config.llm_temperature,
            "max_tokens": self._config.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        data = self._post_chat(payload)
        if data is None:
            return None
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        self.last_output_text = content or ""
        return self.last_output_text

    def generate_article(self, prompt: str) -> Optional[ArticleResult]:
        content = self._complete(prompt, "You are a precise news editor. Only return valid JSON.")
        if content is None:
            return None
        result = self._parse_article(content)
        if result is None:
            self.last_error = "invalid_response"
        return result

    def generate_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        content = self._complete(prompt, "Only return valid JSON.")
        if content is None:
            return None
        try:
            parsed = json.loads(content or "{}")
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict):
            self.last_error = "invalid_response"
            return None
        return parsed

    def _post_chat(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._auth_header(),
        }
        try:
            with httpx.Client(timeout=getattr(settings, "AGENT_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
        except Exception:
            self.last_error = "request_failed"
            return None
        usage = data.get("usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        return data

    @staticmethod
    def _parse_article(content: str) -> Optional[ArticleResult]:
        try:
            parsed = json.loads(content or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        raw_score = parsed.get("importance_score")
        try:
            importance_score = int(raw_score)
        except (TypeError, ValueError):
            importance_score = 1
        importance_score = max(1, min(3, importance_score))
        return ArticleResult(
            title=parsed.get("title") or "",
            summary=parsed.get("summary") or "",
            article_text=parsed.get("article_text") or parsed.get("content") or "",
            impacts=parsed.get("impacts") or [],
            references=parsed.get("references") or [],
            importance_score=importance_score,
            importance_reason=parsed.get("importance_reason") or "",
        )

    def _auth_header(self) -> str:
        if not self._api_key:
            return ""
        scheme = (self._config.llm_auth_scheme or "Bearer").strip()
        return f"{scheme} {self._api_key}"

    @staticmethod
    def _normalize_base_url(raw_url: str) -> str:
        if not raw_url:
            return "https://api.openai.com/v1"
        url = raw_url.strip().rstrip("/")
        for suffix in ("/chat/completions", "/embeddings"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        if "/gateway/models/" in url and not url.endswith("/v1"):
            url = f"{url}/v1"
        return url
