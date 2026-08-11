"""Beauty-TVC canvas executor: freeform nodes + legacy 6-type aliases."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Channel, User, WorkflowRun, WorkflowRunStatus
from app.services import media_ops, seedance

LEGACY_TO_FREE = {
    "BriefInput": "TextAsset",
    "ScenePlan": "TextAsset",
    "MakeupControl": "ImageAsset",
    "ShotGenerate": "ImageToVideo",
    "TimelineMux": "VideoMux",
    "PreviewOut": "VideoAsset",
}

NODE_TYPES = frozenset(
    {
        "TextAsset",
        "ImageAsset",
        "VideoAsset",
        "ImageToVideo",
        "VideoTrim",
        "VideoMux",
        *LEGACY_TO_FREE.keys(),
    }
)


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
        raise WorkflowExecError("工作流图存在环或无效依赖，无法执行")
    return order


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
    elif free == "ImageToVideo" or ntype == "ShotGenerate":
        ports["clips"] = list(out.get("clips") or [])
        ports["video"] = out.get("clip_url") or (ports["clips"][-1] if ports["clips"] else None)
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


def _exec_scene_plan(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    brief = _brief_from_ctx(ctx, data)
    brand = brief.get("brand") or "品牌"
    points = brief.get("selling_points") or "质感与气色"
    slogan = brief.get("slogan") or ""
    base = brief.get("prompt") or f"{brand}美妆广告"
    style = str(data.get("style_hint") or "").strip()
    templates = [
        ("开场钩子", f"特写妆容开场，{base}，镜头推进，电影感光线"),
        ("产品展示", f"产品瓶身与质地特写，{points}，柔焦背景，广告片质感"),
        ("妆前对比", f"妆前素颜自然光，轻妆过渡前的状态，{brand}"),
        ("妆后演绎", f"妆后气色提升，{points}，{slogan}，自信微笑"),
        ("收束口号", f"品牌收束镜头，字幕「{slogan or brand}」，优雅转场"),
    ]
    count = int(data.get("scene_count") or 3)
    count = max(1, min(count, len(templates)))
    scenes = []
    for i, t in enumerate(templates[:count]):
        prompt = t[1]
        if style:
            prompt = f"{prompt}。{style}"
        scenes.append({"index": i, "title": t[0], "prompt": prompt})
    return {**brief, "scenes": scenes, "prompt": scenes[0]["prompt"]}


def _exec_makeup(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    intensity = float(data.get("intensity") if data.get("intensity") is not None else 0.6)
    intensity = max(0.0, min(1.0, intensity))
    before = data.get("before_prompt") or ctx.get("before_prompt") or "素颜自然肤质，淡妆前状态"
    after = data.get("after_prompt") or ctx.get("after_prompt") or "精致妆容，气色明亮"
    blend = (
        f"妆容强度 {int(intensity * 100)}%。"
        f"妆前：{before}。"
        f"妆后：{after}。"
        f"过渡自然，广告级美妆特写。"
    )
    base = ctx.get("prompt") or ""
    prompt = f"{base}。{blend}" if base else blend
    out = {**ctx, "prompt": prompt, "makeup_intensity": intensity}
    scenes = ctx.get("scenes")
    if isinstance(scenes, list) and scenes:
        enriched = []
        for s in scenes:
            sp = dict(s)
            sp["prompt"] = f"{s.get('prompt', '')}。{blend}"
            enriched.append(sp)
        out["scenes"] = enriched
    return out


async def _run_shot(
    db: AsyncSession,
    user: User,
    ctx: dict[str, Any],
    data: dict,
    charged: list[float],
    on_hint=None,
) -> dict[str, Any]:
    model_id = data.get("model_id") or ctx.get("model_id")
    if not model_id:
        raise WorkflowExecError("ShotGenerate 缺少 model_id")

    duration = int(data.get("duration_seconds") or ctx.get("duration_seconds") or 5)
    duration = max(2, min(duration, 30))
    image_url = data.get("image_url") or ctx.get("image_url")

    channel = await _pick_channel(db, str(model_id))
    if channel is None:
        raise WorkflowExecError(f"模型不可用：{model_id}")

    scenes = ctx.get("scenes") if isinstance(ctx.get("scenes"), list) else None
    prompts: list[str]
    if scenes and data.get("use_scenes", True):
        prompts = [str(s.get("prompt") or "") for s in scenes if s.get("prompt")]
    else:
        prompts = [str(data.get("prompt") or ctx.get("prompt") or "")]

    prompts = [p for p in prompts if p.strip()]
    if not prompts:
        raise WorkflowExecError("ShotGenerate 缺少有效提示词")

    # Cap parallel shots in one node (Agnes RPM / cost); sequential for stability
    max_shots = int(data.get("max_shots") or 1)
    prompts = prompts[: max(1, min(max_shots, 5))]

    clips: list[str] = []
    node_cost = 0.0

    for prompt in prompts:
        cost = round(float(channel.cost_per_second) * duration, 4)
        await db.refresh(user)
        if user.balance < cost:
            raise WorkflowExecError("余额不足，无法继续生成镜头")

        user.balance = float(user.balance) - cost
        node_cost += cost
        charged.append(cost)
        await db.commit()

        try:
            task_id = await seedance.submit_generation(
                channel,
                prompt=prompt,
                duration_seconds=duration,
                image_url=image_url,
            )
            url: str | None = None
            # Agnes free tier rate-limits status queries; poll slower + back off on 429.
            is_agnes = channel.provider.lower() in {"agnes", "pavo", "agnes-pavo"}
            interval = 12.0 if is_agnes else 5.0
            polls = 60 if is_agnes else 36
            rate_hits = 0
            for _ in range(polls):
                status, got = await seedance.poll_generation(channel, task_id)
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
                if on_hint and is_agnes:
                    await on_hint("生成中（Agnes 状态查询已节流）…")
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
            user.balance = float(user.balance) + cost
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
    role = str(data.get("textRole") or "brief")
    if role == "script" or data.get("scene_count"):
        return _exec_scene_plan(ctx, data)
    brief = _exec_brief(ctx, data)
    text = data.get("text") or brief.get("prompt") or ""
    return {**brief, "text": text}


def _exec_image_asset(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    out = _exec_makeup(ctx, data) if data.get("before_prompt") or data.get("after_prompt") else {**ctx}
    image = data.get("image_url") or ctx.get("image_url")
    if image:
        out["image_url"] = image
    return out


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

            # Seed outputs for skipped upstream from existing node data
            if target_set is not None:
                for nid in order:
                    if nid in target_set:
                        continue
                    data0 = dict((by_id.get(nid) or {}).get("data") or {})
                    syn = _synthetic_output_from_data(data0)
                    ntype0 = _normalize_type(
                        (by_id.get(nid) or {}).get("type"),
                        data0,
                    )
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

                node_states[nid] = {"status": "running", "output": None, "error": None, "cost": 0.0}
                run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                await db.commit()

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
                    await db.commit()

                if ntype in ("TextAsset", "BriefInput", "ScenePlan"):
                    if str(data.get("textRole") or "") == "script" or ntype == "ScenePlan":
                        out = _exec_scene_plan(ctx, data)
                    elif ntype == "BriefInput" or str(data.get("textRole") or "brief") == "brief":
                        out = _exec_text_asset(ctx, data)
                    else:
                        out = _exec_text_asset(ctx, data)
                elif ntype in ("ImageAsset", "MakeupControl"):
                    out = _exec_image_asset(ctx, data)
                elif ntype in ("ImageToVideo", "ShotGenerate"):
                    out = await _run_shot(db, user, ctx, data, charged, on_hint=_hint)
                    cost = float(out.get("shot_cost") or 0)
                elif ntype == "VideoTrim":
                    out = await _exec_trim(user.id, ctx, data)
                elif ntype in ("VideoMux", "TimelineMux"):
                    out = await _exec_mux(user.id, ctx, data)
                elif ntype in ("VideoAsset", "PreviewOut"):
                    out = _exec_video_asset(ctx, data)
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
                            "makeup_intensity",
                            "aspect",
                            "mux_note",
                            "outputs",
                        )
                    },
                    "error": None,
                    "cost": cost,
                }
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
                return

            run.status = WorkflowRunStatus.SUCCEEDED.value
            run.result_url = result_url
            run.cost = round(sum(charged), 4)
            await db.refresh(user)
            run.balance_after = user.balance
            run.node_states_json = json.dumps(node_states, ensure_ascii=False)
            await db.commit()

        except Exception as exc:  # noqa: BLE001
            await db.refresh(run)
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
                    user.balance = float(user.balance) + refund
                    run.cost = 0.0
                run.balance_after = user.balance
                await db.commit()
                return

            refund = round(sum(charged), 4)
            await db.refresh(user)
            if refund > 0:
                user.balance = float(user.balance) + refund
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
