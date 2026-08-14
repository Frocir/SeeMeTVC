"""Local-simulate text-to-image for canvas TextToImage nodes."""

from __future__ import annotations

from app.models import Channel
from app.services import media_ops

T2I_SIM_MODEL = "t2i-local-simulate"
DEMO_T2I_URL = "/uploads/_mock/demo_t2i_v1.png"


class ImageGenError(Exception):
    pass


async def generate(channel: Channel, *, prompt: str, image_url: str | None = None) -> str:
    _ = prompt, image_url
    provider = (channel.provider or "").strip().lower()
    if provider in {"mock", "local-simulate", "simulate"} or channel.model_id == T2I_SIM_MODEL:
        try:
            return await media_ops.ensure_demo_t2i()
        except media_ops.MediaOpsError as exc:
            raise ImageGenError(str(exc)) from exc
    raise ImageGenError("本轮只支持本地文生图模拟，未接真模型")
