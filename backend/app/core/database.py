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
    # Import models before create_all so SQLAlchemy sees every table.
    import app.models  # noqa: F401

    if settings.database_url.startswith("sqlite"):
        # journal_mode persists in the database; run it outside create_all's
        # transaction to avoid SQLite's journal-mode transaction restrictions.
        async with engine.connect() as connection:
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.commit()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        if settings.database_url.startswith("sqlite"):
            await session.execute(text("PRAGMA foreign_keys=ON"))
        yield session
