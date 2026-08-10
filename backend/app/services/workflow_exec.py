"""Beauty-TVC scoped DAG executor (ComfyUI-like, not ComfyUI-compatible).

Node types (fixed set):
  BriefInput | ScenePlan | ShotGenerate | MakeupControl | TimelineMux | PreviewOut
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Channel, User, WorkflowRun, WorkflowRunStatus
from app.services import seedance

NODE_TYPES = frozenset(
    {
        "BriefInput",
        "ScenePlan",
        "ShotGenerate",
        "MakeupControl",
        "TimelineMux",
        "PreviewOut",
    }
)


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


def _upstream_ids(node_id: str, edges: list[dict]) -> list[str]:
    return [str(e["source"]) for e in edges if str(e.get("target")) == node_id]


def _merge_upstream(outputs: dict[str, dict], ups: list[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    clips: list[str] = []
    scenes: list[dict] = []
    for uid in ups:
        out = outputs.get(uid) or {}
        for k, v in out.items():
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
    templates = [
        ("开场钩子", f"特写妆容开场，{base}，镜头推进，电影感光线"),
        ("产品展示", f"产品瓶身与质地特写，{points}，柔焦背景，广告片质感"),
        ("妆前对比", f"妆前素颜自然光，轻妆过渡前的状态，{brand}"),
        ("妆后演绎", f"妆后气色提升，{points}，{slogan}，自信微笑"),
        ("收束口号", f"品牌收束镜头，字幕「{slogan or brand}」，优雅转场"),
    ]
    count = int(data.get("scene_count") or 3)
    count = max(1, min(count, len(templates)))
    scenes = [
        {"index": i, "title": t[0], "prompt": t[1]} for i, t in enumerate(templates[:count])
    ]
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
    max_shots = int(data.get("max_shots") or 3)
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
            for _ in range(36):
                status, got = await seedance.poll_generation(channel, task_id)
                if status == "succeeded":
                    url = got
                    break
                if status == "failed":
                    raise seedance.SeedanceError("上游生成失败")
                await asyncio.sleep(5)
            if not url:
                raise seedance.SeedanceError("生成超时")
            clips.append(url)
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


def _exec_mux(ctx: dict[str, Any], data: dict) -> dict[str, Any]:
    aspect = data.get("aspect") or "16:9"
    clips = list(ctx.get("clips") or [])
    if ctx.get("clip_url") and ctx["clip_url"] not in clips:
        clips.append(ctx["clip_url"])
    if not clips:
        raise WorkflowExecError("TimelineMux 没有可拼接的片段")
    # MVP: no ffmpeg — expose ordered playlist; primary = last clip (收束镜头优先用最后一镜)
    primary = clips[-1] if data.get("pick") == "last" else clips[0]
    return {
        **ctx,
        "clips": clips,
        "clip_url": primary,
        "aspect": aspect,
        "mux_note": "MVP 输出片段列表；成片拼接可后续接 ffmpeg",
    }


def _exec_preview(ctx: dict[str, Any], _data: dict) -> dict[str, Any]:
    url = ctx.get("clip_url") or (ctx.get("clips") or [None])[-1]
    if not url:
        raise WorkflowExecError("PreviewOut 缺少预览地址")
    return {**ctx, "result_url": url, "clip_url": url}


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
            nodes, edges = _parse_graph(run.graph_json)
            by_id = _node_map(nodes)
            order = topological_order(nodes, edges)

            for nid in order:
                node = by_id[nid]
                ntype = node.get("type") or (node.get("data") or {}).get("type")
                # React Flow often puts type on node.type; data holds params
                data = dict(node.get("data") or {})
                if ntype in (None, "default") and data.get("nodeType"):
                    ntype = data["nodeType"]
                if ntype not in NODE_TYPES:
                    raise WorkflowExecError(f"未知节点类型：{ntype}")

                node_states[nid] = {"status": "running", "output": None, "error": None, "cost": 0.0}
                run.node_states_json = json.dumps(node_states, ensure_ascii=False)
                await db.commit()

                ctx = _merge_upstream(outputs, _upstream_ids(nid, edges))
                out: dict[str, Any]
                cost = 0.0

                if ntype == "BriefInput":
                    out = _exec_brief(ctx, data)
                elif ntype == "ScenePlan":
                    out = _exec_scene_plan(ctx, data)
                elif ntype == "MakeupControl":
                    out = _exec_makeup(ctx, data)
                elif ntype == "ShotGenerate":
                    out = await _run_shot(db, user, ctx, data, charged)
                    cost = float(out.get("shot_cost") or 0)
                elif ntype == "TimelineMux":
                    out = _exec_mux(ctx, data)
                elif ntype == "PreviewOut":
                    out = _exec_preview(ctx, data)
                else:
                    raise WorkflowExecError(f"未实现节点：{ntype}")

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
                            "scenes",
                            "clips",
                            "clip_url",
                            "result_url",
                            "makeup_intensity",
                            "aspect",
                            "mux_note",
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

            # Final result from last PreviewOut or any clip_url
            result_url = None
            for nid in reversed(order):
                o = outputs.get(nid) or {}
                if o.get("result_url"):
                    result_url = o["result_url"]
                    break
                if o.get("clip_url"):
                    result_url = o["clip_url"]
                    break

            run.status = WorkflowRunStatus.SUCCEEDED.value
            run.result_url = result_url
            run.cost = round(sum(charged), 4)
            await db.refresh(user)
            run.balance_after = user.balance
            run.node_states_json = json.dumps(node_states, ensure_ascii=False)
            await db.commit()

        except Exception as exc:  # noqa: BLE001
            # Refund all costs charged in this run
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
            # Mark running node failed
            for nid, st in node_states.items():
                if st.get("status") == "running":
                    st["status"] = "failed"
                    st["error"] = str(exc)[:500]
            run.node_states_json = json.dumps(node_states, ensure_ascii=False)
            await db.commit()
