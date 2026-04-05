"""User models for authentication.

Defines the User model with role-based access control:
- Admin: Full access to all features
- Viewer: Read-only access to dashboard
- Public: Unauthenticated access (limited endpoints)
"""

from enum import Enum
from typing import Optional

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, String
from sqlalchemy.orm import DeclarativeBase


class UserRole(str, Enum):
    """User roles for access control."""

    ADMIN = "admin"
    VIEWER = "viewer"
    PUBLIC = "public"


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    """User model with role-based access.

    Extends FastAPI-Users base user table with:
    - role: User role (admin, viewer, public)
    - display_name: Optional display name

    Attributes:
        id: UUID primary key (inherited)
        email: User email (inherited)
        hashed_password: Password hash (inherited)
        is_active: Whether user is active (inherited)
        is_superuser: Whether user is superuser (inherited)
        is_verified: Whether email is verified (inherited)
        role: User role for access control
        display_name: Optional display name
    """

    __tablename__ = "users"

    role: str = Column(String(20), default=UserRole.VIEWER.value, nullable=False)
    display_name: Optional[str] = Column(String(100), nullable=True)
