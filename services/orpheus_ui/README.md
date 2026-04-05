# Orpheus UI

Modern React/FastAPI UI for Orpheus Wildlife Monitoring System.

## Overview

Orpheus UI is the new frontend service for the Orpheus wildlife monitoring platform. It provides a modern, responsive web interface with full user authentication and role-based access control.

**Important:** This service runs on port **8082** to avoid conflicting with the legacy `orpheus-dashboard` which remains on port 8080 until this service fully replaces it.

## Directory Structure

```bash
orpheus_ui/
├── Makefile              # Root Makefile - delegates to backend/ and frontend/
├── README.md             # This file
├── backend/              # Python FastAPI application
│   ├── Makefile          # Backend-specific targets
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── src/
│   │   └── orpheus_ui/   # Python package
│   └── tests/            # Python unit tests (pytest)
├── frontend/             # React TypeScript application
│   ├── Makefile          # Frontend-specific targets
│   ├── package.json
│   ├── src/              # React source code
│   └── ...
├── e2e/                  # Playwright end-to-end tests
│   ├── package.json
│   ├── playwright.config.ts
│   ├── login.spec.ts
│   └── dashboard.spec.ts
└── systemd/              # Service installation files
    ├── install-service.sh
    ├── uninstall-service.sh
    └── orpheus-ui.service
```

## For Developers

**See repository root documentation for:**

- [Development Guidelines](../../CODING_AGENT_CONTEXT.md) - Core coding standards
- [Testing Strategy](../../docs/TESTING.md) - How to write tests
- [Architecture](../../docs/ARCHITECTURE.md) - System design

## Technology Stack

### Backend

- **FastAPI** - Modern Python web framework
- **FastAPI-Users** - Full-featured user authentication
- **SQLAlchemy** - Database ORM with SQLite
- **structlog** - Structured JSON logging

### Frontend

- **React 18** - UI library
- **Vite** - Build tool
- **TypeScript** - Type-safe JavaScript
- **Tailwind CSS** - Utility-first CSS
- **TanStack Query** - Data fetching and caching
- **React Router** - Client-side routing

## MQTT Topics

**Subscribes to:** Nothing.

**Publishes to:** Nothing directly.

This service is a web application layer. It does not connect to the MQTT broker. All wildlife data is read from DetectionDB (SQLite) and the filesystem via `orpheus-common`. Any commands that require MQTT interaction (e.g., triggering audio playback) are expected to be routed through a dedicated API endpoint that delegates to the appropriate agent — that integration is not yet implemented.

## Quick Start

### Development

```bash
# Install all dependencies (backend + frontend)
make install

# Terminal 1: Run backend on port 8082
make run

# Terminal 2: Run frontend dev server on port 5173
# (proxies API requests to backend on port 8082)
make run-frontend
```

**Open <http://localhost:5173> in your browser** (not 8082!)

The frontend dev server runs on port 5173 and proxies API requests to the backend on port 8082.

### Production Build

```bash
# Build frontend for production
make build-frontend

# Run backend locally (serves built frontend at /)
make run
```

In production mode, the backend serves both API and static files on port 8082.

**For systemd deployment:** Use `make install-service` instead (see below).

## Production Deployment (Jetson/Linux)

### Install as Systemd Service

```bash
# Install the systemd service (requires sudo)
# This automatically enables and starts the service
make install-service

# Check status
make service-status

# View logs
make service-logs
```

**Note:** `make install-service` requires sudo and automatically:

- Downloads Node.js v20.18.0 locally
- Builds the frontend
- Installs the backend and frontend to `/opt/orpheus/ui/`
- Enables the service (auto-start on boot)
- Starts the service

**Access the UI:** In production, the backend serves everything on **port 8082**:

- **<http://your-jetson:8082/>** - Web UI (login page)
- **<http://your-jetson:8082/api/health>** - API health check

There is NO separate frontend dev server (port 5173) in production - that's only for development.

### Manage the Service

```bash
# Start/stop/restart
make service-start
make service-stop
make service-restart

# View status
make service-status

# View logs (follow mode)
make service-logs
```

### Uninstall Service

```bash
sudo make uninstall-service

# Optionally remove deployed files (but NOT user database)
sudo rm -rf /opt/orpheus/ui

# To also remove user database (CAUTION: deletes all users!)
sudo rm -f /data/orpheus/users.db
```

## User Database Persistence

The user database is stored at `/data/orpheus/users.db` and **persists across service updates and reinstalls**. This means:

- User accounts survive `make install-service` updates
- Login credentials are preserved
- You don't need to recreate users after updates

To reset the database (delete all users), manually remove the file:

```bash
sudo rm /data/orpheus/users.db
```

## Authentication

The UI uses JWT-based authentication with role-based access control:

- **Admin** - Full access to all features
- **Viewer** - Read-only access to dashboard
- **Public** - Unauthenticated (limited access)

### First Run

On first startup, two default users are created automatically:

**Admin User:**

- **Email:** `admin@orpheus.example.com`
- **Password:** `changeme`
- **Role:** Admin (full access)

**Guest User:**

- **Email:** `guest@orpheus.example.com`
- **Password:** `guest`
- **Role:** Viewer (read-only)

⚠️ **Security:** Change the default admin password after first login!

💡 **Tip:** Use the guest account for read-only monitoring without admin privileges.

### Environment Variables

| Variable | Description | Default |
| ---------- | ------------- | --------- |
| `ORPHEUS_UI_JWT_SECRET` | Secret for JWT tokens | `CHANGE_ME_IN_PRODUCTION` |
| `ORPHEUS_UI_JWT_LIFETIME` | JWT token lifetime (seconds) | `86400` (24 hours) |
| `ORPHEUS_UI_ADMIN_EMAIL` | Default admin email | `admin@orpheus.example.com` |
| `ORPHEUS_UI_ADMIN_PASSWORD` | Default admin password | `changeme` |
| `ORPHEUS_UI_GUEST_EMAIL` | Default guest email | `guest@orpheus.example.com` |
| `ORPHEUS_UI_GUEST_PASSWORD` | Default guest password | `guest` |
| `ORPHEUS_UI_DATABASE_URL` | SQLite database URL | `sqlite+aiosqlite:////data/orpheus/users.db` |

## API Endpoints

### Public Endpoints

| Endpoint | Description |
| ---------- | ------------- |
| `POST /auth/jwt/login` | Login with email/password |
| `POST /auth/register` | Register new user |
| `GET /api/config` | Get frontend configuration |

### Protected Endpoints (require authentication)

| Endpoint | Description |
| ---------- | ------------- |
| `GET /users/me` | Get current user info |
| `GET /api/health` | System health metrics |
| `GET /api/services/status` | Service status |
| `GET /api/cameras` | Camera status |
| `GET /api/cameras/{name}/snapshot` | Camera snapshot |
| `GET /api/diagnostics/audio` | Audio diagnostics |
| `GET /api/diagnostics/video` | Video diagnostics |
| `GET /api/diagnostics/bird/detections` | Bird detections |
| `GET /api/diagnostics/crow/detections` | Crow detections |

## Port Configuration

| Service | Port | Notes |
| --------- | ------ | ------- |
| **Orpheus UI Backend** | 8082 | FastAPI backend |
| **Orpheus UI Frontend (dev)** | 5173 | Vite dev server, proxies to 8082 |
| **Legacy Dashboard** | 8080 | `orpheus-dashboard` (unchanged) |
| **Legacy Dashboard (old)** | 8081 | Previous legacy port |

**nginx proxy notes:** Once orpheus-ui is ready to fully replace orpheus-dashboard, update nginx to proxy port 80 to port 5173 (or serve built static files directly).

## Troubleshooting

### Frontend dev server memory issues

If you experience memory issues, try:

```bash
# Increase Node.js memory limit
export NODE_OPTIONS="--max-old-space-size=4096"
make run-frontend
```

## Testing

### Backend Unit Tests (Python/pytest)

```bash
# Run backend tests
make test-backend

# Run with coverage
make coverage
```

### End-to-End Tests (Playwright)

```bash
# Install Playwright (first time only)
make install-e2e

# Run e2e tests (requires backend + frontend running)
make test-e2e
```

### All Tests

```bash
# Run all tests
make test
```

## Troubleshooting (continued)

### Backend returns 404

Make sure you're accessing the correct port:

- **Development:** Open <http://localhost:5173> (frontend dev server)
- **Backend API only:** <http://localhost:8082/api/health>

### Login fails with 500 error on `/users/me`

This usually means the email in your database uses an invalid TLD (like `.local`).

**Fix:** Delete the old database and let a new one be created:

```bash
# Development
rm ./users.db

# Production
sudo rm /data/orpheus/users.db
```

Then restart the service - a new admin user will be created with `admin@orpheus.example.com`.

**Note:** The `.local` TLD is rejected by Pydantic's email validator. Always use valid TLDs like `.com`, `.org`, or the reserved `.example.com`.

### Cannot connect to backend

Ensure the backend is running on port 8082:

```bash
curl http://localhost:8082/api/health
```

## For AI Agents / LLMs

When working on this codebase:

1. **Port 8082** - The UI backend runs on 8082, NOT 8080
2. **User DB at `/data/orpheus/users.db`** - Persists across installs
3. **Frontend proxies to backend** - Vite config proxies `/api`, `/auth`, `/users` to 8082
4. **SQLAlchemyUserDatabase generic types** - Use `SQLAlchemyUserDatabase[User, uuid.UUID]`
5. **Import from `fastapi_users_db_sqlalchemy`** - Not `fastapi_users.db`
6. **No loguru** - Use structlog exclusively

## License

MIT License - See repository root LICENSE file.
