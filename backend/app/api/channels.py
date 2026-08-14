from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_super_admin
from app.models import Channel, User
from app.schemas import ChannelCreate, ChannelOut, ChannelProbeOut, ChannelUpdate, ModelOptionOut
from app.services import channel_probe, seedance

router = APIRouter(tags=["channels"])


def _mask_key(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "未设置"
    if len(k) <= 8:
        return "***"
    return f"{k[:4]}***{k[-4:]}"


def _model_meta(ch: Channel) -> tuple[int, int, bool, bool]:
    """duration_min, duration_max, supports_audio, supports_image."""
    if ch.provider == "mock" or (ch.api_key or "").startswith("mock:"):
        return 1, 15, True, True
    if ch.provider.lower() in {"agnes", "pavo", "agnes-pavo"}:
        return 2, 18, False, True
    family = seedance.fal_family(ch)
    if family == "seedance-2.5":
        return 4, 30, True, True
    if family == "seedance-lite":
        return 2, 12, False, True
    return 2, 30, False, True


def to_channel_out(ch: Channel) -> ChannelOut:
    return ChannelOut(
        id=ch.id,
        name=ch.name,
        provider=ch.provider,
        kind=(ch.kind or "video"),
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
async def list_enabled_models(
    db: AsyncSession = Depends(get_db),
    kind: str = "video",
) -> list[ModelOptionOut]:
    want = (kind or "video").strip().lower()
    if want not in {"video", "llm", "tts", "image"}:
        want = "video"
    result = await db.execute(
        select(Channel)
        .where(Channel.enabled.is_(True))
        .order_by(Channel.priority.desc(), Channel.id.asc())
    )
    channels = result.scalars().all()
    seen: set[str] = set()
    out: list[ModelOptionOut] = []
    for ch in channels:
        ch_kind = (ch.kind or "video").strip().lower() or "video"
        if ch_kind != want:
            continue
        if ch.model_id in seen:
            continue
        seen.add(ch.model_id)
        dmin, dmax, audio, image = _model_meta(ch)
        if want == "llm":
            dmin, dmax, audio, image = 0, 0, False, False
        elif want == "tts":
            dmin, dmax, audio, image = 0, 0, True, False
        elif want == "image":
            dmin, dmax, audio, image = 0, 0, False, True
        out.append(
            ModelOptionOut(
                model_id=ch.model_id,
                cost_per_second=ch.cost_per_second,
                provider=ch.provider,
                kind=want,
                label=ch.name or ch.model_id,
                duration_min=dmin,
                duration_max=dmax,
                supports_audio=audio,
                supports_image=image,
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
    data = body.model_dump(exclude_unset=True)
    if "api_key" in data and not str(data.get("api_key") or "").strip():
        data.pop("api_key")
    new_name = data.get("name")
    if isinstance(new_name, str) and new_name.strip() and new_name != ch.name:
        exists = await db.execute(select(Channel).where(Channel.name == new_name, Channel.id != channel_id))
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="渠道名称已存在")
    for key, value in data.items():
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


@router.post("/admin/channels/{channel_id}/probe", response_model=ChannelProbeOut)
async def admin_probe_channel(
    channel_id: int,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ChannelProbeOut:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if ch is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    out = await channel_probe.probe_channel(ch)
    return ChannelProbeOut(**out.as_dict())
