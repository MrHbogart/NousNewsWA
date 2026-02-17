from __future__ import annotations

import hashlib
from uuid import uuid4

from django.contrib.auth.hashers import check_password
from django.core import signing

from agent.models import AgentConfig


TOKEN_SALT = "agent-control-token-v1"


def _get_config() -> AgentConfig:
    config = AgentConfig.objects.first()
    if config is None:
        config = AgentConfig.objects.create()
    return config


def _password_revision() -> str:
    config = _get_config()
    password_hash = getattr(config, "control_password_hash", "") or ""
    digest = hashlib.sha256(password_hash.encode("utf-8")).hexdigest()
    return digest[:16]


def control_password_configured() -> bool:
    config = _get_config()
    return bool((getattr(config, "control_password_hash", "") or "").strip())


def verify_control_password(password: str) -> bool:
    config = _get_config()
    hashed = getattr(config, "control_password_hash", "") or ""
    if not hashed:
        return False
    return check_password(password or "", hashed)


def issue_control_token() -> tuple[str, int]:
    config = _get_config()
    ttl_minutes = max(5, min(1440, int(getattr(config, "control_token_ttl_minutes", 120) or 120)))
    payload = {
        "scope": "agent_control",
        "nonce": uuid4().hex,
        "rev": _password_revision(),
    }
    token = signing.dumps(payload, salt=TOKEN_SALT, compress=True)
    return token, ttl_minutes * 60


def decode_control_token(token: str) -> dict | None:
    if not token:
        return None
    config = _get_config()
    ttl_minutes = max(5, min(1440, int(getattr(config, "control_token_ttl_minutes", 120) or 120)))
    try:
        payload = signing.loads(token, salt=TOKEN_SALT, max_age=ttl_minutes * 60)
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("scope") != "agent_control":
        return None
    if payload.get("rev") != _password_revision():
        return None
    return payload


def extract_control_token(request) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return (request.headers.get("X-Agent-Control-Token") or "").strip()
