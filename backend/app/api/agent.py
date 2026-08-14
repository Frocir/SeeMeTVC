from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.models import Channel, User, Workflow
from app.schemas import AgentChatIn, AgentResumeIn
from app.services import agent_runtime as runtime
from app.services.skills_loader import load_skills

router = APIRouter(prefix="/agent", tags=["agent"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def _pick_llm(db: AsyncSession, model_id: str) -> Channel:
    ch = None
    mid = (model_id or "").strip()
    if mid:
        result = await db.execute(
            select(Channel)
            .where(Channel.model_id == mid, Channel.enabled.is_(True), Channel.kind == "llm")
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
    if ch is None:
        result = await db.execute(
            select(Channel)
            .where(Channel.enabled.is_(True), Channel.kind == "llm")
            .order_by(Channel.priority.desc(), Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
    if ch is None:
        raise HTTPException(status_code=400, detail="没有已启用的 LLM 渠道")
    return ch


async def _owned_wf(db: AsyncSession, workflow_id: int, user: User) -> Workflow:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return wf


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/skills")
async def list_skills(_: User = Depends(get_current_user)) -> list[dict[str, str]]:
    return [{"id": s.id, "name": s.name, "description": s.description} for s in load_skills().values()]


@router.get("/node-contracts")
async def node_contracts(_: User = Depends(get_current_user)) -> dict:
    from app.services.node_contracts import public_payload

    return public_payload()


@router.get("/session")
async def get_session(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wf = await _owned_wf(db, workflow_id, user)
    session = await runtime.get_or_create_session(db, workflow=wf, user=user)
    await db.commit()
    messages = await runtime.list_ui_messages(db, session)
    return {
        "workflow_id": wf.id,
        "skill_id": session.skill_id,
        "status": session.status,
        "model_id": session.model_id,
        "pending_confirm": runtime.pending_confirm(session),
        "messages": messages,
    }


@router.post("/chat")
async def agent_chat(
    body: AgentChatIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    wf = await _owned_wf(db, body.workflow_id, user)
    ch = await _pick_llm(db, body.model_id)
    vp = body.viewport
    viewport = (float(vp.x), float(vp.y)) if vp else (400.0, 280.0)
    user_id = user.id
    wf_id = wf.id
    ch_id = ch.id
    text = body.text.strip()
    skill_id = body.skill_id
    selected = body.selected_node_id

    async def gen():
        q: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await q.put((event, data))

        async def run() -> None:
            try:
                async with SessionLocal() as sdb:
                    u = await sdb.get(User, user_id)
                    w = await sdb.get(Workflow, wf_id)
                    c = await sdb.get(Channel, ch_id)
                    if u is None or w is None or c is None:
                        await emit("error", {"detail": "会话已失效"})
                        await emit("done", {"status": "idle"})
                        return
                    await runtime.run_chat(
                        sdb,
                        user=u,
                        workflow=w,
                        channel=c,
                        text=text,
                        skill_id=skill_id,
                        selected_node_id=selected,
                        viewport=viewport,
                        emit=emit,
                    )
            except Exception as exc:  # noqa: BLE001
                await emit("error", {"detail": str(exc)[:400]})
                await emit("done", {"status": "idle"})
            finally:
                await q.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield _sse(item[0], item[1])
        finally:
            await task

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/resume")
async def agent_resume(
    body: AgentResumeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    wf = await _owned_wf(db, body.workflow_id, user)
    ch = await _pick_llm(db, "")
    session = await runtime.get_or_create_session(db, workflow=wf, user=user)
    if session.model_id:
        ch = await _pick_llm(db, session.model_id)
    vp = body.viewport
    viewport = (float(vp.x), float(vp.y)) if vp else (400.0, 280.0)
    user_id = user.id
    wf_id = wf.id
    ch_id = ch.id
    accept = body.accept
    selected = body.selected_node_id

    async def gen():
        q: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await q.put((event, data))

        async def run() -> None:
            try:
                async with SessionLocal() as sdb:
                    u = await sdb.get(User, user_id)
                    w = await sdb.get(Workflow, wf_id)
                    c = await sdb.get(Channel, ch_id)
                    if u is None or w is None or c is None:
                        await emit("error", {"detail": "会话已失效"})
                        await emit("done", {"status": "idle"})
                        return
                    await runtime.run_resume(
                        sdb,
                        user=u,
                        workflow=w,
                        channel=c,
                        accept=accept,
                        selected_node_id=selected,
                        viewport=viewport,
                        emit=emit,
                    )
            except Exception as exc:  # noqa: BLE001
                await emit("error", {"detail": str(exc)[:400]})
                await emit("done", {"status": "idle"})
            finally:
                await q.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield _sse(item[0], item[1])
        finally:
            await task

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
