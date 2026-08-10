from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin_users, auth, channels, videos
from app.bootstrap import ensure_bootstrap_data
from app.config import get_settings
from app.db import Base, SessionLocal, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
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
app.include_router(admin_users.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "service": "SeeMeTVC"}
