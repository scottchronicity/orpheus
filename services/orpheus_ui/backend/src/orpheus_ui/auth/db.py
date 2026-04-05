"""Database configuration for authentication.

Sets up async SQLAlchemy with SQLite for user storage.
"""

import os
import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orpheus_ui.auth.models import Base, User

# SQLite database path - configurable via environment variable
# Default: /data/orpheus/users.db for persistence across installs
# Falls back to ./users.db for development
DEFAULT_DB_PATH = "/data/orpheus/users.db"
DEV_DB_PATH = "./users.db"

# Check if production path is available
# Priority: 1) /data/orpheus exists and writable, 2) /data exists and writable, 3) use dev path
if os.path.exists("/data/orpheus") and os.access("/data/orpheus", os.W_OK):
    _default_path = DEFAULT_DB_PATH
elif os.path.exists("/data") and os.access("/data", os.W_OK):
    # /data exists, we can create /data/orpheus
    _default_path = DEFAULT_DB_PATH
else:
    _default_path = DEV_DB_PATH

DATABASE_URL = os.environ.get("ORPHEUS_UI_DATABASE_URL", f"sqlite+aiosqlite:///{_default_path}")

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
