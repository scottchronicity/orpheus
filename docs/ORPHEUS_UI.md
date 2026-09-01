# The dashboard service

How the dashboard is built and run: a React frontend over a FastAPI backend, the
auth model, and the build and deployment paths. If you want to *use* the dashboard
rather than work on it, read the [User Guide](user-guide/index.md) instead.

**See [`services/orpheus_ui/README.md`](https://github.com/scottchronicity/orpheus/blob/main/services/orpheus_ui/README.md) for the
component's own documentation.**

---

## Overview

Orpheus UI is the dashboard: a FastAPI backend serving a React frontend, showing what the station has heard and seen.

- **React 18 + TypeScript + Tailwind CSS** frontend
- **FastAPI + FastAPI-Users** backend with JWT authentication
- **Role-based access control**: Admin can accept equivalences and trigger playback;
  Viewer can read everything else. A `public` role exists in the user model but nothing
  assigns or enforces it, and there is no unauthenticated view of station data.
- **Event-bus integration** (the orpheus-backplane: NATS by default, MQTT fallback)
  for real-time system status updates

For what the dashboard shows and how to use it (pages, filters, playback,
Diagnostics), see the [User Guide](user-guide/index.md).

---

## Port Configuration

| Service | Port | Notes |
| --------- | ------ | ------- |
| **Orpheus UI Backend** | 8082 | FastAPI backend (nginx proxies port 80 to it in production) |
| **Orpheus UI Frontend (dev)** | 5173 | Vite dev server, proxies to 8082 |

The backend runs on port **8082** and serves the UI directly.

`dashboard.port` in `orpheus.yaml` ships as `8080` and is **not** the port the UI
binds. It appears in `/api/debug/config` and on the Settings page when you are signed
in as an admin, but nothing reads it. The real port is in the systemd unit (`--port 8082`); to move the UI,
edit `ExecStart` in `services/orpheus_ui/systemd/orpheus-ui.service`. In
production an nginx layer may proxy port 80 to it (see the installer's
note in `services/orpheus_ui/systemd/install-service.sh`).

---

## Node.js: what needs it, and when

The dashboard's frontend is a React/TypeScript application that is compiled to static
files before it can be served. That build step is the only reason Node.js appears
anywhere in Orpheus — no agent, service, or Python component uses it at runtime.

Two paths, and they get Node differently:

- **`make install-service`** (the production path, and what the Jetson quickstart
  uses) downloads its own Node.js 20.18.0 into `services/orpheus_ui/.node/` and builds
  with that. You do not need Node.js installed on the machine.
- **`make install`** from the repository root, or from `services/orpheus_ui`, is the
  developer path: it uses whatever `npm` is on your `PATH`, so it needs **Node.js 20 or
  newer** installed. This is the path every quickstart except the Jetson one follows,
  which is why they list Node as a prerequisite.

The developer install also sets up the end-to-end test harness, which downloads a
private copy of Chromium (a few hundred MB) through Playwright. That browser is used
only by the e2e suite.

If `make install` fails with a missing `npm`, or with a Node engine error naming a
version below 20, install a current Node.js and re-run it — nothing else needs
cleaning up first.

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

These are public knowledge — they are in this repository. **Change them before anyone
else can reach the box.** While a seeded account still accepts one of them, the login
page shows a prompt saying so.

Seeding runs once, guarded on an empty user table, so setting
`ORPHEUS_UI_ADMIN_PASSWORD` / `ORPHEUS_UI_GUEST_PASSWORD` after the first start
rotates nothing. [Security](security.md) has the two ways to rotate an
already-seeded install, and the full picture of what the login does and does not
protect — this page does not repeat the procedure.

---

## User Database

The accounts database persists across service reinstalls. It lives at `users.db` in
the top of `$ORPHEUS_DATA_ROOT` — `/data/orpheus/users.db` on a station,
`~/data/orpheus/users.db` on a laptop that sets the variable. A file that already
exists elsewhere keeps being used rather than being abandoned, and
`ORPHEUS_UI_DATABASE_URL` overrides the choice entirely (the systemd unit sets it).
The backend logs the resolved path at startup.

To reset users, stop the UI and remove that file:

```bash
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

- **[Service README](https://github.com/scottchronicity/orpheus/blob/main/services/orpheus_ui/README.md)** - Complete setup and deployment guide
- **[Copilot Instructions](copilot-workspace-instructions/orpheus-ui.instructions.md)** - Development patterns
- **[Architecture](ARCHITECTURE.md)** - System design and data flows
- **[Adding a frontend page](agent-instructions/32-recipes-frontend-page.md)** — the recipe for a new dashboard page
- **[Agent Index](agents-index.md)** — the entry point for coding agents
