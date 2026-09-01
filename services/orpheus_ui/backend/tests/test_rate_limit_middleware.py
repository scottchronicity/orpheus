"""Per-client API rate-limit middleware (portal prerequisite N2).

Off unless registered (main.py registers it only when ``ui.rate_limit_enabled``);
per-client sliding window over the repo's existing ``CircuitBreaker`` with
``default_limit``; 429 + Retry-After when tripped; static assets and the SPA
shell never gated. Sign-in carries a second, failure-keyed budget.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from orpheus_common.safety import CircuitBreaker

from orpheus_ui.middleware import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_FAILURE_WINDOW_SECONDS,
    build_rate_limit_middleware,
)


def _build_app(tmp_path, *, requests=2, window_seconds=60, login_failures=LOGIN_FAILURE_LIMIT):
    breaker = CircuitBreaker(
        {}, db_path=tmp_path / "rl.db", default_limit=(requests, window_seconds)
    )
    login_breaker = CircuitBreaker(
        {},
        db_path=tmp_path / "login-rl.db",
        default_limit=(login_failures, LOGIN_FAILURE_WINDOW_SECONDS),
    )
    app = FastAPI()
    app.middleware("http")(
        build_rate_limit_middleware(
            requests=requests,
            window_seconds=window_seconds,
            breaker=breaker,
            login_breaker=login_breaker,
        )
    )

    @app.get("/api/data")
    def data():
        return {"ok": True}

    @app.get("/static-thing")
    def static_thing():
        return {"ok": True}

    @app.post("/auth/jwt/login")
    def login(password: str = "wrong"):
        if password != "right":
            raise HTTPException(status_code=400, detail="LOGIN_BAD_CREDENTIALS")
        return {"access_token": "a-jwt"}

    @app.post("/auth/guest-login")
    def guest_login():
        return {"access_token": "a-jwt"}

    return app


class TestRateLimitMiddleware:
    def test_within_limit_passes(self, tmp_path):
        client = TestClient(_build_app(tmp_path))
        assert client.get("/api/data").status_code == 200
        assert client.get("/api/data").status_code == 200

    def test_over_limit_gets_429_with_retry_after(self, tmp_path):
        client = TestClient(_build_app(tmp_path))
        client.get("/api/data")
        client.get("/api/data")
        resp = client.get("/api/data")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "60"
        assert resp.json()["detail"] == "Rate limit exceeded"

    def test_non_api_paths_never_gated(self, tmp_path):
        client = TestClient(_build_app(tmp_path))
        for _ in range(5):
            assert client.get("/static-thing").status_code == 200

    def test_auth_paths_are_gated_too(self, tmp_path):
        """Authentication lives at /auth/, not /api/. Scoping the limiter to
        /api/ exempted the one endpoint a limiter exists for."""
        client = TestClient(_build_app(tmp_path, requests=2))
        assert client.post("/auth/guest-login").status_code == 200
        assert client.post("/auth/guest-login").status_code == 200
        assert client.post("/auth/guest-login").status_code == 429


class TestLoginFailureBudget:
    """Password guessing gets a tighter budget than ordinary API traffic, and
    it is spent on failures so a legitimate sign-in never trips it."""

    def test_failed_logins_trip_well_inside_the_api_budget(self, tmp_path):
        client = TestClient(_build_app(tmp_path, requests=1000, login_failures=3))
        for _ in range(3):
            assert client.post("/auth/jwt/login?password=wrong").status_code == 400

        resp = client.post("/auth/jwt/login?password=wrong")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == str(LOGIN_FAILURE_WINDOW_SECONDS)

    def test_successful_logins_never_consume_the_budget(self, tmp_path):
        """A signed-in operator reloading the page must not lock the box out."""
        client = TestClient(_build_app(tmp_path, requests=1000, login_failures=2))
        for _ in range(10):
            assert client.post("/auth/jwt/login?password=right").status_code == 200

    def test_a_mistype_still_leaves_room_to_sign_in(self, tmp_path):
        client = TestClient(_build_app(tmp_path, requests=1000, login_failures=3))
        assert client.post("/auth/jwt/login?password=wrong").status_code == 400
        assert client.post("/auth/jwt/login?password=right").status_code == 200

    def test_a_junk_bearer_token_does_not_buy_a_fresh_budget(self, tmp_path):
        """The shared budget keys on the Authorization header when there is one,
        so keying sign-ins the same way would let a guesser rotate junk tokens
        for an unlimited supply of buckets. Sign-ins key on the IP."""
        client = TestClient(_build_app(tmp_path, requests=1000, login_failures=1))
        a = {"Authorization": "Bearer junk-a"}
        b = {"Authorization": "Bearer junk-b"}
        assert client.post("/auth/jwt/login?password=wrong", headers=a).status_code == 400
        assert client.post("/auth/jwt/login?password=wrong", headers=b).status_code == 429
        assert client.post("/auth/jwt/login?password=wrong").status_code == 429

    def test_api_traffic_does_not_spend_the_login_budget(self, tmp_path):
        client = TestClient(_build_app(tmp_path, requests=1000, login_failures=1))
        for _ in range(20):
            client.get("/api/data")
        assert client.post("/auth/jwt/login?password=right").status_code == 200

    @pytest.mark.parametrize(
        "limit,window",
        [(LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS)],
    )
    def test_the_shipped_budget_is_tight_enough_to_matter(self, limit, window):
        """Five guesses per five minutes per client: a mistyping human is fine,
        a guesser against a published default password is not."""
        assert limit <= 10
        assert window >= 60

    def test_clients_are_isolated_by_token(self, tmp_path):
        client = TestClient(_build_app(tmp_path))
        a = {"Authorization": "Bearer token-a"}
        b = {"Authorization": "Bearer token-b"}
        client.get("/api/data", headers=a)
        client.get("/api/data", headers=a)
        assert client.get("/api/data", headers=a).status_code == 429  # A tripped
        assert client.get("/api/data", headers=b).status_code == 200  # B unaffected

    def test_options_preflights_never_count_against_the_limit(self, tmp_path):
        """CORS preflights are browser-generated and unauthenticated (IP bucket)
        — they must neither consume the budget nor be 429'd themselves."""
        client = TestClient(_build_app(tmp_path, requests=2))
        for _ in range(5):
            client.options("/api/data")  # never gated, never counted
        # The budget is still fully available for real requests.
        assert client.get("/api/data").status_code == 200
        assert client.get("/api/data").status_code == 200
        assert client.get("/api/data").status_code == 429

    def test_429_passes_back_through_cors(self, tmp_path):
        """main.py registers the limiter BEFORE CORSMiddleware so CORS wraps it:
        a 429 must carry the CORS headers or the browser hides it from the
        frontend's error handling. Pins the wrapped-ordering behavior."""
        from fastapi.middleware.cors import CORSMiddleware

        app = _build_app(tmp_path, requests=1)
        app.add_middleware(  # mirrors main.py: CORS added after the limiter
            CORSMiddleware, allow_origins=["http://localhost:5173"]
        )
        client = TestClient(app)
        origin = {"Origin": "http://localhost:5173"}
        assert client.get("/api/data", headers=origin).status_code == 200
        resp = client.get("/api/data", headers=origin)
        assert resp.status_code == 429
        assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


class TestLoginRateLimitAlwaysOn:
    """The standalone login limiter is registered regardless of
    ``ui.rate_limit_enabled`` — brute-force protection is not the same
    decision as API quotas. These build an app with ONLY that middleware,
    the default-install shape."""

    def _login_only_app(self, tmp_path, *, login_failures=LOGIN_FAILURE_LIMIT):
        from orpheus_ui.middleware import build_login_rate_limit_middleware

        login_breaker = CircuitBreaker(
            {},
            db_path=tmp_path / "login-only.db",
            default_limit=(login_failures, LOGIN_FAILURE_WINDOW_SECONDS),
        )
        app = FastAPI()
        app.middleware("http")(
            build_login_rate_limit_middleware(login_breaker=login_breaker)
        )

        @app.get("/api/data")
        def data():
            return {"ok": True}

        @app.post("/auth/jwt/login")
        def login(password: str = "wrong"):
            if password != "right":
                raise HTTPException(status_code=400, detail="LOGIN_BAD_CREDENTIALS")
            return {"access_token": "a-jwt"}

        @app.post("/auth/guest-login")
        def guest_login():
            return {"access_token": "a-jwt"}

        return app

    def test_brute_force_blocked_with_general_limiter_off(self, tmp_path):
        client = TestClient(self._login_only_app(tmp_path, login_failures=3))
        for _ in range(3):
            assert client.post("/auth/jwt/login?password=wrong").status_code == 400
        resp = client.post("/auth/jwt/login?password=wrong")
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == str(LOGIN_FAILURE_WINDOW_SECONDS)

    def test_successful_login_never_consumes_budget(self, tmp_path):
        client = TestClient(self._login_only_app(tmp_path, login_failures=2))
        for _ in range(10):
            assert client.post("/auth/jwt/login?password=right").status_code == 200

    def test_guest_login_is_covered(self, tmp_path):
        # guest-login always returns 200 here, so it should never trip on
        # success — but a 4xx guest-login (disabled/absent account) counts.
        client = TestClient(self._login_only_app(tmp_path, login_failures=2))
        for _ in range(10):
            assert client.post("/auth/guest-login").status_code == 200

    def test_non_login_traffic_untouched(self, tmp_path):
        client = TestClient(self._login_only_app(tmp_path, login_failures=1))
        for _ in range(20):
            assert client.get("/api/data").status_code == 200

    def test_general_limiter_defers_login_when_not_owner(self, tmp_path):
        """With owns_login=False the general limiter must not charge the login
        budget, so the standalone one is the single counter (no double-count)."""
        login_breaker = CircuitBreaker(
            {},
            db_path=tmp_path / "shared-login.db",
            default_limit=(3, LOGIN_FAILURE_WINDOW_SECONDS),
        )
        general = build_rate_limit_middleware(
            requests=1000,
            window_seconds=60,
            breaker=CircuitBreaker(
                {}, db_path=tmp_path / "api.db", default_limit=(1000, 60)
            ),
            login_breaker=login_breaker,
            owns_login=False,
        )
        app = FastAPI()
        app.middleware("http")(general)

        @app.post("/auth/jwt/login")
        def login(password: str = "wrong"):
            if password != "right":
                raise HTTPException(status_code=400, detail="bad")
            return {"access_token": "a-jwt"}

        client = TestClient(app)
        # General limiter owns_login=False: it must NOT record failures, so the
        # login_breaker (limit 3) never trips through this middleware alone.
        for _ in range(6):
            assert client.post("/auth/jwt/login?password=wrong").status_code == 400
