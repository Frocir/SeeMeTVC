"""Beauty-TVC canvas executor: freeform nodes + legacy 6-type aliases."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Channel, User, Workflow, WorkflowRun, WorkflowRunStatus
from app.services import asr as asr_svc
from app.services import image_gen, media_ops, model_capabilities, seedance, video_reverse
from app.services import llm as llm_svc
from app.services import tts as tts_svc
from app.services.ledger import KIND_CHARGE, KIND_REFUND, record_entry
from app.services.project_assets import (
    is_video_url,
    prune_runs_keep_current,
    refresh_cover,
    replace_output,
    sync_from_graph,
    upsert_asset,
)

LEGACY_TO_FREE = {
    "BriefInput": "TextAsset",
    "ScenePlan": "TextAsset",
    "MakeupControl": "ImageAsset",
    "ShotGenerate": "ImageToVideo",
    "TimelineMux": "VideoMux",
    "PreviewOut": "VideoAsset",
    "LlmChat": "LlmText",
    "LlmBrief": "LlmText",
    "LlmStoryboard": "LlmText",
    "LlmShot": "LlmText",
}

NODE_TYPES = frozenset(
    {
        "TextAsset",
        "ImageAsset",
        "VideoAsset",
        "AudioAsset",
        "LlmText",
        "TextToImage",
        "ImageToVideo",
        "VideoTrim",
        "VideoMux",
        "MixAudio",
        "VideoDemux",
        "VideoReversePrompt",
        "ImageCompare",
        "SpeechToText",
        "AudioTrim",
        "TtsSpeak",
        "SubtitleBurn",
        *LEGACY_TO_FREE.keys(),
    }
)

LLM_TYPES = frozenset({"LlmText", "LlmChat", "LlmBrief", "LlmStoryboard", "LlmShot"})
# Must succeed before downstream may consume their output. Assets are user-provided.
PRODUCER_TYPES = frozenset(
    {
        *LLM_TYPES,
        "TextToImage",
        "ImageToVideo",
        "ShotGenerate",
        "VideoTrim",
        "VideoMux",
        "TimelineMux",
        "TtsSpeak",
        "AudioTrim",
        "MixAudio",
        "VideoDemux",
        "VideoReversePrompt",
        "ImageCompare",
        "SpeechToText",
        "SubtitleBurn",
    }
)
LLM_ROLE = {
    "LlmText": "shot",
    "LlmChat": "chat",
    "LlmBrief": "brief",
    "LlmStoryboard": "shot",
    "LlmShot": "shot",
}


def _normalize_type(ntype: str | None, data: dict) -> str:
    raw = ntype or data.get("nodeType") or data.get("type")
    if not raw:
        return ""
    s = str(raw)
    return LEGACY_TO_FREE.get(s, s)


class WorkflowExecError(Exception):
    pass


def _parse_graph(raw: str | dict) -> tuple[list[dict], list[dict]]:
    data = json.loads(raw) if isinstance(raw, str) else raw
    nodes = list(data.get("nodes") or [])
    edges = list(data.get("edges") or [])
    return nodes, edges


def topological_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    ids = [str(n["id"]) for n in nodes if n.get("id") is not None]
    id_set = set(ids)
    indeg: dict[str, int] = {i: 0 for i in ids}
    adj: dict[str, list[str]] = defaultdict(list)

    for e in edges:
        src, tgt = str(e.get("source")), str(e.get("target"))
        if src not in id_set or tgt not in id_set:
            continue
        adj[src].append(tgt)
        indeg[tgt] += 1

    q = deque([i for i in ids if indeg[i] == 0])
    order: list[str] = []
    while q:
        u = q.popleft()
        order.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    if len(order) != len(ids):
        raise WorkflowExecError("节点图存在环或无效依赖，无法执行")
    return order


def _is_producer(ntype: str) -> bool:
    return ntype in PRODUCER_TYPES


def _has_usable_output(ntype: str, data: dict) -> bool:
    if ntype in LLM_TYPES:
        return bool(str(data.get("prompt") or data.get("text") or data.get("narration") or "").strip())
    if ntype == "TextToImage":
        return bool(str(data.get("image_url") or "").strip())
    if ntype == "ImageCompare":
        return bool(str(data.get("url") or data.get("image_url") or "").strip())
    if ntype in {
        "ImageToVideo",
        "ShotGenerate",
        "VideoTrim",
        "VideoMux",
        "TimelineMux",
        "MixAudio",
        "SubtitleBurn",
    }:
        return bool(
            str(data.get("clip_url") or data.get("result_url") or data.get("preview_url") or "").strip()
        )
    if ntype in {"TtsSpeak", "AudioTrim"}:
        return bool(str(data.get("audio_url") or "").strip())
    if ntype == "VideoDemux":
        video = str(data.get("clip_url") or data.get("result_url") or "").strip()
        return bool(video and str(data.get("audio_url") or "").strip())
    if ntype == "VideoReversePrompt":
        return bool(str(data.get("prompt") or data.get("text") or "").strip() or data.get("scenes"))
    if ntype == "SpeechToText":
        return bool(str(data.get("text") or data.get("srt") or "").strip())
    return True


# 一键整条跑时，这些节点若已有可用结果就复用，避免 Agent 写完镜头再被 LLM 重写一遍。
_REUSE_ON_FULL_RUN = frozenset({*LLM_TYPES, "VideoReversePrompt"})


def _reuse_existing_on_full_run(ntype: str, data: dict, *, targeted: bool) -> bool:
    if targeted:
        return False
    if ntype not in _REUSE_ON_FULL_RUN:
        return False
    if data.get("runStatus") == "failed" or data.get("stale"):
        return False
    return _has_usable_output(ntype, data)


def _ancestor_ids(node_id: str, edges: list[dict], id_set: set[str]) -> list[str]:
    incoming: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        src, tgt = str(e.get("source")), str(e.get("target"))
        if src in id_set and tgt in id_set:
            incoming[tgt].append(src)
    seen: set[str] = set()
    order: list[str] = []

    def walk(nid: str) -> None:
        for src in incoming.get(nid, []):
            if src in seen:
                continue
            seen.add(src)
            walk(src)
            order.append(src)

    walk(node_id)
    return order


def _expand_failed_producers(
    target_set: set[str],
    by_id: dict[str, dict],
    edges: list[dict],
) -> set[str]:
    extra: set[str] = set()
    id_set = set(by_id)
    for tid in target_set:
        for anc in _ancestor_ids(tid, edges, id_set):
            node = by_id.get(anc) or {}
            data0 = dict(node.get("data") or {})
            ntype0 = _normalize_type(node.get("type"), data0)
            if not _is_producer(ntype0):
                continue
            if data0.get("runStatus") == "failed" or not _has_usable_output(ntype0, data0):
                extra.add(anc)
    return target_set | extra


def _blocked_upstream(outputs: dict[str, dict], edges: list[dict], node_id: str) -> str | None:
    for e in _incoming_edges(node_id, edges):
        src = str(e.get("source"))
        bag = outputs.get(src) or {}
        if bag.get("__upstream_failed__"):
            label = str(bag.get("__label__") or src)
            return f"上游「{label}」失败或未出结果，已拦截后续节点"
    return None


def _node_map(nodes: list[dict]) -> dict[str, dict]:
    return {str(n["id"]): n for n in nodes if n.get("id") is not None}


def _incoming_edges(node_id: str, edges: list[dict]) -> list[dict]:
    return [e for e in edges if str(e.get("target")) == node_id]


BRIEF_KEYS = (
    "brand",
    "selling_points",
    "slogan",
    "prompt",
    "image_url",
    "reference_notes",
)


def _as_text(*vals: Any) -> str:
    """Unwrap port dicts so prompt/text/narration survive merge."""
    for val in vals:
        if isinstance(val, dict):
            s = str(val.get("narration") or val.get("prompt") or val.get("text") or "").strip()
        else:
            s = str(val or "").strip()
        if s:
            return s
    return ""


def _port_payload(src_out: dict[str, Any], port: str) -> Any:
    """Resolve a named port from a node output (nested outputs or flat fields)."""
    bag = src_out.get("outputs")
    if isinstance(bag, dict) and port in bag:
        return bag[port]

    if port in ("brief", "text", "prompt"):
        if port == "prompt" and src_out.get("prompt"):
            return str(src_out.get("prompt") or "")
        return {k: src_out[k] for k in (*BRIEF_KEYS, "text", "scenes") if k in src_out and src_out[k] is not None}
    if port == "scenes":
        return src_out.get("scenes")
    if port in ("makeup", "image"):
        if port == "image" and src_out.get("image_url"):
            return src_out.get("image_url")
        return {
            k: src_out[k]
            for k in (
                "prompt",
                "scenes",
                "makeup_intensity",
                "before_prompt",
                "after_prompt",
                "image_url",
                *BRIEF_KEYS,
            )
            if k in src_out and src_out[k] is not None
        }
    if port in ("clips", "video", "timeline", "result"):
        clips = list(src_out.get("clips") or [])
        for key in ("clip_url", "result_url", "preview_url"):
            if src_out.get(key) and src_out[key] not in clips:
                clips.append(src_out[key])
        if port == "clips":
            return clips
        if port == "timeline":
            return {
                k: src_out[k]
                for k in ("clips", "clip_url", "aspect", "mux_note", "result_url")
                if k in src_out and src_out[k] is not None
            }
        return src_out.get("result_url") or src_out.get("clip_url") or (clips[-1] if clips else None)
    if port in ("audio", "bgm", "vo"):
        return src_out.get("audio_url") or src_out.get("result_url")
    if port == "narration":
        return src_out.get("narration") or ""
    return src_out.get(port)


def _apply_port(merged: dict[str, Any], target_port: str | None, value: Any) -> None:
    if value is None:
        return
    port = target_port or ""

    if port in ("", "brief", "text", "prompt"):
        if isinstance(value, str):
            merged["prompt"] = value
            merged["text"] = value
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "scenes" and isinstance(v, list):
                    merged.setdefault("scenes", [])
                    if isinstance(merged["scenes"], list):
                        merged["scenes"] = [*merged["scenes"], *v]
                elif k == "clips" and isinstance(v, list):
                    merged.setdefault("clips", [])
                    if isinstance(merged["clips"], list):
                        merged["clips"] = [*merged["clips"], *v]
                else:
                    merged[k] = v
            if value.get("prompt") and not merged.get("prompt"):
                merged["prompt"] = value["prompt"]
            return

    if port == "scenes":
        if isinstance(value, list):
            merged.setdefault("scenes", [])
            if isinstance(merged["scenes"], list):
                merged["scenes"] = [*merged["scenes"], *value]
        elif isinstance(value, dict) and isinstance(value.get("scenes"), list):
            merged.setdefault("scenes", [])
            if isinstance(merged["scenes"], list):
                merged["scenes"] = [*merged["scenes"], *value["scenes"]]
            for k, v in value.items():
                if k != "scenes":
                    merged[k] = v
        return

    if port in ("makeup", "image"):
        if isinstance(value, str):
            merged["image_url"] = value
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "scenes" and isinstance(v, list):
                    merged["scenes"] = v
                else:
                    merged[k] = v
            return

    if port in ("before", "after"):
        url = value if isinstance(value, str) else (value.get("image_url") if isinstance(value, dict) else None)
        if isinstance(url, str) and url.strip():
            merged[f"{port}_url"] = url.strip()
        return

    if port in ("clips", "timeline", "video", "result"):
        if isinstance(value, str):
            merged.setdefault("clips", [])
            if isinstance(merged["clips"], list) and value not in merged["clips"]:
                merged["clips"].append(value)
            merged["clip_url"] = value
            if port == "result":
                merged["result_url"] = value
            return
        if isinstance(value, list):
            merged.setdefault("clips", [])
            if isinstance(merged["clips"], list):
                merged["clips"] = [*merged["clips"], *value]
            if value:
                merged.setdefault("clip_url", value[-1])
        elif isinstance(value, dict):
            for k, v in value.items():
                if k == "clips" and isinstance(v, list):
                    merged.setdefault("clips", [])
                    if isinstance(merged["clips"], list):
                        merged["clips"] = [*merged["clips"], *v]
                else:
                    merged[k] = v
            return

    if port == "media":
        url = value if isinstance(value, str) else None
        if isinstance(value, dict):
            url = (
                value.get("media_url")
                or value.get("clip_url")
                or value.get("result_url")
                or value.get("preview_url")
                or value.get("audio_url")
            )
        if isinstance(url, str) and url.strip():
            u = url.strip()
            merged["media_url"] = u
            if u.lower().split("?", 1)[0].endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")):
                merged["audio_url"] = u
            else:
                merged["clip_url"] = u
        return

    if port in ("audio", "bgm", "vo"):
        url = value if isinstance(value, str) else (value.get("audio_url") if isinstance(value, dict) else None)
        if isinstance(url, str) and url.strip():
            if port == "bgm":
                merged["bgm_url"] = url.strip()
            elif port == "vo":
                merged["vo_url"] = url.strip()
            merged["audio_url"] = url.strip()
            merged.setdefault("media_url", url.strip())
        return

    if port == "narration":
        if isinstance(value, str):
            merged["narration"] = value
            if value.strip():
                merged.setdefault("text", value)
            return
        if isinstance(value, dict) and value.get("narration"):
            merged["narration"] = value["narration"]
        return

    merged[port] = value


def _merge_upstream_flat(outputs: dict[str, dict], ups: list[str]) -> dict[str, Any]:
    """Legacy full-dict merge for graphs without port handles."""
    merged: dict[str, Any] = {}
    clips: list[str] = []
    scenes: list[dict] = []
    for uid in ups:
        out = outputs.get(uid) or {}
        for k, v in out.items():
            if k == "outputs":
                continue
            if k == "clips" and isinstance(v, list):
                clips.extend(v)
            elif k == "scenes" and isinstance(v, list):
                scenes.extend(v)
            elif k == "clip_url" and v:
                clips.append(v)
            else:
                merged[k] = v
    if clips:
        merged["clips"] = clips
        merged.setdefault("clip_url", clips[-1])
    if scenes:
        merged["scenes"] = scenes
    return merged


def _merge_upstream(outputs: dict[str, dict], edges: list[dict], node_id: str) -> dict[str, Any]:
    incoming = _incoming_edges(node_id, edges)
    if not incoming:
        return {}

    has_ports = any(e.get("sourceHandle") or e.get("targetHandle") for e in incoming)
    if not has_ports:
        return _merge_upstream_flat(outputs, [str(e["source"]) for e in incoming])

    merged: dict[str, Any] = {}
    for e in incoming:
        src = str(e.get("source"))
        src_out = outputs.get(src) or {}
        sh = e.get("sourceHandle")
        th = e.get("targetHandle") or sh
        if sh:
            val = _port_payload(src_out, str(sh))
            _apply_port(merged, str(th) if th else None, val)
        else:
            flat = _merge_upstream_flat(outputs, [src])
            for k, v in flat.items():
                if k == "clips" and isinstance(v, list):
                    merged.setdefault("clips", [])
                    if isinstance(merged["clips"], list):
                        merged["clips"] = [*merged["clips"], *v]
                elif k == "scenes" and isinstance(v, list):
                    merged.setdefault("scenes", [])
                    if isinstance(merged["scenes"], list):
                        merged["scenes"] = [*merged["scenes"], *v]
                else:
                    merged[k] = v
    return merged


def _tag_ports(ntype: str, out: dict[str, Any]) -> dict[str, Any]:
    """Attach named port bag for downstream port-aware merge."""
    ports: dict[str, Any] = {}
    free = _normalize_type(ntype, out)
    if free == "TextAsset" or ntype in ("BriefInput", "ScenePlan"):
        ports["text"] = {k: out[k] for k in (*BRIEF_KEYS, "text", "scenes") if k in out and out[k] is not None}
        ports["brief"] = ports["text"]
        if out.get("scenes") is not None:
            ports["scenes"] = out.get("scenes")
        if out.get("prompt"):
            ports["prompt"] = out.get("prompt")
    elif free == "ImageAsset" or ntype == "MakeupControl":
        ports["image"] = out.get("image_url")
        ports["makeup"] = {
            k: out[k]
            for k in ("prompt", "scenes", "makeup_intensity", "image_url", *BRIEF_KEYS)
            if k in out and out[k] is not None
        }
    elif free == "TextToImage":
        ports["image"] = out.get("image_url")
    elif free == "ImageCompare":
        ports["image"] = out.get("url") or out.get("image_url")
    elif free == "SpeechToText":
        ports["text"] = out.get("text") or ""
        ports["srt"] = out.get("srt") or ""
    elif free == "ImageToVideo" or ntype == "ShotGenerate":
        ports["video"] = out.get("clip_url") or out.get("result_url")
        ports["clips"] = list(out.get("clips") or ([ports["video"]] if ports["video"] else []))
    elif free in ("VideoMux", "VideoTrim") or ntype == "TimelineMux":
        url = out.get("result_url") or out.get("clip_url")
        ports["video"] = url
        ports["clips"] = list(out.get("clips") or ([url] if url else []))
        ports["timeline"] = {
            k: out[k]
            for k in ("clips", "clip_url", "aspect", "mux_note", "result_url")
            if k in out and out[k] is not None
        }
    elif free == "VideoAsset" or ntype == "PreviewOut":
        url = out.get("result_url") or out.get("clip_url")
        ports["video"] = url
        ports["result"] = url
    elif free == "AudioAsset":
        ports["audio"] = out.get("audio_url")
    elif free == "TtsSpeak":
        ports["audio"] = out.get("audio_url")
    elif free == "AudioTrim":
        ports["audio"] = out.get("audio_url")
    elif free == "SubtitleBurn":
        url = out.get("result_url") or out.get("clip_url")
        ports["video"] = url
    elif free == "MixAudio":
        url = out.get("result_url") or out.get("clip_url")
        ports["video"] = url
        ports["clips"] = [url] if url else []
    elif free == "VideoDemux":
        ports["video"] = out.get("result_url") or out.get("clip_url")
        ports["audio"] = out.get("audio_url")
    elif free == "VideoReversePrompt":
        ports["text"] = {
            k: out[k]
            for k in (*BRIEF_KEYS, "text", "scenes", "frames", "timeline", "reference_video_url")
            if k in out and out[k] is not None
        }
        if out.get("prompt"):
            ports["prompt"] = out.get("prompt")
        if out.get("scenes") is not None:
            ports["scenes"] = out.get("scenes")
        if out.get("frames") is not None:
            ports["frames"] = out.get("frames")
        if out.get("timeline") is not None:
            ports["timeline"] = out.get("timeline")
    elif free in LLM_TYPES:
        ports["text"] = {
            k: out[k]
            for k in (*BRIEF_KEYS, "text", "scenes", "narration")
            if k in out and out[k] is not None
        }
        if out.get("prompt"):
            ports["prompt"] = out.get("prompt")
        if out.get("scenes") is not None:
            ports["scenes"] = out.get("scenes")
        if out.get("narration"):
            ports["narration"] = out.get("narration")
    return {**out, "outputs": ports}


def _synthetic_output_from_data(data: dict) -> dict[str, Any]:
    """Use already-materialized node data when skipping upstream in partial runs."""
    out = {k: v for k, v in data.items() if v is not None and k not in ("onLabelChange",)}
    clips = list(out.get("clips") or [])
    for key in ("clip_url", "result_url", "preview_url"):
        if out.get(key) and out[key] not in clips:
            clips.append(out[key])
    if clips:
        out["clips"] = clips
        out.setdefault("clip_url", clips[-1])
    return out


async def _pick_channel(db: AsyncSession, model_id: str) -> Channel | None:
    result = await db.execute(
        select(Channel)
        .where(Channel.model_id == model_id, Channel.enabled.is_(True))
        .order_by(Channel.priority.desc(), Channel.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _pick_kind_channel(db: AsyncSession, model_id: str, kind: str) -> Channel | None:
    mid = (model_id or "").strip()
    if mid:
        ch = await _pick_channel(db, mid)
        if ch is not None and (ch.kind or "").strip().lower() == kind:
            return ch
    if kind == "video":
        preferred = await _pick_channel(db, seedance.DEFAULT_VIDEO_MODEL_ID)
        if preferred is not None and (preferred.kind or "").strip().lower() == "video":
            return preferred
    result = await db.execute(
        select(Channel)
        .where(Channel.enabled.is_(True), Channel.kind == kind)
        .order_by(Channel.priority.desc(), Channel.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _brief_from_ctx(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    return {
        "brand": data.get("brand") or ctx.get("brand") or "",
        "selling_points": data.get("selling_points") or ctx.get("selling_points") or "",
        "slogan": data.get("slogan") or ctx.get("slogan") or "",
        "prompt": data.get("prompt") or ctx.get("prompt") or "",
        "image_url": data.get("image_url") or ctx.get("image_url"),
        "reference_notes": data.get("reference_notes") or ctx.get("reference_notes") or "",
    }


def _exec_brief(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    brief = _brief_from_ctx(ctx, data)
    parts = [
        p
        for p in [
            f"品牌：{brief['brand']}" if brief["brand"] else "",
            f"卖点：{brief['selling_points']}" if brief["selling_points"] else "",
            f"口号：{brief['slogan']}" if brief["slogan"] else "",
            brief["prompt"],
            brief["reference_notes"],
        ]
        if p
    ]
    brief["prompt"] = "。".join(parts) if parts else "美妆广告短片"
    return brief


async def _run_shot(
    db: AsyncSession,
    user: User,
    run: WorkflowRun,
    ctx: dict[str, Any],
    data: dict,
    charged: list[float],
    on_hint=None,
) -> dict[str, Any]:
    # 不要用上游 LLM 的 model_id。Agent 搭的出视频节点常常没填模型。
    channel = await _pick_kind_channel(db, str(data.get("model_id") or ""), "video")
    if channel is None:
        raise WorkflowExecError("没有已启用的视频渠道。请超管填写并启用 Seedance 等模型。")
    model_id = channel.model_id

    image_url = data.get("first_image_url") or data.get("image_url") or ctx.get("image_url")
    last_image_url = data.get("last_image_url") or ctx.get("last_image_url")
    style_image_url = data.get("style_image_url")
    character_image_url = data.get("character_image_url")
    product_image_url = data.get("product_image_url")

    check_data = {
        **data,
        "image_url": image_url,
        "first_image_url": data.get("first_image_url") or image_url,
        "last_image_url": last_image_url,
        "style_image_url": style_image_url,
        "character_image_url": character_image_url,
        "product_image_url": product_image_url,
    }
    cap_err = model_capabilities.validate_node_params_against_capabilities(
        "ImageToVideo",
        check_data,
        model_capabilities.get_channel_capabilities(channel),
    )
    if cap_err:
        raise WorkflowExecError(cap_err)

    duration = seedance.clamp_duration_seconds(
        channel, int(data.get("duration_seconds") or ctx.get("duration_seconds") or 5)
    )

    prompt = _as_text(data.get("prompt"), ctx.get("prompt"), ctx.get("text"))
    if not prompt:
        raise WorkflowExecError(
            "图生视频缺少有效提示词：请在节点填写「镜头提示词」，或把文本接到 prompt 槽"
        )
    prompts = [prompt]

    clips: list[str] = []
    node_cost = 0.0
    is_agnes = channel.provider.lower() in {"agnes", "pavo", "agnes-pavo"}
    interval, polls = seedance.poll_budget(channel)

    for prompt in prompts:
        cost = round(float(channel.cost_per_second) * duration, 4)
        await db.refresh(user)
        if user.balance < cost:
            raise WorkflowExecError("余额不足，无法继续生成镜头")

        await record_entry(
            db,
            user,
            -cost,
            kind=KIND_CHARGE,
            title=f"项目出片 #{run.id} 镜头",
            ref_type="run",
            ref_id=run.id,
        )
        node_cost += cost
        charged.append(cost)
        await db.commit()

        try:
            task_id = await seedance.submit_generation(
                channel,
                prompt=prompt,
                duration_seconds=duration,
                image_url=image_url,
                last_image_url=str(last_image_url) if last_image_url else None,
                style_image_url=str(style_image_url) if style_image_url else None,
                character_image_url=str(character_image_url) if character_image_url else None,
                product_image_url=str(product_image_url) if product_image_url else None,
            )
            url: str | None = None
            rate_hits = 0
            family = seedance.fal_family(channel)
            wait_limit = int(interval * polls)
            started = time.monotonic()
            for _ in range(polls):
                await db.refresh(run)
                if run.status in {
                    WorkflowRunStatus.CANCELLED.value,
                    WorkflowRunStatus.FAILED.value,
                    WorkflowRunStatus.REFUNDED.value,
                }:
                    raise WorkflowExecError("已取消")
                status, got = await seedance.poll_generation(
                    channel, task_id, user_id=user.id
                )
                if status == "succeeded":
                    url = got
                    if on_hint:
                        await on_hint(None)
                    break
                if status == "failed":
                    raise seedance.SeedanceError("上游生成失败")
                if status == "rate_limited":
                    rate_hits += 1
                    if on_hint:
                        await on_hint(f"上游限流，自动退避重试（第 {rate_hits} 次）…")
                    # Extra wait beyond gate backoff inside poll_agnes
                    await asyncio.sleep(min(15.0 * rate_hits, 60.0))
                    continue
                if on_hint:
                    elapsed = max(0, int(time.monotonic() - started))
                    mm, ss = divmod(elapsed, 60)
                    waited = f"{mm} 分 {ss:02d} 秒" if mm else f"{ss} 秒"
                    cap = f"{wait_limit // 60} 分钟"
                    if is_agnes:
                        await on_hint(f"生成中（Agnes，已等 {waited}）…")
                    elif family == "seedance-2.5":
                        await on_hint(f"生成中（Seedance 2.5，已等 {waited}，上限约 {cap}）…")
                    elif family == "seedance-fast":
                        await on_hint(f"生成中（Seedance Fast，已等 {waited}，上限约 {cap}）…")
                    elif family == "seedance-lite":
                        await on_hint(f"生成中（Seedance Lite，已等 {waited}）…")
                    else:
                        await on_hint(f"生成中（已等 {waited}）…")
                await asyncio.sleep(interval)
            if not url:
                if rate_hits:
                    raise seedance.SeedanceError(
                        "生成超时：多次触发上游限流，请稍后重跑该节点（费用已退回）"
                    )
                raise seedance.SeedanceError("生成超时")
            clips.append(url)
            # Small gap between multi-shot submits to ease Agnes RPM
            if is_agnes and len(clips) < len(prompts):
                await asyncio.sleep(5.0)
        except Exception as exc:  # noqa: BLE001
            # Refund this shot's cost
            await db.refresh(user)
            await record_entry(
                db,
                user,
                cost,
                kind=KIND_REFUND,
                title=f"项目出片 #{run.id} 镜头退款",
                ref_type="run",
                ref_id=run.id,
            )
            charged.pop()
            node_cost -= cost
            await db.commit()
            raise WorkflowExecError(str(exc)[:500]) from exc

    return {
        **ctx,
        "clips": clips,
        "clip_url": clips[-1] if clips else None,
        "shot_cost": node_cost,
        "prompt": prompts[-1],
        "model_id": model_id,
        "duration_seconds": duration,
        "image_url": image_url,
        "first_image_url": image_url,
        "last_image_url": last_image_url,
        "style_image_url": style_image_url,
        "character_image_url": character_image_url,
        "product_image_url": product_image_url,
    }


async def _exec_mux(user_id: int, ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    aspect = data.get("aspect") or "16:9"
    clips = list(ctx.get("clips") or [])
    if ctx.get("clip_url") and ctx["clip_url"] not in clips:
        clips.append(ctx["clip_url"])
    if ctx.get("result_url") and ctx["result_url"] not in clips:
        clips.append(ctx["result_url"])
    clips = [c for c in clips if isinstance(c, str) and c]
    if not clips:
        raise WorkflowExecError("没有可拼接的片段")
    try:
        url = await media_ops.concat_videos(user_id, clips)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip() or type(exc).__name__
        raise WorkflowExecError(f"视频拼接失败：{detail}") from exc
    return {
        **ctx,
        "clips": clips,
        "clip_url": url,
        "result_url": url,
        "aspect": aspect,
        "mux_note": "ffmpeg 真拼接",
    }


async def _exec_trim(user_id: int, ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    url = ctx.get("clip_url") or ctx.get("result_url") or (ctx.get("clips") or [None])[-1]
    if not url:
        raise WorkflowExecError("裁时长缺少输入视频")
    start = float(data.get("trim_start") if data.get("trim_start") is not None else 0)
    end = float(data.get("trim_end") if data.get("trim_end") is not None else start + 4)
    try:
        out_url = await media_ops.trim_video(user_id, str(url), start, end)
    except media_ops.MediaOpsError as exc:
        raise WorkflowExecError(str(exc)) from exc
    return {
        **ctx,
        "clip_url": out_url,
        "result_url": out_url,
        "clips": [out_url],
        "trim_start": start,
        "trim_end": end,
    }


def _exec_text_asset(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    brief = _exec_brief(ctx, data)
    text = data.get("text") or brief.get("prompt") or ""
    return {**brief, "text": text, "slogan": brief.get("slogan") or data.get("slogan") or ctx.get("slogan")}


def _exec_image_asset(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    out = {**ctx}
    image = data.get("image_url") or ctx.get("image_url")
    if image:
        out["image_url"] = image
    return out


def _exec_image_compare(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    before = str(data.get("before_url") or ctx.get("before_url") or "").strip()
    after = str(data.get("after_url") or ctx.get("after_url") or "").strip()
    selected = str(data.get("selected") or "after").strip() or "after"
    if selected not in {"before", "after"}:
        selected = "after"
    if not before and not after:
        raise WorkflowExecError("图像对比缺少输入：请连接 A / B 图片")
    url = before if selected == "before" else after
    if not url:
        url = after or before
        selected = "after" if after else "before"
    return {
        **ctx,
        "before_url": before or None,
        "after_url": after or None,
        "selected": selected,
        "compare_mode": data.get("compare_mode") or "slider",
        "url": url,
        "image_url": url,
    }


def _exec_video_asset(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    url = (
        data.get("result_url")
        or data.get("clip_url")
        or data.get("preview_url")
        or ctx.get("result_url")
        or ctx.get("clip_url")
        or (ctx.get("clips") or [None])[-1]
    )
    if not url:
        raise WorkflowExecError("视频节点缺少地址")
    return {**ctx, "result_url": url, "clip_url": url, "clips": list(ctx.get("clips") or [url])}


def _exec_audio_asset(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    url = data.get("audio_url") or ctx.get("audio_url") or ctx.get("bgm_url") or ctx.get("vo_url")
    if not url:
        raise WorkflowExecError("音频节点缺少文件，请上传 BGM 或口播")
    return {**ctx, "audio_url": url}


def _llm_user_payload(ctx: dict[str, Any], data: dict, role: str) -> str:
    node_text = _as_text(data.get("prompt"), data.get("text"))
    up_text = _as_text(ctx.get("text"), ctx.get("prompt"))
    if role == "chat":
        return "\n\n".join(p for p in (up_text, node_text) if p)
    parts = []
    brand = data.get("brand") or ctx.get("brand") or ""
    points = data.get("selling_points") or ctx.get("selling_points") or ""
    slogan = data.get("slogan") or ctx.get("slogan") or ""
    if brand:
        parts.append(f"品牌：{brand}")
    if points:
        parts.append(f"卖点：{points}")
    if slogan:
        parts.append(f"口号：{slogan}")
    if up_text:
        parts.append(up_text)
    elif node_text:
        parts.append(node_text)
    return "\n".join(parts)


async def _exec_llm(
    db: AsyncSession,
    ctx: dict[str, Any],
    data: dict,
    ntype: str,
    on_hint,
) -> dict[str, Any]:
    role = str(data.get("llmRole") or LLM_ROLE.get(ntype) or "shot")
    if role == "storyboard":
        role = "shot"
    want_raw = data.get("wantNarration")
    want_narration = True if want_raw is None else bool(want_raw)
    system = str(data.get("system_prompt") or "").strip() or llm_svc.default_system(
        role, want_narration=want_narration
    )
    user = _llm_user_payload(ctx, data, role)
    if not user.strip():
        raise WorkflowExecError("LLM 缺少输入：请连接上游文本，或在节点填写正文")
    model_id = str(data.get("model_id") or "").strip()
    ch = await _pick_channel(db, model_id) if model_id else None
    if ch is not None and (ch.kind or "").strip().lower() != "llm":
        ch = None
    if ch is None:
        result = await db.execute(
            select(Channel)
            .where(Channel.enabled.is_(True), Channel.kind == "llm")
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
    if ch is None:
        raise WorkflowExecError("没有已启用的 LLM 渠道。请超管填写并启用对话模型。")
    await on_hint("正在写镜头…" if role == "shot" else "正在调用对话模型…")
    try:
        raw = await llm_svc.chat_complete(
            ch, system=system, user=user, role=role, want_narration=want_narration
        )
    except llm_svc.LlmError as exc:
        raise WorkflowExecError(str(exc)) from exc
    out = {**ctx, "text": raw, "prompt": raw, "model_id": ch.model_id}
    if role == "shot":
        parsed = llm_svc.parse_shot(raw, want_narration=want_narration)
        if not want_narration:
            parsed["narration"] = ""
        out.update(parsed)
    return out


async def _exec_tts(db: AsyncSession, ctx: dict[str, Any], data: dict, on_hint) -> dict[str, Any]:
    text = _as_text(data.get("text"), ctx.get("narration"), ctx.get("text"), ctx.get("prompt"))
    if not text:
        raise WorkflowExecError("TTS 缺少口播文本：请连接 narration 或填写正文")
    model_id = str(data.get("model_id") or "tts-1").strip()
    ch = await _pick_channel(db, model_id)
    if ch is None:
        result = await db.execute(
            select(Channel)
            .where(Channel.enabled.is_(True), Channel.kind == "tts")
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
    if ch is None:
        raise WorkflowExecError("没有已启用的 TTS 渠道（aisrv）")
    voice = str(data.get("voice") or tts_svc.DEFAULT_VOICE).strip()
    await on_hint("正在合成口播（本机 aisrv，约 25 秒未响应即失败）…")
    try:
        url = await tts_svc.synthesize(ch, text=text, voice=voice)
    except tts_svc.TtsError as exc:
        raise WorkflowExecError(str(exc)) from exc
    return {**ctx, "audio_url": url, "narration": text, "voice": voice}


async def _exec_speech_to_text(
    db: AsyncSession,
    user_id: int,
    ctx: dict[str, Any],
    data: dict,
    on_hint,
) -> dict[str, Any]:
    media = (
        data.get("media_url")
        or ctx.get("media_url")
        or data.get("audio_url")
        or ctx.get("audio_url")
        or data.get("clip_url")
        or ctx.get("clip_url")
        or data.get("result_url")
        or ctx.get("result_url")
        or data.get("preview_url")
        or ctx.get("preview_url")
        or (ctx.get("clips") or [None])[-1]
    )
    if not media:
        raise WorkflowExecError("口播提取缺少输入视频或音频：请连接 media 或 audio")
    language = str(data.get("language") or "zh").strip() or "zh"
    model_id = str(data.get("model_id") or "").strip()
    ch = await _pick_channel(db, model_id) if model_id else None
    if ch is not None and (ch.kind or "") != "asr":
        ch = None
    if ch is None:
        result = await db.execute(
            select(Channel)
            .where(Channel.enabled.is_(True), Channel.kind == "asr")
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
    if ch is None:
        raise WorkflowExecError("没有已启用的 ASR 渠道")
    await on_hint("正在转写口播…")
    try:
        result = await asr_svc.transcribe(ch, media_url=str(media), user_id=user_id, language=language)
    except asr_svc.AsrError as exc:
        raise WorkflowExecError(str(exc)) from exc
    segments = [{"start": s.start, "end": s.end, "text": s.text} for s in result.segments]
    return {
        **ctx,
        "media_url": str(media),
        "language": language,
        "model_id": ch.model_id,
        "text": result.text,
        "prompt": result.text,
        "segments": segments,
        "srt": result.srt,
    }


async def _exec_mix(user_id: int, ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    video = ctx.get("clip_url") or ctx.get("result_url") or (ctx.get("clips") or [None])[-1]
    bgm = ctx.get("bgm_url") or data.get("bgm_url")
    vo = ctx.get("vo_url") or data.get("vo_url")
    if not video:
        raise WorkflowExecError("混音缺少视频输入")
    if not bgm:
        raise WorkflowExecError("混音缺少 BGM 输入")
    if not vo:
        raise WorkflowExecError("混音缺少口播输入")
    try:
        url = await media_ops.mix_audio(user_id, str(video), str(bgm), str(vo))
    except media_ops.MediaOpsError as exc:
        raise WorkflowExecError(str(exc)) from exc
    return {
        **ctx,
        "clip_url": url,
        "result_url": url,
        "clips": [url],
        "bgm_url": bgm,
        "vo_url": vo,
    }


async def _exec_t2i(
    db: AsyncSession,
    user: User,
    run: WorkflowRun,
    ctx: dict[str, Any],
    data: dict,
    charged: list[float],
    on_hint,
) -> dict[str, Any]:
    prompt = _as_text(data.get("prompt"), ctx.get("prompt"), ctx.get("text"))
    if not prompt:
        raise WorkflowExecError("文生图缺少提示词")
    image_url = data.get("image_url") or ctx.get("image_url")
    model_id = str(data.get("model_id") or "").strip()
    ch = await _pick_channel(db, model_id) if model_id else None
    if ch is not None and ch.kind != "image":
        ch = None
    if ch is None:
        result = await db.execute(
            select(Channel)
            .where(Channel.enabled.is_(True), Channel.kind == "image")
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
    if ch is None:
        raise WorkflowExecError("没有已启用的文生图渠道")

    caps = model_capabilities.get_channel_capabilities(ch)
    cap_err = model_capabilities.validate_node_params_against_capabilities("TextToImage", {**data, "image_url": image_url}, caps)
    if cap_err:
        raise WorkflowExecError(cap_err)
    img_params = model_capabilities.filter_image_params(data, caps)

    cost = round(float(ch.cost_per_second or 0), 4)
    await db.refresh(user)
    if user.balance < cost:
        raise WorkflowExecError("余额不足，无法继续生成图片")
    if cost > 0:
        await record_entry(
            db,
            user,
            -cost,
            kind=KIND_CHARGE,
            title=f"项目出片 #{run.id} 图片",
            ref_type="run",
            ref_id=run.id,
        )
        charged.append(cost)
        await db.commit()

    await on_hint("正在生成图片…")
    try:
        url = await image_gen.generate(
            ch,
            prompt=prompt,
            image_url=str(image_url) if image_url else None,
            user_id=user.id,
            size=str(img_params.get("size") or "") or None,
            negative_prompt=str(img_params.get("negative_prompt") or "") or None,
            seed=img_params.get("seed"),
            batch_size=int(img_params.get("batch_size") or 1),
            image_strength=img_params.get("image_strength"),
        )
    except image_gen.ImageGenError as exc:
        if cost > 0:
            await db.refresh(user)
            await record_entry(
                db,
                user,
                cost,
                kind=KIND_REFUND,
                title=f"项目出片 #{run.id} 图片退款",
                ref_type="run",
                ref_id=run.id,
            )
            charged.pop()
            await db.commit()
        raise WorkflowExecError(str(exc)) from exc
    return {**ctx, "image_url": url, "prompt": prompt, "image_cost": cost, "model_id": ch.model_id, **img_params}


async def _exec_audio_trim(user_id: int, ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    url = (
        data.get("audio_url")
        or ctx.get("audio_url")
        or ctx.get("vo_url")
        or ctx.get("bgm_url")
    )
    if not url:
        raise WorkflowExecError("音频裁切缺少输入")
    start = float(data.get("trim_start") if data.get("trim_start") is not None else 0)
    end = float(data.get("trim_end") if data.get("trim_end") is not None else 0)
    try:
        out_url = await media_ops.trim_audio(user_id, str(url), start, end)
    except media_ops.MediaOpsError as exc:
        raise WorkflowExecError(str(exc)) from exc
    out = {**ctx, "audio_url": out_url}
    if ctx.get("vo_url") or data.get("vo_url"):
        out["vo_url"] = out_url
    return out


async def _exec_subtitle(user_id: int, ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    video = ctx.get("clip_url") or ctx.get("result_url") or (ctx.get("clips") or [None])[-1]
    if not video:
        raise WorkflowExecError("字幕缺少输入视频")
    text = str(
        data.get("text")
        or data.get("slogan")
        or ctx.get("slogan")
        or ctx.get("text")
        or ctx.get("prompt")
        or ""
    ).strip()
    if isinstance(ctx.get("text"), dict):
        text = str(ctx["text"].get("slogan") or ctx["text"].get("text") or text).strip()
    try:
        url = await media_ops.burn_subtitle(user_id, str(video), text)
    except media_ops.MediaOpsError as exc:
        raise WorkflowExecError(str(exc)) from exc
    return {**ctx, "clip_url": url, "result_url": url, "clips": [url], "slogan": text}


async def _exec_demux(user_id: int, ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    url = (
        data.get("clip_url")
        or ctx.get("clip_url")
        or ctx.get("result_url")
        or (ctx.get("clips") or [None])[-1]
    )
    if not url:
        raise WorkflowExecError("拆轨缺少输入视频")
    try:
        silent, audio = await media_ops.demux_av(user_id, str(url))
    except media_ops.MediaOpsError as exc:
        raise WorkflowExecError(str(exc)) from exc
    return {
        **ctx,
        "clip_url": silent,
        "result_url": silent,
        "clips": [silent],
        "audio_url": audio,
    }


HISTORY_NODE_TYPES = frozenset(
    {
        "TextToImage",
        "ImageToVideo",
        "ShotGenerate",
        "TtsSpeak",
        "VideoMux",
        "TimelineMux",
        "SubtitleBurn",
        "VideoReversePrompt",
        "ImageCompare",
        "SpeechToText",
    }
)


async def _record_node_history(
    db: AsyncSession,
    *,
    user: User,
    run: WorkflowRun,
    node_id: str,
    ntype: str,
    data: dict,
    out: dict[str, Any],
    cost: float,
    status: str = "succeeded",
    error: str = "",
) -> None:
    if ntype not in HISTORY_NODE_TYPES or not run.workflow_id:
        return
    from app.services import asset_versions as versions_svc

    prompt = str(out.get("prompt") or data.get("prompt") or data.get("text") or "")
    model_name = str(out.get("model_id") or data.get("model_id") or "")
    params = {
        k: data.get(k)
        for k in (
            "duration_seconds",
            "aspect",
            "size",
            "voice",
            "frame_strategy",
            "prompt_style",
            "selected",
            "compare_mode",
            "language",
            "size",
            "seed",
            "negative_prompt",
            "batch_size",
            "image_strength",
            "first_image_url",
            "last_image_url",
            "reference_strength",
        )
        if data.get(k) is not None
    }
    common = dict(
        user=user,
        workflow_id=run.workflow_id,
        run_id=run.id,
        node_id=node_id,
        node_type=ntype,
        prompt=prompt,
        model_name=model_name,
        params=params,
        cost=cost,
        status=status,
        error_message=error,
    )

    async def _one(*, kind: str, url: str = "", text: str = "", thumbnail_url: str = "") -> None:
        await versions_svc.record_asset_version(
            db,
            kind=kind,
            url=str(url or ""),
            thumbnail_url=str(thumbnail_url or url or ""),
            text=str(text or ""),
            **common,
        )

    if ntype == "TextToImage":
        await _one(kind="image", url=str(out.get("image_url") or ""))
    elif ntype == "ImageCompare":
        await _one(kind="image", url=str(out.get("url") or out.get("image_url") or ""))
    elif ntype in {"ImageToVideo", "ShotGenerate", "VideoMux", "TimelineMux", "SubtitleBurn"}:
        url = str(out.get("clip_url") or out.get("result_url") or "")
        await _one(kind="video", url=url)
    elif ntype == "TtsSpeak":
        await _one(kind="audio", url=str(out.get("audio_url") or ""), text=str(out.get("text") or data.get("text") or ""))
    elif ntype == "SpeechToText":
        await _one(kind="text", text=str(out.get("text") or out.get("srt") or data.get("text") or ""))
    elif ntype == "VideoReversePrompt":
        await _one(
            kind="prompt",
            text=str(out.get("prompt") or out.get("text") or ""),
            thumbnail_url=str((out.get("frames") or [None])[0] or ""),
        )
        frames = out.get("frames") if isinstance(out.get("frames"), list) else []
        for frame in frames:
            if isinstance(frame, str) and frame.strip():
                await _one(kind="image", url=frame.strip(), thumbnail_url=frame.strip())


async def _exec_video_reverse(
    db: AsyncSession,
    user_id: int,
    ctx: dict[str, Any],
    data: dict,
    on_hint,
) -> dict[str, Any]:
    url = (
        data.get("clip_url")
        or data.get("result_url")
        or data.get("preview_url")
        or ctx.get("clip_url")
        or ctx.get("result_url")
        or (ctx.get("clips") or [None])[-1]
    )
    if not url:
        raise WorkflowExecError("视频反推缺少输入视频")
    brief = _as_text(data.get("prompt"), data.get("text"), ctx.get("prompt"), ctx.get("text"))
    frame_strategy = str(data.get("frame_strategy") or "scene_detect")
    await on_hint("正在智能检测参考视频镜头并抽取关键帧…" if frame_strategy != "fixed" else "正在抽取参考视频关键帧…")
    try:
        out = await video_reverse.reverse_prompt(
            db,
            user_id=user_id,
            video_url=str(url),
            brief=brief,
            model_id=str(data.get("model_id") or ""),
            frame_count=int(data.get("frame_count") or 3),
            frame_strategy=frame_strategy,
            max_scenes=int(data.get("max_scenes") or data.get("frame_count") or 6),
            scene_threshold=float(data.get("scene_threshold") or 0.28),
            sample_fps=float(data.get("sample_fps") or 2.0),
            prompt_style=str(data.get("prompt_style") or "seedance"),
        )
    except video_reverse.VideoReverseError as exc:
        raise WorkflowExecError(str(exc)) from exc
    await on_hint(None)
    return {**ctx, **out, "reference_video_url": str(url)}


def _exec_preview(ctx: dict[str, Any], _data: dict) -> dict[str, Any]:
    return _exec_video_asset(ctx, _data)


async def execute_run(run_id: int) -> None:
    async with SessionLocal() as db:
        run = await db.get(WorkflowRun, run_id)
        if run is None:
            return
        user = await db.get(User, run.user_id)
        if user is None:
            run.status = WorkflowRunStatus.FAILED.value
            run.error_message = "用户不存在"
            await db.commit()
            return

        run.status = WorkflowRunStatus.RUNNING.value
        await db.commit()

        charged: list[float] = []
        node_states: dict[str, dict] = {}
        outputs: dict[str, dict] = {}

        try:
            graph_raw = json.loads(run.graph_json) if isinstance(run.graph_json, str) else {}
            nodes, edges = _parse_graph(graph_raw)
            by_id = _node_map(nodes)
            order = topological_order(nodes, edges)
            opts = graph_raw.get("__run_opts__") or {}
            target_ids = opts.get("target_ids")
            target_set = {str(x) for x in target_ids} if target_ids else None
            if target_set is not None:
                target_set = _expand_failed_producers(target_set, by_id, edges)

            # Seed outputs for skipped upstream from existing node data
            if target_set is not None:
                for nid in order:
                    if nid in target_set:
                        continue
                    data0 = dict((by_id.get(nid) or {}).get("data") or {})
                    ntype0 = _normalize_type(
                        (by_id.get(nid) or {}).get("type"),
                        data0,
                    )
                    label0 = str(data0.get("label") or ntype0 or nid)
                    if _is_producer(ntype0) and (
                        data0.get("runStatus") == "failed" or not _has_usable_output(ntype0, data0)
                    ):
                        outputs[nid] = {
                            "__upstream_failed__": True,
                            "__label__": label0,
                            "__node_type__": ntype0,
                        }
                        continue
                    syn = _synthetic_output_from_data(data0)
                    outputs[nid] = _tag_ports(ntype0 or "TextAsset", syn)

            for nid in order:
                await db.refresh(run)
                if run.status == WorkflowRunStatus.CANCELLED.value:
                    raise WorkflowExecError("已取消")

                if target_set is not None and nid not in target_set:
                    continue

                node = by_id[nid]
                data = dict(node.get("data") or {})
                ntype = _normalize_type(node.get("type"), data)
                if ntype not in NODE_TYPES and ntype not in LEGACY_TO_FREE.values():
                    raise WorkflowExecError(f"未知节点类型：{ntype or node.get('type')}")

                if _reuse_existing_on_full_run(ntype, data, targeted=target_set is not None):
                    syn = _tag_ports(str(ntype), _synthetic_output_from_data(data))
                    outputs[nid] = syn
                    node_states[nid] = {
                        "status": "succeeded",
                        "output": {
                            k: syn.get(k)
                            for k in ("prompt", "text", "narration", "scenes", "frames")
                            if syn.get(k) not in (None, "", [])
                        },
                        "error": None,
                        "cost": 0.0,
                        "hint": "已有文案，跳过重写",
                    }
                    run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                    await db.commit()
                    continue

                node_states[nid] = {"status": "running", "output": None, "error": None, "cost": 0.0}
                run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                await db.commit()

                blocked = _blocked_upstream(outputs, edges, nid)
                if blocked:
                    raise WorkflowExecError(blocked)

                ctx = _merge_upstream(outputs, edges, nid)
                out: dict[str, Any]
                cost = 0.0

                async def _hint(msg: str | None) -> None:
                    st = node_states.get(nid) or {}
                    if msg:
                        st["hint"] = msg
                    elif "hint" in st:
                        st.pop("hint", None)
                    node_states[nid] = st
                    run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                    run.updated_at = datetime.now(timezone.utc)
                    await db.commit()

                if ntype in ("TextAsset", "BriefInput", "ScenePlan"):
                    out = _exec_text_asset(ctx, data)
                elif ntype in ("ImageAsset", "MakeupControl"):
                    out = _exec_image_asset(ctx, data)
                elif ntype == "TextToImage":
                    out = await _exec_t2i(db, user, run, ctx, data, charged, _hint)
                    cost = float(out.get("image_cost") or 0)
                elif ntype == "ImageCompare":
                    out = _exec_image_compare(ctx, data)
                elif ntype == "SpeechToText":
                    out = await _exec_speech_to_text(db, user.id, ctx, data, _hint)
                elif ntype in ("ImageToVideo", "ShotGenerate"):
                    image_wired = any(
                        str(e.get("targetHandle") or "") == "image" for e in _incoming_edges(nid, edges)
                    )
                    if image_wired and not (
                        data.get("image_url") or data.get("first_image_url") or ctx.get("image_url")
                    ):
                        raise WorkflowExecError("图生视频已接图片，但上游没有可用图片")
                    out = await _run_shot(db, user, run, ctx, data, charged, on_hint=_hint)
                    cost = float(out.get("shot_cost") or 0)
                elif ntype == "VideoTrim":
                    out = await _exec_trim(user.id, ctx, data)
                elif ntype in ("VideoMux", "TimelineMux"):
                    out = await _exec_mux(user.id, ctx, data)
                elif ntype in ("VideoAsset", "PreviewOut"):
                    out = _exec_video_asset(ctx, data)
                elif ntype == "AudioAsset":
                    out = _exec_audio_asset(ctx, data)
                elif ntype in LLM_TYPES:
                    out = await _exec_llm(db, ctx, data, ntype, _hint)
                elif ntype == "TtsSpeak":
                    out = await _exec_tts(db, ctx, data, _hint)
                elif ntype == "AudioTrim":
                    out = await _exec_audio_trim(user.id, ctx, data)
                elif ntype == "MixAudio":
                    out = await _exec_mix(user.id, ctx, data)
                elif ntype == "VideoDemux":
                    out = await _exec_demux(user.id, ctx, data)
                elif ntype == "VideoReversePrompt":
                    out = await _exec_video_reverse(db, user.id, ctx, data, _hint)
                elif ntype == "SubtitleBurn":
                    out = await _exec_subtitle(user.id, ctx, data)
                else:
                    raise WorkflowExecError(f"未实现节点：{ntype}")

                out = _tag_ports(str(ntype), out)
                outputs[nid] = out
                node_states[nid] = {
                    "status": "succeeded",
                    "output": {
                        k: v
                        for k, v in out.items()
                        if k
                        in (
                            "brand",
                            "slogan",
                            "prompt",
                            "text",
                            "scenes",
                            "clips",
                            "clip_url",
                            "result_url",
                            "image_url",
                            "before_url",
                            "after_url",
                            "url",
                            "selected",
                            "audio_url",
                            "narration",
                            "makeup_intensity",
                            "aspect",
                            "mux_note",
                            "frames",
                            "timeline",
                            "reference_video_url",
                            "outputs",
                            "srt",
                            "segments",
                        )
                    },
                    "error": None,
                    "cost": cost,
                }
                await _record_node_history(
                    db,
                    user=user,
                    run=run,
                    node_id=nid,
                    ntype=ntype,
                    data=data,
                    out=out,
                    cost=cost,
                )
                run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                run.cost = round(sum(charged), 4)
                await db.refresh(user)
                run.balance_after = user.balance
                await db.commit()

            result_url = None
            for nid in reversed(order):
                o = outputs.get(nid) or {}
                if o.get("result_url"):
                    result_url = o["result_url"]
                    break
                if o.get("clip_url"):
                    result_url = o["clip_url"]
                    break

            await db.refresh(run)
            if run.status == WorkflowRunStatus.CANCELLED.value:
                await db.commit()
                return

            run.status = WorkflowRunStatus.SUCCEEDED.value
            run.result_url = result_url
            run.cost = round(sum(charged), 4)
            await db.refresh(user)
            run.balance_after = user.balance
            run.node_states_json = json.dumps(node_states, ensure_ascii=False)
            await db.commit()
            if run.workflow_id:
                wf = await db.get(Workflow, run.workflow_id)
                if wf is not None:
                    last_img = None
                    for nid in order:
                        o = outputs.get(nid) or {}
                        img = o.get("image_url")
                        if isinstance(img, str) and img.strip() and not is_video_url(img):
                            await upsert_asset(
                                db,
                                workflow_id=wf.id,
                                user_id=wf.user_id,
                                url=img.strip(),
                                kind="image",
                            )
                            last_img = img.strip()
                        au = o.get("audio_url")
                        if isinstance(au, str) and au.strip():
                            await upsert_asset(
                                db,
                                workflow_id=wf.id,
                                user_id=wf.user_id,
                                url=au.strip(),
                                kind="audio",
                            )
                    await sync_from_graph(db, wf)
                    if result_url and is_video_url(result_url):
                        wf.cover_url = result_url
                        await replace_output(
                            db, workflow_id=wf.id, user_id=wf.user_id, url=result_url
                        )
                    else:
                        await refresh_cover(db, wf, prefer_url=last_img)
                    await prune_runs_keep_current(db, wf.id, run.id)
                    await db.commit()
            return

        except Exception as exc:  # noqa: BLE001
            await db.refresh(run)
            if run.status in {
                WorkflowRunStatus.FAILED.value,
                WorkflowRunStatus.REFUNDED.value,
                WorkflowRunStatus.SUCCEEDED.value,
            }:
                return
            if run.status == WorkflowRunStatus.CANCELLED.value or str(exc) == "已取消":
                run.status = WorkflowRunStatus.CANCELLED.value
                run.error_message = "已取消"
                for nid, st in node_states.items():
                    if st.get("status") == "running":
                        st["status"] = "failed"
                        st["error"] = "已取消"
                run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                # Refund charges on cancel
                refund = round(sum(charged), 4)
                await db.refresh(user)
                if refund > 0:
                    await record_entry(
                        db,
                        user,
                        refund,
                        kind=KIND_REFUND,
                        title=f"项目出片 #{run.id} 整单退款",
                        ref_type="run",
                        ref_id=run.id,
                    )
                    run.cost = 0.0
                run.balance_after = user.balance
                await db.commit()
                return

            refund = round(sum(charged), 4)
            await db.refresh(user)
            if refund > 0:
                await record_entry(
                    db,
                    user,
                    refund,
                    kind=KIND_REFUND,
                    title=f"项目出片 #{run.id} 整单退款",
                    ref_type="run",
                    ref_id=run.id,
                )
                run.status = WorkflowRunStatus.REFUNDED.value
            else:
                run.status = WorkflowRunStatus.FAILED.value
            run.error_message = str(exc)[:500]
            run.cost = 0.0 if refund > 0 else round(sum(charged), 4)
            run.balance_after = user.balance
            for nid, st in node_states.items():
                if st.get("status") == "running":
                    st["status"] = "failed"
                    st["error"] = str(exc)[:500]
            run.node_states_json = json.dumps(node_states, ensure_ascii=False)
            await db.commit()
