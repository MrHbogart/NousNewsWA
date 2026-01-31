from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from django.conf import settings

from crawler.models import CrawlerConfig


@dataclass(frozen=True)
class LLMResult:
    next_urls: List[str]
    next_urls_by_seed: List[Dict[str, str]]
    articles: List[Dict[str, Any]]


@dataclass(frozen=True)
class BriefResult:
    title: str
    summary: str
    references: List[str]


class LLMClient:
    def __init__(self, config: CrawlerConfig):
        self._config = config
        self._provider = (config.llm_provider or "openai").lower()
        self._api_key = config.llm_api_key or ""
        self._base_url = config.llm_base_url or self._default_base_url(self._provider)
        self.last_output_text = ""
        self.last_error = ""
        self.last_status_code: Optional[int] = None
        self.last_provider = self._provider
        self.last_model = self._config.llm_model

    def _reset_trace(self) -> None:
        self.last_output_text = ""
        self.last_error = ""
        self.last_status_code = None
        self.last_provider = self._provider
        self.last_model = self._config.llm_model

    @staticmethod
    def _default_base_url(provider: str) -> str:
        if provider == "huggingface":
            return "https://api-inference.huggingface.co"
        if provider == "apifreellm":
            return "https://apifreellm.com"
        if provider in {"google", "gemini", "google_ai", "ai_studio"}:
            return "https://generativelanguage.googleapis.com/v1beta"
        return "https://api.openai.com/v1"

    @property
    def enabled(self) -> bool:
        if not self._config.llm_enabled:
            return False
        if self._provider == "apifreellm":
            return True
        if self._provider in {"google", "gemini", "google_ai", "ai_studio"}:
            return bool(self._api_key)
        return bool(self._api_key)

    def extract(self, prompt: str) -> Optional[LLMResult]:
        self._reset_trace()
        if not self.enabled:
            self.last_error = "llm_disabled"
            return None
        if self._provider == "huggingface":
            return self._extract_huggingface(prompt)
        if self._provider == "apifreellm":
            return self._extract_apifreellm(prompt)
        if self._provider in {"google", "gemini", "google_ai", "ai_studio"}:
            return self._extract_google(prompt)
        return self._extract_openai(prompt)

    def generate_brief(self, prompt: str) -> Optional[BriefResult]:
        self._reset_trace()
        if not self.enabled:
            self.last_error = "llm_disabled"
            return None
        if self._provider == "huggingface":
            return self._brief_huggingface(prompt)
        if self._provider == "apifreellm":
            return self._brief_apifreellm(prompt)
        if self._provider in {"google", "gemini", "google_ai", "ai_studio"}:
            return self._brief_google(prompt)
        return self._brief_openai(prompt)

    def _extract_openai(self, prompt: str) -> Optional[LLMResult]:
        payload = {
            "model": self._config.llm_model,
            "temperature": self._config.llm_temperature,
            "max_tokens": self._config.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a high-precision news extraction and URL selection system. "
                        "Only return valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            self.last_output_text = content or ""
            result = self._parse_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _brief_openai(self, prompt: str) -> Optional[BriefResult]:
        payload = {
            "model": self._config.llm_model,
            "temperature": self._config.brief_temperature,
            "max_tokens": self._config.brief_max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a precise news editor. Only return valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            self.last_output_text = content or ""
            result = self._parse_brief_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _extract_huggingface(self, prompt: str) -> Optional[LLMResult]:
        payload = {
            "inputs": self._build_hf_prompt(prompt),
            "parameters": {
                "temperature": self._config.llm_temperature,
                "max_new_tokens": self._config.llm_max_output_tokens,
                "return_full_text": False,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/models/{self._config.llm_model}",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = self._extract_hf_text(data)
            if not content:
                self.last_error = "empty_response"
                return None
            self.last_output_text = content
            result = self._parse_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _brief_huggingface(self, prompt: str) -> Optional[BriefResult]:
        payload = {
            "inputs": self._build_hf_prompt(prompt),
            "parameters": {
                "temperature": self._config.brief_temperature,
                "max_new_tokens": self._config.brief_max_output_tokens,
                "return_full_text": False,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/models/{self._config.llm_model}",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = self._extract_hf_text(data)
            if not content:
                self.last_error = "empty_response"
                return None
            self.last_output_text = content
            result = self._parse_brief_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _extract_apifreellm(self, prompt: str) -> Optional[LLMResult]:
        payload = {"message": prompt}
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/api/chat",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = self._extract_apifreellm_text(data)
            if not content:
                self.last_error = "empty_response"
                return None
            self.last_output_text = content
            result = self._parse_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _brief_apifreellm(self, prompt: str) -> Optional[BriefResult]:
        payload = {"message": prompt}
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/api/chat",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = self._extract_apifreellm_text(data)
            if not content:
                self.last_error = "empty_response"
                return None
            self.last_output_text = content
            result = self._parse_brief_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _extract_google(self, prompt: str) -> Optional[LLMResult]:
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": self._config.llm_temperature,
                "maxOutputTokens": self._config.llm_max_output_tokens,
            },
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/models/{self._config.llm_model}:generateContent",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = self._extract_google_text(data)
            if not content:
                self.last_error = "empty_response"
                return None
            self.last_output_text = content
            result = self._parse_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _brief_google(self, prompt: str) -> Optional[BriefResult]:
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": self._config.brief_temperature,
                "maxOutputTokens": self._config.brief_max_output_tokens,
            },
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=getattr(settings, "CRAWLER_LLM_TIMEOUT_SECONDS", 45)) as client:
                resp = client.post(
                    f"{self._base_url.rstrip('/')}/models/{self._config.llm_model}:generateContent",
                    headers=headers,
                    json=payload,
                )
            self.last_status_code = resp.status_code
            if resp.status_code >= 400:
                self.last_error = f"http_{resp.status_code}"
                return None
            data = resp.json()
            content = self._extract_google_text(data)
            if not content:
                self.last_error = "empty_response"
                return None
            self.last_output_text = content
            result = self._parse_brief_response(content)
            if result is None:
                self.last_error = "invalid_response"
            return result
        except Exception:
            self.last_error = "request_failed"
            return None

    def _build_hf_prompt(self, prompt: str) -> str:
        return "Return ONLY valid JSON.\n" + prompt

    def _extract_hf_text(self, data: Any) -> Optional[str]:
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first.get("generated_text")
        if isinstance(data, dict):
            if "generated_text" in data:
                return data.get("generated_text")
            if "error" in data:
                return None
        return None

    def _extract_apifreellm_text(self, data: Any) -> Optional[str]:
        if isinstance(data, dict):
            for key in ("response", "message", "content", "text"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None

    def _extract_google_text(self, data: Any) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        content = candidates[0].get("content")
        if not isinstance(content, dict):
            return None
        parts = content.get("parts")
        if not isinstance(parts, list):
            return None
        texts: List[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text)
        if not texts:
            return None
        return "\n".join(texts)

    def _parse_response(self, content: str) -> Optional[LLMResult]:
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        try:
            data = json.loads(content)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        next_urls = data.get("next_urls", [])
        next_urls_by_seed = data.get("next_urls_by_seed", [])
        articles = data.get("articles", [])
        if isinstance(next_urls_by_seed, dict):
            next_urls_by_seed = [
                {"seed_url": seed_url, "next_url": next_url}
                for seed_url, next_url in next_urls_by_seed.items()
            ]
        if (
            not isinstance(next_urls, list)
            or not isinstance(next_urls_by_seed, list)
            or not isinstance(articles, list)
        ):
            return None
        next_urls = [u for u in next_urls if isinstance(u, str)]
        next_urls_by_seed = [
            item for item in next_urls_by_seed if isinstance(item, dict)
        ]
        articles = [a for a in articles if isinstance(a, dict)]
        return LLMResult(
            next_urls=next_urls,
            next_urls_by_seed=next_urls_by_seed,
            articles=articles,
        )

    def _parse_brief_response(self, content: str) -> Optional[BriefResult]:
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        try:
            data = json.loads(content)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        title = data.get("title") or ""
        summary = data.get("summary") or ""
        references = data.get("references") or []
        if not isinstance(title, str) or not isinstance(summary, str):
            return None
        if not isinstance(references, list):
            references = []
        references = [r for r in references if isinstance(r, str)]
        return BriefResult(
            title=title.strip(),
            summary=summary.strip(),
            references=references[:5],
        )
