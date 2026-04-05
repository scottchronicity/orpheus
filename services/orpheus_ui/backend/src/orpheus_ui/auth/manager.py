"""User manager for FastAPI-Users.

Handles user-related operations like password reset, verification, etc.
"""

import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin

from orpheus_ui.auth.config import SECRET
from orpheus_ui.auth.db import get_user_db
from orpheus_ui.auth.models import User


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """User manager for handling user operations."""

    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Optional[Request] = None) -> None:
        """Called after a user registers."""
        # Import logger here to avoid circular imports
        from orpheus_common.logging import get_logger

        logger = get_logger(__name__)
        logger.info("User registered", user_id=str(user.id), email=user.email, role=user.role)

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Called after a user requests password reset."""
        from orpheus_common.logging import get_logger

        logger = get_logger(__name__)
        logger.info(
            "Password reset requested", user_id=str(user.id), email=user.email, token=token[:8]
        )

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Called after a user requests email verification."""
        from orpheus_common.logging import get_logger

        logger = get_logger(__name__)
        logger.info(
            "Verification requested", user_id=str(user.id), email=user.email, token=token[:8]
        )


async def get_user_manager(user_db=Depends(get_user_db)):
    """Get the user manager instance."""
    yield UserManager(user_db)
