import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.models import Channel, JobStatus, User, VideoJob
from app.schemas import GenerateIn, JobOut, ParallelQuotaOut
from app.services import seedance

router = APIRouter(prefix="/videos", tags=["videos"])

ACTIVE_STATUSES = (JobStatus.PENDING.value, JobStatus.RUNNING.value)


async def _pick_channel(db: AsyncSession, model_id: str) -> Channel | None:
    result = await db.execute(
        select(Channel)
        .where(Channel.model_id == model_id, Channel.enabled.is_(True))
        .order_by(Channel.priority.desc(), Channel.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _run_job(job_id: int) -> None:
    async with SessionLocal() as db:
        job = await db.get(VideoJob, job_id)
        if job is None:
            return
        channel = await db.get(Channel, job.channel_id) if job.channel_id else None
        user = await db.get(User, job.user_id)
        if channel is None or user is None:
            job.status = JobStatus.FAILED.value
            job.error_message = "渠道或用户不存在"
            await db.commit()
            return

        job.status = JobStatus.RUNNING.value
        await db.commit()

        try:
            task_id = await seedance.submit_generation(
                channel,
                prompt=job.prompt,
                duration_seconds=job.duration_seconds,
                image_url=job.image_url,
            )
            job.upstream_task_id = task_id
            await db.commit()

            # Poll up to ~3–10 minutes (Agnes slower + 429 backoff)
            is_agnes = channel.provider.lower() in {"agnes", "pavo", "agnes-pavo"}
            interval = 12.0 if is_agnes else 5.0
            polls = 60 if is_agnes else 36
            for _ in range(polls):
                status, url = await seedance.poll_generation(channel, task_id)
                if status == "succeeded":
                    job.status = JobStatus.SUCCEEDED.value
                    job.result_url = url
                    await db.commit()
                    return
                if status == "failed":
                    raise seedance.SeedanceError("上游生成失败")
                if status == "rate_limited":
                    await asyncio.sleep(20.0)
                    continue
                await asyncio.sleep(interval)

            raise seedance.SeedanceError("生成超时")
        except Exception as exc:  # noqa: BLE001 — surface to job record + refund
            job.status = JobStatus.REFUNDED.value
            job.error_message = str(exc)[:500]
            user.balance = float(user.balance) + float(job.cost)
            job.balance_after = user.balance
            await db.commit()


async def _count_active_jobs(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(VideoJob)
        .where(VideoJob.user_id == user_id, VideoJob.status.in_(ACTIVE_STATUSES))
    )
    return int(result.scalar_one())


@router.get("/parallel-quota", response_model=ParallelQuotaOut)
async def parallel_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ParallelQuotaOut:
    settings = get_settings()
    active = await _count_active_jobs(db, user.id)
    return ParallelQuotaOut(
        max_parallel=settings.max_parallel_jobs,
        active=active,
        available=max(0, settings.max_parallel_jobs - active),
    )


@router.post("/generate", response_model=JobOut)
async def generate(
    body: GenerateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VideoJob:
    settings = get_settings()
    active = await _count_active_jobs(db, user.id)
    if active >= settings.max_parallel_jobs:
        raise HTTPException(
            status_code=429,
            detail=f"并行任务已满（最多同时 {settings.max_parallel_jobs} 个），请等待进行中的任务完成",
        )

    channel = await _pick_channel(db, body.model_id)
    if channel is None:
        raise HTTPException(status_code=400, detail="模型不可用或未配置渠道")

    cost = round(channel.cost_per_second * body.duration_seconds, 4)
    if user.balance < cost:
        raise HTTPException(status_code=402, detail="余额不足")

    user.balance = float(user.balance) - cost
    job = VideoJob(
        user_id=user.id,
        channel_id=channel.id,
        model_id=body.model_id,
        prompt=body.prompt,
        image_url=body.image_url,
        duration_seconds=body.duration_seconds,
        status=JobStatus.PENDING.value,
        cost=cost,
        balance_after=user.balance,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background.add_task(_run_job, job.id)
    return job


@router.get("/jobs", response_model=list[JobOut])
async def list_my_jobs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    limit: int = 100,
) -> list[VideoJob]:
    limit = max(1, min(limit, 200))
    stmt = select(VideoJob).where(VideoJob.user_id == user.id)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(VideoJob.status.in_(statuses))
    result = await db.execute(stmt.order_by(VideoJob.id.desc()).limit(limit))
    return list(result.scalars().all())


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VideoJob:
    job = await db.get(VideoJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job
