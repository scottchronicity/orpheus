/**
 * Tests for shared UI components.
 * 
 * These tests verify component behavior and rendering.
 * Focus on semantics and accessibility, not CSS implementation details.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Activity, Camera } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  Card,
  CardHeader,
  StatCard,
  StatusIcon,
  StatusBadge,
  getStatusColor,
  EmptyState,
  ProgressBar,
} from '../src/components/ui'

describe('LoadingSpinner', () => {
  it('renders a spinning indicator', () => {
    const { container } = render(<LoadingSpinner />)
    // Check for animation class (implementation detail but acceptable for loading states)
    expect(container.querySelector('[class*="animate"]')).toBeInTheDocument()
  })
})

describe('PageHeader', () => {
  it('renders title as heading', () => {
    render(<PageHeader title="Page Title" />)
    expect(screen.getByRole('heading', { name: 'Page Title' })).toBeInTheDocument()
  })

  it('renders description text when provided', () => {
    render(<PageHeader title="Title" description="Page description" />)
    expect(screen.getByText('Page description')).toBeInTheDocument()
  })

  it('renders action children', () => {
    render(
      <PageHeader title="Title">
        <button>Action Button</button>
      </PageHeader>
    )
    expect(screen.getByRole('button', { name: 'Action Button' })).toBeInTheDocument()
  })
})

describe('ErrorMessage', () => {
  it('renders title', () => {
    render(<ErrorMessage title="Error Title" />)
    expect(screen.getByText('Error Title')).toBeInTheDocument()
  })

  it('renders default error message', () => {
    render(<ErrorMessage title="Error" />)
    expect(screen.getByText('Failed to load data')).toBeInTheDocument()
  })

  it('renders custom message when provided', () => {
    render(<ErrorMessage title="Error" message="Custom error message" />)
    expect(screen.getByText('Custom error message')).toBeInTheDocument()
  })
})

describe('Card', () => {
  it('renders children', () => {
    render(<Card>Card content</Card>)
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })
})

describe('CardHeader', () => {
  it('renders title', () => {
    render(<CardHeader title="Section Title" icon={Activity} />)
    expect(screen.getByText('Section Title')).toBeInTheDocument()
  })
})

describe('StatCard', () => {
  it('renders title and value', () => {
    render(<StatCard title="CPU Usage" value={75} icon={Activity} />)
    expect(screen.getByText('CPU Usage')).toBeInTheDocument()
    expect(screen.getByText('75')).toBeInTheDocument()
  })

  it('renders unit when provided', () => {
    render(<StatCard title="Memory" value={50} unit="%" icon={Activity} />)
    expect(screen.getByText('%')).toBeInTheDocument()
  })

  it('handles string values', () => {
    render(<StatCard title="Uptime" value="5d 3h" icon={Activity} />)
    expect(screen.getByText('5d 3h')).toBeInTheDocument()
  })
})

describe('StatusIcon', () => {
  it('renders for running status', () => {
    const { container } = render(<StatusIcon status="running" />)
    expect(container.firstChild).toBeInTheDocument()
  })

  it('renders for stopped status', () => {
    const { container } = render(<StatusIcon status="stopped" />)
    expect(container.firstChild).toBeInTheDocument()
  })

  it('renders for unknown status', () => {
    const { container } = render(<StatusIcon status="pending" />)
    expect(container.firstChild).toBeInTheDocument()
  })
})

describe('getStatusColor', () => {
  it('returns appropriate color for positive statuses', () => {
    const positiveStatuses = ['running', 'ok', 'healthy', 'active', 'connected']
    positiveStatuses.forEach(status => {
      expect(getStatusColor(status)).toContain('green')
    })
  })

  it('returns appropriate color for negative statuses', () => {
    const negativeStatuses = ['stopped', 'error', 'offline', 'failed']
    negativeStatuses.forEach(status => {
      expect(getStatusColor(status)).toContain('red')
    })
  })

  it('returns amber for unknown statuses', () => {
    expect(getStatusColor('pending')).toContain('amber')
    expect(getStatusColor('unknown')).toContain('amber')
  })
})

describe('StatusBadge', () => {
  it('renders status text', () => {
    render(<StatusBadge status="running" />)
    expect(screen.getByText('running')).toBeInTheDocument()
  })
})

describe('EmptyState', () => {
  it('renders title', () => {
    render(<EmptyState icon={Camera} title="No cameras" />)
    expect(screen.getByText('No cameras')).toBeInTheDocument()
  })

  it('renders description when provided', () => {
    render(<EmptyState icon={Camera} title="Empty" description="Add items" />)
    expect(screen.getByText('Add items')).toBeInTheDocument()
  })
})

describe('ProgressBar', () => {
  it('renders progress element', () => {
    const { container } = render(<ProgressBar value={50} />)
    expect(container.firstChild).toBeInTheDocument()
  })

  it('shows label when enabled', () => {
    render(<ProgressBar value={75} showLabel />)
    expect(screen.getByText('75')).toBeInTheDocument()
  })
})
