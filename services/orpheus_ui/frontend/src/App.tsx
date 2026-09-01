import { Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Entities from './pages/Entities'
import Birds from './pages/Birds'
import Crows from './pages/Crows'
import AudioEvents from './pages/AudioEvents'
import Equivalences from './pages/Equivalences'
import Cameras from './pages/Cameras'
import Audio from './pages/Audio'
import Video from './pages/Video'
import Media from './pages/Media'
import Settings from './pages/Settings'
import DiagnosticsPage from './pages/Diagnostics'
import Layout from './components/Layout'

/**
 * ProtectedLayout wraps the Layout with authentication check.
 * Uses Outlet to render child routes, which is the React Router v6 pattern
 * for nested routes. This ensures navigation between pages works correctly.
 */
function ProtectedLayout() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    )
  }

  if (!isAuthenticated) {
    // Carry the original ``location`` (path + search + hash) through the
    // login bounce so that bookmarked URLs with filter params survive an
    // auth round-trip. Login reads ``location.state.from`` and replays it.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return (
    <Layout>
      <Outlet />
    </Layout>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      
      {/* Protected routes with shared Layout */}
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/entities" element={<Entities />} />
        <Route path="/birds" element={<Birds />} />
        <Route path="/crows" element={<Crows />} />
        <Route path="/audio-events" element={<AudioEvents />} />
        <Route path="/equivalences" element={<Equivalences />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route path="/audio" element={<Audio />} />
        <Route path="/video" element={<Video />} />
        <Route path="/media" element={<Media />} />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
