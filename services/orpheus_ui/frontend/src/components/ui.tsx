/**
 * Shared UI components for consistent styling across the application.
 * 
 * These components implement common patterns used throughout the UI
 * to ensure consistency and reduce code duplication.
 */
import { type ReactNode } from 'react'
import { CheckCircle, XCircle, AlertCircle, ChevronLeft, ChevronRight, type LucideIcon } from 'lucide-react'
import { cn } from '../lib/utils'

/**
 * Loading spinner component.
 * Used as a placeholder while data is being fetched.
 */
export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center justify-center h-64', className)}>
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
    </div>
  )
}

/**
 * Page header with title and optional description.
 */
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children?: ReactNode
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {description && <p className="text-slate-400 mt-1">{description}</p>}
      </div>
      {children}
    </div>
  )
}

/**
 * Error message display for failed data fetches.
 */
export function ErrorMessage({
  title,
  description,
  message = 'Failed to load data',
}: {
  title: string
  description?: string
  message?: string
}) {
  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} />
      <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-center">
        <p className="text-red-400">{message}</p>
      </div>
    </div>
  )
}

/**
 * Card container with consistent styling.
 */
export function Card({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('bg-slate-800/50 rounded-xl border border-slate-700 p-6', className)}>
      {children}
    </div>
  )
}

/**
 * Card header with icon and title.
 */
export function CardHeader({
  title,
  icon: Icon,
  iconColor = 'blue',
}: {
  title: string
  icon: LucideIcon
  iconColor?: 'blue' | 'green' | 'amber' | 'red' | 'purple'
}) {
  const colorClasses = {
    blue: 'bg-blue-500/20 text-blue-400',
    green: 'bg-green-500/20 text-green-400',
    amber: 'bg-amber-500/20 text-amber-400',
    red: 'bg-red-500/20 text-red-400',
    purple: 'bg-purple-500/20 text-purple-400',
  }

  return (
    <div className="flex items-center gap-3 mb-4">
      <div className={cn('p-2 rounded-lg', colorClasses[iconColor])}>
        <Icon className="w-5 h-5" />
      </div>
      <h3 className="text-lg font-medium text-white">{title}</h3>
    </div>
  )
}

/**
 * Stat card for displaying a single metric.
 */
export function StatCard({
  title,
  value,
  unit,
  icon: Icon,
  color = 'blue',
}: {
  title: string
  value: string | number
  unit?: string
  icon: LucideIcon
  color?: 'blue' | 'green' | 'amber' | 'red' | 'purple'
}) {
  const colorClasses = {
    blue: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    green: 'bg-green-500/20 text-green-400 border-green-500/30',
    amber: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    red: 'bg-red-500/20 text-red-400 border-red-500/30',
    purple: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  }

  return (
    <Card>
      <div className="flex items-center gap-3 mb-4">
        <div className={cn('p-2 rounded-lg border', colorClasses[color])}>
          <Icon className="w-5 h-5" />
        </div>
        <h3 className="text-sm font-medium text-slate-400">{title}</h3>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-3xl font-bold text-white">{value}</span>
        {unit && <span className="text-slate-400">{unit}</span>}
      </div>
    </Card>
  )
}

/**
 * Status indicator icon based on status string.
 */
export type StatusType = 'running' | 'ok' | 'healthy' | 'stopped' | 'error' | 'offline' | 'unknown'

export function StatusIcon({ status }: { status: string }) {
  const normalizedStatus = status.toLowerCase()
  
  if (['running', 'ok', 'healthy', 'active', 'connected'].includes(normalizedStatus)) {
    return <CheckCircle className="w-5 h-5 text-green-400" />
  }
  if (['stopped', 'error', 'offline', 'failed', 'disconnected'].includes(normalizedStatus)) {
    return <XCircle className="w-5 h-5 text-red-400" />
  }
  return <AlertCircle className="w-5 h-5 text-amber-400" />
}

/**
 * Get the appropriate text color class for a status.
 */
export function getStatusColor(status: string): string {
  const normalizedStatus = status.toLowerCase()
  
  if (['running', 'ok', 'healthy', 'active', 'connected'].includes(normalizedStatus)) {
    return 'text-green-400'
  }
  if (['stopped', 'error', 'offline', 'failed', 'disconnected'].includes(normalizedStatus)) {
    return 'text-red-400'
  }
  return 'text-amber-400'
}

/**
 * Status badge combining icon and text.
 */
export function StatusBadge({ status }: { status: string }) {
  return (
    <div className="flex items-center gap-2">
      <StatusIcon status={status} />
      <span className={cn('text-sm capitalize', getStatusColor(status))}>
        {status}
      </span>
    </div>
  )
}

/**
 * Empty state placeholder.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon
  title: string
  description?: string
}) {
  return (
    <Card className="p-12 text-center">
      <Icon className="w-12 h-12 text-slate-600 mx-auto mb-4" />
      <p className="text-slate-400">{title}</p>
      {description && <p className="text-slate-500 text-sm mt-1">{description}</p>}
    </Card>
  )
}

/**
 * Progress bar component.
 */
export function ProgressBar({
  value,
  max = 100,
  color = 'blue',
  showLabel = false,
}: {
  value: number
  max?: number
  color?: 'blue' | 'green' | 'amber' | 'red' | 'purple'
  showLabel?: boolean
}) {
  const percent = Math.min((value / max) * 100, 100)
  
  const colorClasses = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    amber: 'bg-amber-500',
    red: 'bg-red-500',
    purple: 'bg-purple-500',
  }

  return (
    <div>
      {showLabel && (
        <div className="flex justify-between text-sm mb-1">
          <span className="text-slate-400">{value}</span>
          <span className="text-slate-500">{percent.toFixed(1)}%</span>
        </div>
      )}
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all', colorClasses[color])}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  )
}

/**
 * Pagination controls: Previous / Page N of M / Next.
 * Only renders when totalPages > 1.
 */
export function Pagination({
  page,
  totalPages,
  onPageChange,
}: {
  page: number
  totalPages: number
  onPageChange: (p: number) => void
}) {
  if (totalPages <= 1) return null
  return (
    <div className="flex items-center justify-center gap-4 pt-4">
      <button
        onClick={() => onPageChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        aria-label="Previous"
        className="flex items-center gap-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-lg transition-colors"
      >
        <ChevronLeft className="w-4 h-4" />
        Previous
      </button>
      <span className="text-sm text-slate-400">Page {page} of {totalPages}</span>
      <button
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        aria-label="Next"
        className="flex items-center gap-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-lg transition-colors"
      >
        Next
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  )
}
