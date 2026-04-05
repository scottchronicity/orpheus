"""Orpheus UI - Modern React/FastAPI Wildlife Monitoring Interface

This is the new UI service for the Orpheus wildlife monitoring system.
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

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from orpheus_common import OrpheusConfig
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient

from orpheus_ui.api import cameras, diagnostics, entities, media, system
from orpheus_ui.auth.backend import auth_backend, fastapi_users
from orpheus_ui.auth.db import create_db_and_tables
from orpheus_ui.auth.schemas import UserCreate, UserRead, UserUpdate
from orpheus_ui.auth.seed import seed_admin_user

# Configure logging using structlog (JSON format for production)
setup_logging("orpheus-ui", level="INFO")
logger = get_logger(__name__)

# Get configuration singleton
config = OrpheusConfig.get_instance()

# MQTT client for real-time updates
_mqtt_client: Optional[MQTTClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle.

    Handles:
    - Database initialization
    - Admin user seeding (first run)
    - MQTT client connection
    """
    global _mqtt_client

    # Create database tables
    await create_db_and_tables()
    logger.info("Database tables created/verified")

    # Seed admin user if needed (first run)
    admin_created = await seed_admin_user()
    if admin_created:
        logger.info("First-run: Default users created (admin + guest)")

    # Connect to MQTT for real-time updates
    try:
        _mqtt_client = MQTTClient(
            broker_host=config.mqtt.broker_host,
            broker_port=config.mqtt.broker_port,
            client_id="orpheus-ui",
            keepalive=config.mqtt.keepalive,
        )
        _mqtt_client.connect()

        # Subscribe to health and detection topics
        _mqtt_client.subscribe(
            topic_pattern="orpheus/system/audio/health",
            callback=diagnostics.on_audio_health_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/system/video/health",
            callback=diagnostics.on_video_health_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/audio/motion/events",
            callback=diagnostics.on_audio_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/video/motion/events",
            callback=diagnostics.on_video_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/detection/bird/events",
            callback=diagnostics.on_bird_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/detection/crow/events",
            callback=diagnostics.on_crow_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/entities/animal",
            callback=entities.on_entity_event_message,
        )

        # Set MQTT client reference in diagnostics module
        diagnostics.set_mqtt_client(_mqtt_client)

        logger.info(
            "Connected to MQTT and subscribed to health/detection topics",
            broker=config.mqtt.broker_host,
        )
    except Exception as e:
        logger.warning("Failed to connect to MQTT for real-time updates", error=str(e))
        _mqtt_client = None

    logger.info(
        "Orpheus UI started",
        config_source=config.config_source(),
        version="0.1.0",
    )

    yield

    # Shutdown
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

# CORS middleware for development (React dev server on different port)
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

# Include authentication routes
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
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
app.include_router(entities.router)
app.include_router(media.router)


@app.get("/api/config")
def get_config():
    """Get frontend configuration (public endpoint)."""
    return {"poll_interval": config.dashboard_poll_interval()}


@app.get("/api/debug/config")
def get_debug_config():
    """Get runtime configuration for debugging (requires auth in production)."""
    debug_values = config.get_debug_safe_values()

    if "orpheus_config" in debug_values and "config.source" in debug_values["orpheus_config"]:
        debug_values["orpheus_config"]["config.source"] = (
            f"Runtime config (YAML + defaults + env overrides) from {config.config_source()}"
        )

    return debug_values


# Determine paths for static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

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

        Serves static files if they exist, otherwise returns index.html
        for client-side routing.
        """
        # Exclude API routes - these should be handled by their specific routers
        if (
            full_path.startswith("api/")
            or full_path.startswith("auth/")
            or full_path.startswith("users/")
        ):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        # Try to serve static file
        static_path = os.path.join(STATIC_DIR, full_path)
        if os.path.exists(static_path) and os.path.isfile(static_path):
            return FileResponse(static_path)

        # Fall back to SPA
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8082)
