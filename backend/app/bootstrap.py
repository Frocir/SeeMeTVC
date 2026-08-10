from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Channel, User, UserRole
from app.security import hash_password


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
                name="Seedance Lite (mock)",
                provider="mock",
                base_url="",
                api_key="mock:demo",
                model_id="seedance-lite",
                upstream_model="fal-ai/bytedance/seedance/v1/lite/text-to-video",
                cost_per_second=1.0,
                priority=10,
                enabled=True,
                remark="本地演示渠道，替换为真实 fal Key 后改 provider=fal",
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
                priority=5,
                enabled=False,
                remark="启用前请填入真实 API Key",
            )
        )
    await db.commit()
