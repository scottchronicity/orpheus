import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import App from './App'
import { loadServedPollInterval } from './config'
import './index.css'

// Query-cache defaults: polling is OPT-IN, not opt-out. Pages that
// genuinely need a live refresh (Dashboard, Birds, Crows, Entities,
// AudioEvents, Diagnostics, Cameras, etc.) explicitly set their own
// ``refetchInterval`` from ``config.POLLING_INTERVALS``. A blanket
// 5-second refetch silently turned every mounted query into a poller —
// including ones backing rarely-changing data (Equivalences,
// Settings.debug-config, AudioPlaybackControl.sounds) and amplified
// DB load disproportionate to the value the user actually got from
// the freshness. ``staleTime`` is bumped to 30s so cross-component
// fetches of the same key (e.g. dashboards mounting multiple panels)
// reuse the cache.
//
// ``refetchOnWindowFocus`` is LEFT at react-query's default of
// ``true``. Combined with the above, this gives non-polling pages
// like /equivalences a sane freshness story: they don't background-
// poll, but tabbing back to a stale page DOES trigger a refresh.
// Without this, a multi-operator workflow on /equivalences would see
// indefinitely-stale lists because no other mechanism would re-fetch.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchInterval: false,
      refetchIntervalInBackground: false,
    },
  },
})

function renderApp() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </React.StrictMode>,
  )
}

// Read the operator-served polling base (GET /api/config → poll_interval, ms)
// BEFORE the first render so pages that reference ``POLLING_INTERVALS.X`` pick
// it up. ``/api/config`` is a public, unauthenticated, fast local endpoint.
// Any failure (offline, 500, malformed, or a response stalled past the
// 2.5s deadline — see CONFIG_FETCH_TIMEOUT_MS) is swallowed and we render
// with the hardcoded defaults — so behavior is unchanged out of the box, the
// dead ``dashboard_poll_interval`` knob takes effect when set, and a hung
// backend can never leave the operator on a blank page.
async function bootstrap() {
  await loadServedPollInterval()
  renderApp()
}

void bootstrap()
