"""Reference-video reverse prompting for Seedance-style TVC workflows."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel
from app.services import llm as llm_svc, media_ops, video_scene_detect


class VideoReverseError(Exception):
    pass


SYSTEM_REVERSE = (
    "你是美妆/产品短片导演，负责把参考视频拆成可复用的 Seedance 生成提示词。"
    "只输出严格 JSON，不要 Markdown："
    '{"prompt":"总体 Seedance 中文提示词","text":"简短中文分析",'
    '"scenes":[{"title":"Clip 01","analysis":"镜头分析","prompt":"单镜 Seedance 中文提示词","narration":"可选口播"}]}。'
    "每个 scene 必须写清景别、构图、运镜、光线、材质、主体动作。"
    "只参考运镜、节奏、构图、光线和材质，不复制真实人物脸、声音、受保护角色或未授权品牌。"
    "不要让模型生成字幕、水印、法务文案。"
)


def _coerce_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise VideoReverseError("反推 LLM 返回不是 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VideoReverseError(f"反推 JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise VideoReverseError("反推结果格式错误")
    prompt = str(data.get("prompt") or "").strip()
    scenes = data.get("scenes")
    if not prompt and isinstance(scenes, list) and scenes:
        first = scenes[0]
        if isinstance(first, dict):
            prompt = str(first.get("prompt") or "").strip()
    if not prompt:
        raise VideoReverseError("反推结果缺少 prompt")
    out_scenes = []
    if isinstance(scenes, list):
        for idx, item in enumerate(scenes[:8], start=1):
            if not isinstance(item, dict):
                continue
            sp = str(item.get("prompt") or "").strip()
            if not sp:
                continue
            out_scenes.append(
                {
                    "id": str(item.get("id") or f"scene_{idx:03d}"),
                    "index": int(item.get("index") or idx),
                    "title": str(item.get("title") or f"Clip {idx:02d}"),
                    "analysis": str(item.get("analysis") or item.get("text") or "").strip(),
                    "prompt": sp,
                    "seedance_prompt": str(item.get("seedance_prompt") or sp).strip(),
                    "midjourney_prompt": str(item.get("midjourney_prompt") or "").strip(),
                    "jimeng_prompt": str(item.get("jimeng_prompt") or "").strip(),
                    "narration": str(item.get("narration") or "").strip(),
                    "negative_prompt": str(
                        item.get("negative_prompt") or "不要字幕、水印、错字、额外 logo、变形瓶身。"
                    ).strip(),
                }
            )
    return {
        "prompt": prompt,
        "text": str(data.get("text") or data.get("analysis") or "").strip() or prompt,
        "scenes": out_scenes,
    }


async def _pick_llm(db: AsyncSession, model_id: str = "") -> Channel | None:
    if model_id.strip():
        result = await db.execute(
            select(Channel)
            .where(Channel.enabled.is_(True), Channel.kind == "llm", Channel.model_id == model_id.strip())
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
        if ch is not None:
            return ch
    result = await db.execute(
        select(Channel)
        .where(Channel.enabled.is_(True), Channel.kind == "llm")
        .order_by(Channel.priority.desc(), Channel.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _timeline_from_detected(items: list[video_scene_detect.DetectedScene]) -> list[dict[str, Any]]:
    return [
        {
            "index": item.index,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "frame_url": item.frame_url,
            "score": item.score,
        }
        for item in items
    ]


async def _fixed_frames(user_id: int, video_url: str, frame_count: int) -> tuple[list[str], list[dict[str, Any]]]:
    frames = await media_ops.extract_video_keyframes(user_id, video_url, count=frame_count)
    try:
        duration = await media_ops.probe_duration_seconds(video_url)
    except media_ops.MediaOpsError:
        duration = float(len(frames) * 2)
    step = duration / max(1, len(frames))
    timeline = [
        {
            "index": idx,
            "start_time": round((idx - 1) * step, 3),
            "end_time": round(idx * step if idx < len(frames) else duration, 3),
            "frame_url": frame,
            "score": 0.0,
        }
        for idx, frame in enumerate(frames, start=1)
    ]
    return frames, timeline


def _merge_scene_metadata(
    scenes: list[dict[str, Any]],
    *,
    fallback: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not scenes:
        return list(fallback.get("scenes") or [])
    out: list[dict[str, Any]] = []
    for idx, scene in enumerate(scenes, start=1):
        item = timeline[min(idx - 1, len(timeline) - 1)] if timeline else {}
        prompt = str(scene.get("prompt") or scene.get("seedance_prompt") or "").strip()
        out.append(
            {
                "id": str(scene.get("id") or f"scene_{idx:03d}"),
                "index": int(scene.get("index") or idx),
                "title": str(scene.get("title") or f"Clip {idx:02d}"),
                "start_time": scene.get("start_time", item.get("start_time")),
                "end_time": scene.get("end_time", item.get("end_time")),
                "frame_url": scene.get("frame_url") or item.get("frame_url"),
                "score": scene.get("score", item.get("score", 0.0)),
                "analysis": str(scene.get("analysis") or "").strip(),
                "prompt": prompt,
                "seedance_prompt": str(scene.get("seedance_prompt") or prompt).strip(),
                "midjourney_prompt": str(scene.get("midjourney_prompt") or "").strip(),
                "jimeng_prompt": str(scene.get("jimeng_prompt") or "").strip(),
                "narration": str(scene.get("narration") or "").strip(),
                "negative_prompt": str(
                    scene.get("negative_prompt") or "不要字幕、水印、错字、额外 logo、变形瓶身。"
                ).strip(),
            }
        )
    return out


async def reverse_prompt(
    db: AsyncSession,
    *,
    user_id: int,
    video_url: str,
    brief: str = "",
    model_id: str = "",
    frame_count: int = 3,
    frame_strategy: str = "scene_detect",
    max_scenes: int = 8,
    scene_threshold: float = 0.28,
    sample_fps: float = 2.0,
    prompt_style: str = "seedance",
) -> dict[str, Any]:
    try:
        if frame_strategy == "fixed":
            frames, timeline = await _fixed_frames(user_id, video_url, frame_count)
        else:
            detected = await video_scene_detect.detect_scenes(
                user_id,
                video_url,
                max_scenes=max_scenes,
                threshold=scene_threshold,
                sample_fps=sample_fps,
            )
            timeline = _timeline_from_detected(detected)
            frames = [x["frame_url"] for x in timeline]
    except media_ops.MediaOpsError as exc:
        raise VideoReverseError(str(exc)) from exc

    ch = await _pick_llm(db, model_id)
    if ch is None:
        raise VideoReverseError("没有已启用的 LLM 渠道，无法反推参考片。请超管填写并启用对话模型。")

    user = "\n".join(
        [
            f"用户 Brief：{brief or '未提供，按美妆/产品 TVC 分析'}",
            f"提示词风格：{prompt_style}",
            "已从参考视频抽取关键帧和时间轴：",
            *[
                f"Scene {item.get('index')}: {item.get('start_time')}s–{item.get('end_time')}s, frame={item.get('frame_url')}, score={item.get('score')}"
                for item in timeline
            ],
            "请基于这些关键帧 URL 和时间轴推断镜头节奏、主体动作、光线、构图、材质，并输出 1–8 个可执行 Clip。",
        ]
    )
    try:
        raw = await llm_svc.chat_complete(ch, system=SYSTEM_REVERSE, user=user, role="chat")
        parsed = _coerce_json(raw)
    except Exception as exc:  # noqa: BLE001
        raise VideoReverseError(f"反推失败：{exc}") from exc

    scenes = _merge_scene_metadata(parsed.get("scenes") or [], fallback={"scenes": []}, timeline=timeline)
    if not scenes:
        raise VideoReverseError("反推结果没有可用分镜")
    return {
        **parsed,
        "scenes": scenes,
        "frames": frames,
        "timeline": timeline,
        "model_id": ch.model_id,
        "frame_strategy": frame_strategy,
        "prompt_style": prompt_style,
    }
