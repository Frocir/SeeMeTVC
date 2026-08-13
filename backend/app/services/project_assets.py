"""Per-project flat media library (image / video / current output)."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.uploads import local_upload_path, uploads_root
from app.models import ProjectAsset, Workflow, WorkflowRun, WorkflowRunStatus

_UPLOAD_RE = re.compile(
    r"/uploads/(\d+)/([a-f0-9]{32}\.(jpg|jpeg|png|webp|gif|mp4|webm|mov))$",
    re.I,
)


def is_video_url(url: str | None) -> bool:
    if not url:
        return False
    path = urlparse(url).path if "://" in url else url
    return path.lower().endswith((".mp4", ".webm", ".mov"))


def _kind_from_url(url: str, forced: str | None = None) -> str:
    if forced:
        return forced
    return "video" if is_video_url(url) else "image"


def _filename(url: str, fallback: str = "") -> str:
    path = urlparse(url).path if "://" in url else url
    name = Path(path).name
    return fallback or name or "asset"


async def upsert_asset(
    db: AsyncSession,
    *,
    workflow_id: int,
    user_id: int,
    url: str,
    kind: str | None = None,
    filename: str = "",
) -> ProjectAsset | None:
    url = (url or "").strip()
    if not url or url.startswith("data:"):
        return None
    kind = _kind_from_url(url, kind)
    result = await db.execute(
        select(ProjectAsset).where(ProjectAsset.workflow_id == workflow_id, ProjectAsset.url == url)
    )
    row = result.scalar_one_or_none()
    if row:
        if kind == "output":
            row.kind = "output"
        return row
    row = ProjectAsset(
        workflow_id=workflow_id,
        user_id=user_id,
        kind=kind,
        url=url,
        filename=_filename(url, filename),
    )
    db.add(row)
    await db.flush()
    return row


async def replace_output(
    db: AsyncSession,
    *,
    workflow_id: int,
    user_id: int,
    url: str | None,
) -> None:
    old = await db.execute(
        select(ProjectAsset).where(
            ProjectAsset.workflow_id == workflow_id, ProjectAsset.kind == "output"
        )
    )
    for row in old.scalars().all():
        if url and row.url == url:
            continue
        await db.delete(row)
    if url:
        await upsert_asset(db, workflow_id=workflow_id, user_id=user_id, url=url, kind="output")


def _urls_from_graph(graph_json: str) -> list[tuple[str, str]]:
    try:
        graph = json.loads(graph_json or "{}")
    except json.JSONDecodeError:
        return []
    found: list[tuple[str, str]] = []
    for node in graph.get("nodes") or []:
        data = (node.get("data") or {}) if isinstance(node, dict) else {}
        for key, kind in (
            ("image_url", "image"),
            ("clip_url", "video"),
            ("preview_url", None),
            ("result_url", "output"),
        ):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                found.append((val.strip(), kind or _kind_from_url(val)))
    return found


async def sync_from_graph(db: AsyncSession, wf: Workflow) -> None:
    for url, kind in _urls_from_graph(wf.graph_json):
        k = "output" if kind == "output" else kind
        if k == "output":
            continue
        await upsert_asset(db, workflow_id=wf.id, user_id=wf.user_id, url=url, kind=k)


def last_image_from_graph(graph_json: str) -> str | None:
    found: str | None = None
    for url, kind in _urls_from_graph(graph_json):
        if kind == "image" or (kind not in {"video", "output"} and not is_video_url(url)):
            found = url
    return found


async def latest_image_url(db: AsyncSession, workflow_id: int) -> str | None:
    result = await db.execute(
        select(ProjectAsset)
        .where(ProjectAsset.workflow_id == workflow_id, ProjectAsset.kind == "image")
        .order_by(ProjectAsset.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row.url if row else None


async def refresh_cover(
    db: AsyncSession,
    wf: Workflow,
    *,
    prefer_url: str | None = None,
) -> None:
    """Keep 成片 on the card; otherwise fill with the last image in this project."""
    if is_video_url(prefer_url):
        wf.cover_url = prefer_url
        return
    if is_video_url(wf.cover_url):
        return
    img = prefer_url if prefer_url and not is_video_url(prefer_url) else None
    if not img:
        img = await latest_image_url(db, wf.id)
    if not img:
        img = last_image_from_graph(wf.graph_json)
    if img:
        wf.cover_url = img


async def fill_empty_covers(db: AsyncSession) -> None:
    wfs = (await db.execute(select(Workflow))).scalars().all()
    for wf in wfs:
        if is_video_url(wf.cover_url):
            continue
        await sync_from_graph(db, wf)
        await refresh_cover(db, wf)


def brand_from_graph(graph_json: str) -> str:
    try:
        graph = json.loads(graph_json or "{}")
    except json.JSONDecodeError:
        return "SeeMe"
    for node in graph.get("nodes") or []:
        data = (node.get("data") or {}) if isinstance(node, dict) else {}
        if data.get("textRole") == "brief" and isinstance(data.get("brand"), str) and data["brand"].strip():
            return data["brand"].strip()
    return "SeeMe"


async def copy_asset(
    db: AsyncSession,
    src: ProjectAsset,
    target: Workflow,
) -> ProjectAsset:
    new_url = src.url
    path = local_upload_path(src.url)
    if path and path.is_file() and target.user_id:
        ext = path.suffix
        dest_dir = uploads_root() / str(target.user_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stored = f"{uuid.uuid4().hex}{ext}"
        shutil.copy2(path, dest_dir / stored)
        new_url = f"/uploads/{target.user_id}/{stored}"
    kind = "video" if src.kind == "output" else src.kind
    row = await upsert_asset(
        db,
        workflow_id=target.id,
        user_id=target.user_id,
        url=new_url,
        kind=kind,
        filename=src.filename,
    )
    assert row is not None
    return row


def collect_upload_paths(*urls: str | None) -> list[Path]:
    out: list[Path] = []
    for url in urls:
        p = local_upload_path(url or "")
        if p:
            out.append(p)
    return out


async def prune_runs_keep_current(db: AsyncSession, workflow_id: int, keep_id: int | None) -> None:
    result = await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id))
    for run in result.scalars().all():
        if keep_id is not None and run.id == keep_id:
            continue
        await db.delete(run)


async def delete_ephemeral_run(db: AsyncSession, run: WorkflowRun) -> None:
    """Drop failed / cancelled runs so they never surface as history."""
    if run.status in (
        WorkflowRunStatus.FAILED.value,
        WorkflowRunStatus.REFUNDED.value,
        WorkflowRunStatus.CANCELLED.value,
    ):
        await db.delete(run)
