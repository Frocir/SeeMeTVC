"""Expire workflow runs that look alive but the executor is gone."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Workflow, WorkflowRun, WorkflowRunStatus
from app.services.ledger import KIND_REFUND, record_entry

_log = logging.getLogger("seemetvc.watchdog")

_ACTIVE = {WorkflowRunStatus.PENDING.value, WorkflowRunStatus.RUNNING.value}
# Poll hints commit about every 5s. No heartbeat → process died (restart / crash).
HEARTBEAT_STALE_SEC = 180
# Wall-clock cap for a whole one-click (several 2.5 shots).
ABSOLUTE_MAX_SEC = 75 * 60
TIMEOUT_MSG = "生成已超时（后台已中断或超过等待上限）"
ABANDON_MSG = "已被新的出片取代"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def is_stale_run(run: WorkflowRun, *, now: datetime | None = None, force: bool = False) -> bool:
    if run.status not in _ACTIVE:
        return False
    if force:
        return True
    clock = now or _now()
    created = _aware(run.created_at)
    updated = _aware(run.updated_at) or created
    if created is None and updated is None:
        return True
    if created is not None and (clock - created).total_seconds() > ABSOLUTE_MAX_SEC:
        return True
    if updated is not None and (clock - updated).total_seconds() > HEARTBEAT_STALE_SEC:
        return True
    return False


def _fail_running_nodes(raw: str, message: str) -> str:
    try:
        states = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw or "{}"
    if not isinstance(states, dict):
        return raw or "{}"
    changed = False
    for st in states.values():
        if isinstance(st, dict) and st.get("status") == "running":
            st["status"] = "failed"
            st["error"] = message
            st.pop("hint", None)
            changed = True
    return json.dumps(states, ensure_ascii=False) if changed else (raw or "{}")


def _clear_graph_running(raw: str, message: str) -> tuple[str, bool]:
    try:
        graph = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw or "{}", False
    changed = False
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("runStatus") == "running":
            data["runStatus"] = "failed"
            data["runError"] = message
            changed = True
    if not changed:
        return raw or "{}", False
    return json.dumps(graph, ensure_ascii=False), True


def sanitize_saved_graph(graph: dict, *, has_live_run: bool) -> dict:
    """Don't let autosave write back 生成中 after the executor is gone."""
    if has_live_run or not isinstance(graph, dict):
        return graph
    raw, changed = _clear_graph_running(json.dumps(graph, ensure_ascii=False), TIMEOUT_MSG)
    return json.loads(raw) if changed else graph


async def _expire_one(db: AsyncSession, run: WorkflowRun, *, message: str) -> None:
    user = await db.get(User, run.user_id)
    refund = round(float(run.cost or 0), 4)
    if user is not None and refund > 0:
        await record_entry(
            db,
            user,
            refund,
            kind=KIND_REFUND,
            title=f"项目出片 #{run.id} 超时退款",
            ref_type="run",
            ref_id=run.id,
        )
        run.status = WorkflowRunStatus.REFUNDED.value
        run.cost = 0.0
        run.balance_after = user.balance
    else:
        run.status = WorkflowRunStatus.FAILED.value
    run.error_message = message
    run.node_states_json = _fail_running_nodes(run.node_states_json, message)
    run.updated_at = _now()
    if run.workflow_id:
        wf = await db.get(Workflow, run.workflow_id)
        if wf is not None:
            nxt, changed = _clear_graph_running(wf.graph_json, message)
            if changed:
                wf.graph_json = nxt


async def abandon_active_runs(
    db: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
) -> int:
    """Drop leftover pending/running rows so a new run can start immediately."""
    return await expire_stale_runs(
        db,
        user_id=user_id,
        workflow_id=workflow_id,
        force=True,
        message=ABANDON_MSG,
    )


async def expire_stale_runs(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    workflow_id: int | None = None,
    run_id: int | None = None,
    force: bool = False,
    message: str = TIMEOUT_MSG,
) -> int:
    q = select(WorkflowRun).where(WorkflowRun.status.in_(_ACTIVE))
    if user_id is not None:
        q = q.where(WorkflowRun.user_id == user_id)
    if workflow_id is not None:
        q = q.where(WorkflowRun.workflow_id == workflow_id)
    if run_id is not None:
        q = q.where(WorkflowRun.id == run_id)
    rows = list((await db.execute(q)).scalars().all())
    now = _now()
    n = 0
    for run in rows:
        if not is_stale_run(run, now=now, force=force):
            continue
        await _expire_one(db, run, message=message)
        n += 1
    await db.flush()
    graph_n = await _clear_orphaned_graphs(
        db,
        user_id=user_id,
        workflow_id=workflow_id,
        extra_ids=[run.workflow_id for run in rows if run.workflow_id],
        message=message,
    )
    if n or graph_n:
        await db.commit()
        if n:
            _log.info("已将 %s 条卡住的出片标为超时", n)
        if graph_n:
            _log.info("已清除 %s 个项目画布上的僵尸「生成中」", graph_n)
    return n


async def _clear_orphaned_graphs(
    db: AsyncSession,
    *,
    user_id: int | None,
    workflow_id: int | None,
    extra_ids: list[int | None],
    message: str = TIMEOUT_MSG,
) -> int:
    """Nodes saved as running with no live executor — leftover after restart."""
    live_q = select(WorkflowRun.workflow_id).where(
        WorkflowRun.status.in_(_ACTIVE),
        WorkflowRun.workflow_id.is_not(None),
    )
    if user_id is not None:
        live_q = live_q.where(WorkflowRun.user_id == user_id)
    live = {wid for (wid,) in (await db.execute(live_q)).all() if wid}

    wf_ids: set[int] = {wid for wid in extra_ids if isinstance(wid, int)}
    if workflow_id is not None:
        wf_ids.add(workflow_id)
    elif user_id is not None:
        rows = await db.execute(select(Workflow.id).where(Workflow.user_id == user_id))
        wf_ids.update(r[0] for r in rows.all())
    elif not wf_ids:
        rows = await db.execute(select(Workflow.id))
        wf_ids.update(r[0] for r in rows.all())

    changed = 0
    for wid in wf_ids:
        if wid in live:
            continue
        wf = await db.get(Workflow, wid)
        if wf is None:
            continue
        nxt, did = _clear_graph_running(wf.graph_json, message)
        if did:
            wf.graph_json = nxt
            changed += 1
    return changed
