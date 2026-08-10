import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.models import Channel, JobStatus, User, VideoJob
from app.schemas import GenerateIn, JobOut
from app.services import seedance

router = APIRouter(prefix="/videos", tags=["videos"])


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

            # Poll up to ~3 minutes
            for _ in range(36):
                status, url = await seedance.poll_generation(channel, task_id)
                if status == "succeeded":
                    job.status = JobStatus.SUCCEEDED.value
                    job.result_url = url
                    await db.commit()
                    return
                if status == "failed":
                    raise seedance.SeedanceError("上游生成失败")
                await asyncio.sleep(5)

            raise seedance.SeedanceError("生成超时")
        except Exception as exc:  # noqa: BLE001 — surface to job record + refund
            job.status = JobStatus.REFUNDED.value
            job.error_message = str(exc)[:500]
            user.balance = float(user.balance) + float(job.cost)
            job.balance_after = user.balance
            await db.commit()


@router.post("/generate", response_model=JobOut)
async def generate(
    body: GenerateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VideoJob:
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
) -> list[VideoJob]:
    result = await db.execute(
        select(VideoJob).where(VideoJob.user_id == user.id).order_by(VideoJob.id.desc()).limit(100)
    )
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
