"""First-run initialization and admin seeding.

Creates an admin user if no users exist in the database.
Also migrates any users with invalid .local emails.
"""

import os
import uuid

from sqlalchemy import select

from orpheus_ui.auth.db import async_session_maker
from orpheus_ui.auth.models import User, UserRole

# The credentials the PROJECT ships with — literals, never environment reads.
# These are what a stolen copy of the repo already knows, so they are what
# ``seeded_defaults_in_use`` has to verify against the stored hashes.
# Note: Using example.com as it's a valid reserved domain for examples (RFC 2606)
# The .local TLD causes Pydantic email validation to fail
SHIPPED_ADMIN_EMAIL = "admin@orpheus.example.com"
SHIPPED_ADMIN_PASSWORD = "changeme"
SHIPPED_GUEST_EMAIL = "guest@orpheus.example.com"
SHIPPED_GUEST_PASSWORD = "guest"

# What SEEDING uses: the environment when an operator set it before the very
# first start, else the shipped literal. These must not drive the rotation
# check — seeding is guarded on an empty user table, so setting the vars later
# rotates nothing, and comparing the new value against the old hash would clear
# the warning on precisely the install that still answers to "changeme".
DEFAULT_ADMIN_EMAIL = os.environ.get("ORPHEUS_UI_ADMIN_EMAIL", SHIPPED_ADMIN_EMAIL)
DEFAULT_ADMIN_PASSWORD = os.environ.get("ORPHEUS_UI_ADMIN_PASSWORD", SHIPPED_ADMIN_PASSWORD)

# Default guest viewer credentials - read-only access
DEFAULT_GUEST_EMAIL = os.environ.get("ORPHEUS_UI_GUEST_EMAIL", SHIPPED_GUEST_EMAIL)
DEFAULT_GUEST_PASSWORD = os.environ.get("ORPHEUS_UI_GUEST_PASSWORD", SHIPPED_GUEST_PASSWORD)


def _accounts_to_check() -> list[tuple[str, str]]:
    """(email, shipped password) pairs the rotation check verifies.

    Both the configured and the shipped address for each account: an operator
    who set ``ORPHEUS_UI_ADMIN_EMAIL`` after the first start is still living
    with the seeded ``admin@orpheus.example.com``. Ordered and de-duplicated,
    so the common case (no email override) is exactly two lookups.
    """
    pairs = [
        (DEFAULT_ADMIN_EMAIL, SHIPPED_ADMIN_PASSWORD),
        (SHIPPED_ADMIN_EMAIL, SHIPPED_ADMIN_PASSWORD),
        (DEFAULT_GUEST_EMAIL, SHIPPED_GUEST_PASSWORD),
        (SHIPPED_GUEST_EMAIL, SHIPPED_GUEST_PASSWORD),
    ]
    return list(dict.fromkeys(pairs))


async def seeded_defaults_in_use() -> bool:
    """True when a seeded account still accepts a password this project ships.

    Verifies the shipped literals against the stored hashes, never the
    environment: the environment says what an operator *intended*, the hash
    says what actually logs in. The login page uses this to prompt for a
    rotation; it never reveals which account or what the password is.

    Errors resolve to False: a broken check must not paint a permanent scare
    banner on a correctly-configured install.
    """
    from fastapi_users.password import PasswordHelper
    from orpheus_common.logging import get_logger

    logger = get_logger(__name__)
    password_helper = PasswordHelper()

    try:
        async with async_session_maker() as session:
            for email, shipped_password in _accounts_to_check():
                result = await session.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()
                if user is None:
                    continue
                verified, _ = password_helper.verify_and_update(
                    shipped_password, user.hashed_password
                )
                if verified:
                    return True
    except Exception as exc:  # noqa: BLE001 - advisory check, never fatal
        logger.warning("Could not check seeded credentials", error=str(exc))
        return False

    return False


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
