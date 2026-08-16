"""SQLite/Postgres additive migrate + one-shot project-space data cleanup."""

from __future__ import annotations

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workflow, WorkflowRun, WorkflowRunStatus
from app.services.project_assets import (
    brand_from_graph,
    last_image_from_graph,
    replace_output,
    refresh_cover,
    sync_from_graph,
)


def apply_schema_updates(sync_conn) -> None:
    insp = inspect(sync_conn)
    names = set(insp.get_table_names())
    if "schema_flags" not in names:
        sync_conn.execute(
            text(
                "CREATE TABLE schema_flags (name VARCHAR(64) PRIMARY KEY, value VARCHAR(64) NOT NULL)"
            )
        )
    if "workflows" not in names:
        return
    cols = {c["name"] for c in insp.get_columns("workflows")}
    if "brand" not in cols:
        sync_conn.execute(text("ALTER TABLE workflows ADD COLUMN brand VARCHAR(120) DEFAULT 'SeeMe'"))
    if "cover_url" not in cols:
        sync_conn.execute(text("ALTER TABLE workflows ADD COLUMN cover_url TEXT"))
    if "channels" in names:
        ch_cols = {c["name"] for c in insp.get_columns("channels")}
        if "kind" not in ch_cols:
            sync_conn.execute(text("ALTER TABLE channels ADD COLUMN kind VARCHAR(16) DEFAULT 'video'"))
        if "config_json" not in ch_cols:
            sync_conn.execute(text("ALTER TABLE channels ADD COLUMN config_json TEXT DEFAULT '{}'"))
    if "agent_sessions" in names:
        ag_cols = {c["name"] for c in insp.get_columns("agent_sessions")}
        if "work_mode" not in ag_cols:
            sync_conn.execute(
                text("ALTER TABLE agent_sessions ADD COLUMN work_mode VARCHAR(16) DEFAULT 'plan'")
            )
        flagged = sync_conn.execute(
            text("SELECT value FROM schema_flags WHERE name = 'agent_work_mode_v2'")
        ).first()
        if not flagged:
            sync_conn.execute(
                text(
                    "UPDATE agent_sessions SET work_mode = 'plan' "
                    "WHERE work_mode IN ('auto', 'click', '') OR work_mode IS NULL"
                )
            )
            sync_conn.execute(
                text("UPDATE agent_sessions SET work_mode = 'auto' WHERE work_mode = 'goal'")
            )
            sync_conn.execute(
                text("INSERT INTO schema_flags (name, value) VALUES ('agent_work_mode_v2', '1')")
            )
    if "agent_sessions" in names and "workflows" in names:
        flagged = sync_conn.execute(
            text("SELECT value FROM schema_flags WHERE name = 'purge_orphan_project_rows_v1'")
        ).first()
        if not flagged:
            sync_conn.execute(
                text(
                    "DELETE FROM agent_messages WHERE session_id IN ("
                    "SELECT id FROM agent_sessions WHERE workflow_id NOT IN (SELECT id FROM workflows))"
                )
            )
            sync_conn.execute(
                text(
                    "DELETE FROM agent_sessions WHERE workflow_id NOT IN (SELECT id FROM workflows)"
                )
            )
            if "graph_revisions" in names:
                sync_conn.execute(
                    text(
                        "DELETE FROM graph_revisions WHERE workflow_id NOT IN (SELECT id FROM workflows)"
                    )
                )
            if "asset_versions" in names:
                sync_conn.execute(
                    text(
                        "DELETE FROM asset_versions WHERE workflow_id NOT IN (SELECT id FROM workflows)"
                    )
                )
            if "project_assets" in names:
                sync_conn.execute(
                    text(
                        "DELETE FROM project_assets WHERE workflow_id NOT IN (SELECT id FROM workflows)"
                    )
                )
            sync_conn.execute(
                text(
                    "INSERT INTO schema_flags (name, value) VALUES ('purge_orphan_project_rows_v1', '1')"
                )
            )


async def migrate_project_space(db: AsyncSession) -> None:
    """One-shot: keep workflows that already have a finished video or an image."""
    flagged = await db.execute(text("SELECT value FROM schema_flags WHERE name = 'project_space_v1'"))
    if flagged.first():
        return

    wfs = (await db.execute(select(Workflow))).scalars().all()
    for wf in wfs:
        runs = (
            (
                await db.execute(
                    select(WorkflowRun)
                    .where(WorkflowRun.workflow_id == wf.id)
                    .order_by(WorkflowRun.id.desc())
                )
            )
            .scalars()
            .all()
        )
        success = next(
            (
                r
                for r in runs
                if r.status == WorkflowRunStatus.SUCCEEDED.value and (r.result_url or "").strip()
            ),
            None,
        )
        img = last_image_from_graph(wf.graph_json)
        if success is None and not img:
            for r in runs:
                await db.delete(r)
            await db.delete(wf)
            continue
        extracted = brand_from_graph(wf.graph_json)
        if extracted:
            wf.brand = extracted
        for r in runs:
            if success is None or r.id != success.id:
                await db.delete(r)
        await sync_from_graph(db, wf)
        if success is not None:
            wf.cover_url = success.result_url
            await replace_output(db, workflow_id=wf.id, user_id=wf.user_id, url=success.result_url)
        else:
            await refresh_cover(db, wf, prefer_url=img)

    await db.execute(
        text("INSERT INTO schema_flags (name, value) VALUES ('project_space_v1', '1')")
    )
    await db.flush()
