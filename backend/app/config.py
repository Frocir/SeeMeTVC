from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_log = logging.getLogger("seemetvc.config")


def _local_secret_file(name: str) -> Path:
    return _BACKEND_DIR / "data" / name


def _persist_local_secret(name: str) -> str:
    """Dev-only: keep a stable secret on disk (gitignored), never bake one into source."""
    path = _local_secret_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    value = secrets.token_urlsafe(32)
    path.write_text(value + "\n", encoding="utf-8")
    _log.warning("未设置 JWT_SECRET，已生成并写入 %s（目录已 gitignore，勿提交）", path)
    return value


class Settings(BaseSettings):
    """Loads repo-root `.env` first, then `backend/.env` (overrides)."""

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./seemetvc.db"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "*"
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = ""
    balance_unit_label: str = "积分"
    max_parallel_jobs: int = 3
    upload_dir: str = "./data/uploads"
    ffmpeg_path: str = ""
    subtitle_font: str = ""
    public_api_base_url: str = ""
    public_asset_base_url: str = ""
    agnes_base_url: str = "https://api.agnes-ai.cn"
    agnes_upstream_model: str = "agnes-video-v2.0"
    agnes_min_gap_sec: float = 8.0
    agnes_429_base_sleep_sec: float = 25.0
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    local_proxy_host: str = "127.0.0.1"
    vectorengine_api_key: str = ""
    aisrv_api_key: str = ""
    aisrv_port: int = 5050
    aisrv_base_url: str = ""

    @model_validator(mode="after")
    def _resolve_jwt_secret(self) -> Settings:
        if (self.jwt_secret or "").strip():
            return self
        self.jwt_secret = _persist_local_secret(".jwt_secret")
        return self

    @property
    def aisrv_url(self) -> str:
        raw = (self.aisrv_base_url or "").strip().rstrip("/")
        if raw:
            return raw
        host = (self.local_proxy_host or "127.0.0.1").strip() or "127.0.0.1"
        return f"http://{host}:{int(self.aisrv_port or 5050)}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def cors_middleware_kwargs(self) -> dict:
        origins = [o for o in self.cors_origin_list if o != "*"]
        if not origins or "*" in self.cors_origin_list:
            return {
                "allow_origins": [],
                "allow_origin_regex": r"https?://[^/]+",
                "allow_credentials": True,
                "allow_methods": ["*"],
                "allow_headers": ["*"],
            }
        return {
            "allow_origins": origins,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
