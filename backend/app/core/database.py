from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    if settings.database_url.startswith("sqlite"):
        # journal_mode persists in the database. Schema creation/evolution is
        # handled by Alembic before this function is called.
        async with engine.connect() as connection:
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.commit()


async def close_db() -> None:
    await engine.dispose()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        if settings.database_url.startswith("sqlite"):
            await session.execute(text("PRAGMA foreign_keys=ON"))
        yield session
