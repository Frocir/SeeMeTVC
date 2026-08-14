"""Lightweight upstream probe for admin channel list."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.models import Channel
from app.services import llm as llm_svc
from app.services.net import make_async_client

PROBE_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
PROBE_USER = "Reply with the single word ok."


class ProbeResult:
    def __init__(self, ok: bool, message: str, latency_ms: int, detail: str = "") -> None:
        self.ok = ok
        self.message = message
        self.latency_ms = latency_ms
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
        }


def _ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _clip(text: str, n: int = 240) -> str:
    raw = (text or "").strip().replace("\n", " ")
    return raw if len(raw) <= n else raw[: n - 1] + "…"


async def probe_channel(channel: Channel) -> ProbeResult:
    started = time.monotonic()
    kind = (channel.kind or "video").strip().lower()
    provider = (channel.provider or "").strip().lower()
    try:
        if provider in {"mock", "local-simulate", "simulate"} or llm_svc.is_simulate_channel(channel):
            return ProbeResult(True, "本地模拟渠道，无需探活", _ms(started))
        if kind == "llm":
            return await _probe_llm(channel, started)
        if kind == "tts":
            return await _probe_tts(channel, started)
        if kind == "image":
            return ProbeResult(False, "本轮文生图只支持本地模拟，真模型未接入", _ms(started))
        if provider in {"agnes", "pavo", "agnes-pavo"}:
            return await _probe_agnes(channel, started)
        if provider in {"ark", "volc", "volcengine", "fal"}:
            return await _probe_ark(channel, started)
        return ProbeResult(False, f"暂不支持探活 provider={provider or '空'}", _ms(started))
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, f"探活异常：{exc}", _ms(started))


async def _probe_llm(channel: Channel, started: float) -> ProbeResult:
    key = (channel.api_key or "").strip()
    if not key:
        return ProbeResult(False, "未填写 API Key，无法探活", _ms(started))
    model = (channel.upstream_model or channel.model_id or "").strip()
    if not model:
        return ProbeResult(False, "未填写 upstream_model / model_id", _ms(started))
    provider = (channel.provider or "openai").lower()
    if provider == "anthropic":
        return await _probe_anthropic(channel, key=key, model=model, started=started)
    return await _probe_openai(channel, key=key, model=model, started=started)


async def _probe_anthropic(channel: Channel, *, key: str, model: str, started: float) -> ProbeResult:
    root = llm_svc._anthropic_root(channel.base_url)
    url = f"{root}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": PROBE_USER}],
    }
    headers = llm_svc.anthropic_headers(key, base_url=channel.base_url)
    try:
        async with make_async_client(timeout=PROBE_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, f"连不上 Anthropic 兼容接口：{exc}", _ms(started), url)

    if resp.status_code < 400:
        return ProbeResult(True, f"Anthropic Messages 探活成功（{model}）", _ms(started), url)

    # Gateways may only expose OpenAI Chat Completions, or reject x-api-key.
    if resp.status_code in {401, 403, 404, 405, 422}:
        fallback = await _probe_openai(channel, key=key, model=model, started=started)
        if fallback.ok:
            fallback.message = f"Messages 不可用，已用 OpenAI 兼容口探活成功（{model}）"
            return fallback
        if resp.status_code in {401, 403}:
            return ProbeResult(
                False,
                f"网关已连通，但 Key 无效（HTTP {resp.status_code}）。请「改 Key」重新粘贴完整 token。",
                _ms(started),
                _clip(resp.text),
            )
        return ProbeResult(
            False,
            f"Messages HTTP {resp.status_code}，OpenAI 兼容口也失败：{fallback.message}",
            _ms(started),
            _clip(resp.text),
        )

    return ProbeResult(
        False,
        f"Anthropic 上游 HTTP {resp.status_code}：{_clip(resp.text)}",
        _ms(started),
        url,
    )


async def _probe_openai(channel: Channel, *, key: str, model: str, started: float) -> ProbeResult:
    url = f"{llm_svc._openai_root(channel.base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROBE_USER}],
        "max_tokens": 16,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with make_async_client(timeout=PROBE_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, f"连不上 OpenAI 兼容接口：{exc}", _ms(started), url)
    if resp.status_code >= 400:
        return ProbeResult(
            False,
            f"OpenAI 兼容上游 HTTP {resp.status_code}：{_clip(resp.text)}",
            _ms(started),
            url,
        )
    return ProbeResult(True, f"OpenAI 兼容探活成功（{model}）", _ms(started), url)


async def _probe_tts(channel: Channel, started: float) -> ProbeResult:
    base = (channel.base_url or "").strip().rstrip("/")
    if not base:
        return ProbeResult(False, "TTS 渠道未填写 Base URL", _ms(started))
    key = (channel.api_key or "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with make_async_client(timeout=PROBE_TIMEOUT) as client:
            resp = await client.get(f"{base}/health", headers=headers)
            if resp.status_code >= 400:
                resp = await client.get(f"{base}/v1/models", headers=headers)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, f"连不上 TTS：{exc}", _ms(started), base)
    if resp.status_code >= 400:
        return ProbeResult(False, f"TTS HTTP {resp.status_code}：{_clip(resp.text)}", _ms(started), base)
    return ProbeResult(True, "TTS 探活成功", _ms(started), base)


async def _probe_ark(channel: Channel, started: float) -> ProbeResult:
    key = (channel.api_key or "").strip()
    if not key:
        return ProbeResult(False, "未填写 ARK_API_KEY，无法探活", _ms(started))
    base = (channel.base_url or "https://ark.cn-beijing.volces.com").strip().rstrip("/")
    url = f"{base}/api/v3/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with make_async_client(timeout=PROBE_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, f"连不上方舟：{exc}", _ms(started), url)
    if resp.status_code >= 400:
        return ProbeResult(False, f"方舟 HTTP {resp.status_code}：{_clip(resp.text)}", _ms(started), url)
    return ProbeResult(True, "火山方舟探活成功", _ms(started), url)


async def _probe_agnes(channel: Channel, started: float) -> ProbeResult:
    key = (channel.api_key or "").strip()
    if not key:
        return ProbeResult(False, "未填写 Agnes Key，无法探活", _ms(started))
    base = (channel.base_url or "https://api.agnes-ai.cn").strip().rstrip("/")
    url = f"{base.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with make_async_client(timeout=PROBE_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                resp = await client.get(base, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, f"连不上 Agnes：{exc}", _ms(started), url)
    if resp.status_code >= 400:
        return ProbeResult(False, f"Agnes HTTP {resp.status_code}：{_clip(resp.text)}", _ms(started), url)
    return ProbeResult(True, "Agnes 探活成功", _ms(started), url)
