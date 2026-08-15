"""Plan-mode stage gates and tool allowlists. Runtime must enforce these; prompts are not enough."""

from __future__ import annotations

from typing import Any

from app.services.node_contracts import normalize_type_name

STAGES = ("brief", "storyboard", "graph", "shoot")
STAGE_TITLES = {
    "brief": "Brief",
    "storyboard": "分镜",
    "graph": "搭图",
    "shoot": "出片",
}
STAGE_START = {
    "brief": "开始 Brief",
    "storyboard": "开始分镜",
    "graph": "开始搭图",
    "shoot": "开始出片",
}

READ_TOOLS = frozenset(
    {"get_graph", "get_node_output", "list_asset_versions", "clear_chat", "propose_plan"}
)
COMPLETE = "complete_stage"
WRITE_CORE = frozenset(
    {"add_node", "patch_node", "connect", "delete_node", "layout_graph", "send_asset_to_canvas"}
)
BRIEF_EXTRA = frozenset({"run_llm_text"})
STORYBOARD_EXTRA = frozenset({"run_llm_text", "run_video_reverse_prompt", "expand_scenes_to_nodes"})
GRAPH_EXTRA = frozenset({"run_llm_text", "expand_scenes_to_nodes"})

BRIEF_NODE_TYPES = frozenset({"TextAsset", "LlmText"})
STORYBOARD_NODE_TYPES = frozenset(
    {"TextAsset", "LlmText", "VideoReversePrompt", "VideoAsset", "ImageAsset"}
)

GATE_STATUSES = frozenset({"plan_pending", "stage_pending"})


def next_stage(stage: str | None) -> str | None:
    if not stage or stage not in STAGES:
        return "brief"
    idx = STAGES.index(stage)
    if idx + 1 >= len(STAGES):
        return None
    return STAGES[idx + 1]


def normalize_plan(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    incoming = data.get("stages") if isinstance(data.get("stages"), list) else []
    by_id = {}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        if sid in {"brief", "storyboard", "graph"}:
            pts = item.get("points") if isinstance(item.get("points"), list) else []
            by_id[sid] = [str(p).strip() for p in pts if str(p).strip()][:8]
    stages = []
    for sid in ("brief", "storyboard", "graph"):
        stages.append(
            {
                "id": sid,
                "title": STAGE_TITLES[sid],
                "points": by_id.get(sid) or [],
            }
        )
    title = str(data.get("title") or "").strip() or "片子方案"
    return {
        "title": title[:80],
        "rebuild": bool(data.get("rebuild")),
        "stages": stages,
    }


def parse_gate(pending_json: str | None) -> dict[str, Any] | None:
    if not (pending_json or "").strip():
        return None
    try:
        import json

        data = json.loads(pending_json)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind") or "")
    if kind not in {"plan", "stage", "plan_run"}:
        return None
    plan = normalize_plan(data.get("plan") if isinstance(data.get("plan"), dict) else data)
    stage = str(data.get("stage") or "brief")
    if stage not in STAGES:
        stage = "brief"
    completed = [s for s in (data.get("completed") or []) if s in STAGES]
    return {
        "kind": kind,
        "stage": stage,
        "plan": plan,
        "completed": completed,
        "executing": bool(data.get("executing")),
        "stop_requested": bool(data.get("stop_requested")),
        "messages": data.get("messages") if isinstance(data.get("messages"), list) else None,
        "confirm": data.get("confirm") if isinstance(data.get("confirm"), dict) else None,
        "tool_name": data.get("tool_name"),
        "tool_call_id": data.get("tool_call_id"),
        "arguments": data.get("arguments") if isinstance(data.get("arguments"), dict) else None,
    }


def dump_gate(gate: dict[str, Any]) -> str:
    import json

    keep = {
        "kind": gate.get("kind") or "plan",
        "stage": gate.get("stage") or "brief",
        "plan": normalize_plan(gate.get("plan") if isinstance(gate.get("plan"), dict) else None),
        "completed": [s for s in (gate.get("completed") or []) if s in STAGES],
        "executing": bool(gate.get("executing")),
        "stop_requested": bool(gate.get("stop_requested")),
    }
    if gate.get("messages") is not None:
        keep["messages"] = gate["messages"]
    for key in ("confirm", "tool_name", "tool_call_id", "arguments"):
        if gate.get(key) is not None:
            keep[key] = gate[key]
    return json.dumps(keep, ensure_ascii=False)


def pending_plan(session) -> dict[str, Any] | None:
    if getattr(session, "status", "") != "plan_pending":
        return None
    gate = parse_gate(getattr(session, "pending_json", ""))
    return gate["plan"] if gate else None


def pending_stage(session) -> dict[str, Any] | None:
    if getattr(session, "status", "") != "stage_pending":
        return None
    gate = parse_gate(getattr(session, "pending_json", ""))
    if not gate:
        return None
    stage = gate["stage"]
    points = []
    for item in gate["plan"].get("stages") or []:
        if item.get("id") == stage:
            points = item.get("points") or []
            break
    return {
        "stage": stage,
        "title": STAGE_TITLES.get(stage, stage),
        "start_label": STAGE_START.get(stage, "开始"),
        "points": points,
        "plan": gate["plan"],
        "completed": gate.get("completed") or [],
    }


def current_stage(session) -> str | None:
    gate = parse_gate(getattr(session, "pending_json", ""))
    if not gate:
        return None
    return str(gate.get("stage") or "") or None


def is_plan_mode(session) -> bool:
    raw = str(getattr(session, "work_mode", "") or "plan").strip().lower()
    return raw not in {"auto", "goal"}


def allowed_tools(session) -> frozenset[str] | None:
    """None = all tools. Otherwise only these names may run."""
    if not is_plan_mode(session):
        return None
    status = getattr(session, "status", "idle")
    if status == "confirm_pending":
        return READ_TOOLS
    gate = parse_gate(getattr(session, "pending_json", ""))
    if status in {"plan_pending", "stage_pending"}:
        return READ_TOOLS
    if status == "running" and gate and gate.get("executing"):
        stage = gate.get("stage") or "brief"
        extra = {COMPLETE}
        if stage == "brief":
            return READ_TOOLS | WRITE_CORE | BRIEF_EXTRA | extra
        if stage == "storyboard":
            return READ_TOOLS | WRITE_CORE | STORYBOARD_EXTRA | extra
        if stage == "graph":
            return READ_TOOLS | WRITE_CORE | GRAPH_EXTRA | extra
        if stage == "shoot":
            return None
    return READ_TOOLS


def allowed_node_types(session) -> frozenset[str] | None:
    if not is_plan_mode(session):
        return None
    if getattr(session, "status", "") != "running":
        return BRIEF_NODE_TYPES
    gate = parse_gate(getattr(session, "pending_json", ""))
    stage = (gate or {}).get("stage") if gate and gate.get("executing") else None
    if stage == "brief":
        return BRIEF_NODE_TYPES
    if stage == "storyboard":
        return STORYBOARD_NODE_TYPES
    return None


def deny_reason(session, name: str, args: dict[str, Any] | None) -> str | None:
    allowed = allowed_tools(session)
    if allowed is not None and name not in allowed:
        return f"当前环节还不能用「{name}」。先把方案/本环点过，或等用户点开始。"
    if name == "add_node":
        types = allowed_node_types(session)
        if types is not None:
            nt = normalize_type_name(str((args or {}).get("node_type") or ""))
            if nt not in types:
                return f"本环只能加 {('、'.join(sorted(types)))}，不能加 {nt or '未知类型'}。"
    return None


def gate_system_note(session, workflow_graph: dict) -> str:
    if not is_plan_mode(session):
        return ""
    nodes = [n for n in (workflow_graph.get("nodes") or []) if isinstance(n, dict)]
    empty = not nodes
    status = getattr(session, "status", "idle")
    gate = parse_gate(getattr(session, "pending_json", ""))
    bits = [
        "Plan 闸门由运行时强制：没批准的环调用写工具会被拦截。必须用 propose_plan 出方案卡。",
        "做完本环调用 complete_stage。搭图环禁止 run_text_to_image / run_image_to_video 等扣费出片。",
    ]
    if empty:
        bits.append("画布是空的，不要问补还是重搭，直接按新片子出方案。")
    else:
        bits.append("画布已有节点。方案里写清是在现有上补还是重搭，推荐补（rebuild=false）。")
    if status == "plan_pending" or (status == "running" and gate and gate.get("kind") == "plan"):
        bits.append("用户正在先改方案：重出 propose_plan，不要改画布。")
    if status == "stage_pending":
        bits.append("环节待批：可以改方案或回答问题，不要改画布，等用户点开始。")
    if status == "running" and gate and gate.get("executing"):
        bits.append(f"正在执行「{STAGE_TITLES.get(gate.get('stage'), gate.get('stage'))}」环，只做这一环。做完调用 complete_stage。")
    return "\n".join(bits)
