"""Generated asset history APIs."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import AssetVersion, User, Workflow
from app.schemas import (
    AssetVersionBulkDeleteIn,
    AssetVersionListOut,
    AssetVersionOut,
    AssetVersionPatchIn,
    AssetVersionSendIn,
    AssetVersionSendOut,
)
from app.services import asset_versions as versions_svc

router = APIRouter(tags=["asset-versions"])


def _out(row: AssetVersion) -> AssetVersionOut:
    params: dict = {}
    try:
        raw = json.loads(row.params_json or "{}")
        if isinstance(raw, dict):
            params = raw
    except json.JSONDecodeError:
        params = {}
    return AssetVersionOut(
        id=row.id,
        workflow_id=row.workflow_id,
        run_id=row.run_id,
        node_id=row.node_id,
        node_type=row.node_type,
        kind=row.kind,
        url=row.url,
        thumbnail_url=row.thumbnail_url or row.url,
        text=row.text,
        prompt=row.prompt,
        model_provider=row.model_provider,
        model_name=row.model_name,
        channel_id=row.channel_id,
        params=params,
        cost=row.cost,
        status=row.status,
        error_message=row.error_message,
        favorite=bool(row.favorite),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _owned_workflow(workflow_id: int, user: User, db: AsyncSession) -> Workflow:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return wf


async def _owned_version(version_id: int, user: User, db: AsyncSession) -> AssetVersion:
    row = await db.get(AssetVersion, version_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="历史素材不存在")
    return row


@router.get("/workflows/{workflow_id}/asset-versions", response_model=AssetVersionListOut)
async def list_versions(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    kind: str | None = None,
    node_type: str | None = None,
    favorite: bool | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AssetVersionListOut:
    await _owned_workflow(workflow_id, user, db)
    rows, total = await versions_svc.list_asset_versions(
        db,
        workflow_id=workflow_id,
        kind=kind,
        node_type=node_type,
        favorite=favorite,
        status=status,
        limit=limit,
        offset=offset,
    )
    return AssetVersionListOut(
        items=[_out(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/asset-versions/{version_id}", response_model=AssetVersionOut)
async def patch_version(
    version_id: int,
    body: AssetVersionPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssetVersionOut:
    row = await _owned_version(version_id, user, db)
    if body.favorite is not None:
        await versions_svc.set_favorite(db, row, body.favorite)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/asset-versions/bulk-delete")
async def bulk_delete(
    body: AssetVersionBulkDeleteIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    deleted = await versions_svc.bulk_delete(db, user_id=user.id, ids=body.ids)
    await db.commit()
    return {"deleted": deleted}


@router.post("/asset-versions/{version_id}/send-to-canvas", response_model=AssetVersionSendOut)
async def send_to_canvas(
    version_id: int,
    body: AssetVersionSendIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssetVersionSendOut:
    row = await _owned_version(version_id, user, db)
    wf = await _owned_workflow(row.workflow_id, user, db)
    try:
        result = await versions_svc.send_to_canvas(
            db,
            workflow=wf,
            row=row,
            viewport=(float(body.x if body.x is not None else 420), float(body.y if body.y is not None else 240)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(wf)
    return AssetVersionSendOut(
        node_id=str(result["node_id"]),
        node_type=str(result["node_type"]),
        graph=result["graph"],
    )
