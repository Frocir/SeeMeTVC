from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_super_admin
from app.models import Channel, User
from app.schemas import ChannelCreate, ChannelOut, ChannelUpdate, ModelOptionOut

router = APIRouter(tags=["channels"])


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def to_channel_out(ch: Channel) -> ChannelOut:
    return ChannelOut(
        id=ch.id,
        name=ch.name,
        provider=ch.provider,
        base_url=ch.base_url,
        model_id=ch.model_id,
        upstream_model=ch.upstream_model,
        cost_per_second=ch.cost_per_second,
        priority=ch.priority,
        enabled=ch.enabled,
        remark=ch.remark,
        api_key_masked=_mask_key(ch.api_key),
    )


@router.get("/models", response_model=list[ModelOptionOut])
async def list_enabled_models(db: AsyncSession = Depends(get_db)) -> list[ModelOptionOut]:
    result = await db.execute(
        select(Channel)
        .where(Channel.enabled.is_(True))
        .order_by(Channel.priority.desc(), Channel.id.asc())
    )
    channels = result.scalars().all()
    seen: set[str] = set()
    out: list[ModelOptionOut] = []
    for ch in channels:
        if ch.model_id in seen:
            continue
        seen.add(ch.model_id)
        out.append(
            ModelOptionOut(
                model_id=ch.model_id,
                cost_per_second=ch.cost_per_second,
                provider=ch.provider,
            )
        )
    return out


@router.get("/admin/channels", response_model=list[ChannelOut])
async def admin_list_channels(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ChannelOut]:
    result = await db.execute(select(Channel).order_by(Channel.priority.desc(), Channel.id.asc()))
    return [to_channel_out(ch) for ch in result.scalars().all()]


@router.post("/admin/channels", response_model=ChannelOut)
async def admin_create_channel(
    body: ChannelCreate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ChannelOut:
    exists = await db.execute(select(Channel).where(Channel.name == body.name))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="渠道名称已存在")
    ch = Channel(**body.model_dump())
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return to_channel_out(ch)


@router.patch("/admin/channels/{channel_id}", response_model=ChannelOut)
async def admin_update_channel(
    channel_id: int,
    body: ChannelUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ChannelOut:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if ch is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(ch, key, value)
    await db.commit()
    await db.refresh(ch)
    return to_channel_out(ch)


@router.delete("/admin/channels/{channel_id}")
async def admin_delete_channel(
    channel_id: int,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if ch is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    await db.delete(ch)
    await db.commit()
    return {"ok": True}
