from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin_users, agent, asset_versions, auth, channels, ledger, uploads, videos, workflows
from app.api.uploads import uploads_root
from app.bootstrap import ensure_bootstrap_data
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.services.ledger import ensure_opening_balances
from app.services.migrate_projects import apply_schema_updates, migrate_project_space
from app.services.project_assets import fill_empty_covers


@asynccontextmanager
async def lifespan(_: FastAPI):
    uploads_root()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(apply_schema_updates)
    async with SessionLocal() as db:
        await ensure_bootstrap_data(db)
        await migrate_project_space(db)
        await fill_empty_covers(db)
        await db.commit()
    async with SessionLocal() as db:
        await ensure_opening_balances(db)
        await db.commit()
    yield
    await engine.dispose()


app = FastAPI(title="GlamPilot", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    **settings.cors_middleware_kwargs(),
)

app.include_router(auth.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(videos.router, prefix="/api")
app.include_router(workflows.router, prefix="/api")
app.include_router(asset_versions.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(admin_users.router, prefix="/api")
app.include_router(ledger.router, prefix="/api")

# Local reference images (UUID filenames); preview in UI via <img src="/uploads/...">
app.mount("/uploads", StaticFiles(directory=str(uploads_root())), name="uploads")


@app.get("/api/health")
async def health() -> dict:
    ffmpeg_ok = False
    ffmpeg_hint = ""
    try:
        from pathlib import Path

        from app.services.media_ops import _ffmpeg_bin

        # Expose basename only — never leak absolute install paths
        ffmpeg_hint = Path(_ffmpeg_bin()).name
        ffmpeg_ok = True
    except Exception as exc:  # noqa: BLE001
        ffmpeg_hint = str(exc)[:200]
    return {"ok": True, "service": "GlamPilot", "ffmpeg_ok": ffmpeg_ok, "ffmpeg": ffmpeg_hint}
