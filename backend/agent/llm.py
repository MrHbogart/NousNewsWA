from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import hashlib

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
        # simple in-memory prompt->response cache to speed repeated runs
        self._cache: dict[str, Any] = {}

    def _reset_trace(self) -> None:
        self.last_output_text = ""
        self.last_error = ""
        self.last_status_code = None
        self.last_model = self._config.llm_model

    @property
    def enabled(self) -> bool:
        return bool(self._config.llm_enabled and self._api_key)

    def generate_article(self, prompt: str) -> Optional[ArticleResult]:
        self._reset_trace()
        if not self.enabled:
            self.last_error = "llm_disabled"
            return None
        # cache key based on prompt content
        try:
            key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        except Exception:
            key = str(hash(prompt))
        if key in self._cache:
            cached = self._cache.get(key)
            if isinstance(cached, ArticleResult):
                return cached
        payload = {
            "model": self._config.llm_model,
            "temperature": self._config.llm_temperature,
            "max_tokens": self._config.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a precise news editor. Only return valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        data = self._post_chat(payload)
        if data is None:
            return None
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        self.last_output_text = content or ""
        result = self._parse_article(content)
        if result is None:
            self.last_error = "invalid_response"
        else:
            # store parsed result in cache
            try:
                self._cache[key] = result
            except Exception:
                pass
        return result

    def generate_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        self._reset_trace()
        if not self.enabled:
            self.last_error = "llm_disabled"
            return None
        try:
            key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        except Exception:
            key = str(hash(prompt))
        if key in self._cache:
            cached = self._cache.get(key)
            if isinstance(cached, dict):
                return cached
        payload = {
            "model": self._config.llm_model,
            "temperature": self._config.llm_temperature,
            "max_tokens": self._config.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Only return valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        data = self._post_chat(payload)
        if data is None:
            return None
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        self.last_output_text = content or ""
        try:
            return json.loads(content or "{}")
        except json.JSONDecodeError:
            self.last_error = "invalid_response"
            return None
        finally:
            # best-effort cache raw json string -> parsed
            try:
                parsed = json.loads(content or "{}")
                self._cache[key] = parsed
            except Exception:
                pass

    def embed(self, text: str, model: Optional[str] = None) -> list[float]:
        self._reset_trace()
        if not self.enabled:
            self.last_error = "llm_disabled"
            return []
        if not text:
            return []
        payload = {"model": model or self._config.llm_model, "input": text}
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._auth_header(),
        }
        try:
            with httpx.Client(timeout=getattr(settings, "AGENT_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url}/embeddings",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return []
            data = resp.json()
            vector = data.get("data", [{}])[0].get("embedding")
            if isinstance(vector, list):
                return [float(v) for v in vector]
        except Exception:
            self.last_error = "request_failed"
        return []

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
            return resp.json()
        except Exception:
            self.last_error = "request_failed"
            return None

    @staticmethod
    def _parse_article(content: str) -> Optional[ArticleResult]:
        try:
            parsed = json.loads(content or "{}")
        except json.JSONDecodeError:
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
        if "arvancloudai.ir" in self._base_url:
            return f"apikey {self._api_key}"
        return f"Bearer {self._api_key}"

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
