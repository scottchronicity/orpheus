import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Settings, User, Shield, Database, Bell, Code, ChevronDown, ChevronRight } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { fetchWithAuth } from '../lib/utils'
import { Card, CardHeader, PageHeader } from '../components/ui'

/**
 * Normalize config value to a Record for display.
 */
function normalizeConfigValue(value: unknown): Record<string, unknown> {
  if (typeof value === 'object' && value !== null) {
    return value as Record<string, unknown>
  }
  return { value }
}

/**
 * Collapsible JSON viewer for configuration data.
 */
function ConfigSection({ title, data }: { title: string; data: Record<string, unknown> }) {
  const [isExpanded, setIsExpanded] = useState(false)

  return (
    <div className="border-b border-slate-700 last:border-b-0">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between py-3 text-left hover:bg-slate-700/30 px-2 rounded transition-colors"
      >
        <span className="text-white font-medium">{title}</span>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-slate-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400" />
        )}
      </button>
      {isExpanded && (
        <pre className="text-xs text-slate-300 bg-slate-900 p-3 rounded-lg mb-3 overflow-x-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const { user } = useAuth()

  // Fetch runtime configuration
  const { data: debugConfig, isLoading: configLoading } = useQuery<Record<string, unknown>>({
    queryKey: ['debug-config'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/debug/config')
      return res.json()
    },
    staleTime: 60000, // Cache for 1 minute
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="System configuration and preferences" />

      {/* User Info */}
      <Card>
        <CardHeader title="Account" icon={User} iconColor="blue" />
        <div className="space-y-3">
          <div className="flex justify-between py-2 border-b border-slate-700">
            <span className="text-slate-400">Email</span>
            <span className="text-white">{user?.email}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-slate-700">
            <span className="text-slate-400">Display Name</span>
            <span className="text-white">{user?.display_name || '-'}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-slate-700">
            <span className="text-slate-400">Role</span>
            <span className="text-white capitalize">{user?.role}</span>
          </div>
          <div className="flex justify-between py-2">
            <span className="text-slate-400">Status</span>
            <span className={user?.is_active ? 'text-green-400' : 'text-red-400'}>
              {user?.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
        </div>
      </Card>

      {/* Placeholder Settings Sections */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader title="Security" icon={Shield} iconColor="purple" />
          <p className="text-slate-500 text-sm">
            Password management and two-factor authentication settings will be available here.
          </p>
          <button
            disabled
            className="mt-4 px-4 py-2 bg-slate-700 text-slate-400 rounded-lg cursor-not-allowed"
          >
            Coming Soon
          </button>
        </Card>

        <Card>
          <CardHeader title="Notifications" icon={Bell} iconColor="green" />
          <p className="text-slate-500 text-sm">
            Configure alert preferences and notification channels.
          </p>
          <button
            disabled
            className="mt-4 px-4 py-2 bg-slate-700 text-slate-400 rounded-lg cursor-not-allowed"
          >
            Coming Soon
          </button>
        </Card>

        <Card>
          <CardHeader title="Data Management" icon={Database} iconColor="amber" />
          <p className="text-slate-500 text-sm">
            Configure data retention policies and storage settings.
          </p>
          <button
            disabled
            className="mt-4 px-4 py-2 bg-slate-700 text-slate-400 rounded-lg cursor-not-allowed"
          >
            Coming Soon
          </button>
        </Card>

        <Card>
          <CardHeader title="System" icon={Settings} iconColor="blue" />
          <p className="text-slate-500 text-sm">
            Advanced system configuration and diagnostics.
          </p>
          <button
            disabled
            className="mt-4 px-4 py-2 bg-slate-700 text-slate-400 rounded-lg cursor-not-allowed"
          >
            Coming Soon
          </button>
        </Card>
      </div>

      {/* Runtime Configuration */}
      <Card>
        <CardHeader title="Runtime Configuration" icon={Code} iconColor="green" />
        <p className="text-slate-500 text-sm mb-4">
          Live configuration values from orpheus.yaml merged with defaults and environment overrides.
        </p>
        {configLoading ? (
          <p className="text-slate-400 text-sm">Loading configuration...</p>
        ) : debugConfig ? (
          <div className="space-y-1">
            {Object.entries(debugConfig).map(([key, value]) => (
              <ConfigSection
                key={key}
                title={key}
                data={normalizeConfigValue(value)}
              />
            ))}
          </div>
        ) : (
          <p className="text-slate-400 text-sm">Configuration unavailable</p>
        )}
      </Card>

      {/* Version Info */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-4">System Information</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-slate-400">UI Version</p>
            <p className="text-white font-medium">0.1.0</p>
          </div>
          <div>
            <p className="text-slate-400">Backend</p>
            <p className="text-white font-medium">FastAPI</p>
          </div>
          <div>
            <p className="text-slate-400">Frontend</p>
            <p className="text-white font-medium">React 18</p>
          </div>
          <div>
            <p className="text-slate-400">Auth</p>
            <p className="text-white font-medium">FastAPI-Users</p>
          </div>
        </div>
      </Card>
    </div>
  )
}
