from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Channel, User, UserRole
from app.security import hash_password

AGNES_CHANNEL_NAME = "Agnes AI Pavo (free)"
LOCAL_SIM_CHANNEL_NAME = "本地seedance模拟版（Seedance LocalSimulate）"
LITE_CHANNEL_NAME = "Seedance Lite（火山方舟）"
SEEDANCE25_CHANNEL_NAME = "Seedance 2.5（火山方舟）"
LOCAL_SIM_MODEL_ID = "seedance-local-simulate"

LITE_PRIORITY = 80
SEEDANCE25_PRIORITY = 70
LOCAL_SIM_PRIORITY = 40
AGNES_PRIORITY = 10
LOCAL_SIM_PRIORITY_OFFLINE = 100

ARK_BASE = "https://ark.cn-beijing.volces.com"
# 默认可被超管改成控制台里的「推理接入点 ID」(ep-xxx)
LITE_UPSTREAM = "doubao-seedance-1-0-lite-t2v-250428"
SEEDANCE25_UPSTREAM = "doubao-seedance-2-0-260128"

_LEGACY_LOCAL_NAMES = ("Seedance Mock (local)", "Seedance Lite (mock)")
_LEGACY_LOCAL_MODEL_IDS = ("seedance-mock",)
_LEGACY_LITE_NAMES = ("Seedance Lite (fal)", "Seedance Lite (fal)")
_LEGACY_25_NAMES = ("Seedance 2.5 (fal)", "Seedance 2.5 (disabled)")


def _looks_like_real_key(key: str) -> bool:
    k = (key or "").strip()
    if not k:
        return False
    if k in {"replace-me", "YOUR_API_KEY", "FAL_KEY", "ARK_API_KEY", "mock:demo", "sk-your-agnes-key", "sk-xxx"}:
        return False
    return len(k) >= 8


async def ensure_bootstrap_data(db: AsyncSession) -> None:
    settings = get_settings()
    result = await db.execute(select(User).where(User.email == settings.bootstrap_admin_email))
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = User(
            email=settings.bootstrap_admin_email,
            password_hash=hash_password(settings.bootstrap_admin_password),
            display_name="Super Admin",
            role=UserRole.SUPER_ADMIN.value,
            balance=10000.0,
        )
        db.add(admin)

    await _ensure_seedance_channels(db)
    await _ensure_agnes_channel(db)
    await _heal_channels(db)
    await db.commit()


async def _get_by_name(db: AsyncSession, name: str) -> Channel | None:
    result = await db.execute(select(Channel).where(Channel.name == name))
    return result.scalar_one_or_none()


async def _any_enabled_ark(db: AsyncSession) -> bool:
    result = await db.execute(
        select(Channel).where(
            Channel.provider.in_(("ark", "volc", "volcengine", "fal")),
            Channel.enabled.is_(True),
        )
    )
    return any(
        _looks_like_real_key(ch.api_key) and ch.model_id in {"seedance-lite", "seedance-2.5"}
        for ch in result.scalars().all()
    )


async def _ensure_seedance_channels(db: AsyncSession) -> None:
    """Seedance Lite / 2.5 via 火山方舟 Ark. Keys only via 超管 UI."""

    local = await _get_by_name(db, LOCAL_SIM_CHANNEL_NAME)
    if local is None:
        for legacy_name in _LEGACY_LOCAL_NAMES:
            legacy = await _get_by_name(db, legacy_name)
            if legacy is not None:
                legacy.name = LOCAL_SIM_CHANNEL_NAME
                local = legacy
                break
    if local is None:
        result = await db.execute(
            select(Channel).where(Channel.provider == "mock").order_by(Channel.id.asc()).limit(1)
        )
        local = result.scalar_one_or_none()

    local_remark = (
        "本地 ffmpeg 样片（离线演示，非真实 Seedance）。"
        "真正 Seedance 请超管填写火山方舟 ARK_API_KEY 并启用 Lite / 2.5。"
    )
    if local is None:
        db.add(
            Channel(
                name=LOCAL_SIM_CHANNEL_NAME,
                provider="mock",
                base_url="",
                api_key="",
                model_id=LOCAL_SIM_MODEL_ID,
                upstream_model="local-simulate",
                cost_per_second=0.0,
                priority=LOCAL_SIM_PRIORITY_OFFLINE,
                enabled=True,
                remark=local_remark,
            )
        )
    else:
        local.name = LOCAL_SIM_CHANNEL_NAME
        local.provider = "mock"
        local.model_id = LOCAL_SIM_MODEL_ID
        local.upstream_model = "local-simulate"
        local.enabled = True
        local.remark = local_remark

    await _ensure_ark_model_channel(
        db,
        name=LITE_CHANNEL_NAME,
        legacy_names=_LEGACY_LITE_NAMES,
        model_id="seedance-lite",
        upstream=LITE_UPSTREAM,
        priority=LITE_PRIORITY,
        cost=1.0,
        remark=(
            "火山方舟 Seedance 1.0 Lite。"
            "Base URL: https://ark.cn-beijing.volces.com ；"
            "upstream_model 填模型 ID 或推理接入点 ep-xxx。"
            "超管「改 Key」写入 ARK_API_KEY 后启用。无原生音频。"
        ),
    )
    await _ensure_ark_model_channel(
        db,
        name=SEEDANCE25_CHANNEL_NAME,
        legacy_names=_LEGACY_25_NAMES,
        model_id="seedance-2.5",
        upstream=SEEDANCE25_UPSTREAM,
        priority=SEEDANCE25_PRIORITY,
        cost=8.0,
        remark=(
            "火山方舟 Seedance 2.x（产品名 2.5）。"
            "默认 generate_audio；时长约 4–30 秒。"
            "upstream_model 可改为你控制台的接入点 ID。超管「改 Key」后启用。"
        ),
    )


async def _ensure_ark_model_channel(
    db: AsyncSession,
    *,
    name: str,
    legacy_names: tuple[str, ...],
    model_id: str,
    upstream: str,
    priority: int,
    cost: float,
    remark: str,
) -> None:
    ch = await _get_by_name(db, name)
    if ch is None:
        for legacy_name in legacy_names:
            legacy = await _get_by_name(db, legacy_name)
            if legacy is not None:
                legacy.name = name
                ch = legacy
                break
    if ch is None:
        result = await db.execute(
            select(Channel)
            .where(Channel.model_id == model_id)
            .order_by(Channel.id.asc())
            .limit(1)
        )
        ch = result.scalar_one_or_none()
        # Don't steal mock rows
        if ch is not None and ch.provider == "mock":
            ch = None

    if ch is None:
        db.add(
            Channel(
                name=name,
                provider="ark",
                base_url=ARK_BASE,
                api_key="",
                model_id=model_id,
                upstream_model=upstream,
                cost_per_second=cost,
                priority=priority,
                enabled=False,
                remark=remark,
            )
        )
        return

    ch.name = name
    ch.provider = "ark"
    ch.base_url = ARK_BASE
    ch.model_id = model_id
    # Migrate away from fal upstream paths
    um = (ch.upstream_model or "").strip()
    if (not um) or "fal-ai/" in um or um.startswith("bytedance/") or "queue.fal" in um:
        ch.upstream_model = upstream
    ch.priority = max(int(ch.priority or 0), priority)
    ch.remark = remark
    # Keep enabled if already had a real key; otherwise stay disabled
    if not _looks_like_real_key(ch.api_key):
        ch.enabled = False


async def _ensure_agnes_channel(db: AsyncSession) -> None:
    settings = get_settings()
    agnes = await _get_by_name(db, AGNES_CHANNEL_NAME)
    if agnes is None:
        db.add(
            Channel(
                name=AGNES_CHANNEL_NAME,
                provider="agnes",
                base_url=settings.agnes_base_url.rstrip("/") or "https://api.agnes-ai.cn",
                api_key="",
                model_id="agnes-pavo",
                upstream_model=settings.agnes_upstream_model or "agnes-video-v2.0",
                cost_per_second=0.0,
                priority=AGNES_PRIORITY,
                enabled=False,
                remark=(
                    "免费 Agnes AI Pavo（agnes-video-v2.0）。默认关闭。"
                    "超管「改 Key」写入后启用。"
                ),
            )
        )
    else:
        if not (agnes.base_url or "").strip():
            agnes.base_url = settings.agnes_base_url.rstrip("/") or "https://api.agnes-ai.cn"
        if not (agnes.upstream_model or "").strip():
            agnes.upstream_model = settings.agnes_upstream_model or "agnes-video-v2.0"


async def _heal_channels(db: AsyncSession) -> None:
    has_ark = await _any_enabled_ark(db)

    result = await db.execute(select(Channel))
    for ch in result.scalars().all():
        if not _looks_like_real_key(ch.api_key):
            ch.api_key = ""

    result = await db.execute(select(Channel).where(Channel.provider == "mock"))
    for local in result.scalars().all():
        if local.model_id in {"seedance-lite", "seedance-2.5", *_LEGACY_LOCAL_MODEL_IDS}:
            local.model_id = LOCAL_SIM_MODEL_ID
        local.name = LOCAL_SIM_CHANNEL_NAME
        local.upstream_model = "local-simulate"
        local.priority = LOCAL_SIM_PRIORITY if has_ark else LOCAL_SIM_PRIORITY_OFFLINE
        local.enabled = True

    # Any leftover fal seedance → ark
    result = await db.execute(
        select(Channel).where(
            Channel.provider == "fal",
            Channel.model_id.in_(("seedance-lite", "seedance-2.5")),
        )
    )
    for ch in result.scalars().all():
        ch.provider = "ark"
        ch.base_url = ARK_BASE
        if ch.model_id == "seedance-lite":
            ch.name = LITE_CHANNEL_NAME
            if "fal" in (ch.upstream_model or "") or "bytedance/" in (ch.upstream_model or ""):
                ch.upstream_model = LITE_UPSTREAM
        else:
            ch.name = SEEDANCE25_CHANNEL_NAME
            if "fal" in (ch.upstream_model or "") or "bytedance/" in (ch.upstream_model or ""):
                ch.upstream_model = SEEDANCE25_UPSTREAM

    agnes = await _get_by_name(db, AGNES_CHANNEL_NAME)
    if agnes is not None and int(agnes.priority or 0) > AGNES_PRIORITY:
        agnes.priority = AGNES_PRIORITY
