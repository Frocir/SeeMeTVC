"""Minimal OpenAI-compatible TTS for machines without Docker.

Uses the `edge-tts` library (not a copy of travisvn/openai-edge-tts).
POST /v1/audio/speech  Authorization: Bearer $API_KEY
"""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

API_KEY = (os.environ.get("API_KEY") or os.environ.get("AISRV_API_KEY") or "").strip()
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE") or "zh-CN-XiaoxiaoNeural"

app = FastAPI(title="SeeMeTVC aisrv", version="0.1.0")


class SpeechIn(BaseModel):
    input: str
    voice: str | None = None
    model: str | None = "tts-1"
    response_format: str | None = "mp3"


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "aisrv", "voice": DEFAULT_VOICE}


@app.post("/v1/audio/speech")
async def speech(body: SpeechIn, authorization: str | None = Header(default=None)) -> Response:
    token = (authorization or "").replace("Bearer", "").strip()
    if API_KEY and token != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    text = (body.input or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="input required")
    try:
        import edge_tts
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="未安装 edge-tts：pip install edge-tts") from exc
    voice = (body.voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    communicate = edge_tts.Communicate(text[:4096], voice)
    chunks: list[bytes] = []

    async def _collect() -> None:
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])

    try:
        await asyncio.wait_for(_collect(), timeout=20.0)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="edge-tts 超时：连不上微软语音服务") from exc
    if not chunks:
        raise HTTPException(status_code=502, detail="edge-tts 未返回音频")
    return Response(content=b"".join(chunks), media_type="audio/mpeg")
