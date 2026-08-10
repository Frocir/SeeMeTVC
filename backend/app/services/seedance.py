"""Seedance upstream client.

Supports fal-style queue API. When no real key/channel works, jobs can be
marked failed with a clear error — local mock mode is available for UI demos.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.models import Channel


class SeedanceError(Exception):
    pass


async def submit_generation(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None = None,
) -> str:
    """Submit a generation task and return upstream task id."""
    if channel.api_key.startswith("mock:") or channel.provider == "mock":
        return f"mock-{asyncio.get_running_loop().time()}"

    if channel.provider != "fal":
        raise SeedanceError(f"暂未实现的 provider: {channel.provider}")

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
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise SeedanceError(f"上游提交失败: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        request_id = data.get("request_id") or data.get("id")
        if not request_id:
            raise SeedanceError(f"上游未返回任务 ID: {data}")
        return str(request_id)


async def poll_generation(channel: Channel, task_id: str) -> tuple[str, str | None]:
    """Return (status, result_url). status in: running|succeeded|failed."""
    if task_id.startswith("mock-") or channel.provider == "mock" or channel.api_key.startswith("mock:"):
        await asyncio.sleep(1.0)
        # Public sample clip for local demo (not real Seedance output).
        return (
            "succeeded",
            "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
        )

    if channel.provider != "fal":
        raise SeedanceError(f"暂未实现的 provider: {channel.provider}")

    base = (channel.base_url or "https://queue.fal.run").rstrip("/")
    model = channel.upstream_model.lstrip("/")
    status_url = f"{base}/{model}/requests/{task_id}/status"
    result_url = f"{base}/{model}/requests/{task_id}"
    headers = {"Authorization": f"Key {channel.api_key}"}

    async with httpx.AsyncClient(timeout=60.0) as client:
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
