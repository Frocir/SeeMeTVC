"""In-process MCP-shaped tool registry for TVC Agent."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, User, Workflow, WorkflowRun, WorkflowRunStatus
from app.services import graph_ops
from app.services.graph_revisions import persist_graph
from app.services.project_assets import refresh_cover, sync_from_graph
from app.services.run_preflight import cannot_run_reason
from app.services.workflow_exec import execute_run

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

RUN_TOOLS: dict[str, str] = {
    "run_llm_text": "LlmText",
    "run_text_to_image": "TextToImage",
    "run_image_to_video": "ImageToVideo",
    "run_tts_speak": "TtsSpeak",
    "run_video_trim": "VideoTrim",
    "run_video_mux": "VideoMux",
    "run_mix_audio": "MixAudio",
    "run_video_demux": "VideoDemux",
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


def openai_tools() -> list[dict[str, Any]]:
    from app.services.node_contracts import tool_add_node_description, tool_connect_description

    out = []
    for t in TOOL_SPECS:
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


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def call_tool(ctx: McpContext, name: str, arguments: dict[str, Any]) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    graph = graph_ops.parse_graph(ctx.workflow.graph_json)
    if name == "get_graph":
        return dumps(graph_ops.slim_graph(graph))
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
        return dumps({"ok": True, "edge_id": eid})
    if name == "delete_node":
        graph_ops.delete_node(graph, str(args.get("node_id") or ""))
        await _save(ctx, graph)
        return dumps({"ok": True})
    if name in RUN_TOOLS:
        return await _run_node(ctx, graph, name, str(args.get("node_id") or ""))
    raise ValueError(f"未知工具：{name}")


async def estimate_run_cost(db: AsyncSession, graph: dict, node_id: str) -> dict[str, Any]:
    node = graph_ops._find(graph, node_id)
    nt = graph_ops.normalize_type(node)
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    label = str(data.get("label") or nt)
    model_id = str(data.get("model_id") or "")
    cost = 0.0
    if nt == "ImageToVideo":
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
