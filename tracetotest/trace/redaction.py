"""Conservative redaction for trace fields that may contain credentials."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "cookies",
        "password",
        "passwd",
        "session",
        "signature",
        "refresh_token",
        "secret",
        "set-cookie",
        "storage_state",
        "token",
    }
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_DASHSCOPE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization|cookie)"
    r"(\s*[:=]\s*)(?:[\"']?)([^\s,;\"'<>\]}]+)"
)


def is_sensitive_key(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return normalized in {item.replace("-", "_") for item in SENSITIVE_KEYS} or any(
        marker in normalized for marker in ("password", "passwd", "secret", "token", "api_key", "cookie")
    )


def redact_text(value: str) -> str:
    value = _DASHSCOPE_KEY.sub(REDACTED, _BEARER.sub(f"Bearer {REDACTED}", value))
    value = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", value)
    return _EMAIL.sub(REDACTED, value)


def redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return redact_text(value)
    if not parts.scheme or not parts.netloc:
        return redact_text(value)
    query = [
        (key, REDACTED if is_sensitive_key(key) else redact_text(item))
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    fragment = REDACTED if any(is_sensitive_key(key) for key, _ in parse_qsl(parts.fragment)) else redact_text(parts.fragment)
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), fragment))


def redact(value: Any, *, key: str | None = None) -> Any:
    if key and is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_url(value) if value.startswith(("http://", "https://")) else redact_text(value)
    return value
