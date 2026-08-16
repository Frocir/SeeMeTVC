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

LOOK_TOOLS = frozenset(
    {"get_graph", "get_node_output", "list_asset_versions", "clear_chat"}
)
READ_TOOLS = LOOK_TOOLS | {"propose_plan"}
COMPLETE = "complete_stage"
WRITE_CORE = frozenset(
    {"add_node", "patch_node", "connect", "delete_node", "layout_graph", "send_asset_to_canvas"}
)
BRIEF_EXTRA = frozenset({"run_llm_text"})
STORYBOARD_EXTRA = frozenset({"run_llm_text", "run_video_reverse_prompt", "expand_scenes_to_nodes"})
GRAPH_EXTRA = frozenset({"expand_scenes_to_nodes"})

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


def prev_stage(stage: str | None) -> str | None:
    if not stage or stage not in STAGES:
        return None
    idx = STAGES.index(stage)
    if idx <= 0:
        return None
    return STAGES[idx - 1]


def _graph_edit_tools() -> frozenset[str]:
    return LOOK_TOOLS | WRITE_CORE | GRAPH_EXTRA


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
        "resume": bool(data.get("resume")),
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
        "resume": bool(gate.get("resume")),
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
    start = STAGE_START.get(stage, "开始")
    if gate.get("resume"):
        start = f"继续{STAGE_TITLES.get(stage, '')}" if STAGE_TITLES.get(stage) else "继续"
    return {
        "stage": stage,
        "title": STAGE_TITLES.get(stage, stage),
        "start_label": start,
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
    raw = str(getattr(session, "work_mode", "") or "auto").strip().lower()
    return raw not in {"auto", "goal"}


def match_stage_command(text: str) -> str | None:
    """Whole-message shortcuts like「开始搭图」so chat can start/return to a ring."""
    compact = (
        (text or "")
        .strip()
        .replace(" ", "")
        .replace("「", "")
        .replace("」", "")
        .replace("“", "")
        .replace("”", "")
        .lower()
    )
    mapping = {
        "开始brief": "brief",
        "继续brief": "brief",
        "开始分镜": "storyboard",
        "继续分镜": "storyboard",
        "开始搭图": "graph",
        "继续搭图": "graph",
        "开始出片": "shoot",
        "继续出片": "shoot",
    }
    return mapping.get(compact)


def _has_nodes(graph: dict | None) -> bool:
    nodes = (graph or {}).get("nodes") if isinstance(graph, dict) else None
    return bool(nodes)


def _plan_held(gate: dict[str, Any] | None) -> bool:
    return bool(
        gate and gate.get("kind") in {"stage", "plan_run"} and gate.get("stage") in {"graph", "shoot"}
    )


def allowed_tools(session, graph: dict | None = None) -> frozenset[str] | None:
    """None = all tools. Otherwise only these names may run."""
    if not is_plan_mode(session):
        return None
    status = getattr(session, "status", "idle")
    if status == "confirm_pending":
        return LOOK_TOOLS
    gate = parse_gate(getattr(session, "pending_json", ""))
    held = _plan_held(gate)
    if status in {"plan_pending", "stage_pending"}:
        return _graph_edit_tools() if held else READ_TOOLS
    if status == "running" and gate and gate.get("executing"):
        stage = gate.get("stage") or "brief"
        extra = {COMPLETE}
        if stage == "brief":
            return LOOK_TOOLS | WRITE_CORE | BRIEF_EXTRA | extra
        if stage == "storyboard":
            return LOOK_TOOLS | WRITE_CORE | STORYBOARD_EXTRA | extra
        if stage == "graph":
            return LOOK_TOOLS | WRITE_CORE | GRAPH_EXTRA | extra
        if stage == "shoot":
            return None
    if status == "running" and held and not (gate or {}).get("executing"):
        return _graph_edit_tools()
    if status == "running" and not gate and _has_nodes(graph):
        return _graph_edit_tools() | {"propose_plan"}
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


def deny_reason(
    session, name: str, args: dict[str, Any] | None, graph: dict | None = None
) -> str | None:
    if name == "propose_plan":
        gate = parse_gate(getattr(session, "pending_json", ""))
        if getattr(session, "status", "") == "running" and gate and gate.get("executing"):
            return (
                "方案已批准，本环已开始。不要再出方案卡。"
                "用 add_node / patch_node 做这一环，做完调用 complete_stage。"
            )
    gate = parse_gate(getattr(session, "pending_json", ""))
    if (
        name == "run_llm_text"
        and getattr(session, "status", "") == "running"
        and gate
        and gate.get("executing")
        and gate.get("stage") == "graph"
    ):
        return "搭图环不要写镜头。用 expand_scenes_to_nodes 或 add_node / connect 搭节点和连线，做完 complete_stage。"
    allowed = allowed_tools(session, graph)
    if allowed is not None and name not in allowed:
        if name == "propose_plan":
            return (
                "方案已批准，本环已开始。不要再出方案卡。"
                "用 add_node / patch_node 做这一环，做完调用 complete_stage。"
            )
        stage = str((gate or {}).get("stage") or "")
        title = STAGE_TITLES.get(stage, stage)
        if name in WRITE_CORE and stage in {"brief", "storyboard"}:
            return f"当前停在「{title}」，还不能改画布。等用户点{STAGE_START.get(stage, '开始')}，不要让用户去点开始搭图。"
        if name in WRITE_CORE:
            return f"当前还不能用「{name}」。画布已有节点就直接改；空画布先出方案卡。"
        return f"当前环节还不能用「{name}」。先把方案/本环点过，或等用户点开始。"
    if name == "add_node":
        types = allowed_node_types(session)
        if types is not None:
            raw = args or {}
            nt = normalize_type_name(str(raw.get("node_type") or raw.get("type") or ""))
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
    executing = bool(status == "running" and gate and gate.get("executing"))
    bits = [
        "Plan 闸门由运行时强制：没批准的环调用写工具会被拦截。",
        "做完本环调用 complete_stage。搭图环禁止 run_text_to_image / run_image_to_video 等扣费出片。",
    ]
    if status in {"idle", "plan_pending"} or (
        status == "running" and gate and gate.get("kind") == "plan" and not executing
    ):
        bits.append("方案未批准前必须调用 propose_plan 出方案卡。")
    if empty and not executing:
        bits.append("画布是空的，不要问补还是重搭，直接按新片子出方案。")
    elif not executing:
        bits.append("画布已有节点。方案里写清是在现有上补还是重搭，推荐补（rebuild=false）。")
    if status == "plan_pending" or (status == "running" and gate and gate.get("kind") == "plan" and not executing):
        bits.append("用户正在先改方案：重出 propose_plan，不要改画布。")
    if status == "stage_pending":
        bits.append("环节待批：可以改方案或回答问题。")
        if (gate or {}).get("stage") in {"graph", "shoot"}:
            bits.append(
                "画布不对时直接 add_node / connect / patch_node，不要让用户再点开始搭图，也不要出片。"
            )
        else:
            bits.append("不要改画布，等用户点开始。")
    if status == "running" and gate and not executing and (gate or {}).get("stage") in {"graph", "shoot"}:
        bits.append(
            "用户要改图就直接 add_node / connect / patch_node，不要出片，不要重出方案卡，不要让用户再点开始搭图。"
        )
    if status == "running" and not gate and not empty:
        bits.append(
            "方案闸门已结束，画布还在。用户要改节点就直接 add_node / connect / patch_node，不要让用户点开始搭图。"
        )
    if executing:
        stage = str((gate or {}).get("stage") or "")
        bits.append(
            f"用户已点开始「{STAGE_TITLES.get(stage, stage)}」。"
            "禁止再调用 propose_plan。立刻用工具改画布，只做这一环，做完调用 complete_stage。"
        )
        bits.append("系统提示里已有画布摘要和节点 id，不要反复 get_graph。")
        if stage == "graph":
            bits.append(
                "搭图环只搭节点和连线：优先 expand_scenes_to_nodes，或 add_node + connect。"
                "不要 run_llm_text / 写镜头。不要把轮次耗在反复查看画布上。"
                "搭完立刻 complete_stage。已有节点就补全，禁止拆光重搭。"
            )
        if (gate or {}).get("resume"):
            bits.append("这是续跑：从现有画布缺的部分继续，不要重来。")
    return "\n".join(bits)
