"""Agent loop: Skill + Memory + in-process MCP + SSE events."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMessage, AgentSession, Channel, User, Workflow
from app.services import graph_ops, llm as llm_svc
from app.services import mcp_server
from app.services.skills_loader import get_skill

MAX_TOOL_ROUNDS = 12
USER_TURNS = 16
STALE_RUNNING_SEC = 600

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

PERSONA = (
    "你是 SeeMeTVC 画布上的 TVC Agent，用简洁中文协助用户做美妆广告短片。"
    "改画布、连线、跑节点必须调用工具。不要声称已经改了画布或已经出片，除非对应工具已成功。"
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
    session.model_id = channel.model_id
    if skill_id.strip():
        session.skill_id = skill_id.strip()
    session.status = "running"
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
    )


async def run_resume(
    db: AsyncSession,
    *,
    user: User,
    workflow: Workflow,
    channel: Channel,
    accept: bool,
    selected_node_id: str,
    viewport: tuple[float, float],
    emit: Emit,
) -> None:
    session = await get_or_create_session(db, workflow=workflow, user=user)
    if session.status != "confirm_pending":
        raise RuntimeError("没有待确认的生成")
    pending = _loads(session.pending_json)
    if not isinstance(pending, dict):
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
    if accept:
        await emit("tool", {"name": tool_name, "status": "running", "detail": "生成中…"})
        try:
            result = await mcp_server.call_tool(ctx, tool_name, args)
            await emit("tool", {"name": tool_name, "status": "done", "detail": result[:240]})
        except Exception as exc:  # noqa: BLE001
            result = json.dumps({"error": str(exc)}, ensure_ascii=False)
            await emit("tool", {"name": tool_name, "status": "error", "detail": str(exc)[:240]})
    else:
        result = json.dumps({"error": "用户拒绝了本次生成", "cancelled": True}, ensure_ascii=False)
        await emit("tool", {"name": tool_name, "status": "done", "detail": "已取消生成"})
    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": result})
    db.add(
        AgentMessage(
            session_id=session.id,
            role="tool",
            content=result[:8000],
            meta_json=json.dumps({"tool_call_id": tool_call_id, "name": tool_name}, ensure_ascii=False),
        )
    )
    session.pending_json = ""
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
) -> None:
    ctx = mcp_server.McpContext(db=db, user=user, workflow=workflow, viewport=viewport, emit=emit)
    tools = mcp_server.openai_tools()
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            await db.refresh(workflow)
            ctx.workflow = workflow
            system = _system_prompt(session, workflow, selected_node_id)
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
                            }
                            session.status = "confirm_pending"
                            session.pending_json = json.dumps(
                                {
                                    "tool_name": name,
                                    "tool_call_id": call_id,
                                    "arguments": args,
                                    "messages": messages,
                                    "confirm": conf,
                                },
                                ensure_ascii=False,
                            )
                            await db.commit()
                            await emit("confirm_required", conf)
                            await emit("done", {"status": "confirm_pending"})
                            paused = True
                            break
                    await emit("tool", {"name": name, "status": "running", "detail": ""})
                    try:
                        result = await mcp_server.call_tool(ctx, name, args)
                        await emit("tool", {"name": name, "status": "done", "detail": result[:240]})
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
                if paused:
                    return
                continue
            text = "".join(acc_text).strip() or "（无回复）"
            db.add(AgentMessage(session_id=session.id, role="assistant", content=text[:8000], meta_json=""))
            session.status = "idle"
            session.pending_json = ""
            await _maybe_summarize(db, session, channel)
            await db.commit()
            await emit("done", {"status": "idle"})
            return
        session.status = "idle"
        await db.commit()
        await emit("error", {"detail": "工具调用轮次过多，已停止"})
        await emit("done", {"status": "idle"})
    except Exception as exc:  # noqa: BLE001
        session.status = "idle"
        session.pending_json = ""
        await db.commit()
        await emit("error", {"detail": str(exc)[:400]})
        await emit("done", {"status": "idle"})


def _system_prompt(session: AgentSession, workflow: Workflow, selected_id: str) -> str:
    from app.services.node_contracts import render_cards

    parts = [PERSONA, render_cards()]
    skill = get_skill(session.skill_id)
    if skill:
        parts.append(f"当前 Skill：{skill.name}\n\n{skill.full}")
    graph = graph_ops.parse_graph(workflow.graph_json)
    parts.append("画布摘要：\n" + graph_ops.graph_summary(graph, selected_id=selected_id))
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
