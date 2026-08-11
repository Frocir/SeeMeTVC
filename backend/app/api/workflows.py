import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.models import User, Workflow, WorkflowRun, WorkflowRunStatus
from app.schemas import (
    WorkflowCreateIn,
    WorkflowOut,
    WorkflowRunCreateIn,
    WorkflowRunOut,
    WorkflowUpdateIn,
)
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


def _workflow_out(wf: Workflow) -> WorkflowOut:
    try:
        graph = json.loads(wf.graph_json or "{}")
    except json.JSONDecodeError:
        graph = {"nodes": [], "edges": []}
    return WorkflowOut(
        id=wf.id,
        name=wf.name,
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
    return [_workflow_out(w) for w in result.scalars().all()]


@router.post("", response_model=WorkflowOut)
async def create_workflow(
    body: WorkflowCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    graph = body.graph.model_dump() if body.graph else {"nodes": [], "edges": []}
    wf = Workflow(user_id=user.id, name=body.name or "未命名工作流", graph_json=_graph_dumps(graph))
    db.add(wf)
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
            raise HTTPException(status_code=404, detail="工作流不存在")
        try:
            graph_dict = json.loads(wf.graph_json or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="工作流图损坏") from exc
        if body.name and wf.name != body.name:
            wf.name = body.name
    else:
        raise HTTPException(status_code=400, detail="请提供 workflow_id 或 graph")

    nodes = graph_dict.get("nodes") or []
    if not nodes:
        raise HTTPException(status_code=400, detail="工作流图为空")

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
    return _run_out(run)


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return _workflow_out(wf)


@router.patch("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: int,
    body: WorkflowUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if body.name is not None:
        wf.name = body.name
    if body.graph is not None:
        wf.graph_json = _graph_dumps(body.graph.model_dump())
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
        raise HTTPException(status_code=404, detail="工作流不存在")
    await db.delete(wf)
    await db.commit()
    return {"ok": True}
