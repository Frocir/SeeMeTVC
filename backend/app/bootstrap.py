import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Channel, User, UserRole
from app.security import hash_password

_log = logging.getLogger("seemetvc.bootstrap")

AGNES_CHANNEL_NAME = "Agnes AI Pavo (free)"
LOCAL_SIM_CHANNEL_NAME = "本地seedance模拟版（Seedance LocalSimulate）"
LITE_CHANNEL_NAME = "Seedance Lite（火山方舟）"
SEEDANCE25_CHANNEL_NAME = "Seedance 2.5（火山方舟）"
LOCAL_SIM_MODEL_ID = "seedance-local-simulate"
OPENAI_LLM_CHANNEL_NAME = "OpenAI 兼容 · 对话"
ANTHROPIC_LLM_CHANNEL_NAME = "Anthropic · 对话"
TTS_CHANNEL_NAME = "Edge TTS（aisrv）"
IMAGE_SIM_CHANNEL_NAME = "本地文生图模拟"
IMAGE_SIM_MODEL_ID = "t2i-local-simulate"
LLM_SIM_CHANNEL_NAME = "本地 LLM 模拟"
LLM_SIM_MODEL_ID = "llm-local-simulate"

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
    password = (settings.bootstrap_admin_password or "").strip()
    if admin is None:
        if len(password) < 6:
            _log.warning(
                "未设置 BOOTSTRAP_ADMIN_PASSWORD（至少 6 位），跳过创建超管。请写在仓库根目录 .env。"
            )
        else:
            admin = User(
                email=settings.bootstrap_admin_email,
                password_hash=hash_password(password),
                display_name="Super Admin",
                role=UserRole.SUPER_ADMIN.value,
                balance=10000.0,
            )
            db.add(admin)

    await _ensure_seedance_channels(db)
    await _ensure_agnes_channel(db)
    await _ensure_llm_channels(db)
    await _ensure_tts_channel(db)
    await _ensure_image_channel(db)
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
        if local is not None and (local.kind or "") in {"llm", "image", "tts"}:
            local = None

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
                kind="video",
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
                kind="video",
                remark=remark,
            )
        )
        return

    ch.name = name
    ch.provider = "ark"
    ch.kind = "video"
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
                kind="video",
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
        agnes.kind = "video"


async def _ensure_llm_channels(db: AsyncSession) -> None:
    sim = await _get_by_name(db, LLM_SIM_CHANNEL_NAME)
    sim_remark = "本地即时文案（不调上游、不扣费）。真模型请另启用 OpenAI / Anthropic 并填 Key。"
    if sim is None:
        db.add(
            Channel(
                name=LLM_SIM_CHANNEL_NAME,
                provider="mock",
                kind="llm",
                base_url="",
                api_key="",
                model_id=LLM_SIM_MODEL_ID,
                upstream_model="local-simulate",
                cost_per_second=0.0,
                priority=95,
                enabled=True,
                remark=sim_remark,
            )
        )
    else:
        sim.kind = "llm"
        sim.provider = "mock"
        sim.model_id = LLM_SIM_MODEL_ID
        sim.upstream_model = "local-simulate"
        sim.enabled = True
        sim.remark = sim_remark

    openai = await _get_by_name(db, OPENAI_LLM_CHANNEL_NAME)
    if openai is None:
        # Don't resurrect the official row if the admin deleted it and already
        # has another OpenAI-compatible LLM channel.
        existing = await db.execute(
            select(Channel).where(Channel.kind == "llm", Channel.provider == "openai").limit(1)
        )
        if existing.scalar_one_or_none() is None:
            db.add(
                Channel(
                    name=OPENAI_LLM_CHANNEL_NAME,
                    provider="openai",
                    kind="llm",
                    base_url="https://api.openai.com/v1",
                    api_key="",
                    model_id="gpt-4o-mini",
                    upstream_model="gpt-4o-mini",
                    cost_per_second=0.0,
                    priority=60,
                    enabled=False,
                    remark="OpenAI 兼容 Chat Completions。超管改 Key 后启用。也可把 base_url 改成网关。",
                )
            )
    else:
        openai.kind = "llm"
        if not (openai.base_url or "").strip():
            openai.base_url = "https://api.openai.com/v1"

    anthropic = await _get_by_name(db, ANTHROPIC_LLM_CHANNEL_NAME)
    if anthropic is None:
        existing = await db.execute(
            select(Channel).where(Channel.kind == "llm", Channel.provider == "anthropic").limit(1)
        )
        if existing.scalar_one_or_none() is None:
            db.add(
                Channel(
                    name=ANTHROPIC_LLM_CHANNEL_NAME,
                    provider="anthropic",
                    kind="llm",
                    base_url="https://api.anthropic.com",
                    api_key="",
                    model_id="claude-sonnet-4-5",
                    upstream_model="claude-sonnet-4-5",
                    cost_per_second=0.0,
                    priority=50,
                    enabled=False,
                    remark="Anthropic Messages API（x-api-key）。超管改 Key 后启用。自定义网关请另建一条。",
                )
            )
    else:
        anthropic.kind = "llm"
        if not (anthropic.base_url or "").strip():
            anthropic.base_url = "https://api.anthropic.com"


async def _ensure_tts_channel(db: AsyncSession) -> None:
    settings = get_settings()
    key = (settings.aisrv_api_key or "").strip()
    base = settings.aisrv_url
    ch = await _get_by_name(db, TTS_CHANNEL_NAME)
    remark = (
        "本机 aisrv（travisvn/openai-edge-tts 镜像）。OpenAI /v1/audio/speech。"
        "钥匙来自 .env 的 AISRV_API_KEY，超管仍可改。"
    )
    if ch is None:
        db.add(
            Channel(
                name=TTS_CHANNEL_NAME,
                provider="openai",
                kind="tts",
                base_url=base,
                api_key=key,
                model_id="tts-1",
                upstream_model="tts-1",
                cost_per_second=0.0,
                priority=90,
                enabled=_looks_like_real_key(key),
                remark=remark,
            )
        )
        return
    ch.kind = "tts"
    ch.provider = "openai"
    ch.base_url = base
    ch.model_id = ch.model_id or "tts-1"
    ch.upstream_model = ch.upstream_model or "tts-1"
    ch.remark = remark
    if not (ch.api_key or "").strip() and _looks_like_real_key(key):
        ch.api_key = key
        ch.enabled = True


async def _ensure_image_channel(db: AsyncSession) -> None:
    ch = await _get_by_name(db, IMAGE_SIM_CHANNEL_NAME)
    remark = "本地占位图（本轮不接真模型，不扣费）。超管可见 kind=image。"
    if ch is None:
        db.add(
            Channel(
                name=IMAGE_SIM_CHANNEL_NAME,
                provider="mock",
                kind="image",
                base_url="",
                api_key="",
                model_id=IMAGE_SIM_MODEL_ID,
                upstream_model="local-simulate",
                cost_per_second=0.0,
                priority=95,
                enabled=True,
                remark=remark,
            )
        )
        return
    ch.kind = "image"
    ch.provider = "mock"
    ch.model_id = IMAGE_SIM_MODEL_ID
    ch.upstream_model = "local-simulate"
    ch.enabled = True
    ch.remark = remark


async def _heal_channels(db: AsyncSession) -> None:
    has_ark = await _any_enabled_ark(db)

    result = await db.execute(select(Channel))
    for ch in result.scalars().all():
        kind = (ch.kind or "").strip().lower()
        if kind not in {"video", "llm", "tts", "image"}:
            if ch.provider in {"openai", "anthropic"} and "tts" in (ch.model_id or "").lower():
                ch.kind = "tts"
            elif ch.provider in {"openai", "anthropic"}:
                ch.kind = "llm"
            else:
                ch.kind = "video"
        if ch.kind == "tts":
            continue
        if not _looks_like_real_key(ch.api_key):
            ch.api_key = ""

    result = await db.execute(select(Channel).where(Channel.provider == "mock"))
    for local in result.scalars().all():
        if (local.kind or "") == "image" or local.model_id == IMAGE_SIM_MODEL_ID:
            local.kind = "image"
            local.name = IMAGE_SIM_CHANNEL_NAME
            local.model_id = IMAGE_SIM_MODEL_ID
            local.upstream_model = "local-simulate"
            local.enabled = True
            continue
        if (local.kind or "") == "llm" or local.model_id == LLM_SIM_MODEL_ID:
            local.kind = "llm"
            local.name = LLM_SIM_CHANNEL_NAME
            local.model_id = LLM_SIM_MODEL_ID
            local.upstream_model = "local-simulate"
            local.enabled = True
            continue
        if local.model_id in {"seedance-lite", "seedance-2.5", *_LEGACY_LOCAL_MODEL_IDS}:
            local.model_id = LOCAL_SIM_MODEL_ID
        local.name = LOCAL_SIM_CHANNEL_NAME
        local.upstream_model = "local-simulate"
        local.priority = LOCAL_SIM_PRIORITY if has_ark else LOCAL_SIM_PRIORITY_OFFLINE
        local.enabled = True
        local.kind = "video"

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
