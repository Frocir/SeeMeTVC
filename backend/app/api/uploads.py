"""Resolve reference images for remote video providers.

Remote APIs (Agnes/fal) cannot fetch localhost / LAN / Vite static URLs.
Local uploads and other private URLs are inlined as data URIs.
"""

from __future__ import annotations

import base64
import ipaddress
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
MAX_BYTES = 10 * 1024 * 1024
VIDEO_EXT = {".mp4", ".webm", ".mov"}
VIDEO_MIME = {"video/mp4", "video/webm", "video/quicktime"}
MAX_VIDEO_BYTES = 80 * 1024 * 1024
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac"}
AUDIO_MIME = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac", "audio/m4a"}
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class UploadOut(BaseModel):
    url: str
    filename: str
    size: int


def uploads_root() -> Path:
    root = Path(get_settings().upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_ext(filename: str | None, content_type: str | None) -> str:
    name = (filename or "").lower()
    for ext in ALLOWED_EXT:
        if name.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    mime = (content_type or "").lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, "")


def local_upload_path(image_url: str | None) -> Path | None:
    """If URL points at our /uploads/... store, return filesystem path."""
    if not image_url:
        return None
    path = urlparse(image_url).path if "://" in image_url else image_url
    m = re.fullmatch(
        r"/uploads/(\d+)/([a-z0-9_/-]*[a-f0-9]{32}(?:_(?:mux|trim|mix|demux|tts|bgm|vo|t2i|frame\d+))?\.(jpg|jpeg|png|webp|gif|mp4|webm|mov|mp3|wav|m4a|aac)|video_reverse/[a-f0-9]{32}/scene_\d{3}\.(jpg|jpeg|png|webp))",
        path,
        re.I,
    )
    if not m:
        return None
    user_id, filename = m.group(1), m.group(2)
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        return None
    candidate = uploads_root() / user_id / filename
    if candidate.is_file():
        return candidate
    return None


def _bytes_to_data_uri(raw: bytes, mime: str | None = None) -> str:
    mt = mime or "application/octet-stream"
    return f"data:{mt};base64,{base64.b64encode(raw).decode('ascii')}"


def _is_non_public_host(host: str | None) -> bool:
    if not host:
        return True
    h = host.lower().strip("[]")
    if h in {"localhost", "127.0.0.1", "::1"} or h.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def needs_inline_for_upstream(image_url: str) -> bool:
    if image_url.startswith("data:"):
        return False
    if local_upload_path(image_url) is not None:
        return True
    parsed = urlparse(image_url if "://" in image_url else f"http://local{image_url}")
    path = parsed.path or ""
    if path.startswith("/beauty/") or path.startswith("/uploads/"):
        return True
    if "://" not in image_url and image_url.startswith("/"):
        return True
    return _is_non_public_host(parsed.hostname)


def resolve_image_for_upstream(image_url: str | None) -> str | None:
    """Sync resolve: local uploads → data URI; leave public URLs unchanged."""
    if not image_url:
        return None
    if image_url.startswith("data:"):
        return image_url
    path = local_upload_path(image_url)
    if path is not None:
        mime = MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
        return _bytes_to_data_uri(path.read_bytes(), mime)
    return image_url


async def async_resolve_image_for_upstream(image_url: str | None) -> str | None:
    """Convert private/local reference images to data URIs for Agnes/fal."""
    if not image_url:
        return None
    if image_url.startswith("data:"):
        return image_url

    path = local_upload_path(image_url)
    if path is not None:
        mime = MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
        return _bytes_to_data_uri(path.read_bytes(), mime)

    if not needs_inline_for_upstream(image_url):
        return image_url

    fetch_url = image_url
    if image_url.startswith("/"):
        base = (get_settings().public_asset_base_url or "").rstrip("/")
        if not base:
            raise RuntimeError(
                "参考图是站点内相对地址，且未配置 PUBLIC_ASSET_BASE_URL。"
                "请改用「上传」本地文件。"
            )
        fetch_url = f"{base}{image_url}"

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.get(fetch_url)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")
            raw = resp.content
            if not raw or len(raw) > MAX_BYTES:
                raise RuntimeError("empty or too large")
            mime = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            if mime not in ALLOWED_MIME:
                ext = Path(urlparse(fetch_url).path).suffix.lower()
                mime = MIME_BY_EXT.get(ext, "image/jpeg")
            return _bytes_to_data_uri(raw, mime)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "参考图地址无法被上游访问（本机/局域网 URL）。请改用「上传」本地文件，或使用公网可访问的图片链接。"
        ) from exc


@router.post("/images", response_model=UploadOut)
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> UploadOut:
    ext = _safe_ext(file.filename, file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="仅支持 jpg / png / webp / gif")
    if file.content_type and file.content_type.lower() not in ALLOWED_MIME and ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="文件类型不被允许")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")

    user_dir = uploads_root() / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (user_dir / stored).write_bytes(raw)

    return UploadOut(url=f"/uploads/{user.id}/{stored}", filename=file.filename or stored, size=len(raw))


@router.post("/videos", response_model=UploadOut)
async def upload_video(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> UploadOut:
    name = (file.filename or "").lower()
    ext = next((candidate for candidate in VIDEO_EXT if name.endswith(candidate)), "")
    mime = (file.content_type or "").lower()
    if not ext:
        ext = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}.get(mime, "")
    if not ext:
        raise HTTPException(status_code=400, detail="仅支持 mp4 / webm / mov")
    if mime and mime not in VIDEO_MIME and ext not in VIDEO_EXT:
        raise HTTPException(status_code=400, detail="文件类型不被允许")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=400, detail="视频不能超过 80MB")

    user_dir = uploads_root() / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (user_dir / stored).write_bytes(raw)
    return UploadOut(url=f"/uploads/{user.id}/{stored}", filename=file.filename or stored, size=len(raw))


@router.post("/audio", response_model=UploadOut)
async def upload_audio(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> UploadOut:
    name = (file.filename or "").lower()
    ext = next((candidate for candidate in AUDIO_EXT if name.endswith(candidate)), "")
    mime = (file.content_type or "").lower()
    if not ext:
        ext = {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/aac": ".aac",
            "audio/m4a": ".m4a",
        }.get(mime, "")
    if not ext:
        raise HTTPException(status_code=400, detail="仅支持 mp3 / wav / m4a / aac")
    if mime and mime not in AUDIO_MIME and ext not in AUDIO_EXT:
        raise HTTPException(status_code=400, detail="文件类型不被允许")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="音频不能超过 20MB")

    user_dir = uploads_root() / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (user_dir / stored).write_bytes(raw)
    return UploadOut(url=f"/uploads/{user.id}/{stored}", filename=file.filename or stored, size=len(raw))
