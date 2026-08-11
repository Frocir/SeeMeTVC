from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Channel, User, UserRole
from app.security import hash_password

AGNES_CHANNEL_NAME = "Agnes AI Pavo (free)"
MOCK_CHANNEL_NAME = "Seedance Lite (mock)"
# Local demo must win /api/models sort (priority DESC) over paid/free upstreams.
MOCK_PRIORITY = 100
AGNES_PRIORITY = 10
FAL_PRIORITY = 5


def _looks_like_agnes_key(key: str) -> bool:
    k = (key or "").strip()
    return bool(k) and k not in {"replace-me", "YOUR_API_KEY", "sk-your-agnes-key", "sk-xxx"}


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

    channel_result = await db.execute(select(Channel).limit(1))
    if channel_result.scalar_one_or_none() is None:
        db.add(
            Channel(
                name=MOCK_CHANNEL_NAME,
                provider="mock",
                base_url="",
                api_key="mock:demo",
                model_id="seedance-lite",
                upstream_model="fal-ai/bytedance/seedance/v1/lite/text-to-video",
                cost_per_second=1.0,
                priority=MOCK_PRIORITY,
                enabled=True,
                remark="本地演示渠道（默认优先）。替换为真实 fal Key 后改 provider=fal",
            )
        )
        db.add(
            Channel(
                name="Seedance 2.5 (disabled)",
                provider="fal",
                base_url="https://queue.fal.run",
                api_key="replace-me",
                model_id="seedance-2.5",
                upstream_model="bytedance/seedance-2.5/text-to-video",
                cost_per_second=8.0,
                priority=FAL_PRIORITY,
                enabled=False,
                remark="启用前请填入真实 API Key",
            )
        )

    # Always ensure free Agnes/Pavo channel exists.
    # Key source: AGNES_API_KEY / settings.agnes_api_key (no shared public trial token exists).
    # Channel stays disabled by default; super admin enables after verifying the key.
    agnes_key = settings.agnes_api_key.strip() or "replace-me"
    agnes_result = await db.execute(select(Channel).where(Channel.name == AGNES_CHANNEL_NAME))
    agnes = agnes_result.scalar_one_or_none()
    if agnes is None:
        db.add(
            Channel(
                name=AGNES_CHANNEL_NAME,
                provider="agnes",
                base_url=settings.agnes_base_url.rstrip("/") or "https://api.agnes-ai.cn",
                api_key=agnes_key,
                model_id="agnes-pavo",
                upstream_model=settings.agnes_upstream_model or "agnes-video-v2.0",
                cost_per_second=0.0,
                priority=AGNES_PRIORITY,
                enabled=False,
                remark=(
                    "免费 Agnes AI Pavo 格式（agnes-video-v2.0）。默认关闭。"
                    "国内默认 Base URL: https://api.agnes-ai.cn ；"
                    "写入 AGNES_API_KEY 或超管「改 Key」后启用。"
                    "优先级低于 mock，避免本地演示默认撞限流。"
                ),
            )
        )
    elif _looks_like_agnes_key(settings.agnes_api_key) and (
        not _looks_like_agnes_key(agnes.api_key) or agnes.api_key == "replace-me"
    ):
        # Refresh placeholder key from env without forcing enable.
        agnes.api_key = agnes_key
        agnes.base_url = settings.agnes_base_url.rstrip("/") or agnes.base_url
        agnes.upstream_model = settings.agnes_upstream_model or agnes.upstream_model

    await _heal_local_demo_channels(db)
    await db.commit()


async def _heal_local_demo_channels(db: AsyncSession) -> None:
    """Keep mock as the default local model even on DBs toggled by earlier admin ops."""
    mock_result = await db.execute(
        select(Channel).where(Channel.provider == "mock").order_by(Channel.id.asc()).limit(1)
    )
    mock = mock_result.scalar_one_or_none()
    if mock is None:
        db.add(
            Channel(
                name=MOCK_CHANNEL_NAME,
                provider="mock",
                base_url="",
                api_key="mock:demo",
                model_id="seedance-lite",
                upstream_model="fal-ai/bytedance/seedance/v1/lite/text-to-video",
                cost_per_second=1.0,
                priority=MOCK_PRIORITY,
                enabled=True,
                remark="本地演示渠道（默认优先）。替换为真实 fal Key 后改 provider=fal",
            )
        )
        await db.flush()
        mock_result = await db.execute(
            select(Channel).where(Channel.provider == "mock").order_by(Channel.id.asc()).limit(1)
        )
        mock = mock_result.scalar_one_or_none()

    if mock is not None:
        mock.enabled = True
        if int(mock.priority or 0) < MOCK_PRIORITY:
            mock.priority = MOCK_PRIORITY

    agnes_result = await db.execute(select(Channel).where(Channel.name == AGNES_CHANNEL_NAME))
    agnes = agnes_result.scalar_one_or_none()
    if agnes is not None:
        # Migrate old bootstrap priority (20) under mock; never outrank mock.
        if mock is not None and int(agnes.priority or 0) >= int(mock.priority or 0):
            agnes.priority = AGNES_PRIORITY
        elif int(agnes.priority or 0) > AGNES_PRIORITY:
            agnes.priority = AGNES_PRIORITY
