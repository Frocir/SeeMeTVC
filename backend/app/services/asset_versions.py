"""Generated asset history (versions) per project."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssetVersion, User, Workflow
from app.services import graph_ops
from app.services.graph_revisions import persist_graph
from app.services.project_assets import sync_from_graph

KIND_NODE = {
    "image": "ImageAsset",
    "video": "VideoAsset",
    "audio": "AudioAsset",
    "text": "TextAsset",
    "prompt": "TextAsset",
}


def _clip(val: Any, n: int = 8000) -> str:
    s = str(val or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


async def record_asset_version(
    db: AsyncSession,
    *,
    user: User,
    workflow_id: int | None,
    run_id: int | None = None,
    node_id: str = "",
    node_type: str = "",
    kind: str,
    url: str = "",
    thumbnail_url: str = "",
    text: str = "",
    prompt: str = "",
    model_provider: str = "",
    model_name: str = "",
    channel_id: int | None = None,
    params: dict[str, Any] | None = None,
    cost: float = 0.0,
    status: str = "succeeded",
    error_message: str = "",
) -> AssetVersion | None:
    if not workflow_id:
        return None
    kind = (kind or "").strip().lower() or "image"
    url = (url or "").strip()
    text = _clip(text, 8000)
    prompt = _clip(prompt, 4000)
    if kind in {"image", "video", "audio"} and not url and status == "succeeded":
        return None
    if kind in {"text", "prompt"} and not (text or prompt or url) and status == "succeeded":
        return None
    row = AssetVersion(
        user_id=user.id,
        workflow_id=workflow_id,
        run_id=run_id,
        node_id=(node_id or "")[:64],
        node_type=(node_type or "")[:64],
        kind=kind[:16],
        url=url,
        thumbnail_url=(thumbnail_url or url or "").strip(),
        text=text,
        prompt=prompt,
        model_provider=(model_provider or "")[:64],
        model_name=(model_name or "")[:120],
        channel_id=channel_id,
        params_json=json.dumps(params or {}, ensure_ascii=False),
        cost=round(float(cost or 0), 4),
        status=(status or "succeeded")[:32],
        error_message=_clip(error_message, 500),
    )
    db.add(row)
    await db.flush()
    return row


async def list_asset_versions(
    db: AsyncSession,
    *,
    workflow_id: int,
    kind: str | None = None,
    node_type: str | None = None,
    favorite: bool | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AssetVersion], int]:
    filters = [AssetVersion.workflow_id == workflow_id]
    if kind:
        filters.append(AssetVersion.kind == kind)
    if node_type:
        filters.append(AssetVersion.node_type == node_type)
    if favorite is True:
        filters.append(AssetVersion.favorite.is_(True))
    if status:
        filters.append(AssetVersion.status == status)
    total = int(
        (await db.execute(select(func.count()).select_from(AssetVersion).where(*filters))).scalar_one()
    )
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    rows = (
        (
            await db.execute(
                select(AssetVersion)
                .where(*filters)
                .order_by(AssetVersion.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def set_favorite(db: AsyncSession, row: AssetVersion, favorite: bool) -> AssetVersion:
    row.favorite = bool(favorite)
    await db.flush()
    return row


async def bulk_delete(db: AsyncSession, *, user_id: int, ids: list[int]) -> int:
    if not ids:
        return 0
    result = await db.execute(
        select(AssetVersion).where(AssetVersion.user_id == user_id, AssetVersion.id.in_(ids))
    )
    rows = list(result.scalars().all())
    for row in rows:
        await db.delete(row)
    return len(rows)


def canvas_payload(row: AssetVersion) -> dict[str, Any]:
    nt = KIND_NODE.get(row.kind, "TextAsset")
    data: dict[str, Any] = {
        "label": "历史素材",
        "source_asset_version_id": row.id,
    }
    if nt == "ImageAsset":
        data["image_url"] = row.url
    elif nt == "VideoAsset":
        data["clip_url"] = row.url
        data["result_url"] = row.url
        data["preview_url"] = row.url
    elif nt == "AudioAsset":
        data["audio_url"] = row.url
    else:
        body = (row.text or row.prompt or "").strip()
        data["text"] = body
        data["prompt"] = row.prompt or body
        data["textRole"] = "prompt" if row.kind == "prompt" else "notes"
    return {"node_type": nt, "data": data, "url": row.url, "kind": row.kind}


async def send_to_canvas(
    db: AsyncSession,
    *,
    workflow: Workflow,
    row: AssetVersion,
    viewport: tuple[float, float] = (420.0, 240.0),
) -> dict[str, Any]:
    graph = graph_ops.parse_graph(workflow.graph_json)
    payload = canvas_payload(row)
    nid = graph_ops.add_node(
        graph,
        node_type=str(payload["node_type"]),
        label=str(payload["data"].get("label") or "历史素材"),
        data=payload["data"],
        viewport=viewport,
    )
    await persist_graph(db, workflow, graph, source="asset_history")
    await sync_from_graph(db, workflow)
    return {
        "node_id": nid,
        "node_type": payload["node_type"],
        "graph": graph,
    }
