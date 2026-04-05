"""Authentication backend configuration.

Configures JWT authentication for the FastAPI-Users system.
"""

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from orpheus_ui.auth.config import JWT_LIFETIME_SECONDS, SECRET
from orpheus_ui.auth.manager import get_user_manager
from orpheus_ui.auth.models import User

# Bearer transport for JWT tokens
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    """Get JWT strategy with configured secret and lifetime."""
    return JWTStrategy(secret=SECRET, lifetime_seconds=JWT_LIFETIME_SECONDS)


# Authentication backend configuration
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# FastAPI-Users instance
fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)

# Dependency for getting the current active user
current_active_user = fastapi_users.current_user(active=True)

# Dependency for getting the current superuser
current_superuser = fastapi_users.current_user(active=True, superuser=True)


async def current_user_or_token_param(
    request: Request,
    token: Optional[str] = Query(None),
    user_manager=Depends(get_user_manager),
) -> User:
    """Authenticate via Bearer header OR ?token= query param.

    HTML media elements (<video>, <audio>) cannot send Authorization
    headers, so this dependency also accepts the JWT as a query parameter.
    Used only on media-file endpoints.
    """
    # Try Bearer header first via standard flow
    auth_header = request.headers.get("authorization", "")
    jwt_token = None
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:]
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    strategy = get_jwt_strategy()
    user = await strategy.read_token(jwt_token, user_manager)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def require_role(required_role: str):
    """Dependency factory for requiring a specific role.

    Args:
        required_role: The role required to access the endpoint.

    Returns:
        Dependency function that validates the user has the required role.

    Example:
        @app.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_role("admin"))):
            return {"message": "Admin access granted"}
    """

    async def _require_role(user: User = Depends(current_active_user)) -> User:
        # Superusers always have access
        if user.is_superuser:
            return user

        # Check if user has the required role
        if user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {required_role}",
            )
        return user

    return _require_role
