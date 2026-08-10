from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default to SQLite for zero-deps local run; docker-compose overrides to Postgres.
    database_url: str = "sqlite+aiosqlite:///./seemetvc.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "admin123456"
    # Balance unit name shown to users (e.g. 积分)
    balance_unit_label: str = "积分"
    # Max concurrent pending/running video jobs per user
    max_parallel_jobs: int = 3
    # Local reference-image uploads directory (relative to backend cwd or absolute)
    upload_dir: str = "./data/uploads"
    # Base URL used when inlining relative /beauty assets for upstream (Vite/nginx)
    public_asset_base_url: str = "http://127.0.0.1:5173"
    # Optional Agnes AI free-tier key (from https://platform.agnes-ai.com).
    # Open-source Agnes/Pavo projects do NOT ship shared trial tokens; each install
    # registers its own free key. When set, bootstrap fills the Agnes channel.
    agnes_api_key: str = ""
    agnes_base_url: str = "https://api.agnes-ai.cn"
    agnes_upstream_model: str = "agnes-video-v2.0"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
