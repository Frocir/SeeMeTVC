"""Server-side graph undo snapshots (max 50 per project)."""

from __future__ import annotations

import json

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphRevision, Workflow

KEEP = 50


def dumps_graph(graph: dict | None) -> str:
    data = dict(graph or {"nodes": [], "edges": []})
    data.pop("__run_opts__", None)
    if "nodes" not in data:
        data["nodes"] = []
    if "edges" not in data:
        data["edges"] = []
    return json.dumps(data, ensure_ascii=False)


async def _last_json(db: AsyncSession, workflow_id: int) -> str | None:
    result = await db.execute(
        select(GraphRevision.graph_json)
        .where(GraphRevision.workflow_id == workflow_id)
        .order_by(GraphRevision.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return str(row) if row is not None else None


async def _insert(db: AsyncSession, workflow_id: int, graph_json: str, source: str) -> None:
    last = await _last_json(db, workflow_id)
    if last == graph_json:
        return
    db.add(GraphRevision(workflow_id=workflow_id, graph_json=graph_json, source=source))
    await db.flush()
    count = (
        await db.execute(
            select(func.count()).select_from(GraphRevision).where(GraphRevision.workflow_id == workflow_id)
        )
    ).scalar_one()
    extra = int(count) - KEEP
    if extra <= 0:
        return
    old_ids = (
        (
            await db.execute(
                select(GraphRevision.id)
                .where(GraphRevision.workflow_id == workflow_id)
                .order_by(GraphRevision.id.asc())
                .limit(extra)
            )
        )
        .scalars()
        .all()
    )
    if old_ids:
        await db.execute(delete(GraphRevision).where(GraphRevision.id.in_(list(old_ids))))


async def persist_graph(
    db: AsyncSession,
    wf: Workflow,
    graph: dict,
    *,
    source: str,
) -> bool:
    """Write graph_json and push undo snapshots. False if unchanged."""
    old = wf.graph_json or "{}"
    new_s = dumps_graph(graph)
    try:
        old_norm = dumps_graph(json.loads(old) if old.strip() else {})
    except json.JSONDecodeError:
        old_norm = old
    if old_norm == new_s:
        return False
    await _insert(db, wf.id, old_norm, source)
    wf.graph_json = new_s
    await _insert(db, wf.id, new_s, source)
    return True


async def undo_graph(db: AsyncSession, wf: Workflow) -> dict:
    result = await db.execute(
        select(GraphRevision)
        .where(GraphRevision.workflow_id == wf.id)
        .order_by(GraphRevision.id.desc())
        .limit(2)
    )
    revs = list(result.scalars().all())
    if len(revs) < 2:
        raise ValueError("没有可撤销的画布版本")
    newest, prev = revs[0], revs[1]
    await db.delete(newest)
    wf.graph_json = prev.graph_json
    try:
        return json.loads(prev.graph_json or "{}")
    except json.JSONDecodeError:
        return {"nodes": [], "edges": []}
