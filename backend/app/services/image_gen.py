"""Text/image generation clients for canvas TextToImage nodes."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.api.uploads import local_upload_path, uploads_root
from app.models import Channel
from app.services import media_ops
from app.services.net import make_async_client

T2I_SIM_MODEL = "t2i-local-simulate"
DEMO_T2I_URL = "/uploads/_mock/demo_t2i_v1.png"
IMAGE_HTTP_TIMEOUT = httpx.Timeout(90.0, connect=8.0)
OPENAI_IMAGE_PROVIDERS = {"openai", "openai-compatible", "image-openai", "gpt-image"}


class ImageGenError(Exception):
    pass


def _openai_root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return "https://api.openai.com/v1"
    if root.endswith("/v1"):
        return root
    return f"{root}/v1"


def _public_upload_url(user_id: int, filename: str) -> str:
    return f"/uploads/{user_id}/{filename}"


def _guess_ext(content_type: str, fallback: str = ".png") -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(ct, fallback)


def _save_image_bytes(user_id: int, raw: bytes, *, ext: str = ".png") -> str:
    if not raw:
        raise ImageGenError("图像上游返回空文件")
    if len(raw) > 20 * 1024 * 1024:
        raise ImageGenError("图像上游返回文件过大")
    safe_ext = ext if ext.startswith(".") else f".{ext}"
    if safe_ext.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        safe_ext = ".png"
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}_t2i{safe_ext.lower()}"
    (user_dir / name).write_bytes(raw)
    return _public_upload_url(user_id, name)


def _extract_data_uri(data_uri: str) -> tuple[bytes, str]:
    head, _, body = data_uri.partition(",")
    if not body:
        raise ImageGenError("图像 data URI 无法解析")
    ext = ".png"
    if ";" in head:
        mime = head.split(":", 1)[-1].split(";", 1)[0]
        ext = _guess_ext(mime)
    try:
        return base64.b64decode(body), ext
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError("图像 base64 无法解析") from exc


async def _download_and_store(user_id: int, url: str) -> str:
    if url.startswith("data:"):
        raw, ext = _extract_data_uri(url)
        return _save_image_bytes(user_id, raw, ext=ext)
    try:
        async with make_async_client(timeout=IMAGE_HTTP_TIMEOUT) as client:
            resp = await client.get(url, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(f"下载生成图片失败：{exc}") from exc
    if resp.status_code >= 400:
        raise ImageGenError(f"下载生成图片失败 HTTP {resp.status_code}")
    ext = _guess_ext(resp.headers.get("content-type") or "")
    path_ext = Path(url.split("?", 1)[0]).suffix.lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        ext = path_ext
    return _save_image_bytes(user_id, resp.content, ext=ext)


def _first_image_item(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ImageGenError("图像上游返回无法解析")
    return items[0]


async def _generate_openai(
    channel: Channel,
    *,
    prompt: str,
    image_url: str | None,
    user_id: int | None,
) -> str:
    if user_id is None:
        raise ImageGenError("真实文生图需要 user_id 才能保存结果")
    key = (channel.api_key or "").strip()
    if not key:
        raise ImageGenError("未配置图像 API Key，请超管填写并启用渠道")
    model = (channel.upstream_model or channel.model_id or "").strip()
    if not model:
        raise ImageGenError("图像渠道未填写 upstream_model")

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
    }
    headers = {"Authorization": f"Bearer {key}"}
    local_ref = local_upload_path(image_url) if image_url else None
    try:
        async with make_async_client(timeout=IMAGE_HTTP_TIMEOUT) as client:
            if local_ref is not None:
                url = f"{_openai_root(channel.base_url)}/images/edits"
                files = {"image": (local_ref.name, local_ref.read_bytes(), "application/octet-stream")}
                resp = await client.post(url, headers=headers, data=payload, files=files)
            else:
                url = f"{_openai_root(channel.base_url)}/images/generations"
                json_headers = {**headers, "Content-Type": "application/json"}
                if image_url:
                    payload["image"] = image_url
                resp = await client.post(url, headers=json_headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(f"图像请求失败：{exc}") from exc
    if resp.status_code >= 400:
        raise ImageGenError(f"图像上游 HTTP {resp.status_code}：{(resp.text or '')[:400]}")

    item = _first_image_item(resp.json())
    if isinstance(item.get("b64_json"), str) and item["b64_json"].strip():
        try:
            raw = base64.b64decode(item["b64_json"])
        except Exception as exc:  # noqa: BLE001
            raise ImageGenError("图像上游 base64 无法解析") from exc
        return _save_image_bytes(user_id, raw, ext=".png")
    got_url = str(item.get("url") or "").strip()
    if got_url:
        return await _download_and_store(user_id, got_url)
    raise ImageGenError("图像上游没有返回 url 或 b64_json")


async def generate(
    channel: Channel,
    *,
    prompt: str,
    image_url: str | None = None,
    user_id: int | None = None,
) -> str:
    provider = (channel.provider or "").strip().lower()
    if provider in {"mock", "local-simulate", "simulate"} or channel.model_id == T2I_SIM_MODEL:
        try:
            return await media_ops.ensure_demo_t2i()
        except media_ops.MediaOpsError as exc:
            raise ImageGenError(str(exc)) from exc
    if provider in OPENAI_IMAGE_PROVIDERS:
        return await _generate_openai(channel, prompt=prompt, image_url=image_url, user_id=user_id)
    raise ImageGenError(f"暂未实现的图像 provider: {channel.provider}（可用 openai / openai-compatible / mock）")
