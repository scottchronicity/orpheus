---
applyTo: "services/orpheus_ui/**"
---

# Orpheus UI Service Instructions

**See [`CODING_AGENT_CONTEXT.md`](https://github.com/scottchronicity/orpheus/blob/main/CODING_AGENT_CONTEXT.md) for core guidelines.** This file contains orpheus-ui-specific quick reference patterns.

**See [`services/orpheus_ui/README.md`](https://github.com/scottchronicity/orpheus/blob/main/services/orpheus_ui/README.md) for comprehensive documentation.**

---

## Overview

Orpheus UI is the React/FastAPI web interface for the Orpheus wildlife monitoring system. It provides:

- **React 18 + TypeScript + Tailwind CSS** frontend
- **FastAPI + FastAPI-Users** backend with JWT authentication
- **Role-based access control**: Admin and Viewer. A `public` role exists in the
  user model (`UserRole.PUBLIC`) but nothing assigns or enforces it.
- **MQTT integration** for real-time updates

---

## Critical Port Configuration

| Service | Port | Notes |
| --------- | ------ | ------- |
| **Orpheus UI Backend** | 8082 | FastAPI backend |
| **Orpheus UI Frontend (dev)** | 5173 | Vite dev server, proxies to 8082 |
| **Orpheus UI (production)** | 80 | nginx proxies port 80 → 8082 |

The backend runs on port **8082**. In production, nginx proxies port 80 → 8082.

---

## User Database

- `users.db` at the top of `$ORPHEUS_DATA_ROOT` (`/data/orpheus/users.db` on a
  station), or an existing accounts file wherever it already is
- `ORPHEUS_UI_DATABASE_URL` overrides it; the systemd unit sets it

The database **persists across service reinstalls**. To reset:
```bash
# Development
rm ./users.db

# Production
sudo rm /data/orpheus/users.db
```

---

## FastAPI-Users Setup

### Correct Import Pattern

```python
# ✅ CORRECT - use fastapi_users_db_sqlalchemy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

# ❌ WRONG - don't use fastapi_users.db
from fastapi_users.db import SQLAlchemyUserDatabase  # This is deprecated
```

### User Database with Generic Types

```python
import uuid
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID], None]:
    """Get the SQLAlchemy user database."""
    yield SQLAlchemyUserDatabase[User, uuid.UUID](session, User)
```

### User Model

```python
# ✅ CORRECT - use fastapi_users_db_sqlalchemy for User base class too
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, String

class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"
    role: str = Column(String(20), default="viewer", nullable=False)
    display_name: Optional[str] = Column(String(100), nullable=True)
```

**IMPORTANT:** Both `SQLAlchemyUserDatabase` AND `SQLAlchemyBaseUserTableUUID` must be imported from `fastapi_users_db_sqlalchemy`, NOT from `fastapi_users.db`. The latter is deprecated and will cause 500 errors on `/users/me`.

---

## Backend API Patterns

### Protected Endpoints

```python
from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User

@router.get("/api/resource")
async def get_resource(user: User = Depends(current_active_user)):
    """Endpoint requires authentication."""
    return {"data": ...}
```

### Role-Based Access

```python
from orpheus_ui.auth.backend import require_role

@router.get("/api/admin-only")
async def admin_endpoint(user: User = Depends(require_role("admin"))):
    """Endpoint requires admin role."""
    return {"message": "Admin access granted"}
```

---

## Frontend Patterns

### API Fetch with Auth

```typescript
// src/lib/utils.ts
export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = getToken()
  const headers = new Headers(options.headers)
  
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  headers.set('Content-Type', 'application/json')

  const response = await fetch(url, { ...options, headers })

  if (response.status === 401) {
    removeToken()
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }

  return response
}
```

### TanStack Query Pattern

```typescript
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth } from '../lib/utils'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/health')
      return res.json()
    },
    refetchInterval: 5000,  // Refresh every 5 seconds
  })
}
```

---

## Vite Proxy Configuration

The frontend dev server proxies API requests to the backend:

```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8082', changeOrigin: true },
      '/auth': { target: 'http://localhost:8082', changeOrigin: true },
      '/users': { target: 'http://localhost:8082', changeOrigin: true },
    },
  },
})
```

---

## Logging

Use **structlog** exclusively (no loguru!):

```python
from orpheus_common.logging import get_logger

logger = get_logger(__name__)
logger.info("User logged in", user_id=str(user.id), email=user.email)
```

---

## Development Workflow

```bash
# Terminal 1: Backend on port 8082
cd services/orpheus_ui
make install
make run

# Terminal 2: Frontend on port 5173
cd services/orpheus_ui
make run-frontend

# Open http://localhost:5173 (NOT 8082!)
```

---

## Testing

```bash
cd services/orpheus_ui
make test           # Run tests
make coverage       # Run with coverage
make lint           # Lint code
```

Mock pattern for tests:
```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_config():
    with patch("orpheus_common.OrpheusConfig.get_instance") as mock:
        config = MagicMock()
        config.mqtt.broker_host = "localhost"
        mock.return_value = config
        yield config
```

---

## Common Errors

### "Module 'fastapi_users.db' has no attribute 'SQLAlchemyUserDatabase'"
Use `from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase` instead.

### "cannot import name 'SQLAlchemyBaseUserTableUUID' from 'fastapi_users.db'"
Use `from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID` instead.
This applies to **BOTH** `SQLAlchemyUserDatabase` AND `SQLAlchemyBaseUserTableUUID`.

### 500 error on `/users/me`
Two possible causes:
1. Wrong import: Use `from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID` in models.py
2. Missing generic types: Use `SQLAlchemyUserDatabase[User, uuid.UUID]` in db.py

### Frontend shows 404
- Development: Open http://localhost:5173 (not 8082)
- Production: Ensure static files are built (`make build-frontend`)

### "Port 8080 already in use"
Orpheus UI uses port 8082. Check the Makefile and vite.config.ts are updated.

---

## File Structure

```
services/orpheus_ui/
├── src/orpheus_ui/
│   ├── main.py              # FastAPI app entry point
│   ├── auth/                # Authentication module
│   │   ├── backend.py       # JWT auth backend
│   │   ├── config.py        # Centralized auth config
│   │   ├── db.py            # Database setup
│   │   ├── manager.py       # User manager
│   │   ├── models.py        # User model
│   │   ├── schemas.py       # Pydantic schemas
│   │   └── seed.py          # First-run admin seeding
│   ├── api/                 # API routers
│   │   ├── cameras.py
│   │   ├── diagnostics.py
│   │   └── system.py
│   └── static/              # Built frontend (gitignored)
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── lib/utils.ts     # Auth utilities
│   │   ├── pages/           # Route pages
│   │   ├── components/      # React components
│   │   └── hooks/           # Custom hooks
│   ├── vite.config.ts
│   └── package.json
├── systemd/                 # Service installation
│   ├── install-service.sh
│   ├── uninstall-service.sh
│   └── orpheus-ui.service
├── tests/
├── Makefile
└── README.md
```

---

## References

- [FastAPI-Users Documentation](https://fastapi-users.github.io/fastapi-users/)
- [TanStack Query](https://tanstack.com/query)
- [Vite Configuration](https://vitejs.dev/config/)
- [`CODING_AGENT_CONTEXT.md`](https://github.com/scottchronicity/orpheus/blob/main/CODING_AGENT_CONTEXT.md) - Core guidelines
