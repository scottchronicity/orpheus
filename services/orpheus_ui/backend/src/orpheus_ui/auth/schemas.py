"""User management and authentication schemas.

Defines Pydantic schemas for user creation, reading, and updates.
"""

import uuid
from typing import Optional

from fastapi_users import schemas
from pydantic import Field

from orpheus_ui.auth.models import UserRole


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Schema for reading user data.

    Includes the role and display_name fields.
    """

    role: str = Field(default=UserRole.VIEWER.value, description="User role")
    display_name: Optional[str] = Field(default=None, description="Display name")


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a new user.

    Includes optional role and display_name fields.
    """

    role: str = Field(default=UserRole.VIEWER.value, description="User role")
    display_name: Optional[str] = Field(default=None, description="Display name")


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating a user.

    All fields are optional for partial updates.
    """

    role: Optional[str] = Field(default=None, description="User role")
    display_name: Optional[str] = Field(default=None, description="Display name")
