"""OpenAI-compatible speech via aisrv (edge-tts)."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.api.uploads import uploads_root
from app.models import Channel
from app.services.net import make_async_client

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_TIMEOUT = httpx.Timeout(25.0, connect=5.0)


class TtsError(Exception):
    pass


def _speech_url(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        raise TtsError("TTS 渠道未填写 base_url（aisrv 地址）")
    if root.endswith("/v1"):
        return f"{root}/audio/speech"
    return f"{root}/v1/audio/speech"


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


async def synthesize(channel: Channel, *, text: str, voice: str | None = None) -> str:
    """Call /v1/audio/speech and store mp3 under uploads. Returns public URL."""
    text = (text or "").strip()
    if not text:
        raise TtsError("TTS 缺少口播文本")
    key = (channel.api_key or "").strip()
    model = (channel.upstream_model or channel.model_id or "tts-1").strip() or "tts-1"
    chosen = (voice or "").strip() or DEFAULT_VOICE
    url = _speech_url(channel.base_url)
    payload = {
        "model": model,
        "input": text[:4096],
        "voice": chosen,
        "response_format": "mp3",
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with make_async_client(timeout=TTS_TIMEOUT, force_direct=_is_local(url)) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise TtsError(
            f"TTS 请求失败（本机 aisrv 约 25 秒未响应即超时，请确认 5050 已启动）：{exc}"
        ) from exc
    if resp.status_code >= 400:
        raise TtsError(f"TTS 上游 HTTP {resp.status_code}：{(resp.text or '')[:300]}")
    raw = resp.content
    if not raw or len(raw) < 64:
        raise TtsError("TTS 返回空音频")
    user_dir = uploads_root() / "_tts"
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}_tts.mp3"
    (user_dir / name).write_bytes(raw)
    return f"/uploads/_tts/{name}"


def public_to_path(url: str) -> Path | None:
    if not url.startswith("/uploads/"):
        return None
    rel = url[len("/uploads/") :]
    candidate = uploads_root() / rel
    return candidate if candidate.is_file() else None
