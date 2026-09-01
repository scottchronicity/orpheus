"""Orpheus UI - Modern React/FastAPI Wildlife Monitoring Interface

The UI service for the Orpheus wildlife monitoring system.
It provides a React-based frontend with FastAPI backend and full authentication.

Architecture:
- FastAPI backend with JWT authentication via FastAPI-Users
- SQLite database for user storage
- React + TypeScript + Tailwind CSS frontend
- MQTT integration for real-time updates
- structlog for JSON-formatted logging

Features:
- User authentication with roles (Admin, Viewer, Public)
- System health monitoring
- Service status tracking
- Camera feeds and snapshots
- Detection history (audio, video, bird, crow)
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from orpheus_common import EventBus, OrpheusConfig, create_event_bus
from orpheus_common.logging import get_logger, setup_logging

from orpheus_ui.api import cameras, diagnostics, entities, media, presence, system, weather
from orpheus_ui.auth.backend import (
    auth_backend,
    current_superuser,
    fastapi_users,
    get_jwt_strategy,
)
from orpheus_ui.auth.db import create_db_and_tables
from orpheus_ui.auth.manager import get_user_manager
from orpheus_ui.auth.models import User, UserRole
from orpheus_ui.auth.schemas import UserCreate, UserRead, UserUpdate
from orpheus_ui.auth.seed import DEFAULT_GUEST_EMAIL, seed_admin_user, seeded_defaults_in_use
from orpheus_ui.middleware import (
    build_login_rate_limit_middleware,
    build_rate_limit_middleware,
    timing_middleware,
)
from orpheus_ui.storage_history import get_storage_history_db

# Configure logging using structlog (JSON format for production)
setup_logging("orpheus-ui", level="INFO")
logger = get_logger(__name__)

# Get configuration singleton
config = OrpheusConfig.get_instance()

# How often the background task samples storage usage. History is keyed by
# day, so sampling more than daily just refreshes today's row (cheap) — a
# few-hour cadence means a restart or a mid-day check still records a point.
_STORAGE_SAMPLE_INTERVAL_SECONDS = 6 * 60 * 60

# MQTT client for real-time updates
_mqtt_client: Optional[EventBus] = None

# Background storage-usage sampler task
_storage_sampler_task: Optional["asyncio.Task[None]"] = None

# Whether a seeded account still accepts its shipped default password. Computed
# once at startup (the check is a deliberately slow password hash, and
# /api/config is public and unauthenticated) and served to the login page as a
# rotation prompt. A rotation performed at runtime is reflected on next restart.
_default_credentials_in_use: bool = False

# Background operational-health KV re-snapshot task (§11 Phase 2 — the correctness
# floor under the kv_watch shadow consumer). Only started when ui.health_source is
# "kv"/"both" AND the backend serves KV; serving still comes from the bus this phase.
_health_resnapshot_task: Optional["asyncio.Task[None]"] = None

# Whether the kv_watch attach has succeeded (lifespan or a later re-snapshot
# retry). The watch is best-effort — the re-snapshot floor keeps the cache
# honest either way — but re-attaching restores sub-30s freshness after a
# boot-time broker blip.
_health_kv_watch_started: bool = False


async def _health_resnapshot_loop() -> None:
    """Periodically re-snapshot the orpheus_health KV bucket into the shadow cache —
    the correctness floor so the cache never depends on a long-lived kv_watch staying
    alive (kv_watch stops permanently on error). Best-effort; never dies on a blip.

    This loop is also the RETRY mechanism for a failed boot: it runs regardless of
    whether the initial prime/kv_watch succeeded, re-attaches the watch if it never
    started, and promotes ``health_kv.CONSUMER_ACTIVE`` once a prime lands — so a
    transient broker outage at UI boot degrades to a ≤30s-stale cache instead of
    killing the shadow consumer for the process lifetime. ``kv_list``/``kv_watch``
    block on the bus op timeout (up to ~5s against a slow broker), so both run in
    a worker thread — never on the uvicorn event loop."""
    global _health_kv_watch_started
    from orpheus_ui import health_kv

    while True:
        await asyncio.sleep(health_kv.HEALTH_RESNAPSHOT_SECONDS)
        try:
            await asyncio.to_thread(
                health_kv.prime_cache, _mqtt_client, health_kv.HEALTH_KV_CACHE
            )
            if not _health_kv_watch_started:
                from orpheus_common.actor import OperationalHealth  # noqa: PLC0415

                attached = await asyncio.to_thread(
                    OperationalHealth(_mqtt_client).watch,
                    health_kv.HEALTH_KV_CACHE.on_change,
                )
                if attached:
                    _health_kv_watch_started = True
                    logger.info("Operational-health kv_watch attached by re-snapshot loop")
            # Promote only on a non-empty view (see the boot-time gate): an
            # empty bucket means no producer dual-writes yet.
            if health_kv.HEALTH_KV_CACHE.snapshot():
                health_kv.CONSUMER_ACTIVE = True
        except Exception as e:  # never let the floor die on a transient KV error
            logger.warning("operational-health KV re-snapshot failed", error=str(e))


async def _storage_sampler_loop() -> None:
    """Sample storage usage for every volume on startup, then periodically.

    Persists one row per volume per day (see ``StorageHistoryDB``) so the
    Diagnostics page can chart free-space-over-time and project days-until-
    full. Runs in the always-on UI service — no separate systemd timer.
    Disk reads are blocking, so they're offloaded to a thread.
    """
    while True:
        try:
            written = await asyncio.to_thread(lambda: get_storage_history_db().sample_now())
            logger.debug("Sampled storage usage", volumes=written)
        except Exception as e:  # never let the loop die on a transient error
            logger.warning("Storage usage sampling failed", error=str(e))
        await asyncio.sleep(_STORAGE_SAMPLE_INTERVAL_SECONDS)


def _subscribe_topics(client: EventBus, health_source: str) -> None:
    """Wire the UI's bus subscriptions. Domain/detection subs (the data pages + entity
    updates) are ALWAYS subscribed; the operational-HEALTH subs are dropped once the UI
    serves health from the KV plane (§11 Phase 5b: ``health_source == "kv"``), kept for
    ``bus``/``both`` which still serve health from the bus."""
    # Domain/detection — always (never gated by the health migration).
    client.subscribe(
        topic_pattern="orpheus/audio/motion/events",
        callback=diagnostics.on_audio_detection_message,
    )
    client.subscribe(
        topic_pattern="orpheus/video/motion/events",
        callback=diagnostics.on_video_detection_message,
    )
    client.subscribe(
        topic_pattern="orpheus/detection/bird/events",
        callback=diagnostics.on_bird_detection_message,
    )
    client.subscribe(
        topic_pattern="orpheus/detection/crow/events",
        callback=diagnostics.on_crow_detection_message,
    )
    client.subscribe(
        topic_pattern="orpheus/entities/animal",
        callback=entities.on_entity_event_message,
    )

    # Operational health — dropped when serving from KV (Phase 5b). The video
    # diagnostics endpoint's camera_count/last_detection stays domain-cache-derived
    # (from the detection subs above), so dropping video/health doesn't regress it.
    if health_source != "kv":
        client.subscribe(
            topic_pattern="orpheus/system/audio/health",
            callback=diagnostics.on_audio_health_message,
        )
        client.subscribe(
            topic_pattern="orpheus/system/video/health",
            callback=diagnostics.on_video_health_message,
        )
        client.subscribe(
            topic_pattern="orpheus/system/auto-discovery/health",
            callback=entities.on_auto_discovery_health_message,
        )
        client.subscribe(
            topic_pattern="orpheus/system/audio-events/health",
            callback=entities.on_audio_events_health_message,
        )
        client.subscribe(
            topic_pattern="orpheus/system/+/health",
            callback=entities.on_agent_health_message,
        )


async def _start_health_kv_consumer(client: EventBus, health_source: str) -> str:
    """Start the operational-health KV shadow consumer; return the health source
    to actually subscribe with.

    §11 Phase 2/3: shadow-read operational health from the KV plane (kv_watch +
    a periodic re-snapshot floor) when ui.health_source is "kv"/"both" AND the
    backend serves KV. Runs BEFORE the bus subscriptions so the Phase-5b
    health-subscription drop can require the consumer to have actually started —
    config alone must never drop the bus subs and then serve from a never-fed
    cache. Boot feature-detect: if KV is unsupported (mqtt), we skip it and stay
    on the bus, so a misconfigured flag can never blank the health view. All kv_*
    calls block on the bus op timeout, so they run in a worker thread rather than
    stalling the uvicorn event loop.
    """
    global _health_resnapshot_task, _health_kv_watch_started

    if health_source not in ("kv", "both"):
        return health_source

    from orpheus_common.actor import OperationalHealth  # noqa: PLC0415

    from orpheus_ui import health_kv  # noqa: PLC0415

    if await asyncio.to_thread(OperationalHealth(client).supported):
        # The re-snapshot loop is the retry mechanism, so it starts BEFORE
        # (and regardless of) the first prime/watch attempt — a boot-time
        # broker blip must not permanently kill the shadow consumer.
        _health_resnapshot_task = asyncio.create_task(_health_resnapshot_loop())
        try:
            await asyncio.to_thread(
                health_kv.prime_cache, client, health_kv.HEALTH_KV_CACHE
            )
            # Through the writer's consumer surface (create=False is enforced
            # inside watch(), same as api/presence.py). watch() returns False
            # when the bucket doesn't exist yet — that is NOT a started
            # consumer; the re-snapshot loop keeps retrying the attach until a
            # producer creates the bucket.
            attached = await asyncio.to_thread(
                OperationalHealth(client).watch,
                health_kv.HEALTH_KV_CACHE.on_change,
            )
            _health_kv_watch_started = bool(attached)
            # Promotion floor (frozen-flag landmine): an EMPTY prime means no
            # producer is dual-writing (health_kv_enabled off or fleet down) —
            # do not declare the KV side active on nothing, or health_source=kv
            # would serve an empty view.
            primed = bool(health_kv.HEALTH_KV_CACHE.snapshot())
            health_kv.CONSUMER_ACTIVE = _health_kv_watch_started and primed
            if health_kv.CONSUMER_ACTIVE:
                logger.info("Operational-health KV shadow consumer started")
            else:
                logger.warning(
                    "Health KV consumer not promoted yet",
                    watch_attached=_health_kv_watch_started,
                    primed_agents=primed,
                    hint="producers dual-write only with "
                    "event_bus.health_kv_enabled: true",
                )
        except Exception as e:
            logger.warning(
                "Failed to start health KV shadow consumer; the re-snapshot "
                "loop will keep retrying",
                error=str(e),
            )
    else:
        logger.warning(
            "ui.health_source=%s but backend has no KV; serving health from "
            "the bus (unchanged)",
            health_source,
        )

    # Drop the bus health subscriptions only when the KV consumer actually
    # started (prime + watch succeeded). "kv" configured but consumer down ⇒
    # keep serving/subscribing on the bus, matching _serve_health_from_kv's
    # CONSUMER_ACTIVE gate — there is no later resubscribe path for the health
    # topics, so this must fail toward the bus.
    if health_source == "kv" and not health_kv.CONSUMER_ACTIVE:
        logger.warning(
            "ui.health_source=kv but the KV plane is not serving (watch "
            "attached: %s, primed: %s); keeping bus health — check "
            "event_bus.health_kv_enabled on the producers",
            _health_kv_watch_started,
            bool(health_kv.HEALTH_KV_CACHE.snapshot()),
        )
        return "bus"
    return health_source


async def _connect_event_bus(config: OrpheusConfig) -> Optional[EventBus]:
    """Connect the event bus and subscribe to it. Returns the bus, or None if it
    could not be created/connected at all.

    Subscribing is the load-bearing step and has its own error boundary. It used
    to share one try with the optional KV shadow consumer, so a failure in that
    optional path skipped subscribing entirely and dropped the bus — leaving a UI
    that reported itself connected, served an ever-staler cache, and had no path
    back short of a restart.
    """
    try:
        client = create_event_bus(config, client_id="orpheus-ui")
        client.connect()
    except Exception as e:
        logger.warning(
            "Failed to connect to event bus for real-time updates", error=str(e)
        )
        return None

    health_source = getattr(config.ui, "health_source", "bus")
    try:
        effective_health_source = await _start_health_kv_consumer(client, health_source)
    except Exception as e:
        logger.warning(
            "Failed to start the health KV shadow consumer; serving health from the bus",
            error=str(e),
        )
        effective_health_source = "bus"

    # Set MQTT client reference in diagnostics module
    diagnostics.set_mqtt_client(client)

    # Give the presence endpoint the same bus (KV-only; it feature-detects).
    presence.set_bus(client)

    try:
        _subscribe_topics(client, effective_health_source)
    except Exception as e:
        # Connected but not listening is the failure that hides. Log it at error
        # level so it is greppable, and keep the bus: it re-applies subscriptions
        # itself once the broker accepts them, and /api/diagnostics/bus reports
        # what is still pending in the meantime.
        logger.error(
            "Connected to the event bus but failed to subscribe; real-time updates "
            "will be missing until the subscriptions apply",
            error=str(e),
        )
        return client

    logger.info(
        "Connected to event bus and subscribed to health/detection topics",
        backend=config.event_bus.backend,
        broker=(
            config.event_bus.nats_url
            if config.event_bus.backend == "nats"
            else config.mqtt.broker_host
        ),
    )
    return client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle.

    Handles:
    - Database initialization
    - Admin user seeding (first run)
    - MQTT client connection
    """
    global _mqtt_client, _default_credentials_in_use, _health_resnapshot_task

    # Create database tables
    await create_db_and_tables()
    logger.info("Database tables created/verified")

    # Seed admin user if needed (first run)
    admin_created = await seed_admin_user()
    if admin_created:
        logger.info("First-run: Default users created (admin + guest)")

    # Say where the accounts live, every start. An operator who cannot answer
    # "which file holds my logins" cannot back it up, move it, or tell whether
    # a re-seed is about to hand them default credentials.
    from orpheus_ui.auth.db import DEV_DB_PATH, resolve_db_path  # noqa: PLC0415

    _accounts_db = resolve_db_path()
    if _accounts_db == DEV_DB_PATH:
        logger.warning(
            "Accounts database is in the working directory: the data root was "
            "missing or not writable, so logins will not survive running the "
            "server from somewhere else. Set ORPHEUS_DATA_ROOT to a writable "
            "path (or ORPHEUS_UI_DATABASE_URL to an explicit file).",
            accounts_db=str(_accounts_db.resolve()),
        )
    else:
        logger.info("Accounts database", accounts_db=str(_accounts_db))

    _default_credentials_in_use = await seeded_defaults_in_use()
    if _default_credentials_in_use:
        # Name the remediation that works on an ALREADY-SEEDED box. Seeding is
        # guarded on an empty user table, so setting the environment variables
        # here and restarting changes nothing.
        logger.warning(
            "A seeded account still uses a password this project ships. Rotate it: "
            "sign in and PATCH /users/me with a new password, or set "
            "ORPHEUS_UI_ADMIN_PASSWORD and ORPHEUS_UI_GUEST_PASSWORD, delete "
            "the accounts database and restart to re-seed.",
            accounts_db=str(_accounts_db),
        )

    # Connect to the event bus for real-time updates
    _mqtt_client = await _connect_event_bus(config)

    # Start the background storage-usage sampler (daily history + fill-rate
    # projection for the Diagnostics storage trend).
    global _storage_sampler_task
    _storage_sampler_task = asyncio.create_task(_storage_sampler_loop())

    logger.info(
        "Orpheus UI started",
        config_source=config.config_source(),
        version="0.1.0",
    )

    yield

    # Shutdown
    if _storage_sampler_task is not None:
        _storage_sampler_task.cancel()
        try:
            await _storage_sampler_task
        except asyncio.CancelledError:
            pass
        _storage_sampler_task = None

    if _health_resnapshot_task is not None:
        _health_resnapshot_task.cancel()
        try:
            await _health_resnapshot_task
        except asyncio.CancelledError:
            pass
        _health_resnapshot_task = None
        # The consumer is gone with its task — clear the serving gate so a
        # (test-harness) restart of the lifespan re-derives it from scratch.
        from orpheus_ui import health_kv  # noqa: PLC0415

        health_kv.CONSUMER_ACTIVE = False
        _health_kv_watch_started = False

    if _mqtt_client:
        try:
            _mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")
        except Exception as e:
            logger.error("Error disconnecting from MQTT", error=str(e))
        _mqtt_client = None


app = FastAPI(
    title="Orpheus UI",
    description="Modern Wildlife Monitoring Interface with Full Authentication",
    version="0.1.0",
    lifespan=lifespan,
)

# Per-client API rate limiting (portal prerequisite N2) — registered ONLY when
# ui.rate_limit_enabled (default off, so the default deploy has zero new code on
# the hot path). 429 + Retry-After once a client exceeds the sliding window.
# Registered BEFORE CORS so CORS sits outside it (Starlette applies the
# last-added middleware first): a 429 must still pass back through
# CORSMiddleware to pick up its headers, or the browser hides the response
# body/status from the frontend's error handling.
_ui_cfg = getattr(config, "ui", None)
# `is True`: the real config layer yields a strict bool; anything else (absent
# section, mocked configs in tests) means OFF — never register on a Mock.
_general_limiter_on = getattr(_ui_cfg, "rate_limit_enabled", False) is True
if _general_limiter_on:
    app.middleware("http")(
        build_rate_limit_middleware(
            requests=_ui_cfg.rate_limit_requests,
            window_seconds=_ui_cfg.rate_limit_window_seconds,
            # The always-on login middleware below owns credential-guessing;
            # tell the general limiter not to double-charge it.
            owns_login=False,
        )
    )
    logger.info(
        "API rate limiting enabled",
        requests=_ui_cfg.rate_limit_requests,
        window_seconds=_ui_cfg.rate_limit_window_seconds,
    )

# Login brute-force protection is registered ALWAYS, not behind
# rate_limit_enabled: the shipped admin password is public and /api/config
# advertises whether it still works, so unlimited guesses cannot be the
# default. Off-by-default here would defeat every credential fix on this
# branch. Registered last among the limiters so it runs first (Starlette
# applies the last-added middleware outermost).
app.middleware("http")(build_login_rate_limit_middleware())
logger.info("Sign-in brute-force protection enabled")

# CORS middleware for development (React dev server on different port).
# Added AFTER the rate limiter so it wraps it (see above).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request-timing middleware. Registered after CORS so it sits OUTERMOST (Starlette
# applies the last-added middleware first) and measures the full request time.
# Tags every response with X-Response-Time-ms and warns on slow requests.
app.middleware("http")(timing_middleware)

# Include authentication routes
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    # Account creation is an administrative act: the payload carries `role`,
    # so an open route lets anyone who can reach the port grant themselves
    # admin. Seeded-password hygiene does not cover this — the attacker never
    # touches a seeded account.
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(current_superuser)],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

# Include API routers
app.include_router(system.router)
app.include_router(cameras.router)
app.include_router(diagnostics.router)
app.include_router(presence.router)
app.include_router(entities.router)
app.include_router(media.router)
app.include_router(weather.router)


def _guest_quick_login_enabled() -> bool:
    """Read ``ui.guest_quick_login``, defaulting to on for an older config."""
    ui = getattr(config, "ui", None)
    return bool(getattr(ui, "guest_quick_login", True)) if ui is not None else True


@app.post("/auth/guest-login", tags=["auth"])
async def guest_login(user_manager=Depends(get_user_manager)):
    """Sign in as the seeded read-only guest account.

    The guest password lives on the server, so the browser bundle carries no
    credential and the button keeps working after an operator rotates it.
    Gated by ``ui.guest_quick_login``: while it is on, dashboard viewing is
    open to anyone who can reach the port.
    """
    if not _guest_quick_login_enabled():
        raise HTTPException(status_code=403, detail="Guest sign-in is disabled")

    user = await user_manager.get_by_email(DEFAULT_GUEST_EMAIL)
    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Guest sign-in is unavailable")

    # This mints a session for an UNAUTHENTICATED caller, so it may only ever
    # mint a viewer's. Nothing else holds that line: an admin can promote the
    # guest account through PATCH /users/{id} (UserUpdate withholds `role` but
    # not `is_superuser`), and ORPHEUS_UI_GUEST_EMAIL can be repointed at a
    # real account — either would turn this button into an admin handout.
    if user.is_superuser or user.role != UserRole.VIEWER.value:
        logger.warning(
            "Guest quick-login refused: the guest account is not a viewer",
            email=DEFAULT_GUEST_EMAIL,
        )
        raise HTTPException(status_code=403, detail="Guest sign-in is unavailable")

    token = await get_jwt_strategy().write_token(user)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/config")
def get_config():
    """Get frontend configuration (public endpoint).

    ``default_credentials_in_use`` drives the login page's rotation prompt. It
    is computed once at startup and says only *that* a shipped default is still
    accepted, never which account or what the password is — an attacker learns
    nothing they could not settle with one login attempt.
    """
    return {
        "poll_interval": config.dashboard_poll_interval(),
        "guest_quick_login": _guest_quick_login_enabled(),
        "default_credentials_in_use": _default_credentials_in_use,
    }


@app.get("/api/debug/config")
def get_debug_config(user: User = Depends(current_superuser)):
    """Get runtime configuration for debugging.

    Superuser-only: the payload includes broker URLs and the site's precise
    coordinates, so it is an administrative view rather than a public one.
    """
    debug_values = config.get_debug_safe_values()

    if "orpheus_config" in debug_values and "config.source" in debug_values["orpheus_config"]:
        debug_values["orpheus_config"]["config.source"] = (
            f"Runtime config (YAML + defaults + env overrides) from {config.config_source()}"
        )

    return debug_values


# Determine paths for static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def resolve_spa_path(full_path: str) -> str:
    """Map a browser path to a file inside the built bundle, else the SPA shell.

    ``full_path`` is the raw, un-normalized URL tail: the browser sends
    ``../``, ``%2e%2e/`` and absolute paths through unchanged, and this route
    is unauthenticated. So the join is resolved and *contained* — anything
    landing outside the bundle serves index.html instead of a file, which is
    also the right answer for a client-side route that happens to look like a
    path. Without the containment a bare GET reads any file the service user
    can open (``/opt/orpheus/config/.env``, ``users.db``), which is the whole
    login gate and every role check at once.

    Lives at module scope (rather than inside the catch-all) so it is testable
    on a checkout with no built frontend, where the route is not registered.
    """
    if (
        full_path.startswith("api/")
        or full_path.startswith("auth/")
        or full_path.startswith("users/")
    ):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    index_html = os.path.join(STATIC_DIR, "index.html")
    static_root = os.path.realpath(STATIC_DIR)
    # realpath (not abspath) so a symlink inside the bundle cannot point out of it.
    candidate = os.path.realpath(os.path.join(static_root, full_path))
    contained = candidate == static_root or candidate.startswith(static_root + os.sep)
    if contained and os.path.isfile(candidate):
        return candidate

    return index_html


# Check if built frontend exists
if os.path.exists(STATIC_DIR) and os.path.exists(os.path.join(STATIC_DIR, "index.html")):
    # Mount static files for production (built React app)
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def serve_spa():
        """Serve the React SPA."""
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}")
    async def catch_all(full_path: str):
        """Catch-all route for SPA routing.

        Serves a file from the built bundle when the path resolves inside it,
        otherwise index.html for client-side routing.
        """
        return FileResponse(resolve_spa_path(full_path))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8082)
