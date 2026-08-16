"""Local network / proxy auto-detection for upstream HTTP clients.

Rules:
1. If a local SOCKS proxy is listening and socksio is available → use SOCKS.
2. Else if a local HTTP proxy is listening → use HTTP proxy.
3. Else assume domestic direct access (no proxy).

Detection result is cached briefly so Clash on/off is picked up without restart.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_COMMON_SOCKS_PORTS = (7897, 7891, 7890, 1080, 10808, 1086)
_COMMON_HTTP_PORTS = (7897, 7890, 7892, 10809, 1087, 8118)
_CACHE_TTL_SEC = 20.0


@dataclass(frozen=True)
class ProxyPlan:
    mode: str  # socks | http | direct
    proxy_url: str | None
    reason: str


_cached_plan: ProxyPlan | None = None
_cached_at = 0.0


def _tcp_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_proxy(url: str) -> tuple[str, str, int] | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    host = parsed.hostname or os.environ.get("LOCAL_PROXY_HOST", "127.0.0.1")
    if parsed.port is None:
        return None
    scheme = (parsed.scheme or "http").lower()
    return scheme, host, parsed.port


def _env_proxy_candidates() -> list[str]:
    keys = (
        "UPSTREAM_HTTP_PROXY",
        "ALL_PROXY",
        "all_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    )
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        val = (os.environ.get(key) or "").strip()
        if val and val not in seen:
            seen.add(val)
            out.append(val)
    return out


def _socksio_available() -> bool:
    try:
        import socksio  # noqa: F401

        return True
    except ImportError:
        return False


def _normalize_socks_url(candidate: str, host: str, port: int) -> str:
    if "://" in candidate:
        url = candidate
        if url.startswith("socks://"):
            url = "socks5://" + url[len("socks://") :]
        return url
    return f"socks5://{host}:{port}"


def _detect_proxy_plan_uncached() -> ProxyPlan:
    for candidate in _env_proxy_candidates():
        parsed = _parse_proxy(candidate)
        if not parsed:
            continue
        scheme, host, port = parsed
        if not _tcp_open(host, port):
            continue
        if scheme.startswith("socks"):
            if _socksio_available():
                return ProxyPlan(
                    "socks",
                    _normalize_socks_url(candidate, host, port),
                    f"env SOCKS listening on {host}:{port}",
                )
            return ProxyPlan(
                "http",
                f"http://{host}:{port}",
                f"SOCKS open but socksio missing; HTTP fallback {host}:{port}",
            )
        return ProxyPlan(
            "http",
            candidate if "://" in candidate else f"http://{candidate}",
            f"env HTTP proxy {host}:{port}",
        )

    probe_host = os.environ.get("LOCAL_PROXY_HOST", "127.0.0.1")

    for port in _COMMON_SOCKS_PORTS:
        if not _tcp_open(probe_host, port):
            continue
        if _socksio_available():
            return ProxyPlan("socks", f"socks5://{probe_host}:{port}", f"local SOCKS open on :{port}")
        return ProxyPlan("http", f"http://{probe_host}:{port}", f"local proxy :{port} (HTTP fallback)")

    for port in _COMMON_HTTP_PORTS:
        if _tcp_open(probe_host, port):
            return ProxyPlan("http", f"http://{probe_host}:{port}", f"local HTTP proxy open on :{port}")

    return ProxyPlan("direct", None, "no local proxy detected; domestic direct")


def detect_proxy_plan(*, force: bool = False) -> ProxyPlan:
    global _cached_plan, _cached_at
    now = time.monotonic()
    if not force and _cached_plan is not None and (now - _cached_at) < _CACHE_TTL_SEC:
        return _cached_plan
    _cached_plan = _detect_proxy_plan_uncached()
    _cached_at = now
    return _cached_plan


def clear_proxy_plan_cache() -> None:
    global _cached_plan, _cached_at
    _cached_plan = None
    _cached_at = 0.0


def make_async_client(timeout: float = 60.0, *, force_direct: bool = False) -> httpx.AsyncClient:
    if force_direct:
        return httpx.AsyncClient(timeout=timeout, trust_env=False)
    plan = detect_proxy_plan()
    if plan.proxy_url:
        return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=plan.proxy_url)
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


_TRANSIENT_HTTPX = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
)
_TRANSIENT_HINTS = (
    "disconnected",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "forcibly closed",
    "winerror 10054",
    "winerror 10053",
    "server disconnected",
    "network is unreachable",
)


def is_transient_httpx(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_HTTPX):
        return True
    msg = str(exc).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


def describe_upstream_disconnect(exc: BaseException, *, who: str) -> str:
    """Human error that names which Key/channel dropped, not a vague 网关."""
    raw = str(exc).strip() or exc.__class__.__name__
    clip = raw if len(raw) <= 180 else raw[:179] + "…"
    if is_transient_httpx(exc):
        return (
            f"{who}连接被断开（不是对话/出片 Key 填错时的典型 401）。"
            f"多半是上游网关或线路闪断，请重试；连续失败再去超管对该渠道点探活。详情：{clip}"
        )
    return f"{who}请求失败：{clip}"


def resolve_agnes_base_url(configured: str | None) -> str:
    """Pick Agnes endpoint by network mode.

    - Direct / domestic: prefer China site api.agnes-ai.cn
    - Proxy available: keep explicit channel URL; default to international hub
    """
    configured = (configured or "").rstrip("/")
    plan = detect_proxy_plan()
    cn = "https://api.agnes-ai.cn"
    intl = "https://apihub.agnes-ai.com"

    if plan.mode == "direct":
        if not configured or "agnes-ai.com" in configured or configured.endswith("apihub.agnes-ai.cn"):
            return cn
        return configured

    if configured:
        return configured
    return intl


def agnes_should_force_direct(base_url: str) -> bool:
    """China Agnes gateways are usually better reached without overseas SOCKS."""
    return "agnes-ai.cn" in (base_url or "")
