"""OpenAI-compatible speech-to-text for canvas SpeechToText nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models import Channel
from app.services import media_ops
from app.services.net import make_async_client

ASR_TIMEOUT = httpx.Timeout(120.0, connect=8.0)


class AsrError(Exception):
    pass


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscribeResult:
    text: str
    segments: list[TranscriptSegment]
    srt: str
    raw: dict[str, Any] = field(default_factory=dict)


def _openai_root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return "https://api.openai.com/v1"
    if root.endswith("/v1"):
        return root
    return f"{root}/v1"


def _transcriptions_url(base_url: str) -> str:
    return f"{_openai_root(base_url)}/audio/transcriptions"


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    if not segments:
        return ""

    def _ts(sec: float) -> str:
        total_ms = max(0, int(round(float(sec) * 1000)))
        hours, rem = divmod(total_ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, millis = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        text = (seg.text or "").strip()
        if not text:
            continue
        start = max(0.0, float(seg.start or 0))
        end = max(start + 0.2, float(seg.end or 0))
        lines.append(str(i))
        lines.append(f"{_ts(start)} --> {_ts(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def _segments_from_payload(payload: dict[str, Any], fallback_text: str) -> list[TranscriptSegment]:
    raw_segs = payload.get("segments")
    out: list[TranscriptSegment] = []
    if isinstance(raw_segs, list):
        for item in raw_segs:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start = float(item.get("start") or 0)
            end = float(item.get("end") or start)
            out.append(TranscriptSegment(start=start, end=max(start + 0.2, end), text=text))
    if out:
        return out
    text = (fallback_text or "").strip()
    if not text:
        return []
    return [TranscriptSegment(start=0.0, end=6.0, text=text)]


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }.get(ext, "application/octet-stream")


async def _prepare_audio(user_id: int | None, media_url: str) -> Path:
    uid = int(user_id or 0)
    try:
        _, path = await media_ops.extract_audio(uid if uid > 0 else 0, media_url)
    except media_ops.MediaOpsError as exc:
        raise AsrError(str(exc)) from exc
    if not path.is_file() or path.stat().st_size < 64:
        raise AsrError("抽音频失败，无法转写")
    return path


async def transcribe(
    channel: Channel,
    *,
    media_url: str,
    user_id: int | None = None,
    language: str | None = "zh",
) -> TranscribeResult:
    """Transcribe audio or video via the configured ASR channel."""
    url = (media_url or "").strip()
    if not url:
        raise AsrError("口播提取缺少输入音视频")

    key = (channel.api_key or "").strip()
    if not key:
        raise AsrError("未配置 ASR API Key，请超管填写并启用渠道")
    model = (channel.upstream_model or channel.model_id or "whisper-1").strip() or "whisper-1"
    lang = (language or "").strip().lower()
    if lang in {"auto", "detect", ""}:
        lang = ""

    audio_path = await _prepare_audio(user_id, url)
    endpoint = _transcriptions_url(channel.base_url)
    headers = {"Authorization": f"Bearer {key}"}
    form = {
        "model": model,
        "response_format": "verbose_json",
    }
    if lang:
        form["language"] = lang[:16]
    try:
        async with make_async_client(timeout=ASR_TIMEOUT, force_direct=_is_local(endpoint)) as client:
            resp = await client.post(
                endpoint,
                headers=headers,
                data=form,
                files={"file": (audio_path.name, audio_path.read_bytes(), _guess_mime(audio_path))},
            )
    except Exception as exc:  # noqa: BLE001
        raise AsrError(f"ASR 请求失败：{exc}") from exc
    if resp.status_code >= 400:
        raise AsrError(f"ASR 上游 HTTP {resp.status_code}：{(resp.text or '')[:300]}")
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise AsrError("ASR 返回不是 JSON") from exc
    if not isinstance(payload, dict):
        raise AsrError("ASR 返回无法解析")
    text = str(payload.get("text") or "").strip()
    segments = _segments_from_payload(payload, text)
    if not text:
        text = " ".join(s.text for s in segments).strip()
    if not text:
        raise AsrError("ASR 没有识别出文本")
    return TranscribeResult(
        text=text,
        segments=segments,
        srt=segments_to_srt(segments),
        raw=payload,
    )
