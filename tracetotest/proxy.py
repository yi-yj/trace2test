"""Separate model transport proxy policy from browser traffic proxy policy."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Mapping, MutableMapping
from urllib.parse import unquote, urlsplit, urlunsplit

_INTERNAL_SERVER = "TRACETOTEST_BROWSER_PROXY_SERVER"
_INTERNAL_ENABLED = "TRACETOTEST_BROWSER_PROXY_ENABLED"
_INTERNAL_SOURCE = "TRACETOTEST_BROWSER_PROXY_SOURCE"
_INTERNAL_BYPASS = "TRACETOTEST_BROWSER_PROXY_BYPASS"
_INTERNAL_USERNAME = "TRACETOTEST_BROWSER_PROXY_USERNAME"
_INTERNAL_PASSWORD = "TRACETOTEST_BROWSER_PROXY_PASSWORD"
_INTERNAL_NAMES = (
    _INTERNAL_ENABLED,
    _INTERNAL_SOURCE,
    _INTERNAL_SERVER,
    _INTERNAL_BYPASS,
    _INTERNAL_USERNAME,
    _INTERNAL_PASSWORD,
)


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean setting: {value!r}")


@dataclass(frozen=True)
class BrowserProxySettings:
    enabled: bool
    configured: bool
    source: str
    server: str | None = field(default=None, repr=False)
    bypass: str | None = field(default=None, repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def playwright(self) -> dict[str, str] | None:
        if not self.enabled or not self.server:
            return None
        value = {"server": self.server}
        for name in ("bypass", "username", "password"):
            item = getattr(self, name)
            if item:
                value[name] = item
        return value

    def safe_summary(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "source": self.source,
            "credentials_configured": bool(self.username or self.password),
        }


def resolve_browser_proxy(environment: Mapping[str, str] | None = None) -> BrowserProxySettings:
    """Resolve an explicit browser proxy without exposing its URL or credentials."""
    values = os.environ if environment is None else environment
    enabled = _enabled(values.get("BROWSER_PROXY_ENABLED"), default=True)
    if not enabled:
        return BrowserProxySettings(enabled=False, configured=False, source="disabled")

    candidates = (
        ("BROWSER_PROXY_SERVER", values.get("BROWSER_PROXY_SERVER")),
        ("HTTPS_PROXY", values.get("HTTPS_PROXY")),
        ("https_proxy", values.get("https_proxy")),
        ("HTTP_PROXY", values.get("HTTP_PROXY")),
        ("http_proxy", values.get("http_proxy")),
    )
    source, raw = next(((name, item.strip()) for name, item in candidates if item and item.strip()), ("none", ""))
    if not raw:
        return BrowserProxySettings(enabled=True, configured=False, source=source)

    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https", "socks5"} or not parsed.hostname:
        raise ValueError(f"{source} must be an HTTP(S) or SOCKS5 proxy URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"{source} must not contain a path, query, or fragment")
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    server = urlunsplit((parsed.scheme.casefold(), netloc, "", "", ""))
    bypass = (
        values.get("BROWSER_PROXY_BYPASS")
        or values.get("NO_PROXY")
        or values.get("no_proxy")
        or "localhost,127.0.0.1"
    ).strip()
    username = values.get("BROWSER_PROXY_USERNAME") or (
        unquote(parsed.username) if parsed.username else None
    )
    password = values.get("BROWSER_PROXY_PASSWORD") or (
        unquote(parsed.password) if parsed.password else None
    )
    return BrowserProxySettings(
        enabled=True,
        configured=True,
        source=source,
        server=server,
        bypass=bypass or None,
        username=username,
        password=password,
    )


def install_browser_proxy_environment(
    environment: MutableMapping[str, str], settings: BrowserProxySettings
) -> None:
    """Pass proxy settings privately to browser adapters, including subprocess adapters."""
    for name in _INTERNAL_NAMES:
        environment.pop(name, None)
    environment[_INTERNAL_ENABLED] = "true" if settings.enabled else "false"
    environment[_INTERNAL_SOURCE] = settings.source
    proxy = settings.playwright()
    if not proxy:
        return
    mapping = {
        _INTERNAL_SERVER: proxy.get("server"),
        _INTERNAL_BYPASS: proxy.get("bypass"),
        _INTERNAL_USERNAME: proxy.get("username"),
        _INTERNAL_PASSWORD: proxy.get("password"),
    }
    environment.update({name: value for name, value in mapping.items() if value})


@contextmanager
def browser_proxy_environment(settings: BrowserProxySettings):
    """Temporarily expose the browser-only proxy handoff to an in-process adapter."""
    previous = {name: os.environ.get(name) for name in _INTERNAL_NAMES}
    install_browser_proxy_environment(os.environ, settings)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def runtime_browser_proxy(environment: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """Read the private adapter handoff without consulting model proxy variables."""
    values = os.environ if environment is None else environment
    server = values.get(_INTERNAL_SERVER)
    if not server:
        return None
    proxy = {"server": server}
    for source, target in (
        (_INTERNAL_BYPASS, "bypass"),
        (_INTERNAL_USERNAME, "username"),
        (_INTERNAL_PASSWORD, "password"),
    ):
        if values.get(source):
            proxy[target] = values[source]
    return proxy


def runtime_browser_proxy_summary(
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    values = os.environ if environment is None else environment
    proxy = runtime_browser_proxy(values)
    return {
        "enabled": _enabled(values.get(_INTERNAL_ENABLED), default=False),
        "configured": proxy is not None,
        "source": values.get(_INTERNAL_SOURCE, "none"),
        "credentials_configured": bool(proxy and (proxy.get("username") or proxy.get("password"))),
    }
