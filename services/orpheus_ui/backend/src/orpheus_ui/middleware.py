"""Request-timing + per-client rate-limit middleware for the UI backend.

Timing: the UI was reported as sluggish, but the backend had zero server-side
timing instrumentation — no way to tell from logs or the Diagnostics page whether
``/api/entities``, a history endpoint, or DB contention was the culprit, nor to
confirm a fix worked. This adds the minimal, zero-dead-weight signal: every
response carries an ``X-Response-Time-ms`` header, and any request slower than
``SLOW_REQUEST_MS`` emits a structured warning through ``get_logger`` so it lands
in ``journalctl`` next to the agent logs.

Rate limiting: ``build_rate_limit_middleware`` is the portal-prerequisite N2
per-client API limiter, registered by ``main.py`` only when
``ui.rate_limit_enabled`` (default off) — see its docstring for the policy.

Kept as standalone ``dispatch`` functions (registered in ``main.py``) so they are
unit-testable without standing up the full app/lifespan. A configurable
threshold + a rolling p50/p95 ``/api/diagnostics/perf`` endpoint for a Diagnostics
chart are deliberately left as follow-ups (tracked in the backlog).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Awaitable, Callable, Optional

from orpheus_common.logging import get_logger
from orpheus_common.safety import CircuitBreaker
from orpheus_common.storage import get_data_root
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = get_logger(__name__)

# A request slower than this logs a structured warning. This is an operability
# signal (when should ops look?), not a product/model threshold — 1s is a
# generous bar for a local edge API; anything above it is worth a log line.
SLOW_REQUEST_MS = 1000.0

# Paths the limiter covers. ``/auth/`` is where password guessing happens
# (``/auth/jwt/login``), so leaving it out — as the first cut did — exempted the
# one endpoint a limiter exists for. ``/users/`` carries the account routes.
_LIMITED_PREFIXES = ("/api/", "/auth/", "/users/")

# Sign-in attempts get a second, much tighter budget on TOP of the shared one,
# counted per failure rather than per request: a human who mistypes a password
# twice must not be locked out, while a guesser gets five tries per five
# minutes per IP instead of the general budget's hundreds. Deliberately not a
# config knob — an operator who turns the limiter on should not have to reason
# about credential-stuffing arithmetic to get a working default.
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 300

# Auth routes that verify a credential. A failure here is a guess; a failure on
# any other /auth/ route (an expired token on logout, say) is not.
_LOGIN_PATHS = ("/auth/jwt/login", "/auth/guest-login")


def _client_key(request: Request) -> str:
    """A stable per-client identity for rate limiting. Prefer the (hashed)
    Authorization bearer token — one browser session/API client each — falling
    back to the client IP for unauthenticated requests. Hashing keeps tokens
    out of the breaker DB and log lines."""
    auth = request.headers.get("authorization")
    if auth:
        return "tok:" + hashlib.sha256(auth.encode()).hexdigest()[:16]
    return _ip_key(request)


def _ip_key(request: Request) -> str:
    """The client IP, ignoring any Authorization header.

    The login budget must key on this and not on ``_client_key``: a guesser has
    no session, but nothing stops them sending a different junk bearer token
    with every attempt, which would hand them a fresh bucket each time.
    """
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _is_login_attempt(request: Request) -> bool:
    """True for a POST that submits a credential (the guessable surface)."""
    return request.method == "POST" and request.url.path in _LOGIN_PATHS


def build_rate_limit_middleware(
    *,
    requests: int,
    window_seconds: int,
    breaker: Optional[CircuitBreaker] = None,
    login_breaker: Optional[CircuitBreaker] = None,
    owns_login: bool = True,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Per-client API rate limiting (portal prerequisite N2), OFF unless
    registered — main.py only registers this when ``ui.rate_limit_enabled``.

    Wraps ``CircuitBreaker.record_if_allowed`` (the repo's existing sliding-
    window limiter; see the portal N2 design) with ``default_limit`` so every
    dynamic client key shares one configured policy. Its SQLite ledger lives in
    its OWN file (never the detections DB). ``/api/``, ``/auth/`` and
    ``/users/`` are limited — static assets and the SPA shell stay free. A
    tripped client gets 429 + Retry-After; the trip logs once per edge via the
    breaker's on_trip.

    Sign-in POSTs carry a second, tighter budget counted per FAILURE
    (``LOGIN_FAILURE_LIMIT`` per ``LOGIN_FAILURE_WINDOW_SECONDS``, keyed on the
    IP since these calls are unauthenticated). Without it the shared budget is
    hundreds of guesses a window against an account whose shipped password is
    public, and ``/api/config`` tells the caller whether that password still
    works."""
    cb = breaker or CircuitBreaker(
        {},
        db_path=get_data_root() / "ui_rate_limit.db",
        default_limit=(requests, window_seconds),
        on_trip=lambda status: logger.warning(
            "API rate limit tripped",
            client=status.action,
            count=status.count,
            limit=status.limit,
        ),
    )
    # Its OWN ledger file, not the shared one: CircuitBreaker's periodic sweep
    # prunes every action older than ITS widest window, so co-tenanting the two
    # would let the shorter API window quietly delete login-failure history.
    login_cb = login_breaker or CircuitBreaker(
        {},
        db_path=get_data_root() / "ui_login_rate_limit.db",
        default_limit=(LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS),
        on_trip=lambda status: logger.warning(
            "Sign-in rate limit tripped",
            client=status.action,
            count=status.count,
            limit=status.limit,
        ),
    )

    def _too_many_requests(retry_after: int) -> JSONResponse:
        return JSONResponse(
            {"detail": "Rate limit exceeded"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    async def rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith(_LIMITED_PREFIXES):
            return await call_next(request)
        # CORS preflights are browser-generated, unauthenticated (keyed to the
        # IP bucket, not the token), and precede many real requests — counting
        # them would double-charge every cross-origin call and could 429 the
        # preflight itself, which the browser surfaces as an opaque CORS error.
        if request.method == "OPTIONS":
            return await call_next(request)
        # record_if_allowed is a synchronous SQLite write transaction (BEGIN
        # IMMEDIATE + COUNT/INSERT/DELETE). Run it in a worker thread — inline it
        # would serialize EVERY concurrent /api request through one write lock ON
        # the event loop, converting the protection into a server-wide stall.
        key = _client_key(request)
        if not await asyncio.to_thread(cb.record_if_allowed, key):
            return _too_many_requests(window_seconds)

        # When the always-on login middleware owns credential-guessing, don't
        # also charge it here — it would double-count every failed attempt.
        if not owns_login or not _is_login_attempt(request):
            return await call_next(request)

        # Failure-keyed: check before, record only after a rejected credential,
        # so a legitimate sign-in (and a mistype or two) never consumes it.
        login_key = f"login:{_ip_key(request)}"
        if not await asyncio.to_thread(login_cb.check, login_key):
            return _too_many_requests(LOGIN_FAILURE_WINDOW_SECONDS)

        response = await call_next(request)
        if response.status_code >= 400:
            await asyncio.to_thread(login_cb.record, login_key)
        return response

    return rate_limit_middleware


def build_login_rate_limit_middleware(
    *,
    login_breaker: Optional[CircuitBreaker] = None,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Credential-guessing protection for the sign-in routes, registered
    ALWAYS — independent of ``ui.rate_limit_enabled``.

    The general API limiter is an opt-in quota an operator turns on for an
    exposed instance. Brute-force protection is a different decision: the
    shipped admin password is public, ``/api/config`` advertises whether it
    still works, and there is no token revocation — so unlimited guesses must
    not be the default. This middleware carries ONLY the failure-keyed login
    budget (``LOGIN_FAILURE_LIMIT`` per ``LOGIN_FAILURE_WINDOW_SECONDS``, per
    IP), counted per rejected credential so a legitimate sign-in and a mistype
    or two never consume it. When the general limiter is also registered it
    skips the login accounting (``owns_login=False``) to avoid double-charging.
    """
    # The breaker opens a SQLite file, so build it LAZILY on the first login
    # attempt rather than at registration: resolving the data root and touching
    # the filesystem at import time would tie app startup to it (and blow up
    # under a mocked config in tests). Non-login traffic never triggers it.
    _cb_box: dict[str, CircuitBreaker] = {}

    def _get_login_cb() -> CircuitBreaker:
        if login_breaker is not None:
            return login_breaker
        if "cb" not in _cb_box:
            _cb_box["cb"] = CircuitBreaker(
                {},
                db_path=get_data_root() / "ui_login_rate_limit.db",
                default_limit=(LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS),
                on_trip=lambda status: logger.warning(
                    "Sign-in rate limit tripped",
                    client=status.action,
                    count=status.count,
                    limit=status.limit,
                ),
            )
        return _cb_box["cb"]

    async def login_rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not _is_login_attempt(request):
            return await call_next(request)
        login_cb = _get_login_cb()
        login_key = f"login:{_ip_key(request)}"
        if not await asyncio.to_thread(login_cb.check, login_key):
            return JSONResponse(
                {"detail": "Too many sign-in attempts"},
                status_code=429,
                headers={"Retry-After": str(LOGIN_FAILURE_WINDOW_SECONDS)},
            )
        response = await call_next(request)
        if response.status_code >= 400:
            await asyncio.to_thread(login_cb.record, login_key)
        return response

    return login_rate_limit_middleware


async def timing_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Time each request, tag the response, and warn on slow ones."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Header is informational (curl / devtools / ops); not exposed to JS by
    # default, which is fine — nothing in the frontend reads it.
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"

    if elapsed_ms >= SLOW_REQUEST_MS:
        logger.warning(
            "Slow request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(elapsed_ms, 1),
        )
    return response
