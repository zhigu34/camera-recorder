import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import BASE_DIR, settings


def _upgrade_database() -> None:
    backend_dir = BASE_DIR / "backend"
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


async def upgrade_database() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_upgrade_database)
