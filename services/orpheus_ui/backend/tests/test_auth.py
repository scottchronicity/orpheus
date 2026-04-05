"""Tests for authentication module."""

import uuid

import pytest


class TestUserModels:
    """Tests for user models."""

    def test_user_role_enum(self):
        """Test UserRole enum values."""
        from orpheus_ui.auth.models import UserRole

        assert UserRole.ADMIN.value == "admin"
        assert UserRole.VIEWER.value == "viewer"
        assert UserRole.PUBLIC.value == "public"

    def test_user_model_import(self):
        """Test User model can be imported from fastapi_users_db_sqlalchemy."""
        from orpheus_ui.auth.models import User

        # Verify User inherits from the correct base
        assert hasattr(User, "__tablename__")
        assert User.__tablename__ == "users"
        assert hasattr(User, "role")
        assert hasattr(User, "display_name")


class TestUserSchemas:
    """Tests for user schemas."""

    def test_user_read_schema(self):
        """Test UserRead schema."""
        from orpheus_ui.auth.schemas import UserRead

        user = UserRead(
            id=uuid.uuid4(),
            email="test@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            role="viewer",
            display_name="Test User",
        )
        assert user.email == "test@example.com"
        assert user.role == "viewer"
        assert user.display_name == "Test User"

    def test_user_create_schema(self):
        """Test UserCreate schema."""
        from orpheus_ui.auth.schemas import UserCreate

        user = UserCreate(
            email="new@example.com",
            password="securepassword123",
            role="admin",
            display_name="New Admin",
        )
        assert user.email == "new@example.com"
        assert user.password == "securepassword123"
        assert user.role == "admin"

    def test_user_create_default_role(self):
        """Test UserCreate default role is viewer."""
        from orpheus_ui.auth.schemas import UserCreate

        user = UserCreate(
            email="viewer@example.com",
            password="password123",
        )
        assert user.role == "viewer"


class TestAuthBackend:
    """Tests for authentication backend."""

    def test_jwt_strategy_config(self):
        """Test JWT strategy configuration."""
        from orpheus_ui.auth.backend import get_jwt_strategy

        strategy = get_jwt_strategy()
        assert strategy is not None

    def test_auth_backend_config(self):
        """Test authentication backend configuration."""
        from orpheus_ui.auth.backend import auth_backend

        assert auth_backend.name == "jwt"

    def test_fastapi_users_instance(self):
        """Test FastAPIUsers instance is configured."""
        from orpheus_ui.auth.backend import fastapi_users

        assert fastapi_users is not None

    def test_require_role_factory(self):
        """Test require_role dependency factory."""
        from orpheus_ui.auth.backend import require_role

        admin_dep = require_role("admin")
        viewer_dep = require_role("viewer")

        # Both should be callable dependencies
        assert callable(admin_dep)
        assert callable(viewer_dep)


class TestDatabaseSetup:
    """Tests for database setup and user database."""

    def test_sqlalchemy_user_database_import(self):
        """Test SQLAlchemyUserDatabase is imported from correct package."""
        from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase as ExpectedClass

        from orpheus_ui.auth.db import SQLAlchemyUserDatabase

        assert SQLAlchemyUserDatabase is ExpectedClass

    @pytest.mark.asyncio
    async def test_create_db_and_tables(self):
        """Test database tables can be created."""
        import os
        import tempfile

        # Use a temporary database for testing
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            test_db_path = f.name

        try:
            # Temporarily override DATABASE_URL
            original_url = os.environ.get("ORPHEUS_UI_DATABASE_URL")
            os.environ["ORPHEUS_UI_DATABASE_URL"] = f"sqlite+aiosqlite:///{test_db_path}"

            # Re-import to pick up new DATABASE_URL
            import importlib

            from orpheus_ui.auth import db

            importlib.reload(db)

            # Create tables
            await db.create_db_and_tables()

            # Verify the database file was created
            assert os.path.exists(test_db_path)

        finally:
            # Dispose of the async engine to prevent hanging
            from orpheus_ui.auth import db

            await db.engine.dispose()

            # Cleanup
            if original_url:
                os.environ["ORPHEUS_UI_DATABASE_URL"] = original_url
            elif "ORPHEUS_UI_DATABASE_URL" in os.environ:
                del os.environ["ORPHEUS_UI_DATABASE_URL"]

            if os.path.exists(test_db_path):
                os.unlink(test_db_path)


class TestLoginFlow:
    """Integration tests for the full login flow."""

    @pytest.mark.asyncio
    async def test_login_and_get_me(self, mock_config):
        """Test full login flow: login -> get /users/me.

        This test reproduces the exact flow a user experiences:
        1. POST /auth/jwt/login with credentials
        2. GET /users/me with the returned JWT token

        This caught a bug where .local TLD emails failed Pydantic validation.
        """
        import os
        import tempfile

        # Create isolated test database
        test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        test_db_path = test_db.name
        test_db.close()

        original_url = os.environ.get("ORPHEUS_UI_DATABASE_URL")
        os.environ["ORPHEUS_UI_DATABASE_URL"] = f"sqlite+aiosqlite:///{test_db_path}"

        try:
            # Re-import with new database URL
            import importlib

            from orpheus_ui.auth import db

            importlib.reload(db)

            # Initialize database
            await db.create_db_and_tables()

            # Seed admin user
            from orpheus_ui.auth.seed import seed_admin_user

            await seed_admin_user()

            # Test the login flow
            from httpx import ASGITransport, AsyncClient

            from orpheus_ui.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Step 1: Login
                login_response = await client.post(
                    "/auth/jwt/login",
                    data={"username": "admin@orpheus.example.com", "password": "changeme"},
                )
                assert login_response.status_code == 200, f"Login failed: {login_response.text}"

                token = login_response.json().get("access_token")
                assert token, "No access token in response"

                # Step 2: Get /users/me - this was failing with 500 error
                me_response = await client.get(
                    "/users/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert me_response.status_code == 200, f"/users/me failed: {me_response.text}"

                user_data = me_response.json()
                assert user_data["email"] == "admin@orpheus.example.com"
                assert user_data["role"] == "admin"
                assert user_data["is_superuser"] is True

        finally:
            # Dispose of the async engine to prevent hanging
            from orpheus_ui.auth import db

            await db.engine.dispose()

            # Cleanup
            if original_url:
                os.environ["ORPHEUS_UI_DATABASE_URL"] = original_url
            elif "ORPHEUS_UI_DATABASE_URL" in os.environ:
                del os.environ["ORPHEUS_UI_DATABASE_URL"]

            if os.path.exists(test_db_path):
                os.unlink(test_db_path)

    def test_default_admin_email_uses_valid_tld(self):
        """Verify the default admin email doesn't use .local TLD.

        The .local TLD fails Pydantic's email validation, causing 500 errors.
        """
        from orpheus_ui.auth.seed import DEFAULT_ADMIN_EMAIL

        # Must not use .local TLD
        assert not DEFAULT_ADMIN_EMAIL.endswith(".local"), (
            f"Default email {DEFAULT_ADMIN_EMAIL} uses .local TLD which fails Pydantic validation"
        )

        # Should use a valid domain
        assert "@" in DEFAULT_ADMIN_EMAIL
        assert "." in DEFAULT_ADMIN_EMAIL.split("@")[1]
