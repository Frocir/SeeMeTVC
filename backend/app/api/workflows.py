import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.models import Channel, ProjectAsset, User, Workflow, WorkflowRun, WorkflowRunStatus
from app.schemas import (
    ProjectAssetCopyIn,
    ProjectAssetCreateIn,
    ProjectAssetOut,
    WorkflowCreateIn,
    WorkflowExpandScenesIn,
    WorkflowExpandScenesOut,
    WorkflowOut,
    WorkflowRunCreateIn,
    WorkflowRunOut,
    WorkflowUpdateIn,
)
from app.services import graph_ops, scene_expand
from app.services.graph_revisions import persist_graph, undo_graph
from app.services.project_assets import (
    brand_from_graph,
    collect_upload_paths,
    copy_asset,
    last_image_from_graph,
    latest_image_url,
    refresh_cover,
    sync_from_graph,
    upsert_asset,
)
from app.services.run_preflight import cannot_run_reason
from app.services.workflow_exec import execute_run

router = APIRouter(prefix="/workflows", tags=["workflows"])


_TERMINAL = {
    WorkflowRunStatus.SUCCEEDED.value,
    WorkflowRunStatus.FAILED.value,
    WorkflowRunStatus.REFUNDED.value,
    WorkflowRunStatus.CANCELLED.value,
}


def _graph_dumps(graph: dict | None) -> str:
    return json.dumps(graph or {"nodes": [], "edges": []}, ensure_ascii=False)


def _workflow_out(wf: Workflow, thumb: str | None = None) -> WorkflowOut:
    try:
        graph = json.loads(wf.graph_json or "{}")
    except json.JSONDecodeError:
        graph = {"nodes": [], "edges": []}
    cover = wf.cover_url or thumb or last_image_from_graph(wf.graph_json)
    return WorkflowOut(
        id=wf.id,
        name=wf.name,
        brand=wf.brand or "SeeMe",
        cover_url=cover,
        graph=graph,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


def _run_out(run: WorkflowRun) -> WorkflowRunOut:
    try:
        graph = json.loads(run.graph_json or "{}")
    except json.JSONDecodeError:
        graph = {"nodes": [], "edges": []}
    try:
        node_states = json.loads(run.node_states_json or "{}")
    except json.JSONDecodeError:
        node_states = {}
    return WorkflowRunOut(
        id=run.id,
        workflow_id=run.workflow_id,
        status=run.status,
        graph=graph,
        node_states=node_states,
        cost=run.cost,
        balance_after=run.balance_after,
        result_url=run.result_url,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowOut]:
    result = await db.execute(
        select(Workflow).where(Workflow.user_id == user.id).order_by(Workflow.id.desc())
    )
    wfs = result.scalars().all()
    thumbs: dict[int, str] = {}
    need = [w.id for w in wfs if not w.cover_url]
    for wid in need:
        url = await latest_image_url(db, wid)
        if url:
            thumbs[wid] = url
    return [_workflow_out(w, thumb=thumbs.get(w.id)) for w in wfs]


@router.post("", response_model=WorkflowOut)
async def create_workflow(
    body: WorkflowCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    graph = body.graph.model_dump() if body.graph else {"nodes": [], "edges": []}
    brand = (body.brand or "").strip() or brand_from_graph(_graph_dumps(graph))
    wf = Workflow(
        user_id=user.id,
        name=body.name or "未命名项目",
        brand=brand,
        graph_json=_graph_dumps(graph),
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    await sync_from_graph(db, wf)
    await refresh_cover(db, wf)
    await db.commit()
    await db.refresh(wf)
    return _workflow_out(wf)


# Runs routes BEFORE /{workflow_id} so "runs" is not parsed as an id
@router.post("/runs", response_model=WorkflowRunOut)
async def start_run(
    body: WorkflowRunCreateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut:
    graph_dict: dict | None = None
    workflow_id = body.workflow_id

    if body.graph is not None:
        graph_dict = body.graph.model_dump()
    elif workflow_id is not None:
        wf = await db.get(Workflow, workflow_id)
        if wf is None or wf.user_id != user.id:
            raise HTTPException(status_code=404, detail="项目不存在")
        try:
            graph_dict = json.loads(wf.graph_json or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="项目画布数据损坏，请保存后重试") from exc
        if body.name and wf.name != body.name:
            wf.name = body.name
    else:
        raise HTTPException(status_code=400, detail="请提供项目或画布数据")
    if graph_dict is None:
        raise HTTPException(status_code=400, detail="请提供项目或画布数据")

    ch_rows = (
        await db.execute(select(Channel).where(Channel.enabled.is_(True)))
    ).scalars().all()
    kinds = {(c.kind or "video").strip().lower() or "video" for c in ch_rows}
    reason = cannot_run_reason(
        graph_dict,
        target_ids=list(body.target_ids or []),
        has_video_model="video" in kinds,
        has_llm_model="llm" in kinds,
        has_tts_model="tts" in kinds,
        has_image_model="image" in kinds,
    )
    if reason:
        raise HTTPException(status_code=400, detail=reason)

    if body.target_ids:
        graph_dict = {
            **graph_dict,
            "__run_opts__": {
                **(graph_dict.get("__run_opts__") or {}),
                "target_ids": list(body.target_ids),
            },
        }

    if workflow_id is None and body.name:
        wf = Workflow(
            user_id=user.id,
            name=body.name,
            graph_json=_graph_dumps({k: v for k, v in graph_dict.items() if k != "__run_opts__"}),
        )
        db.add(wf)
        await db.flush()
        workflow_id = wf.id

    run = WorkflowRun(
        workflow_id=workflow_id,
        user_id=user.id,
        status=WorkflowRunStatus.PENDING.value,
        graph_json=_graph_dumps(graph_dict),
        node_states_json="{}",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background.add_task(execute_run, run.id)
    return _run_out(run)


@router.get("/runs", response_model=list[WorkflowRunOut])
async def list_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 30,
) -> list[WorkflowRunOut]:
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.user_id == user.id)
        .order_by(WorkflowRun.id.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [_run_out(r) for r in result.scalars().all()]


@router.get("/runs/{run_id}", response_model=WorkflowRunOut)
async def get_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut:
    run = await db.get(WorkflowRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return _run_out(run)


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: int,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE: push WorkflowRunOut snapshots until the run reaches a terminal status."""
    async with SessionLocal() as db:
        run = await db.get(WorkflowRun, run_id)
        if run is None or run.user_id != user.id:
            raise HTTPException(status_code=404, detail="运行记录不存在")

    async def event_gen():
        last = ""
        idle = 0
        while True:
            async with SessionLocal() as db:
                run = await db.get(WorkflowRun, run_id)
                if run is None:
                    yield "event: error\ndata: {\"detail\":\"gone\"}\n\n"
                    return
                payload = _run_out(run).model_dump(mode="json")
                blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                terminal = run.status in _TERMINAL

            if blob != last:
                last = blob
                idle = 0
                yield f"event: run\ndata: {blob}\n\n"
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": keepalive\n\n"

            if terminal:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunOut)
async def cancel_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut:
    run = await db.get(WorkflowRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status in (
        WorkflowRunStatus.SUCCEEDED.value,
        WorkflowRunStatus.FAILED.value,
        WorkflowRunStatus.REFUNDED.value,
        WorkflowRunStatus.CANCELLED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"运行已结束（{run.status}），无法取消",
        )
    run.status = WorkflowRunStatus.CANCELLED.value
    run.error_message = "已取消"
    await db.commit()
    await db.refresh(run)
    payload = _run_out(run)
    from app.services.project_assets import delete_ephemeral_run

    await delete_ephemeral_run(db, run)
    await db.commit()
    return payload


@router.post("/{workflow_id}/expand-scenes", response_model=WorkflowExpandScenesOut)
async def expand_workflow_scenes(
    workflow_id: int,
    body: WorkflowExpandScenesIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowExpandScenesOut:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    graph = graph_ops.parse_graph(wf.graph_json)
    try:
        result = scene_expand.expand_scenes_to_nodes(
            graph,
            source_node_id=body.source_node_id,
            mode=body.mode,
            create_images=body.create_images,
            create_tts=body.create_tts,
            create_subtitles=body.create_subtitles,
            layout=body.layout,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await persist_graph(db, wf, result["graph"], source="expand_scenes")
    await sync_from_graph(db, wf)
    await refresh_cover(db, wf)
    await db.commit()
    await db.refresh(wf)
    return WorkflowExpandScenesOut(
        workflow_id=wf.id,
        graph=json.loads(wf.graph_json or "{}"),
        created_node_ids=list(result.get("created_node_ids") or []),
        created_edge_ids=list(result.get("created_edge_ids") or []),
        final_node_id=result.get("final_node_id"),
    )


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    thumb = None if wf.cover_url else await latest_image_url(db, wf.id)
    return _workflow_out(wf, thumb=thumb)


@router.patch("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: int,
    body: WorkflowUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    if body.name is not None:
        wf.name = body.name
    if body.brand is not None:
        wf.brand = body.brand.strip() or wf.brand
    if body.graph is not None:
        dumped = body.graph.model_dump()
        await persist_graph(db, wf, dumped, source="user_save")
        if not (body.brand or "").strip():
            wf.brand = brand_from_graph(wf.graph_json)
        await sync_from_graph(db, wf)
        await refresh_cover(db, wf)
    await db.commit()
    await db.refresh(wf)
    return _workflow_out(wf)


@router.post("/{workflow_id}/undo", response_model=WorkflowOut)
async def undo_workflow(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        await undo_graph(db, wf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await sync_from_graph(db, wf)
    await refresh_cover(db, wf)
    await db.commit()
    await db.refresh(wf)
    return _workflow_out(wf)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    urls = [wf.cover_url]
    assets = (
        await db.execute(select(ProjectAsset).where(ProjectAsset.workflow_id == wf.id))
    ).scalars().all()
    urls.extend(a.url for a in assets)
    runs = (
        await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id))
    ).scalars().all()
    for run in runs:
        urls.append(run.result_url)
        await db.delete(run)
    for asset in assets:
        await db.delete(asset)
    await db.delete(wf)
    await db.commit()
    for path in collect_upload_paths(*urls):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    return {"ok": True}


def _asset_out(row: ProjectAsset) -> ProjectAssetOut:
    return ProjectAssetOut(
        id=row.id,
        workflow_id=row.workflow_id,
        kind=row.kind,
        url=row.url,
        filename=row.filename,
        created_at=row.created_at,
    )


async def _owned_workflow(workflow_id: int, user: User, db: AsyncSession) -> Workflow:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return wf


@router.get("/{workflow_id}/assets", response_model=list[ProjectAssetOut])
async def list_assets(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    kind: str | None = None,
) -> list[ProjectAssetOut]:
    await _owned_workflow(workflow_id, user, db)
    stmt = select(ProjectAsset).where(ProjectAsset.workflow_id == workflow_id)
    if kind in {"image", "video", "output"}:
        stmt = stmt.where(ProjectAsset.kind == kind)
    stmt = stmt.order_by(ProjectAsset.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_asset_out(r) for r in rows]


@router.post("/{workflow_id}/assets", response_model=ProjectAssetOut)
async def add_asset(
    workflow_id: int,
    body: ProjectAssetCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectAssetOut:
    wf = await _owned_workflow(workflow_id, user, db)
    kind = body.kind if body.kind in {"image", "video"} else None
    row = await upsert_asset(
        db,
        workflow_id=wf.id,
        user_id=user.id,
        url=body.url,
        kind=kind,
        filename=body.filename,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="无效素材地址")
    await refresh_cover(db, wf)
    await db.commit()
    await db.refresh(row)
    return _asset_out(row)


@router.post("/{workflow_id}/assets/{asset_id}/copy", response_model=ProjectAssetOut)
async def copy_asset_to_project(
    workflow_id: int,
    asset_id: int,
    body: ProjectAssetCopyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectAssetOut:
    await _owned_workflow(workflow_id, user, db)
    src = await db.get(ProjectAsset, asset_id)
    if src is None or src.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="素材不存在")
    target = await _owned_workflow(body.target_workflow_id, user, db)
    if target.id == workflow_id:
        raise HTTPException(status_code=400, detail="请选择其他项目")
    row = await copy_asset(db, src, target)
    await refresh_cover(db, target)
    await db.commit()
    await db.refresh(row)
    return _asset_out(row)


@router.delete("/{workflow_id}/assets/{asset_id}")
async def delete_asset(
    workflow_id: int,
    asset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _owned_workflow(workflow_id, user, db)
    row = await db.get(ProjectAsset, asset_id)
    if row is None or row.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="素材不存在")
    url = row.url
    await db.delete(row)
    await db.commit()
    for path in collect_upload_paths(url):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    return {"ok": True}

