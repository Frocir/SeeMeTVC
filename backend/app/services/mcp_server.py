"""In-process MCP-shaped tool registry for TVC Agent."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssetVersion, Channel, User, Workflow, WorkflowRun, WorkflowRunStatus
from app.services import asset_versions, graph_ops, scene_expand
from app.services.graph_revisions import persist_graph
from app.services.project_assets import refresh_cover, sync_from_graph
from app.services.run_preflight import cannot_run_reason
from app.services.workflow_exec import execute_run

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

RUN_TOOLS: dict[str, str] = {
    "run_llm_text": "LlmText",
    "run_text_to_image": "TextToImage",
    "run_image_compare": "ImageCompare",
    "run_image_to_video": "ImageToVideo",
    "run_tts_speak": "TtsSpeak",
    "run_speech_to_text": "SpeechToText",
    "run_video_trim": "VideoTrim",
    "run_video_mux": "VideoMux",
    "run_mix_audio": "MixAudio",
    "run_video_demux": "VideoDemux",
    "run_video_reverse_prompt": "VideoReversePrompt",
    "run_audio_trim": "AudioTrim",
    "run_subtitle_burn": "SubtitleBurn",
}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class McpContext:
    db: AsyncSession
    user: User
    workflow: Workflow
    viewport: tuple[float, float] = (400.0, 280.0)
    emit: Emit | None = None
    add_count: int = 0
    mutated: bool = False
    structure_changed: bool = False
    chat_cleared: bool = False


def openai_tools(allowed: frozenset[str] | None = None) -> list[dict[str, Any]]:
    from app.services.node_contracts import tool_add_node_description, tool_connect_description

    out = []
    for t in TOOL_SPECS:
        if allowed is not None and t.name not in allowed:
            continue
        desc = t.description
        if t.name == "add_node":
            desc = tool_add_node_description()
        elif t.name == "connect":
            desc = tool_connect_description()
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": desc,
                    "parameters": t.parameters,
                },
            }
        )
    return out


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "get_graph",
        "读取当前项目画布节点与连线（瘦身版）。改图前先调用。",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        "add_node",
        "在画布上新增一个节点。node_type 必须是现有类型。",
        {
            "type": "object",
            "properties": {
                "node_type": {"type": "string"},
                "label": {"type": "string"},
                "data": {"type": "object"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["node_type"],
        },
    ),
    ToolSpec(
        "patch_node",
        "修改已有节点的 data / 名称 / 位置。",
        {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "data": {"type": "object"},
                "label": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["node_id"],
        },
    ),
    ToolSpec(
        "connect",
        "连接两个节点的端口。必须传 source_handle 与 target_handle。",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "source_handle": {"type": "string"},
                "target_handle": {"type": "string"},
            },
            "required": ["source", "target", "source_handle", "target_handle"],
        },
    ),
    ToolSpec(
        "delete_node",
        "删除节点及其连线。",
        {"type": "object", "properties": {"node_id": {"type": "string"}}, "required": ["node_id"]},
    ),
    ToolSpec(
        "layout_graph",
        "按连线把画布节点自动排开，避免叠在一起。搭完工作流后必须调用；用户说排版/整理/对齐时也调用。不要手填 x/y 去摆位置。",
        {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["horizontal", "vertical"]},
            },
        },
    ),
    ToolSpec(
        "clear_chat",
        "清空当前项目的 Agent 对话和摘要，画布节点不动。用户说清空对话、新对话、忘掉刚才说的时调用。不要在用户没要求时调用。",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        "propose_plan",
        "Plan 模式必须调用：把 Brief → 分镜 → 搭图 的方案写成卡片。批准前不要改画布。先改方案时再调用一次覆盖旧卡。",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "rebuild": {"type": "boolean", "description": "true=重搭画布，false=在现有上补"},
                "stages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "enum": ["brief", "storyboard", "graph"]},
                            "points": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "required": ["stages"],
        },
    ),
    ToolSpec(
        "complete_stage",
        "当前创作环做完时调用，进入下一环等待用户点开始。不要用它代替出片。",
        {
            "type": "object",
            "properties": {"note": {"type": "string"}},
        },
    ),
    ToolSpec(
        "expand_scenes_to_nodes",
        "把 VideoReversePrompt 的 scenes 展开成多镜头节点链。1–4 条可直接展开；超过 4 条须先询问用户是否压缩，不要擅自全部展开。mode：silent / with_image / with_tts / full_tvc。",
        {
            "type": "object",
            "properties": {
                "source_node_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["silent", "with_image", "with_tts", "full_tvc"]},
                "create_images": {"type": "boolean"},
                "create_tts": {"type": "boolean"},
                "create_subtitles": {"type": "boolean"},
                "layout": {"type": "string", "enum": ["horizontal", "vertical"]},
            },
            "required": ["source_node_id"],
        },
    ),
    ToolSpec(
        "get_node_output",
        "读取指定节点的当前输出：prompt、text、srt、scenes 摘要、媒体 URL、运行状态。反推完成后用它读分镜。",
        {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
    ),
    ToolSpec(
        "list_asset_versions",
        "列出当前项目的生成历史（图/视频/音频/文案）。复用素材前先调用。",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["image", "video", "audio", "text", "prompt"]},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    ),
    ToolSpec(
        "send_asset_to_canvas",
        "把一条生成历史放到画布，自动新建对应素材节点。",
        {
            "type": "object",
            "properties": {
                "version_id": {"type": "integer"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["version_id"],
        },
    ),
]

for _tool, _nt in RUN_TOOLS.items():
    TOOL_SPECS.append(
        ToolSpec(
            _tool,
            f"运行画布上已有的 {_nt} 节点（id=node_id）。会扣费的生成需等用户确认卡。",
            {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
            },
        )
    )


TOOL_PROGRESS: dict[str, str] = {
    "get_graph": "正在查看画布…",
    "add_node": "正在添加节点…",
    "patch_node": "正在修改节点…",
    "connect": "正在连线…",
    "delete_node": "正在删除节点…",
    "layout_graph": "正在给节点排版…",
    "clear_chat": "正在清空对话…",
    "propose_plan": "正在写方案…",
    "complete_stage": "正在结束本环…",
    "expand_scenes_to_nodes": "正在把分镜展开成工作流…",
    "get_node_output": "正在读取节点输出…",
    "list_asset_versions": "正在查看生成历史…",
    "send_asset_to_canvas": "正在把历史素材放到画布…",
    "run_llm_text": "正在写分镜提示词…",
    "run_text_to_image": "正在生成图片…",
    "run_image_compare": "正在对比图片…",
    "run_image_to_video": "正在生成视频…",
    "run_tts_speak": "正在合成口播…",
    "run_speech_to_text": "正在提取口播文案…",
    "run_video_trim": "正在裁剪视频…",
    "run_video_mux": "正在拼接视频…",
    "run_mix_audio": "正在混音…",
    "run_video_demux": "正在分离音视频…",
    "run_video_reverse_prompt": "正在反推参考视频…",
    "run_audio_trim": "正在裁剪音频…",
    "run_subtitle_burn": "正在烧录字幕…",
}

CONFIRM_WAIT_DETAIL = "等待你确认扣费后才会开始生成，确认前不扣费。"


def tool_progress_detail(name: str, status: str = "running") -> str:
    if status == "waiting":
        return CONFIRM_WAIT_DETAIL
    if status == "running":
        return TOOL_PROGRESS.get(name, "正在执行工具…")
    return ""


def tool_done_detail(name: str, result: str) -> str:
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return (result or "")[:160]
    if not isinstance(data, dict):
        return (result or "")[:160]
    err = data.get("error")
    if err:
        return str(err)[:240]
    if name == "expand_scenes_to_nodes":
        n = len(data.get("created_node_ids") or [])
        warn = data.get("warning")
        msg = f"已展开 {n} 个节点"
        return f"{msg}。{warn}" if warn else msg
    if name == "get_node_output":
        sc = data.get("scene_count")
        if sc:
            return f"读到 {sc} 条分镜"
        return "已读取节点输出"
    if name == "list_asset_versions":
        return f"共 {data.get('total') or 0} 条历史"
    if name == "send_asset_to_canvas":
        return f"已放到画布：{data.get('node_id') or ''}"
    if name == "layout_graph":
        return f"已排开 {data.get('moved') or 0} 个节点"
    if name == "clear_chat":
        return "已清空对话"
    if name == "propose_plan":
        return "已写出方案卡"
    if name == "complete_stage":
        return "本环做完了"
    if name in RUN_TOOLS:
        st = str(data.get("status") or "")
        if st == "succeeded":
            return "生成完成"
        return st or "已完成"
    if data.get("ok"):
        return "完成"
    return "完成"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _clip_text(val: Any, n: int = 400) -> str:
    s = str(val or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _node_output_payload(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    run_out = data.get("runOutput") if isinstance(data.get("runOutput"), dict) else {}
    merged: dict[str, Any] = dict(run_out)
    merged.update({k: v for k, v in data.items() if v not in (None, "")})
    scenes = merged.get("scenes")
    scene_summaries: list[dict[str, Any]] = []
    scene_count = 0
    if isinstance(scenes, list):
        scene_count = len(scenes)
        for idx, item in enumerate(scenes[:8], start=1):
            if isinstance(item, dict):
                scene_summaries.append(
                    {
                        "index": idx,
                        "title": str(item.get("title") or ""),
                        "prompt": _clip_text(item.get("prompt") or item.get("seedance_prompt") or "", 400),
                        "narration": _clip_text(item.get("narration") or "", 200),
                    }
                )
            else:
                scene_summaries.append({"index": idx, "prompt": _clip_text(item, 400)})
    payload: dict[str, Any] = {
        "node_id": str(node.get("id") or ""),
        "node_type": graph_ops.normalize_type(node),
        "label": str(data.get("label") or ""),
        "runStatus": data.get("runStatus") or "",
        "runError": data.get("runError") or None,
    }
    for key in (
        "prompt",
        "text",
        "srt",
        "narration",
        "image_url",
        "clip_url",
        "result_url",
        "preview_url",
        "audio_url",
        "before_url",
        "after_url",
        "url",
        "selected",
        "reference_video_url",
    ):
        val = merged.get(key)
        if isinstance(val, str) and val.strip():
            payload[key] = val.strip() if key in {"image_url", "clip_url", "result_url", "preview_url", "audio_url", "before_url", "after_url", "url", "selected", "reference_video_url"} else _clip_text(val, 1200)
    if scene_summaries:
        payload["scenes"] = scene_summaries
        payload["scene_count"] = scene_count
    frames = merged.get("frames")
    if isinstance(frames, list) and frames:
        payload["frame_count"] = len(frames)
        payload["frames"] = [str(f) for f in frames[:6] if isinstance(f, str)]
    segments = merged.get("segments")
    if isinstance(segments, list) and segments:
        payload["segment_count"] = len(segments)
    timeline = merged.get("timeline")
    if timeline not in (None, "", []):
        payload["timeline"] = timeline
    return payload


def _asset_version_brief(row: AssetVersion) -> dict[str, Any]:
    created = row.created_at.isoformat() if row.created_at else None
    return {
        "id": row.id,
        "kind": row.kind,
        "node_type": row.node_type,
        "url": (row.url or "")[:500],
        "thumbnail_url": (row.thumbnail_url or row.url or "")[:500],
        "text": _clip_text(row.text, 200),
        "prompt": _clip_text(row.prompt, 200),
        "cost": row.cost,
        "status": row.status,
        "favorite": bool(row.favorite),
        "created_at": created,
    }


async def call_tool(ctx: McpContext, name: str, arguments: dict[str, Any]) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    graph = graph_ops.parse_graph(ctx.workflow.graph_json)
    if name == "get_graph":
        return dumps(graph_ops.slim_graph(graph))
    if name == "propose_plan":
        from app.services.agent_gates import normalize_plan

        return dumps({"ok": True, "plan": normalize_plan(args)})
    if name == "complete_stage":
        return dumps({"ok": True, "note": str(args.get("note") or "")})
    if name == "add_node":
        ctx.add_count += 1
        nid = graph_ops.add_node(
            graph,
            node_type=str(args.get("node_type") or ""),
            label=str(args.get("label") or ""),
            data=args.get("data") if isinstance(args.get("data"), dict) else None,
            x=args.get("x"),
            y=args.get("y"),
            viewport=(
                ctx.viewport[0] + 36 * (ctx.add_count % 6),
                ctx.viewport[1] + 36 * (ctx.add_count % 6),
            ),
        )
        await _save(ctx, graph)
        ctx.structure_changed = True
        return dumps({"node_id": nid, "node_type": str(args.get("node_type") or "")})
    if name == "patch_node":
        graph_ops.patch_node(
            graph,
            str(args.get("node_id") or ""),
            data=args.get("data") if isinstance(args.get("data"), dict) else None,
            label=args.get("label"),
            x=args.get("x"),
            y=args.get("y"),
        )
        await _save(ctx, graph)
        return dumps({"ok": True, "node_id": args.get("node_id")})
    if name == "connect":
        eid = graph_ops.connect(
            graph,
            source=str(args.get("source") or ""),
            target=str(args.get("target") or ""),
            source_handle=str(args.get("source_handle") or ""),
            target_handle=str(args.get("target_handle") or ""),
        )
        await _save(ctx, graph)
        ctx.structure_changed = True
        return dumps({"ok": True, "edge_id": eid})
    if name == "delete_node":
        graph_ops.delete_node(graph, str(args.get("node_id") or ""))
        await _save(ctx, graph)
        ctx.structure_changed = True
        return dumps({"ok": True})
    if name == "layout_graph":
        moved = graph_ops.layout_graph(graph, direction=str(args.get("direction") or "horizontal"))
        ctx.structure_changed = False
        if moved:
            await _save(ctx, graph)
        return dumps({"ok": True, "moved": moved, "direction": str(args.get("direction") or "horizontal")})
    if name == "clear_chat":
        from app.services import agent_runtime as runtime

        session = await runtime.get_or_create_session(ctx.db, workflow=ctx.workflow, user=ctx.user)
        if session.status == "confirm_pending":
            raise ValueError("请先确认或取消当前的生成，再清空对话")
        n = await runtime.clear_session_chat(ctx.db, session)
        ctx.chat_cleared = True
        await ctx.db.commit()
        if ctx.emit:
            await ctx.emit("chat_cleared", {"ok": True})
        return dumps({"ok": True, "cleared": n})
    if name == "expand_scenes_to_nodes":
        result = scene_expand.expand_scenes_to_nodes(
            graph,
            source_node_id=str(args.get("source_node_id") or ""),
            mode=str(args.get("mode") or "with_image"),
            create_images=args.get("create_images") if isinstance(args.get("create_images"), bool) else None,
            create_tts=args.get("create_tts") if isinstance(args.get("create_tts"), bool) else None,
            create_subtitles=args.get("create_subtitles") if isinstance(args.get("create_subtitles"), bool) else None,
            layout=str(args.get("layout") or "horizontal"),
        )
        await _save(ctx, graph)
        ctx.structure_changed = True
        return dumps(
            {
                "ok": True,
                "created_node_ids": result.get("created_node_ids") or [],
                "created_edge_ids": result.get("created_edge_ids") or [],
                "final_node_id": result.get("final_node_id"),
                "scene_count": result.get("scene_count"),
                "source_scene_count": result.get("source_scene_count"),
                "warning": result.get("warning"),
            }
        )
    if name == "get_node_output":
        node = graph_ops._find(graph, str(args.get("node_id") or ""))
        return dumps(_node_output_payload(node))
    if name == "list_asset_versions":
        kind = str(args.get("kind") or "").strip() or None
        if kind and kind not in {"image", "video", "audio", "text", "prompt"}:
            raise ValueError("kind 只能是 image / video / audio / text / prompt")
        try:
            limit = int(args.get("limit") or 30)
            offset = int(args.get("offset") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit / offset 必须是数字") from exc
        rows, total = await asset_versions.list_asset_versions(
            ctx.db,
            workflow_id=ctx.workflow.id,
            kind=kind,
            limit=limit,
            offset=offset,
        )
        return dumps(
            {
                "ok": True,
                "total": total,
                "items": [_asset_version_brief(row) for row in rows],
            }
        )
    if name == "send_asset_to_canvas":
        try:
            version_id = int(args.get("version_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("version_id 必须是数字") from exc
        row = await ctx.db.get(AssetVersion, version_id)
        if row is None or row.workflow_id != ctx.workflow.id or row.user_id != ctx.user.id:
            raise ValueError(f"素材历史不存在：{version_id}")
        x = args.get("x")
        y = args.get("y")
        viewport = (
            float(x) if isinstance(x, (int, float)) else ctx.viewport[0],
            float(y) if isinstance(y, (int, float)) else ctx.viewport[1],
        )
        sent = await asset_versions.send_to_canvas(
            ctx.db,
            workflow=ctx.workflow,
            row=row,
            viewport=viewport,
        )
        graph = sent.get("graph") if isinstance(sent.get("graph"), dict) else graph_ops.parse_graph(ctx.workflow.graph_json)
        await _save(ctx, graph)
        ctx.structure_changed = True
        return dumps(
            {
                "ok": True,
                "node_id": sent.get("node_id"),
                "node_type": sent.get("node_type"),
            }
        )
    if name in RUN_TOOLS:
        return await _run_node(ctx, graph, name, str(args.get("node_id") or ""))
    raise ValueError(f"未知工具：{name}")


async def maybe_autolayout(ctx: McpContext) -> int:
    """After add/connect/delete/expand, tidy the canvas even if the model forgot layout_graph."""
    if not ctx.structure_changed:
        return 0
    graph = graph_ops.parse_graph(ctx.workflow.graph_json)
    moved = graph_ops.layout_graph(graph)
    ctx.structure_changed = False
    if not moved:
        return 0
    await _save(ctx, graph)
    if ctx.emit:
        await ctx.emit(
            "tool",
            {
                "name": "layout_graph",
                "status": "done",
                "detail": f"已排开 {moved} 个节点",
            },
        )
    return moved


async def estimate_run_cost(db: AsyncSession, graph: dict, node_id: str) -> dict[str, Any]:
    node = graph_ops._find(graph, node_id)
    nt = graph_ops.normalize_type(node)
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    label = str(data.get("label") or nt)
    model_id = str(data.get("model_id") or "")
    cost = 0.0
    if nt == "TextToImage":
        ch = await _channel(db, model_id, kind="image")
        if ch is not None:
            model_id = ch.model_id
            cost = round(float(ch.cost_per_second or 0), 4)
    elif nt == "ImageToVideo":
        ch = await _channel(db, model_id, kind="video")
        if ch is not None:
            model_id = ch.model_id
            dur = int(data.get("duration_seconds") or 5)
            cost = round(float(ch.cost_per_second or 0) * dur, 4)
    return {
        "node_id": node_id,
        "node_type": nt,
        "label": label,
        "model_id": model_id,
        "estimated_cost": cost,
        "needs_confirm": cost > 0,
    }


async def _run_node(ctx: McpContext, graph: dict, tool_name: str, node_id: str) -> str:
    want = RUN_TOOLS[tool_name]
    node = graph_ops._find(graph, node_id)
    nt = graph_ops.normalize_type(node)
    if nt != want:
        raise ValueError(f"{tool_name} 只能跑 {want} 节点，当前是 {nt}")
    ch_rows = (await ctx.db.execute(select(Channel).where(Channel.enabled.is_(True)))).scalars().all()
    kinds = {(c.kind or "video").strip().lower() or "video" for c in ch_rows}
    reason = cannot_run_reason(
        graph,
        target_ids=[node_id],
        has_video_model="video" in kinds,
        has_llm_model="llm" in kinds,
        has_tts_model="tts" in kinds,
        has_image_model="image" in kinds,
        has_asr_model="asr" in kinds,
    )
    if reason:
        raise ValueError(reason)
    payload = dict(graph)
    payload["__run_opts__"] = {"target_ids": [node_id]}
    run = WorkflowRun(
        workflow_id=ctx.workflow.id,
        user_id=ctx.user.id,
        status=WorkflowRunStatus.PENDING.value,
        graph_json=json.dumps(payload, ensure_ascii=False),
        node_states_json="{}",
    )
    ctx.db.add(run)
    await ctx.db.commit()
    await ctx.db.refresh(run)
    await execute_run(run.id)
    await ctx.db.refresh(run)
    states = {}
    try:
        states = json.loads(run.node_states_json or "{}")
    except json.JSONDecodeError:
        states = {}
    st = states.get(node_id) or {}
    status = str(run.status or st.get("status") or "")
    err = str(run.error_message or st.get("error") or "")
    output = st.get("output") if isinstance(st.get("output"), dict) else {}
    await ctx.db.refresh(ctx.workflow)
    graph = graph_ops.parse_graph(ctx.workflow.graph_json)
    graph_ops.apply_run_output(graph, node_id, output, "succeeded" if status == "succeeded" else "failed", err)
    await _save(ctx, graph)
    return dumps(
        {
            "run_id": run.id,
            "status": status,
            "cost": run.cost,
            "output": output,
            "error": err or None,
        }
    )


async def _save(ctx: McpContext, graph: dict) -> None:
    changed = await persist_graph(ctx.db, ctx.workflow, graph, source="agent_tool")
    if changed:
        await sync_from_graph(ctx.db, ctx.workflow)
        await refresh_cover(ctx.db, ctx.workflow)
        ctx.mutated = True
    await ctx.db.commit()
    await ctx.db.refresh(ctx.workflow)
    if ctx.emit:
        await ctx.emit("graph", graph_ops.parse_graph(ctx.workflow.graph_json))


async def _channel(db: AsyncSession, model_id: str, *, kind: str) -> Channel | None:
    if model_id.strip():
        result = await db.execute(
            select(Channel)
            .where(Channel.model_id == model_id, Channel.enabled.is_(True), Channel.kind == kind)
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
        if ch is not None:
            return ch
    result = await db.execute(
        select(Channel)
        .where(Channel.enabled.is_(True), Channel.kind == kind)
        .order_by(Channel.priority.desc(), Channel.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
