import pytest

from app.core.database import Base
from app.models.system_settings import SystemSettings
from app.services.system_settings import load_runtime_settings, update_webdav_password


@pytest.mark.asyncio
async def test_webdav_password_is_encrypted_and_loaded(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_path = tmp_path / "settings.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        row = SystemSettings(id=1)
        update_webdav_password(row, "super-secret", False)
        session.add(row)
        await session.commit()
        assert row.webdav_password_encrypted
        assert "super-secret" not in row.webdav_password_encrypted

    async with Session() as session:
        runtime = await load_runtime_settings(session)
        assert runtime.webdav_password == "super-secret"

    await engine.dispose()
