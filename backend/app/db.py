from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


if "sqlite" in (settings.database_url or ""):
    event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        if "sqlite" in (settings.database_url or ""):
            await session.execute(text("PRAGMA foreign_keys=ON"))
        yield session
