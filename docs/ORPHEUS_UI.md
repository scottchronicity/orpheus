# Orpheus UI

Modern React/FastAPI UI for the Orpheus wildlife monitoring platform.

**See [`services/orpheus_ui/README.md`](../services/orpheus_ui/README.md) for comprehensive documentation.**

---

## Overview

Orpheus UI is the new frontend replacing the legacy vanilla JS `orpheus-dashboard`. It provides:

- **React 18 + TypeScript + Tailwind CSS** frontend
- **FastAPI + FastAPI-Users** backend with JWT authentication
- **Role-based access control** (Admin, Viewer, Public)
- **MQTT integration** for real-time system status updates

---

## Port Configuration

| Service | Port | Notes |
| --------- | ------ | ------- |
| **Orpheus UI Backend** | 8082 | FastAPI backend |
| **Orpheus UI Frontend (dev)** | 5173 | Vite dev server, proxies to 8082 |
| **Legacy Dashboard** | 8080 | `orpheus-dashboard` (until replaced) |

⚠️ **Important:** The backend runs on port **8082**, not 8080. The legacy dashboard remains on 8080 until orpheus-ui fully replaces it.

---

## Quick Start

### Development

```bash
cd services/orpheus_ui

# Install all dependencies
make install

# Terminal 1: Run backend (port 8082)
make run

# Terminal 2: Run frontend dev server (port 5173)
make run-frontend
```

Open **<http://localhost:5173>** (not 8082!)

### Production (Jetson)

```bash
cd services/orpheus_ui

# Install as systemd service
make install-service

# Check status
make service-status
```

Access at **<http://your-jetson:8082/>**

---

## Default Users

On first startup, two users are created automatically:

| Role | Email | Password |
| ------ | ------- | ---------- |
| Admin | `admin@orpheus.example.com` | `changeme` |
| Viewer | `guest@orpheus.example.com` | `guest` |

⚠️ **Change the admin password after first login!**

---

## User Database

The user database persists across service reinstalls:

- **Development:** `./users.db` (current directory)
- **Production:** `/data/orpheus/users.db`

To reset users:

```bash
# Production
sudo rm /data/orpheus/users.db
```

---

## Technology Stack

### Backend

- FastAPI + FastAPI-Users (JWT authentication)
- SQLAlchemy + SQLite
- structlog (structured logging)

### Frontend

- React 18 + TypeScript
- Vite + Tailwind CSS
- TanStack Query (data fetching)
- React Router

---

## Related Documentation

- **[Service README](../services/orpheus_ui/README.md)** - Complete setup and deployment guide
- **[Copilot Instructions](copilot-workspace-instructions/orpheus-ui.instructions.md)** - Development patterns
- **[Architecture](ARCHITECTURE.md)** - System design and data flows
- **[CODING_AGENT_CONTEXT.md](../CODING_AGENT_CONTEXT.md)** - Core development guidelines
