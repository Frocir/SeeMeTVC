"""Agent loop: Skill + Memory + in-process MCP + SSE events."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMessage, AgentSession, Channel, User, Workflow
from app.services import agent_gates as gates
from app.services import graph_ops, llm as llm_svc
from app.services import mcp_server
from app.services.skills_loader import get_skill

MAX_TOOL_ROUNDS = 12
USER_TURNS = 16
STALE_RUNNING_SEC = 600

WORK_MODES = ("auto", "plan")
WORK_MODE_ALIASES = {
    "auto": "auto",
    "goal": "auto",
    "plan": "plan",
    "click": "plan",
}

MODE_PROMPTS = {
    "auto": (
        "当前工作模式：Auto。用户已经把你当「直接开工的团队」。Skill 只决定导演风格。"
        "不要出计划卡、不要等批准、不要在环与环之间停。"
        "四件套（品牌 / 卖点 / 时长 / 画幅）齐了就干；缺则先像售前问一轮，其余用当前 Skill 默认。"
        "开工前仍用一两句人话交代你会怎么拍，然后马上调用工具搭画布。"
        "默认在现有画布上补，用户说重做才拆。扣费生成仍必须走确认卡。"
    ),
    "plan": (
        "当前工作模式：Plan。先当售前主理人，再当执行导演。Skill 只决定美学。"
        "方案没谈妥之前禁止改画布。必须调用 propose_plan 出方案卡（Brief → 分镜 → 搭图），等用户点批准。"
        "用户点开始某环后再做那一环；做完调用 complete_stage。搭图结束不要出片，等用户点开始出片。"
        "已有节点时方案里推荐在现有上补（rebuild=false）。按 Skill 问满风格、禁忌、是否口播。"
        "扣费生成仍必须走确认卡。"
    ),
}


def normalize_work_mode(raw: str | None) -> str:
    key = (raw or "plan").strip().lower()
    return WORK_MODE_ALIASES.get(key, "plan")

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

PERSONA = (
    "你是 SeeMeTVC 的片子主理人：用户像在找一支真人美妆广告团队，你负责接洽、出方案、再带团队去画布落地。"
    "不是客服机器人，也不是只会点按钮的脚本。先把片子想清楚，再动手。"
    "语气：面对面聊 brief 的售前导演。用「我」「咱们」；有判断、会给更好的拍法，但不油腻、不堆感叹号、不自称 AI、不说「已收到您的需求」。"
    "短句、口语、专业。好例子：「这支我建议 15 秒三镜，开场橱窗、中段涂抹、收在产品。你更想种草还是大片感？」"
    "坏例子：「请提供品牌、卖点、时长和画幅，以便我为您生成工作流。」一次只推进一件事，不要甩工具清单。"
    "方案没构思完不要改画布。谈妥后再调用工具，可以说「那我去画布上搭了」。"
    "改画布、连线、跑节点必须调用工具。不要声称已经改了画布或已经出片，除非对应工具已成功。"
    "付费生成必须等用户点确认卡：确认前不要开始生成、不要扣费、不要催促；用「点一下确认我就去出」而不是系统提示腔。"
    "搭完工作流（add_node / connect / expand_scenes_to_nodes）后必须调用 layout_graph 给节点排版，不要手填 x/y。"
    "用户说排版、整理、对齐、分开叠着的节点时，调用 layout_graph。"
    "用户说清空对话、新对话、忘掉刚才说的时，调用 clear_chat。不要在用户没要求时清空。清空只删聊天，不动画布。"
    "不要给用户看 JSON 代码围栏。"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _loads(raw: str | None) -> Any:
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return None


async def get_or_create_session(db: AsyncSession, *, workflow: Workflow, user: User) -> AgentSession:
    result = await db.execute(select(AgentSession).where(AgentSession.workflow_id == workflow.id))
    row = result.scalar_one_or_none()
    if row is None:
        row = AgentSession(workflow_id=workflow.id, user_id=user.id, status="idle")
        db.add(row)
        await db.flush()
        return row
    return row


async def clear_session_chat(db: AsyncSession, session: AgentSession) -> int:
    result = await db.execute(delete(AgentMessage).where(AgentMessage.session_id == session.id))
    session.summary = ""
    session.pending_json = ""
    return int(result.rowcount or 0)


async def list_ui_messages(db: AsyncSession, session: AgentSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id, AgentMessage.role.in_(("user", "assistant")))
        .order_by(AgentMessage.id.asc())
    )
    out = []
    for m in result.scalars().all():
        if m.role == "assistant" and _loads(m.meta_json) and (_loads(m.meta_json) or {}).get("tool_calls"):
            continue
        out.append({"id": m.id, "role": m.role, "content": m.content, "meta": _loads(m.meta_json)})
    return out


def pending_confirm(session: AgentSession) -> dict[str, Any] | None:
    if session.status != "confirm_pending":
        return None
    data = _loads(session.pending_json)
    if not isinstance(data, dict):
        return None
    conf = data.get("confirm")
    return conf if isinstance(conf, dict) else None


async def run_chat(
    db: AsyncSession,
    *,
    user: User,
    workflow: Workflow,
    channel: Channel,
    text: str,
    skill_id: str,
    work_mode: str,
    selected_node_id: str,
    viewport: tuple[float, float],
    emit: Emit,
) -> None:
    session = await get_or_create_session(db, workflow=workflow, user=user)
    if session.status == "running":
        ts = session.updated_at
        stale = True
        if ts is not None:
            try:
                aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                stale = (_now() - aware).total_seconds() > STALE_RUNNING_SEC
            except Exception:  # noqa: BLE001
                stale = True
        if not stale:
            raise RuntimeError("Agent 正在回复，请稍候")
        session.status = "idle"
        session.pending_json = ""
    if session.status == "confirm_pending":
        raise RuntimeError("请先确认或取消当前的生成")
    resume_after = ""
    if session.status in gates.GATE_STATUSES:
        resume_after = session.status
        gate = gates.parse_gate(session.pending_json) or {
            "kind": "plan",
            "stage": "brief",
            "plan": gates.normalize_plan(None),
            "completed": [],
        }
        gate["executing"] = False
        session.pending_json = gates.dump_gate(gate)
    session.model_id = channel.model_id
    if skill_id.strip():
        session.skill_id = skill_id.strip()
    else:
        session.skill_id = ""
    session.work_mode = normalize_work_mode(work_mode)
    session.status = "running"
    if resume_after not in gates.GATE_STATUSES:
        session.pending_json = ""
    db.add(
        AgentMessage(session_id=session.id, role="user", content=text.strip(), meta_json="")
    )
    await db.commit()
    await db.refresh(session)
    messages = await _llm_messages(db, session)
    await _loop(
        db,
        user=user,
        workflow=workflow,
        session=session,
        channel=channel,
        messages=messages,
        selected_node_id=selected_node_id,
        viewport=viewport,
        emit=emit,
        resume_after=resume_after,
    )


async def run_resume(
    db: AsyncSession,
    *,
    user: User,
    workflow: Workflow,
    channel: Channel,
    accept: bool,
    action: str = "",
    selected_node_id: str,
    viewport: tuple[float, float],
    emit: Emit,
) -> None:
    session = await get_or_create_session(db, workflow=workflow, user=user)
    act = _normalize_resume_action(action, accept, session.status)
    if act == "stop":
        await _request_stop(db, session, emit)
        return
    if act == "cancel":
        await _cancel_plan(db, session, emit)
        return
    if act == "skip_to_auto":
        await _skip_to_auto(
            db,
            user=user,
            workflow=workflow,
            session=session,
            channel=channel,
            selected_node_id=selected_node_id,
            viewport=viewport,
            emit=emit,
        )
        return
    if act == "approve" and session.status == "plan_pending":
        await _approve_plan(db, session, emit)
        return
    if act == "approve" and session.status == "stage_pending":
        await _start_stage(
            db,
            user=user,
            workflow=workflow,
            session=session,
            channel=channel,
            selected_node_id=selected_node_id,
            viewport=viewport,
            emit=emit,
        )
        return
    if act == "revise":
        await _emit_gate(session, emit)
        await emit("done", {"status": session.status})
        return
    if session.status != "confirm_pending":
        raise RuntimeError("没有待确认的生成")
    pending = _loads(session.pending_json)
    if not isinstance(pending, dict) or not pending.get("confirm"):
        session.status = "idle"
        session.pending_json = ""
        await db.commit()
        raise RuntimeError("确认状态已失效，请重新发送")
    session.status = "running"
    await db.commit()
    messages = list(pending.get("messages") or [])
    tool_name = str(pending.get("tool_name") or "")
    tool_call_id = str(pending.get("tool_call_id") or "call_run")
    args = pending.get("arguments") if isinstance(pending.get("arguments"), dict) else {}
    ctx = mcp_server.McpContext(
        db=db, user=user, workflow=workflow, viewport=viewport, emit=emit
    )
    if act in {"confirm", "approve"} or (act != "reject" and accept):
        await emit(
            "tool",
            {
                "name": tool_name,
                "status": "running",
                "detail": mcp_server.tool_progress_detail(tool_name, "running"),
            },
        )
        try:
            result = await mcp_server.call_tool(ctx, tool_name, args)
            await emit(
                "tool",
                {
                    "name": tool_name,
                    "status": "done",
                    "detail": mcp_server.tool_done_detail(tool_name, result),
                },
            )
        except Exception as exc:  # noqa: BLE001
            result = json.dumps({"error": str(exc)}, ensure_ascii=False)
            await emit("tool", {"name": tool_name, "status": "error", "detail": str(exc)[:240]})
    else:
        result = json.dumps({"error": "用户拒绝了本次生成", "cancelled": True}, ensure_ascii=False)
        await emit("tool", {"name": tool_name, "status": "done", "detail": "已取消生成，未扣费"})
    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": result})
    db.add(
        AgentMessage(
            session_id=session.id,
            role="tool",
            content=result[:8000],
            meta_json=json.dumps({"tool_call_id": tool_call_id, "name": tool_name}, ensure_ascii=False),
        )
    )
    keep = gates.parse_gate(
        json.dumps(
            {
                "kind": pending.get("kind") or "plan_run",
                "stage": pending.get("stage") or "shoot",
                "plan": pending.get("plan") or gates.normalize_plan(None),
                "completed": pending.get("completed") or [],
            }
        )
    )
    session.pending_json = (
        gates.dump_gate({**keep, "executing": True}) if keep and keep.get("plan") else ""
    )
    await db.commit()
    await db.refresh(workflow)
    await _loop(
        db,
        user=user,
        workflow=workflow,
        session=session,
        channel=channel,
        messages=messages,
        selected_node_id=selected_node_id,
        viewport=viewport,
        emit=emit,
        resume_after="",
    )


async def _loop(
    db: AsyncSession,
    *,
    user: User,
    workflow: Workflow,
    session: AgentSession,
    channel: Channel,
    messages: list[dict[str, Any]],
    selected_node_id: str,
    viewport: tuple[float, float],
    emit: Emit,
    resume_after: str = "",
) -> None:
    ctx = mcp_server.McpContext(db=db, user=user, workflow=workflow, viewport=viewport, emit=emit)
    wrote = False
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            await db.refresh(session)
            await db.refresh(workflow)
            ctx.workflow = workflow
            live = gates.parse_gate(session.pending_json)
            if live and live.get("stop_requested"):
                await _hold_stage(db, session, emit, completed=False)
                return
            allowed = gates.allowed_tools(session)
            tools = mcp_server.openai_tools(allowed)
            system = _system_prompt(session, workflow, selected_id=selected_node_id)
            acc_text: list[str] = []
            calls: list[dict[str, Any]] = []
            async for ev in llm_svc.chat_turn(
                channel, system=system, messages=messages, tools=tools
            ):
                kind = ev.get("kind")
                if kind == "token":
                    piece = str(ev.get("text") or "")
                    acc_text.append(piece)
                    await emit("token", {"text": piece})
                elif kind == "tool_calls":
                    calls = list(ev.get("calls") or [])
                elif kind == "message":
                    acc_text = [str(ev.get("text") or "".join(acc_text))]
            if calls:
                assistant_tool = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": c.get("id"),
                            "type": "function",
                            "function": {
                                "name": c.get("name"),
                                "arguments": json.dumps(c.get("arguments") or {}, ensure_ascii=False),
                            },
                        }
                        for c in calls
                    ],
                }
                messages.append(assistant_tool)
                db.add(
                    AgentMessage(
                        session_id=session.id,
                        role="assistant",
                        content="",
                        meta_json=json.dumps({"tool_calls": assistant_tool["tool_calls"]}, ensure_ascii=False),
                    )
                )
                await db.commit()
                paused = False
                for c in calls:
                    name = str(c.get("name") or "")
                    args = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
                    call_id = str(c.get("id") or name)
                    deny = gates.deny_reason(session, name, args)
                    if deny:
                        result = json.dumps({"error": deny}, ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                        db.add(
                            AgentMessage(
                                session_id=session.id,
                                role="tool",
                                content=result[:8000],
                                meta_json=json.dumps({"tool_call_id": call_id, "name": name}, ensure_ascii=False),
                            )
                        )
                        await emit("tool", {"name": name, "status": "error", "detail": deny[:240]})
                        await db.commit()
                        continue
                    if name in mcp_server.RUN_TOOLS:
                        await db.refresh(workflow)
                        graph = graph_ops.parse_graph(workflow.graph_json)
                        try:
                            est = await mcp_server.estimate_run_cost(db, graph, str(args.get("node_id") or ""))
                        except Exception as exc:  # noqa: BLE001
                            result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                            messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                            db.add(
                                AgentMessage(
                                    session_id=session.id,
                                    role="tool",
                                    content=result[:8000],
                                    meta_json=json.dumps({"tool_call_id": call_id, "name": name}, ensure_ascii=False),
                                )
                            )
                            await emit("tool", {"name": name, "status": "error", "detail": str(exc)[:240]})
                            continue
                        if est.get("needs_confirm"):
                            from app.config import get_settings

                            conf = {
                                **est,
                                "unit": get_settings().balance_unit_label,
                                "message": "确认前不会开始生成，也不会扣费。",
                            }
                            session.status = "confirm_pending"
                            prev = gates.parse_gate(session.pending_json) or {}
                            session.pending_json = json.dumps(
                                {
                                    "tool_name": name,
                                    "tool_call_id": call_id,
                                    "arguments": args,
                                    "messages": messages,
                                    "confirm": conf,
                                    "kind": prev.get("kind") or "plan_run",
                                    "stage": prev.get("stage") or "shoot",
                                    "plan": prev.get("plan") or gates.normalize_plan(None),
                                    "completed": prev.get("completed") or [],
                                    "executing": True,
                                },
                                ensure_ascii=False,
                            )
                            await db.commit()
                            await db.refresh(workflow)
                            ctx.workflow = workflow
                            await mcp_server.maybe_autolayout(ctx)
                            await emit(
                                "tool",
                                {
                                    "name": name,
                                    "status": "waiting",
                                    "detail": mcp_server.tool_progress_detail(name, "waiting"),
                                },
                            )
                            await emit("confirm_required", conf)
                            await emit("done", {"status": "confirm_pending"})
                            paused = True
                            break
                    await emit(
                        "tool",
                        {
                            "name": name,
                            "status": "running",
                            "detail": mcp_server.tool_progress_detail(name, "running"),
                        },
                    )
                    try:
                        result = await mcp_server.call_tool(ctx, name, args)
                        await emit(
                            "tool",
                            {
                                "name": name,
                                "status": "done",
                                "detail": mcp_server.tool_done_detail(name, result),
                            },
                        )
                    except Exception as exc:  # noqa: BLE001
                        result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                        await emit("tool", {"name": name, "status": "error", "detail": str(exc)[:240]})
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                    db.add(
                        AgentMessage(
                            session_id=session.id,
                            role="tool",
                            content=result[:8000],
                            meta_json=json.dumps({"tool_call_id": call_id, "name": name}, ensure_ascii=False),
                        )
                    )
                    await db.commit()
                    await db.refresh(workflow)
                    ctx.workflow = workflow
                    if name in {
                        "add_node",
                        "patch_node",
                        "connect",
                        "delete_node",
                        "layout_graph",
                        "send_asset_to_canvas",
                        "expand_scenes_to_nodes",
                        "run_llm_text",
                        "run_video_reverse_prompt",
                    }:
                        wrote = True
                    if name == "propose_plan":
                        payload = _loads(result) if isinstance(_loads(result), dict) else {}
                        plan = payload.get("plan") if isinstance(payload, dict) else None
                        await _pause_plan(db, session, emit, plan if isinstance(plan, dict) else args, acc_text)
                        paused = True
                        break
                    if name == "complete_stage":
                        await _hold_stage(db, session, emit, completed=True)
                        paused = True
                        break
                    if ctx.chat_cleared:
                        keep = 0
                        for i, m in enumerate(messages):
                            if m.get("role") == "assistant" and m.get("tool_calls"):
                                keep = i
                        messages[:] = messages[keep:]
                        ctx.chat_cleared = False
                if paused:
                    return
                continue
            text = "".join(acc_text).strip() or "（无回复）"
            db.add(AgentMessage(session_id=session.id, role="assistant", content=text[:8000], meta_json=""))
            await _maybe_summarize(db, session, channel)
            await db.refresh(workflow)
            ctx.workflow = workflow
            await mcp_server.maybe_autolayout(ctx)
            await _finish_text_turn(db, session, emit, wrote=wrote, resume_after=resume_after)
            return
        await db.refresh(workflow)
        ctx.workflow = workflow
        await mcp_server.maybe_autolayout(ctx)
        if gates.parse_gate(session.pending_json):
            await _hold_stage(db, session, emit, completed=False)
            await emit("error", {"detail": "这一环工具轮次过多，先停在这里"})
            return
        session.status = "idle"
        await db.commit()
        await emit("error", {"detail": "工具调用轮次过多，已停止"})
        await emit("done", {"status": "idle"})
    except Exception as exc:  # noqa: BLE001
        if gates.parse_gate(session.pending_json):
            await _hold_stage(db, session, emit, completed=False)
            await emit("error", {"detail": str(exc)[:400]})
            return
        session.status = "idle"
        session.pending_json = ""
        await db.commit()
        await emit("error", {"detail": str(exc)[:400]})
        await emit("done", {"status": "idle"})


def _system_prompt(session: AgentSession, workflow: Workflow, selected_id: str) -> str:
    from app.services.node_contracts import render_cards

    parts = [PERSONA, MODE_PROMPTS[normalize_work_mode(session.work_mode)], render_cards()]
    skill = get_skill(session.skill_id)
    if skill:
        parts.append(f"当前 Skill：{skill.name}\n\n{skill.full}")
    graph = graph_ops.parse_graph(workflow.graph_json)
    parts.append("画布摘要：\n" + graph_ops.graph_summary(graph, selected_id=selected_id))
    note = gates.gate_system_note(session, graph)
    if note:
        parts.append(note)
    if (session.summary or "").strip():
        parts.append("更早对话摘要：\n" + session.summary.strip())
    return "\n\n".join(parts)


async def _llm_messages(db: AsyncSession, session: AgentSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session.id).order_by(AgentMessage.id.asc())
    )
    rows = list(result.scalars().all())
    user_idxs = [i for i, m in enumerate(rows) if m.role == "user"]
    keep_from = 0
    if len(user_idxs) > USER_TURNS:
        keep_from = user_idxs[-USER_TURNS]
    sliced = rows[keep_from:]
    out: list[dict[str, Any]] = []
    for m in sliced:
        meta = _loads(m.meta_json) or {}
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": str(meta.get("tool_call_id") or ""),
                    "content": m.content,
                }
            )
        elif m.role == "assistant" and meta.get("tool_calls"):
            out.append({"role": "assistant", "content": None, "tool_calls": meta["tool_calls"]})
        elif m.role in {"user", "assistant"} and (m.content or "").strip():
            out.append({"role": m.role, "content": m.content})
    return out


async def _maybe_summarize(db: AsyncSession, session: AgentSession, channel: Channel) -> None:
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id, AgentMessage.role.in_(("user", "assistant")))
        .order_by(AgentMessage.id.asc())
    )
    rows = [m for m in result.scalars().all() if not ((_loads(m.meta_json) or {}).get("tool_calls"))]
    user_n = sum(1 for m in rows if m.role == "user")
    if user_n <= USER_TURNS:
        return
    older = []
    seen_users = 0
    cutoff_users = user_n - USER_TURNS
    for m in rows:
        if m.role == "user":
            seen_users += 1
        if seen_users <= cutoff_users:
            older.append(f"{m.role}: {m.content[:400]}")
    blob = "\n".join(older[-30:])
    try:
        text = await llm_svc.chat_messages(
            channel,
            messages=[{"role": "user", "content": "把下列对话压成不超过 400 字的中文摘要，保留品牌/卖点/已做的画布操作：\n" + blob}],
            system="只输出摘要正文。",
        )
        session.summary = ((session.summary or "") + "\n" + text).strip()[-4000:]
    except Exception:  # noqa: BLE001
        session.summary = ((session.summary or "") + "\n" + blob[:800]).strip()[-4000:]


def _normalize_resume_action(action: str, accept: bool, status: str) -> str:
    key = (action or "").strip().lower()
    aliases = {
        "approve": "approve",
        "confirm": "confirm",
        "reject": "reject",
        "cancel": "cancel",
        "stop": "stop",
        "skip_to_auto": "skip_to_auto",
        "revise": "revise",
    }
    if key in aliases:
        return aliases[key]
    if status == "confirm_pending":
        return "confirm" if accept else "reject"
    if status in gates.GATE_STATUSES:
        return "approve" if accept else "cancel"
    return "confirm" if accept else "reject"


async def _emit_gate(session: AgentSession, emit: Emit) -> None:
    plan = gates.pending_plan(session)
    if plan:
        await emit("plan_required", plan)
        return
    stage = gates.pending_stage(session)
    if stage:
        await emit("stage_required", stage)


async def _pause_plan(
    db: AsyncSession,
    session: AgentSession,
    emit: Emit,
    plan_raw: dict[str, Any] | None,
    acc_text: list[str],
) -> None:
    text = "".join(acc_text).strip()
    if text:
        db.add(AgentMessage(session_id=session.id, role="assistant", content=text[:8000], meta_json=""))
    prev = gates.parse_gate(session.pending_json) or {}
    session.status = "plan_pending"
    session.pending_json = gates.dump_gate(
        {
            "kind": "plan",
            "stage": "brief",
            "plan": gates.normalize_plan(plan_raw),
            "completed": prev.get("completed") or [],
            "executing": False,
        }
    )
    await db.commit()
    await _emit_gate(session, emit)
    await emit("done", {"status": "plan_pending"})


async def _hold_stage(db: AsyncSession, session: AgentSession, emit: Emit, *, completed: bool) -> None:
    gate = gates.parse_gate(session.pending_json)
    if not gate:
        session.status = "idle"
        session.pending_json = ""
        await db.commit()
        await emit("done", {"status": "idle"})
        return
    if completed:
        done = list(gate.get("completed") or [])
        cur = str(gate.get("stage") or "brief")
        if cur not in done:
            done.append(cur)
        nxt = gates.next_stage(cur)
        if nxt is None:
            session.status = "idle"
            session.pending_json = ""
            await db.commit()
            await emit("done", {"status": "idle"})
            return
        gate["stage"] = nxt
        gate["completed"] = done
    gate["kind"] = "stage"
    gate["executing"] = False
    gate["stop_requested"] = False
    session.status = "stage_pending"
    session.pending_json = gates.dump_gate(gate)
    await db.commit()
    await _emit_gate(session, emit)
    await emit("done", {"status": "stage_pending"})


async def _finish_text_turn(
    db: AsyncSession,
    session: AgentSession,
    emit: Emit,
    *,
    wrote: bool,
    resume_after: str,
) -> None:
    gate = gates.parse_gate(session.pending_json)
    if gate and gate.get("executing") and wrote:
        await _hold_stage(db, session, emit, completed=True)
        return
    if resume_after in gates.GATE_STATUSES and gate:
        session.status = resume_after
        gate["executing"] = False
        session.pending_json = gates.dump_gate(gate)
        await db.commit()
        await _emit_gate(session, emit)
        await emit("done", {"status": resume_after})
        return
    if gate and not gate.get("executing"):
        status = "stage_pending" if gate.get("kind") == "stage" else "plan_pending"
        if gate.get("kind") == "plan_run":
            status = "stage_pending"
            gate["kind"] = "stage"
        session.status = status
        session.pending_json = gates.dump_gate(gate)
        await db.commit()
        await _emit_gate(session, emit)
        await emit("done", {"status": status})
        return
    session.status = "idle"
    if not gate:
        session.pending_json = ""
    await db.commit()
    await emit("done", {"status": "idle"})


async def _approve_plan(db: AsyncSession, session: AgentSession, emit: Emit) -> None:
    gate = gates.parse_gate(session.pending_json) or {
        "kind": "stage",
        "stage": "brief",
        "plan": gates.normalize_plan(None),
        "completed": [],
    }
    gate["kind"] = "stage"
    gate["stage"] = "brief"
    gate["executing"] = False
    session.status = "stage_pending"
    session.pending_json = gates.dump_gate(gate)
    await db.commit()
    await _emit_gate(session, emit)
    await emit("done", {"status": "stage_pending"})


async def _start_stage(
    db: AsyncSession,
    *,
    user: User,
    workflow: Workflow,
    session: AgentSession,
    channel: Channel,
    selected_node_id: str,
    viewport: tuple[float, float],
    emit: Emit,
) -> None:
    gate = gates.parse_gate(session.pending_json) or {
        "kind": "stage",
        "stage": "brief",
        "plan": gates.normalize_plan(None),
        "completed": [],
    }
    stage = str(gate.get("stage") or "brief")
    title = gates.STAGE_START.get(stage, "开始")
    gate["kind"] = "plan_run"
    gate["executing"] = True
    session.status = "running"
    session.pending_json = gates.dump_gate(gate)
    db.add(AgentMessage(session_id=session.id, role="user", content=title, meta_json=""))
    await db.commit()
    await db.refresh(session)
    messages = await _llm_messages(db, session)
    await _loop(
        db,
        user=user,
        workflow=workflow,
        session=session,
        channel=channel,
        messages=messages,
        selected_node_id=selected_node_id,
        viewport=viewport,
        emit=emit,
        resume_after="",
    )


async def _cancel_plan(db: AsyncSession, session: AgentSession, emit: Emit) -> None:
    session.status = "idle"
    session.pending_json = ""
    await db.commit()
    await emit("done", {"status": "idle"})


async def _request_stop(db: AsyncSession, session: AgentSession, emit: Emit) -> None:
    if session.status in gates.GATE_STATUSES:
        await _emit_gate(session, emit)
        await emit("done", {"status": session.status})
        return
    if session.status != "running":
        session.status = "idle"
        await db.commit()
        await emit("done", {"status": "idle"})
        return
    gate = gates.parse_gate(session.pending_json)
    if not gate:
        await emit("done", {"status": "running"})
        return
    gate["stop_requested"] = True
    session.pending_json = gates.dump_gate(gate)
    await db.commit()
    await emit("done", {"status": "running"})


async def _skip_to_auto(
    db: AsyncSession,
    *,
    user: User,
    workflow: Workflow,
    session: AgentSession,
    channel: Channel,
    selected_node_id: str,
    viewport: tuple[float, float],
    emit: Emit,
) -> None:
    session.work_mode = "auto"
    session.status = "running"
    session.pending_json = ""
    db.add(
        AgentMessage(
            session_id=session.id,
            role="user",
            content="已切到 Auto，跳过剩余创作闸门，继续把画布搭完。扣费仍要确认卡。",
            meta_json="",
        )
    )
    await db.commit()
    await db.refresh(session)
    messages = await _llm_messages(db, session)
    await _loop(
        db,
        user=user,
        workflow=workflow,
        session=session,
        channel=channel,
        messages=messages,
        selected_node_id=selected_node_id,
        viewport=viewport,
        emit=emit,
        resume_after="",
    )
