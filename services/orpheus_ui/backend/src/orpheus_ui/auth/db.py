"""Database configuration for authentication.

Sets up async SQLAlchemy with SQLite for user storage.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orpheus_ui.auth.models import Base, User

# The accounts database lives under the data root like every other persistent
# file. It used to probe /data/orpheus directly, so a station with a data root
# anywhere else silently kept its accounts in the source checkout.
LEGACY_DB_PATH = Path("/data/orpheus/users.db")
DEV_DB_PATH = Path("users.db")


def _data_root() -> Path | None:
    """The configured data root, or ``None`` when it cannot be resolved."""
    try:
        from orpheus_common.storage import get_data_root  # noqa: PLC0415

        return get_data_root()
    except Exception:  # noqa: BLE001 - no config/library -> fall through to the legacy paths
        return None


def _usable_dir(path: Path) -> bool:
    """True when ``path`` is a writable directory, creating it if we can."""
    if path.is_dir():
        return os.access(path, os.W_OK)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)


def resolve_db_path() -> Path:
    """Where the accounts database lives.

    An existing file always wins over a new location: rotating a station's
    data root must not silently strand the accounts (and the passwords) that
    were already seeded. Only when no database exists anywhere do we choose a
    home for a fresh one, and that home is the data root.
    """
    root = _data_root()

    # A seeded database under the configured root, or at the pre-data-root
    # location a station was installed with.
    if root is not None and (root / "users.db").exists():
        return root / "users.db"
    if LEGACY_DB_PATH.exists():
        return LEGACY_DB_PATH

    # Otherwise it belongs with the rest of the persistent data. A stray
    # users.db in the working directory is deliberately NOT preferred — that
    # is how accounts ended up living in the source checkout.
    if root is not None and _usable_dir(root):
        return root / "users.db"
    return DEV_DB_PATH


def resolve_database_url() -> str:
    """The SQLAlchemy URL for the accounts database.

    ``ORPHEUS_UI_DATABASE_URL`` overrides everything — the shipped systemd unit
    sets it, so a deployed station's location is explicit rather than inferred.
    """
    explicit = os.environ.get("ORPHEUS_UI_DATABASE_URL")
    if explicit:
        return explicit
    return f"sqlite+aiosqlite:///{resolve_db_path()}"


DATABASE_URL = resolve_database_url()

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables() -> None:
    """Create database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID], None]:
    """Get the SQLAlchemy user database."""
    yield SQLAlchemyUserDatabase[User, uuid.UUID](session, User)
