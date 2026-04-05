# Orpheus UI Frontend

React 18 + TypeScript + Tailwind CSS frontend for the Orpheus wildlife monitoring interface.

## Quick Start

```bash
# Install dependencies
make install

# Run dev server (port 5173, proxies API to backend on 8082)
make dev

# Run tests
make test

# Build for production
make build
```

## Tech Stack

- **React 18** with TypeScript
- **Tailwind CSS** for styling
- **Vite** for dev server and builds
- **React Router** for navigation
- **TanStack React Query** for data fetching
- **Recharts** for data visualization
- **Vitest** for unit tests
- **Playwright** for E2E tests

## Pages

| Page | Description |
| ------------- | ----------- |
| Dashboard | System overview and health status |
| Cameras | Live camera feeds and snapshots |
| Audio | Audio detection events |
| Video | Video motion events |
| Birds | BirdNET detection results |
| Crows | Crow behavioral analysis |
| Entities | Detection entity management |
| Media | Audio/video media browser |
| Diagnostics | System health diagnostics |
| Settings | User and system settings |

## Development

```bash
make install        # Install npm dependencies
make dev            # Vite dev server (port 5173)
make build          # Production build to dist/
make test           # Run Vitest unit tests
make test-coverage  # Tests with coverage
make lint           # Run ESLint
make format         # ESLint with --fix
make clean          # Remove node_modules and dist
```

## Testing

- **Unit tests**: Vitest + React Testing Library (`make test`)
- **E2E tests**: Playwright (`npm run test:e2e`)
- **Type checking**: `npm run type-check`

## Related Documentation

- [Orpheus UI Overview](../../../docs/ORPHEUS_UI.md) — full UI documentation
- [Parent README](../README.md) — combined backend/frontend setup
- [UI Instructions](../../../docs/copilot-workspace-instructions/orpheus-ui.instructions.md) — development patterns
