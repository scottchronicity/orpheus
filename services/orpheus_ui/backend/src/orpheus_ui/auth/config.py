"""Shared configuration for authentication.

Centralizes configuration to avoid duplication and circular imports.
"""

import os
import secrets

import structlog

logger = structlog.get_logger(__name__)

# Secret for JWT tokens - should be set via environment variable in production
# This is used by both the JWT strategy and the password reset/verification tokens
_default_secret = os.environ.get("ORPHEUS_UI_JWT_SECRET")

if _default_secret is None:
    # Generate a random secret for development - logs a warning
    _default_secret = secrets.token_urlsafe(32)
    logger.warning(
        "No ORPHEUS_UI_JWT_SECRET set - using random secret. "
        "Sessions will not persist across restarts. "
        "Set ORPHEUS_UI_JWT_SECRET environment variable in production."
    )

SECRET = _default_secret

# JWT token lifetime in seconds (24 hours by default)
JWT_LIFETIME_SECONDS = int(os.environ.get("ORPHEUS_UI_JWT_LIFETIME", "86400"))
