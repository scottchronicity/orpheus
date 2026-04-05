"""First-run initialization and admin seeding.

Creates an admin user if no users exist in the database.
Also migrates any users with invalid .local emails.
"""

import os
import uuid

from sqlalchemy import select

from orpheus_ui.auth.db import async_session_maker
from orpheus_ui.auth.models import User, UserRole

# Default admin credentials - should be changed after first login
# Note: Using example.com as it's a valid reserved domain for examples (RFC 2606)
# The .local TLD causes Pydantic email validation to fail
DEFAULT_ADMIN_EMAIL = os.environ.get("ORPHEUS_UI_ADMIN_EMAIL", "admin@orpheus.example.com")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ORPHEUS_UI_ADMIN_PASSWORD", "changeme")

# Default guest viewer credentials - read-only access
DEFAULT_GUEST_EMAIL = os.environ.get("ORPHEUS_UI_GUEST_EMAIL", "guest@orpheus.example.com")
DEFAULT_GUEST_PASSWORD = os.environ.get("ORPHEUS_UI_GUEST_PASSWORD", "guest")


async def migrate_local_emails() -> int:
    """Migrate any users with .local emails to .example.com.

    The .local TLD is rejected by Pydantic's email validator, causing 500 errors.
    This migration fixes existing databases created before the fix.

    Returns:
        Number of users migrated.
    """
    from orpheus_common.logging import get_logger

    logger = get_logger(__name__)

    async with async_session_maker() as session:
        # Find users with .local emails
        result = await session.execute(select(User).where(User.email.like("%@%.local")))
        users_to_migrate = result.scalars().all()

        if not users_to_migrate:
            return 0

        migrated = 0
        for user in users_to_migrate:
            old_email = user.email
            # Replace .local with .example.com
            new_email = old_email.replace(".local", ".example.com")
            user.email = new_email
            migrated += 1
            logger.info(
                "Migrated user email from .local to .example.com",
                old_email=old_email,
                new_email=new_email,
                user_id=str(user.id),
            )

        await session.commit()
        logger.warning(
            f"Migrated {migrated} user(s) with .local emails. "
            "The .local TLD is rejected by Pydantic's email validator."
        )
        return migrated


async def seed_admin_user() -> bool:
    """Create default users if no users exist.

    Creates two default users on first run:
    - Admin user (admin@orpheus.example.com / changeme) with full access
    - Guest user (guest@orpheus.example.com / guest) with read-only access

    Also runs migration for any .local emails.

    Returns:
        True if users were created, False if users already exist.
    """
    from fastapi_users.password import PasswordHelper
    from orpheus_common.logging import get_logger

    logger = get_logger(__name__)
    password_helper = PasswordHelper()

    # First, migrate any .local emails
    await migrate_local_emails()

    async with async_session_maker() as session:
        # Check if any users exist
        result = await session.execute(select(User).limit(1))
        existing_user = result.scalar_one_or_none()

        if existing_user is not None:
            logger.debug("Users exist, skipping default user seed")
            return False

        # Create admin user
        admin_password = password_helper.hash(DEFAULT_ADMIN_PASSWORD)
        admin_user = User(
            id=uuid.uuid4(),
            email=DEFAULT_ADMIN_EMAIL,
            hashed_password=admin_password,
            is_active=True,
            is_superuser=True,
            is_verified=True,
            role=UserRole.ADMIN.value,
            display_name="Admin",
        )

        # Create guest user (read-only viewer)
        guest_password = password_helper.hash(DEFAULT_GUEST_PASSWORD)
        guest_user = User(
            id=uuid.uuid4(),
            email=DEFAULT_GUEST_EMAIL,
            hashed_password=guest_password,
            is_active=True,
            is_superuser=False,
            is_verified=True,
            role=UserRole.VIEWER.value,
            display_name="Guest",
        )

        session.add(admin_user)
        session.add(guest_user)
        await session.commit()

        logger.info(
            "First-run: Default users created",
            admin_email=DEFAULT_ADMIN_EMAIL,
            guest_email=DEFAULT_GUEST_EMAIL,
        )
        logger.warning("SECURITY: Please change the default admin password after first login!")

        return True
