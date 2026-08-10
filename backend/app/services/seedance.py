"""Upstream video generation clients.

Supports:
- mock: local demo clip
- fal: fal queue API (Seedance etc.)
- agnes / pavo: Agnes AI free video API (OpenAI-compatible async videos)

Network: auto-detect local SOCKS/HTTP proxy via app.services.net
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.models import Channel
from app.services.net import agnes_should_force_direct, make_async_client, resolve_agnes_base_url
from app.api.uploads import async_resolve_image_for_upstream

AGNES_PROVIDERS = {"agnes", "pavo", "agnes-pavo"}


class SeedanceError(Exception):
    pass


def _client(timeout: float = 60.0, *, force_direct: bool = False) -> httpx.AsyncClient:
    return make_async_client(timeout=timeout, force_direct=force_direct)


def _is_mock(channel: Channel, task_id: str | None = None) -> bool:
    if task_id and task_id.startswith("mock-"):
        return True
    return channel.provider == "mock" or channel.api_key.startswith("mock:")


def _is_agnes(channel: Channel) -> bool:
    return channel.provider.lower() in AGNES_PROVIDERS


def _agnes_num_frames(duration_seconds: int, frame_rate: int = 24) -> int:
    """Map duration to Agnes num_frames (must be 8n+1 and <= 441)."""
    raw = max(1, duration_seconds) * frame_rate
    n = max(0, round((raw - 1) / 8))
    frames = 8 * n + 1
    return min(441, max(81, frames))


async def submit_generation(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None = None,
) -> str:
    """Submit a generation task and return upstream task id."""
    try:
        image_url = await async_resolve_image_for_upstream(image_url)
    except Exception as exc:  # noqa: BLE001
        raise SeedanceError(str(exc)) from exc

    if _is_mock(channel):
        return f"mock-{asyncio.get_running_loop().time()}"

    if _is_agnes(channel):
        return await _submit_agnes(channel, prompt=prompt, duration_seconds=duration_seconds, image_url=image_url)

    if channel.provider == "fal":
        return await _submit_fal(channel, prompt=prompt, duration_seconds=duration_seconds, image_url=image_url)

    raise SeedanceError(f"暂未实现的 provider: {channel.provider}")


async def poll_generation(channel: Channel, task_id: str) -> tuple[str, str | None]:
    """Return (status, result_url). status in: running|succeeded|failed."""
    if _is_mock(channel, task_id):
        await asyncio.sleep(1.0)
        return (
            "succeeded",
            "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
        )

    if _is_agnes(channel) or task_id.startswith("agnes:"):
        return await _poll_agnes(channel, task_id)

    if channel.provider == "fal":
        return await _poll_fal(channel, task_id)

    raise SeedanceError(f"暂未实现的 provider: {channel.provider}")


async def _submit_fal(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None,
) -> str:
    base = (channel.base_url or "https://queue.fal.run").rstrip("/")
    url = f"{base}/{channel.upstream_model.lstrip('/')}"
    payload: dict[str, Any] = {
        "prompt": prompt,
        "duration": duration_seconds,
    }
    if image_url:
        payload["image_url"] = image_url

    headers = {
        "Authorization": f"Key {channel.api_key}",
        "Content-Type": "application/json",
    }
    async with _client() as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise SeedanceError(f"上游提交失败: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        request_id = data.get("request_id") or data.get("id")
        if not request_id:
            raise SeedanceError(f"上游未返回任务 ID: {data}")
        return str(request_id)


async def _poll_fal(channel: Channel, task_id: str) -> tuple[str, str | None]:
    base = (channel.base_url or "https://queue.fal.run").rstrip("/")
    model = channel.upstream_model.lstrip("/")
    status_url = f"{base}/{model}/requests/{task_id}/status"
    result_url = f"{base}/{model}/requests/{task_id}"
    headers = {"Authorization": f"Key {channel.api_key}"}

    async with _client() as client:
        status_resp = await client.get(status_url, headers=headers)
        if status_resp.status_code >= 400:
            raise SeedanceError(f"上游状态查询失败: {status_resp.status_code}")
        status_data = status_resp.json()
        st = str(status_data.get("status", "")).upper()
        if st in {"IN_QUEUE", "IN_PROGRESS"}:
            return "running", None
        if st in {"FAILED", "ERROR"}:
            return "failed", None
        if st != "COMPLETED":
            return "running", None

        result_resp = await client.get(result_url, headers=headers)
        if result_resp.status_code >= 400:
            raise SeedanceError(f"上游结果获取失败: {result_resp.status_code}")
        data = result_resp.json()
        video = data.get("video") or {}
        url = video.get("url") or data.get("video_url") or data.get("url")
        if not url:
            raise SeedanceError(f"上游结果无视频地址: {data}")
        return "succeeded", str(url)


async def _submit_agnes(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None,
) -> str:
    """Agnes AI / Pavo free video API: POST /v1/videos → video_id."""
    if not channel.api_key or channel.api_key in {"replace-me", "YOUR_API_KEY"}:
        raise SeedanceError("Agnes AI Pavo 渠道未配置 API Key，请在超管后台填入后启用")

    base = resolve_agnes_base_url(channel.base_url)
    model = channel.upstream_model or "agnes-video-v2.0"
    frame_rate = 24
    num_frames = _agnes_num_frames(duration_seconds, frame_rate)

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "height": 768,
        "width": 1152,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }
    if image_url:
        payload["image"] = image_url
        payload["mode"] = "ti2vid"

    headers = {
        "Authorization": f"Bearer {channel.api_key}",
        "Content-Type": "application/json",
    }
    async with _client(force_direct=agnes_should_force_direct(base)) as client:
        resp = await client.post(f"{base}/v1/videos", json=payload, headers=headers)
        if resp.status_code >= 400:
            raise SeedanceError(f"Agnes 提交失败: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        video_id = data.get("video_id") or data.get("task_id") or data.get("id")
        if not video_id:
            raise SeedanceError(f"Agnes 未返回 video_id: {data}")
        return f"agnes:{base}|{video_id}"


async def _poll_agnes(channel: Channel, task_id: str) -> tuple[str, str | None]:
    """Poll Agnes result via GET /agnesapi?video_id=..."""
    raw = task_id.removeprefix("agnes:")
    if "|" in raw:
        base, video_id = raw.split("|", 1)
    else:
        base = resolve_agnes_base_url(channel.base_url)
        video_id = raw
    model = channel.upstream_model or "agnes-video-v2.0"
    headers = {"Authorization": f"Bearer {channel.api_key}"}

    async with _client(force_direct=agnes_should_force_direct(base)) as client:
        resp = await client.get(
            f"{base}/agnesapi",
            params={"video_id": video_id, "model_name": model},
            headers=headers,
        )
        if resp.status_code == 404:
            return "running", None
        if resp.status_code >= 400:
            raise SeedanceError(f"Agnes 状态查询失败: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        st = str(data.get("status", "")).lower()
        if st in {"queued", "in_progress", "pending", "processing"}:
            return "running", None
        if st in {"failed", "error", "cancelled"}:
            err = data.get("error")
            if err:
                raise SeedanceError(f"Agnes 生成失败: {err}")
            return "failed", None
        if st != "completed":
            return "running", None

        meta = data.get("metadata") or {}
        url = meta.get("url") or data.get("url") or data.get("video_url")
        if isinstance(url, dict):
            url = url.get("url")
        if not url:
            raise SeedanceError(f"Agnes 结果无视频地址: {data}")
        return "succeeded", str(url)
