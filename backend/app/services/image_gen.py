"""Text/image generation clients for canvas TextToImage nodes."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.api.uploads import local_upload_path, uploads_root
from app.models import Channel
from app.services.net import make_async_client

IMAGE_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=8.0)
OPENAI_IMAGE_PROVIDERS = {"openai", "openai-compatible", "image-openai", "gpt-image"}
GEMINI_IMAGE_PROVIDERS = {"gemini", "google", "goog", "vectorengine", "vector-engine", "ve"}
DEFAULT_GEMINI_IMAGE_BASE = "https://api.vectorengine.ai"
IMAGE_SIZE_TO_GEMINI = {
    "1024x1024": ("1:1", "1K"),
    "512x512": ("1:1", "1K"),
    "1024x1792": ("9:16", "1K"),
    "1792x1024": ("16:9", "1K"),
    "1:1": ("1:1", "1K"),
    "9:16": ("9:16", "1K"),
    "16:9": ("16:9", "1K"),
    "4:3": ("4:3", "1K"),
    "3:4": ("3:4", "1K"),
    "1k": ("1:1", "1K"),
    "2k": ("1:1", "2K"),
    "4k": ("1:1", "4K"),
}


class ImageGenError(Exception):
    pass


def _openai_root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return "https://api.openai.com/v1"
    if root.endswith("/v1"):
        return root
    return f"{root}/v1"


def _gemini_root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return DEFAULT_GEMINI_IMAGE_BASE
    lowered = root.lower()
    for suffix in ("/v1beta", "/v1"):
        if lowered.endswith(suffix):
            root = root[: -len(suffix)].rstrip("/")
            break
    return root or DEFAULT_GEMINI_IMAGE_BASE


def is_gemini_image_model(model: str) -> bool:
    m = (model or "").strip().lower()
    if not m:
        return False
    if "gemini" in m and "image" in m:
        return True
    if m.startswith("imagen"):
        return True
    compact = m.replace(" ", "").replace("_", "-")
    return "nano-banana" in compact or "nanobanana" in compact


def is_gemini_image_channel(channel: Channel) -> bool:
    provider = (channel.provider or "").strip().lower()
    model = (channel.upstream_model or channel.model_id or "").strip()
    if provider in GEMINI_IMAGE_PROVIDERS:
        return True
    return is_gemini_image_model(model)


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
    size: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    batch_size: int = 1,
    image_strength: float | None = None,
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
        "n": max(1, min(int(batch_size or 1), 4)),
        "size": (size or "1024x1024").strip() or "1024x1024",
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = int(seed)
    if image_strength is not None and image_url:
        payload["image_strength"] = float(image_strength)
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


def _gemini_size(size: str | None) -> tuple[str, str]:
    raw = (size or "").strip()
    mapped = IMAGE_SIZE_TO_GEMINI.get(raw) or IMAGE_SIZE_TO_GEMINI.get(raw.lower())
    if mapped:
        return mapped
    if "x" in raw.lower():
        try:
            w_s, h_s = raw.lower().split("x", 1)
            w, h = int(w_s), int(h_s)
            if w > 0 and h > 0:
                ratio = w / h
                if abs(ratio - 1) < 0.08:
                    return "1:1", "1K"
                if ratio < 0.8:
                    return "9:16", "1K"
                if ratio > 1.25:
                    return "16:9", "1K"
        except ValueError:
            pass
    return "1:1", "1K"


def _gemini_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "x-goog-api-key": key,
        "Content-Type": "application/json",
    }


def _inline_ref_part(image_url: str | None) -> dict[str, Any] | None:
    local = local_upload_path(image_url) if image_url else None
    if local is None or not local.is_file():
        return None
    raw = local.read_bytes()
    if not raw:
        return None
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(local.suffix.lower(), "image/png")
    return {
        "inline_data": {
            "mime_type": mime,
            "data": base64.b64encode(raw).decode("ascii"),
        }
    }


def _extract_gemini_image(data: dict[str, Any]) -> tuple[bytes, str]:
    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        raise ImageGenError(f"Gemini 上游错误：{err.get('message')}")
    for cand in data.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content") if isinstance(cand.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if not isinstance(inline, dict):
                continue
            b64 = str(inline.get("data") or "").strip()
            if not b64:
                continue
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
            try:
                return base64.b64decode(b64), _guess_ext(mime)
            except Exception as exc:  # noqa: BLE001
                raise ImageGenError("Gemini 图像 base64 无法解析") from exc
    try:
        item = _first_image_item(data)
    except ImageGenError:
        item = None
    if isinstance(item, dict):
        if isinstance(item.get("b64_json"), str) and item["b64_json"].strip():
            try:
                return base64.b64decode(item["b64_json"]), ".png"
            except Exception as exc:  # noqa: BLE001
                raise ImageGenError("Gemini 图像 base64 无法解析") from exc
        url = str(item.get("url") or "").strip()
        if url:
            raise ImageGenError(f"GEMINI_URL:{url}")
    raise ImageGenError("Gemini 上游没有返回图片")


async def _generate_gemini(
    channel: Channel,
    *,
    prompt: str,
    image_url: str | None,
    user_id: int | None,
    size: str | None = None,
    negative_prompt: str | None = None,
) -> str:
    if user_id is None:
        raise ImageGenError("真实文生图需要 user_id 才能保存结果")
    key = (channel.api_key or "").strip()
    if not key:
        raise ImageGenError("未配置图像 API Key，请超管填写并启用渠道")
    model = (channel.upstream_model or channel.model_id or "").strip()
    if not model:
        raise ImageGenError("图像渠道未填写 upstream_model")
    model = model.replace("models/", "", 1).strip("/")
    text = (prompt or "").strip()
    if negative_prompt:
        text = f"{text}\n不要出现：{negative_prompt.strip()}"
    parts: list[dict[str, Any]] = [{"text": text}]
    ref = _inline_ref_part(image_url)
    if ref:
        parts.append(ref)
    aspect, image_size = _gemini_size(size)
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect, "imageSize": image_size},
        },
    }
    root = _gemini_root(channel.base_url)
    url = f"{root}/v1beta/models/{model}:generateContent"
    headers = _gemini_headers(key)
    try:
        async with make_async_client(timeout=IMAGE_HTTP_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload, params={"key": key})
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(f"Gemini 图像请求失败：{exc}") from exc
    if resp.status_code >= 400:
        raise ImageGenError(f"Gemini 上游 HTTP {resp.status_code}：{(resp.text or '')[:400]}")
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError("Gemini 上游返回无法解析") from exc
    if not isinstance(data, dict):
        raise ImageGenError("Gemini 上游返回无法解析")
    try:
        raw, ext = _extract_gemini_image(data)
    except ImageGenError as exc:
        msg = str(exc)
        if msg.startswith("GEMINI_URL:"):
            return await _download_and_store(user_id, msg.split(":", 1)[1])
        raise
    return _save_image_bytes(user_id, raw, ext=ext)


async def generate(
    channel: Channel,
    *,
    prompt: str,
    image_url: str | None = None,
    user_id: int | None = None,
    size: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    batch_size: int = 1,
    image_strength: float | None = None,
) -> str:
    provider = (channel.provider or "").strip().lower()
    if is_gemini_image_channel(channel):
        try:
            return await _generate_gemini(
                channel,
                prompt=prompt,
                image_url=image_url,
                user_id=user_id,
                size=size,
                negative_prompt=negative_prompt,
            )
        except ImageGenError as exc:
            detail = str(exc)
            if provider in OPENAI_IMAGE_PROVIDERS and any(code in detail for code in ("HTTP 404", "HTTP 405")):
                return await _generate_openai(
                    channel,
                    prompt=prompt,
                    image_url=image_url,
                    user_id=user_id,
                    size=size,
                    negative_prompt=negative_prompt,
                    seed=seed,
                    batch_size=batch_size,
                    image_strength=image_strength,
                )
            raise
    if provider in OPENAI_IMAGE_PROVIDERS:
        return await _generate_openai(
            channel,
            prompt=prompt,
            image_url=image_url,
            user_id=user_id,
            size=size,
            negative_prompt=negative_prompt,
            seed=seed,
            batch_size=batch_size,
            image_strength=image_strength,
        )
    raise ImageGenError(
        f"暂未实现的图像 provider: {channel.provider}（请用 gemini / vectorengine / openai）"
    )
