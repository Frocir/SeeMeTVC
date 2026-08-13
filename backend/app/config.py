from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Loads repo-root `.env` first, then `backend/.env` (overrides)."""

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./seemetvc.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "*"
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "admin123456"
    balance_unit_label: str = "积分"
    max_parallel_jobs: int = 3
    upload_dir: str = "./data/uploads"
    ffmpeg_path: str = ""
    public_api_base_url: str = ""
    public_asset_base_url: str = ""
    agnes_base_url: str = "https://api.agnes-ai.cn"
    agnes_upstream_model: str = "agnes-video-v2.0"
    agnes_min_gap_sec: float = 8.0
    agnes_429_base_sleep_sec: float = 25.0
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    local_proxy_host: str = "127.0.0.1"

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
