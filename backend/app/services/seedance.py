"""Upstream video generation clients.

Supports:
- mock: local demo clip (Seedance LocalSimulate)
- ark: 火山方舟 Volcengine Ark Seedance（文生/图生）
- agnes / pavo: Agnes AI free video API

Network: auto-detect local SOCKS/HTTP proxy via app.services.net
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

import httpx

from app.api.uploads import async_resolve_image_for_upstream, uploads_root
from app.config import get_settings
from app.models import Channel
from app.services.net import agnes_should_force_direct, make_async_client, resolve_agnes_base_url

AGNES_PROVIDERS = {"agnes", "pavo", "agnes-pavo"}
ARK_PROVIDERS = {"ark", "volc", "volcengine", "doubao"}
# Legacy fal rows are migrated to ark in bootstrap; still recognize for one release.
LEGACY_FAL_PROVIDERS = {"fal"}

DEFAULT_ARK_BASE = "https://ark.cn-beijing.volces.com"

# Process-wide throttle: Agnes free tier rate-limits status queries hard.
_agnes_gate = asyncio.Lock()
_agnes_last_call_at = 0.0


class SeedanceError(Exception):
    pass


def _agnes_min_gap() -> float:
    return max(0.0, float(get_settings().agnes_min_gap_sec or 0))


def _agnes_429_sleep() -> float:
    return max(1.0, float(get_settings().agnes_429_base_sleep_sec or 25.0))


async def _agnes_gated(factory):
    """Run one Agnes HTTP call under a process-wide lock + minimum gap."""
    global _agnes_last_call_at
    async with _agnes_gate:
        now = time.monotonic()
        wait = _agnes_min_gap() - (now - _agnes_last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await factory()
        finally:
            _agnes_last_call_at = time.monotonic()


async def _agnes_backoff_429() -> None:
    """Hold the gate while sleeping after a 429 so all callers wait."""
    global _agnes_last_call_at
    async with _agnes_gate:
        await asyncio.sleep(_agnes_429_sleep())
        _agnes_last_call_at = time.monotonic()


def _client(timeout: float = 60.0, *, force_direct: bool = False) -> httpx.AsyncClient:
    return make_async_client(timeout=timeout, force_direct=force_direct)


def _is_mock(channel: Channel, task_id: str | None = None) -> bool:
    if task_id and task_id.startswith("mock-"):
        return True
    return channel.provider == "mock" or (channel.api_key or "").startswith("mock:")


def _is_agnes(channel: Channel) -> bool:
    return channel.provider.lower() in AGNES_PROVIDERS


def _is_ark(channel: Channel, task_id: str | None = None) -> bool:
    if task_id and (task_id.startswith("ark:") or task_id.startswith("fal:")):
        # fal: prefix kept only for in-flight tasks during migration
        return True
    return channel.provider.lower() in ARK_PROVIDERS | LEGACY_FAL_PROVIDERS


def ark_should_force_direct(base_url: str) -> bool:
    """Domestic Ark gateways are usually better without overseas SOCKS."""
    b = (base_url or "").lower()
    return "volces.com" in b or "volcengine" in b or "ark.cn" in b


def _agnes_num_frames(duration_seconds: int, frame_rate: int = 24) -> int:
    """Map duration to Agnes num_frames (must be 8n+1 and <= 441)."""
    raw = max(1, duration_seconds) * frame_rate
    n = max(0, round((raw - 1) / 8))
    frames = 8 * n + 1
    return min(441, max(81, frames))


def _upstream_blob(channel: Channel) -> str:
    return (channel.upstream_model or channel.model_id or "").strip().lstrip("/")


def fal_family(channel: Channel) -> str:
    """Return 'seedance-2.5' | 'seedance-lite' | 'other' (name kept for callers)."""
    mid = (channel.model_id or "").lower().strip()
    blob = f"{_upstream_blob(channel)} {mid}".lower()
    if mid == "seedance-2.5" or "seedance-2.5" in blob or "seedance-2-0" in blob or "seedance-2.0" in blob:
        return "seedance-2.5"
    if mid == "seedance-lite" or ("seedance" in blob and "lite" in blob):
        return "seedance-lite"
    return "other"


def clamp_duration_seconds(channel: Channel, duration_seconds: int) -> int:
    """Clamp duration to what the upstream model accepts."""
    dur = int(duration_seconds or 5)
    if _is_mock(channel):
        return max(1, min(dur, 15))
    if _is_agnes(channel):
        return max(2, min(dur, 18))
    family = fal_family(channel)
    if family == "seedance-2.5":
        return max(4, min(dur, 30))
    if family == "seedance-lite":
        return max(2, min(dur, 12))
    return max(2, min(dur, 30))


def poll_budget(channel: Channel) -> tuple[float, int]:
    """Return (interval_seconds, max_polls) for a generation wait loop."""
    if _is_agnes(channel):
        return 12.0, 60
    if fal_family(channel) == "seedance-2.5":
        return 5.0, 180
    if _is_ark(channel):
        return 5.0, 96
    return 2.0, 30


def _ark_base(channel: Channel) -> str:
    raw = (channel.base_url or DEFAULT_ARK_BASE).strip().rstrip("/")
    if not raw or "fal.run" in raw or "fal.ai" in raw:
        return DEFAULT_ARK_BASE
    return raw


def _ark_model(channel: Channel) -> str:
    m = (_upstream_blob(channel) or "").strip()
    if not m or "fal-ai/" in m or m.startswith("bytedance/"):
        family = fal_family(channel)
        if family == "seedance-2.5":
            return "doubao-seedance-2-0-260128"
        return "doubao-seedance-1-0-lite-t2v-250428"
    return m


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
        dur = clamp_duration_seconds(channel, duration_seconds)
        return f"mock-{dur}-{asyncio.get_running_loop().time()}"

    if _is_agnes(channel):
        return await _submit_agnes(
            channel, prompt=prompt, duration_seconds=duration_seconds, image_url=image_url
        )

    if _is_ark(channel):
        return await _submit_ark(
            channel, prompt=prompt, duration_seconds=duration_seconds, image_url=image_url
        )

    raise SeedanceError(f"暂未实现的 provider: {channel.provider}（Seedance 请用 ark）")


def _mock_duration_from_task(task_id: str) -> int:
    try:
        parts = (task_id or "").split("-")
        if len(parts) >= 2 and parts[0] == "mock":
            return max(1, min(int(float(parts[1])), 15))
    except (TypeError, ValueError):
        pass
    return 5


async def poll_generation(
    channel: Channel,
    task_id: str,
    *,
    user_id: int | None = None,
) -> tuple[str, str | None]:
    """Return (status, result_url). status in: running|succeeded|failed|rate_limited."""
    if _is_mock(channel, task_id):
        await asyncio.sleep(1.0)
        from app.services.media_ops import MediaOpsError, ensure_mock_demo_clip

        try:
            url = await ensure_mock_demo_clip(_mock_duration_from_task(task_id))
        except MediaOpsError as exc:
            raise SeedanceError(str(exc)) from exc
        return ("succeeded", url)

    if _is_agnes(channel) or task_id.startswith("agnes:"):
        return await _poll_agnes(channel, task_id)

    if _is_ark(channel, task_id) or task_id.startswith("ark:"):
        status, url = await _poll_ark(channel, task_id)
        if status == "succeeded" and url and user_id is not None:
            try:
                url = await _mirror_remote_video(user_id, url)
            except Exception:
                pass
        return status, url

    raise SeedanceError(f"暂未实现的 provider: {channel.provider}")


async def _mirror_remote_video(user_id: int, url: str) -> str:
    """Download remote mp4 into uploads so trim/mux/playback stay local-stable."""
    raw = (url or "").strip()
    if not raw:
        raise SeedanceError("空视频地址")
    if raw.startswith("/uploads/"):
        return raw
    if not re.match(r"^https?://", raw, re.I):
        return raw

    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}_ark.mp4"
    dest = user_dir / name

    async with _client(timeout=180.0) as client:
        resp = await client.get(raw, follow_redirects=True)
        if resp.status_code >= 400 or not resp.content:
            raise SeedanceError(f"镜像上游视频失败 HTTP {resp.status_code}")
        dest.write_bytes(resp.content)

    if dest.stat().st_size < 1000:
        try:
            dest.unlink()
        except OSError:
            pass
        raise SeedanceError("镜像上游视频过小，可能无效")
    return f"/uploads/{user_id}/{name}"


def _build_ark_payload(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None,
) -> dict[str, Any]:
    dur = clamp_duration_seconds(channel, duration_seconds)
    family = fal_family(channel)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    payload: dict[str, Any] = {
        "model": _ark_model(channel),
        "content": content,
        "duration": dur,
        "resolution": "720p",
        "watermark": False,
    }
    # 有参考图时用 adaptive 跟图；纯文生默认 16:9
    payload["ratio"] = "adaptive" if image_url else "16:9"
    if family == "seedance-2.5":
        payload["generate_audio"] = True
    else:
        payload["generate_audio"] = False
    return payload


async def _submit_ark(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None,
) -> str:
    if not channel.api_key or channel.api_key in {"replace-me", "YOUR_API_KEY", "FAL_KEY", "ARK_API_KEY"}:
        raise SeedanceError("火山方舟渠道未配置 API Key，请在超管后台「改 Key」写入 ARK_API_KEY 后启用")

    base = _ark_base(channel)
    url = f"{base}/api/v3/contents/generations/tasks"
    payload = _build_ark_payload(
        channel, prompt=prompt, duration_seconds=duration_seconds, image_url=image_url
    )
    headers = {
        "Authorization": f"Bearer {channel.api_key.strip()}",
        "Content-Type": "application/json",
    }

    async with _client(timeout=90.0, force_direct=ark_should_force_direct(base)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 401:
            raise SeedanceError(
                "火山方舟认证失败（401）：API Key 无效。"
                "请在方舟控制台复制 ARK_API_KEY，超管「改 Key」后重试。"
                f" model={payload.get('model')}"
            )
        if resp.status_code == 403:
            raise SeedanceError(
                "火山方舟拒绝访问（403）：可能未开通该模型/接入点或余额不足。"
                f" model={payload.get('model')} 详情：{resp.text[:240]}"
            )
        if resp.status_code >= 400:
            raise SeedanceError(f"方舟提交失败: {resp.status_code} {resp.text[:400]}")
        data = resp.json()
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise SeedanceError(f"方舟未返回任务 ID: {data}")
        return f"ark:{task_id}"


async def _poll_ark(channel: Channel, task_id: str) -> tuple[str, str | None]:
    raw = task_id.removeprefix("ark:").removeprefix("fal:")
    base = _ark_base(channel)
    url = f"{base}/api/v3/contents/generations/tasks/{raw}"
    headers = {"Authorization": f"Bearer {channel.api_key.strip()}"}

    async with _client(timeout=90.0, force_direct=ark_should_force_direct(base)) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return "running", None
        if resp.status_code == 401:
            raise SeedanceError("方舟状态查询认证失败（401），请检查超管渠道 Key")
        if resp.status_code == 429:
            return "rate_limited", None
        if resp.status_code >= 400:
            raise SeedanceError(f"方舟状态查询失败: {resp.status_code} {resp.text[:300]}")
        data = resp.json()

    st = str(data.get("status") or "").lower()
    if st in {"queued", "pending", "running", "processing", "in_progress"}:
        return "running", None
    if st in {"failed", "error", "cancelled", "canceled"}:
        err = data.get("error") or data.get("message") or data.get("detail") or ""
        if isinstance(err, dict):
            err = err.get("message") or err.get("code") or str(err)
        if err:
            raise SeedanceError(f"方舟生成失败: {err}")
        return "failed", None
    if st not in {"succeeded", "success", "completed"}:
        return "running", None

    content = data.get("content") or {}
    if isinstance(content, list) and content:
        content = content[0] if isinstance(content[0], dict) else {}
    url_out = None
    if isinstance(content, dict):
        url_out = content.get("video_url")
        video = content.get("video")
        if not url_out and isinstance(video, dict):
            url_out = video.get("url")
        if not url_out and isinstance(video, str):
            url_out = video
    url_out = url_out or data.get("video_url") or data.get("url")
    if not url_out:
        raise SeedanceError(f"方舟结果无视频地址: {data}")
    return "succeeded", str(url_out)


async def _submit_agnes(
    channel: Channel,
    *,
    prompt: str,
    duration_seconds: int,
    image_url: str | None,
) -> str:
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

    async def _do():
        async with _client(force_direct=agnes_should_force_direct(base)) as client:
            return await client.post(f"{base}/v1/videos", json=payload, headers=headers)

    resp = await _agnes_gated(_do)
    if resp.status_code == 429:
        await _agnes_backoff_429()
        raise SeedanceError("Agnes 提交被限流（429），请稍后再试；可重跑该节点")
    if resp.status_code >= 400:
        raise SeedanceError(f"Agnes 提交失败: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    video_id = data.get("video_id") or data.get("task_id") or data.get("id")
    if not video_id:
        raise SeedanceError(f"Agnes 未返回 video_id: {data}")
    return f"agnes:{base}|{video_id}"


async def _poll_agnes(channel: Channel, task_id: str) -> tuple[str, str | None]:
    raw = task_id.removeprefix("agnes:")
    if "|" in raw:
        base, video_id = raw.split("|", 1)
    else:
        base = resolve_agnes_base_url(channel.base_url)
        video_id = raw
    model = channel.upstream_model or "agnes-video-v2.0"
    headers = {"Authorization": f"Bearer {channel.api_key}"}

    async def _do():
        async with _client(force_direct=agnes_should_force_direct(base)) as client:
            return await client.get(
                f"{base}/agnesapi",
                params={"video_id": video_id, "model_name": model},
                headers=headers,
            )

    resp = await _agnes_gated(_do)
    if resp.status_code == 404:
        return "running", None
    if resp.status_code == 429:
        await _agnes_backoff_429()
        return "rate_limited", None
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
