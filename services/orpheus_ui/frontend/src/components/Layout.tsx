import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { fetchWithAuth } from '../lib/utils'
import {
  Bird,
  Brain,
  LayoutDashboard,
  Camera,
  Mic,
  Video,
  Settings,
  Terminal,
  Waves,
  Network,
  LogOut,
  Menu,
  X,
  ChevronDown,
  User,
} from 'lucide-react'
import { OrpheusMark } from './OrpheusMark'
import { cn } from '../lib/utils'

interface LayoutProps {
  children: React.ReactNode
}

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Entities', href: '/entities', icon: Brain },
  { name: 'Birds', href: '/birds', icon: Bird },
  { name: 'Crows', href: '/crows', icon: Bird },  // Crow-specific analysis
  { name: 'Audio Events', href: '/audio-events', icon: Waves },  // General-purpose AudioSet tagger
  { name: 'Equivalences', href: '/equivalences', icon: Network },  // Cross-classifier identity review
  { name: 'Cameras', href: '/cameras', icon: Camera },
  { name: 'Audio', href: '/audio', icon: Mic },
  { name: 'Video', href: '/video', icon: Video },
  { name: 'Media', href: '/media', icon: Video },  // Historical media
  { name: 'Diagnostics', href: '/diagnostics', icon: Terminal },
  { name: 'Settings', href: '/settings', icon: Settings },
]

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const location = useLocation()
  const { user, logout } = useAuth()

  // Pending-equivalence-count badge on the Equivalences nav item.
  // Polls /api/equivalences every 2 minutes. Auth-gated by fetchWithAuth.
  const { data: equivalences } = useQuery<{ counts?: { pending_review?: number } }>({
    queryKey: ['equivalences-counts'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/equivalences')
      if (!res.ok) return { counts: { pending_review: 0 } }
      return res.json()
    },
    enabled: !!user,  // Only poll when the user is authed.
    refetchInterval: 120_000,
    staleTime: 60_000,
  })
  const pendingReviewCount = equivalences?.counts?.pending_review ?? 0

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar — flex column so the nav can scroll and the User
          section stays pinned at the bottom without overlapping the
          last nav items on short viewports: an absolutely-positioned
          footer would intercept pointer events for the bottom-most
          nav links (e.g. Settings) once the nav outgrows the
          viewport. */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 bg-slate-800 border-r border-slate-700 transform transition-transform duration-200 ease-in-out lg:translate-x-0 flex flex-col',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-700">
          <div className="p-2 rounded-lg bg-blue-500/20">
            <OrpheusMark className="w-6 h-6 text-blue-400" />
          </div>
          <span className="text-xl font-bold text-white">Orpheus</span>
          <button
            className="ml-auto lg:hidden p-1 text-slate-400 hover:text-white"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation — flex-1 + overflow-y-auto so it scrolls when
            the item count outgrows the viewport (12 items today;
            growing). */}
        <nav className="flex-1 overflow-y-auto p-4 space-y-1">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href
            const showPendingBadge =
              item.href === '/equivalences' && pendingReviewCount > 0
            return (
              <Link
                key={item.name}
                to={item.href}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-500/20 text-blue-400'
                    : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                )}
                onClick={() => setSidebarOpen(false)}
              >
                <item.icon className="w-5 h-5" />
                <span className="flex-1">{item.name}</span>
                {showPendingBadge && (
                  <span
                    className="ml-auto inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-amber-500/30 text-amber-200 text-xs font-medium"
                    title={`${pendingReviewCount} equivalence proposal${
                      pendingReviewCount === 1 ? '' : 's'
                    } awaiting review`}
                  >
                    {pendingReviewCount}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>

        {/* User section — pinned to the bottom via flex layout
            (was ``absolute bottom-0`` which intercepted clicks on
            the last nav items once the list outgrew the viewport). */}
        <div className="p-4 border-t border-slate-700">
          <div className="relative">
            <button
              aria-label="User menu"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors"
              onClick={() => setUserMenuOpen(!userMenuOpen)}
            >
              <div className="p-1.5 rounded-full bg-slate-700">
                <User className="w-4 h-4" />
              </div>
              <div className="flex-1 text-left">
                <p className="text-sm text-white">{user?.display_name || user?.email}</p>
                <p className="text-xs text-slate-500 capitalize">{user?.role}</p>
              </div>
              <ChevronDown className={cn('w-4 h-4 transition-transform', userMenuOpen && 'rotate-180')} />
            </button>

            {userMenuOpen && (
              <div className="absolute bottom-full left-0 right-0 mb-2 bg-slate-800 border border-slate-700 rounded-lg shadow-lg overflow-hidden">
                <button
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-red-400 hover:bg-slate-700/50 transition-colors"
                  onClick={() => {
                    logout()
                    setUserMenuOpen(false)
                  }}
                >
                  <LogOut className="w-4 h-4" />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="lg:pl-64">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex items-center gap-4 px-4 py-3 bg-slate-900/80 backdrop-blur border-b border-slate-800 lg:px-6">
          <button
            aria-label="Open menu"
            className="p-2 text-slate-400 hover:text-white lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex-1" />
          <div className="text-sm text-slate-500">
            Wildlife Monitoring System
          </div>
        </header>

        {/* Page content */}
        <main className="p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
