from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin_users, auth, channels, uploads, videos, workflows
from app.api.uploads import uploads_root
from app.bootstrap import ensure_bootstrap_data
from app.config import get_settings
from app.db import Base, SessionLocal, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    uploads_root()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await ensure_bootstrap_data(db)
    yield
    await engine.dispose()


app = FastAPI(title="SeeMeTVC", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(videos.router, prefix="/api")
app.include_router(workflows.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(admin_users.router, prefix="/api")

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
    return {"ok": True, "service": "SeeMeTVC", "ffmpeg_ok": ffmpeg_ok, "ffmpeg": ffmpeg_hint}
