/**
 * Chart components using Recharts
 * 
 * Simple, clean chart implementations for data visualization.
 * Focused on reliability and readability over complexity.
 */
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
  ScatterChart,
  Scatter,
  ZAxis,
  AreaChart,
  Area,
} from 'recharts'
import { scatterXDomain } from './chartDomain'
import { formatBytes } from '../lib/utils'

// Color palette for charts
const COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // purple
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
]

interface HourlyData {
  hour: number
  count: number
}

interface BirdDetectionPoint {
  timestamp: string
  confidence: number
  species_common: string
}

/**
 * Bar chart for hourly activity data
 */
export function HourlyActivityChart({ data }: { data: HourlyData[] }) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No hourly data available</div>
  }

  // Format hour labels
  const formattedData = data.map(d => ({
    ...d,
    label: `${d.hour}:00`,
  }))

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={formattedData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis 
          dataKey="hour" 
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => value % 4 === 0 ? `${value}` : ''}
        />
        <YAxis 
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            color: '#f1f5f9',
          }}
          labelFormatter={(value) => `${value}:00`}
        />
        <Bar dataKey="count" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/**
 * Pie chart for distribution data (call types, age, etc)
 */
export function DistributionPieChart({ 
  data, 
  title 
}: { 
  data: Record<string, number>
  title?: string 
}) {
  if (!data || Object.keys(data).length === 0) {
    return <div className="text-slate-500 text-center py-8">No data available</div>
  }

  const chartData = Object.entries(data)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8) // Limit to top 8 for readability

  return (
    <div>
      {title && <h3 className="text-sm font-medium text-slate-400 mb-2">{title}</h3>}
      <ResponsiveContainer width="100%" height={250}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={40}
            outerRadius={80}
            paddingAngle={2}
            dataKey="value"
            nameKey="name"
          >
            {chartData.map((_, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#f1f5f9',
            }}
          />
          <Legend 
            wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

/**
 * Scatter plot for time vs confidence visualization
 * Used for bird detections to show patterns over time
 */
export function ConfidenceScatterChart({
  data,
  maxPoints = 500,
  startDate,
  endDate,
}: {
  data: BirdDetectionPoint[]
  maxPoints?: number
  startDate?: string
  endDate?: string
}) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No detection data available</div>
  }

  // Sample data if too many points for performance
  const sampledData = data.length > maxPoints
    ? data.filter((_, i) => i % Math.ceil(data.length / maxPoints) === 0)
    : data

  // Group by species and assign colors
  const speciesSet = new Set(sampledData.map(d => d.species_common))
  const speciesColors: Record<string, string> = {}
  Array.from(speciesSet).forEach((species, i) => {
    speciesColors[species] = COLORS[i % COLORS.length]
  })

  // Transform data for scatter plot
  const chartData = sampledData.map(d => ({
    x: new Date(d.timestamp).getTime(),
    y: d.confidence * 100,
    species: d.species_common,
    color: speciesColors[d.species_common],
  }))

  // Use selected date range for X-axis domain when provided.
  // Use local-time boundaries (no 'Z' suffix) so the domain aligns with the
  // local calendar days shown by toLocaleDateString() tick labels.
  // Clamp the X-axis to 'now' so the right side isn't an empty future gap.
  const xDomain = scatterXDomain(startDate, endDate)

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          type="number"
          dataKey="x"
          domain={xDomain}
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => new Date(value).toLocaleDateString()}
        />
        <YAxis
          type="number"
          dataKey="y"
          domain={[0, 100]}
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => `${value}%`}
        />
        <ZAxis range={[30, 30]} />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload || payload.length === 0) return null
            const data = payload[0].payload
            return (
              <div
                style={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#f1f5f9',
                  padding: '8px 12px',
                }}
              >
                <p style={{ fontWeight: 600, marginBottom: '4px' }}>{data.species}</p>
                <p style={{ fontSize: '12px', color: '#94a3b8' }}>
                  {new Date(data.x).toLocaleString()}
                </p>
                <p style={{ fontSize: '14px', marginTop: '4px' }}>
                  Confidence: {data.y.toFixed(1)}%
                </p>
              </div>
            )
          }}
        />
        <Scatter
          data={chartData}
          fill="#3b82f6"
        >
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.color} />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}

/**
 * Scatter plot for verified bird entities over time.
 * Shows each entity (deduplicated bird) as a colored dot based on species.
 * Used in the "Clean Signal" verified entities section.
 */
export function EntityScatterChart({
  data,
  maxPoints = 500,
  startDate,
  endDate,
}: {
  data: Array<{ timestamp: string; common_name: string; species_code: string; confidence: number }>
  maxPoints?: number
  startDate?: string
  endDate?: string
}) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No entity data available</div>
  }

  // Sample data if too many points for performance
  const sampledData = data.length > maxPoints
    ? data.filter((_, i) => i % Math.ceil(data.length / maxPoints) === 0)
    : data

  // Group by species and assign colors
  const speciesSet = new Set(sampledData.map(d => d.common_name || d.species_code))
  const speciesColors: Record<string, string> = {}
  Array.from(speciesSet).forEach((species, i) => {
    speciesColors[species] = COLORS[i % COLORS.length]
  })

  // Transform data for scatter plot
  const chartData = sampledData.map(d => {
    const speciesName = d.common_name || d.species_code
    return {
      x: new Date(d.timestamp).getTime(),
      y: d.confidence * 100,
      species: speciesName,
      color: speciesColors[speciesName],
    }
  })

  // Use selected date range for X-axis domain when provided.
  // Use local-time boundaries (no 'Z' suffix) so the domain aligns with the
  // local calendar days shown by toLocaleDateString() tick labels.
  // Clamp the X-axis to 'now' so the right side isn't an empty future gap.
  const xDomain = scatterXDomain(startDate, endDate)

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          type="number"
          dataKey="x"
          domain={xDomain}
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => new Date(value).toLocaleDateString()}
        />
        <YAxis
          type="number"
          dataKey="y"
          domain={[0, 100]}
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => `${value}%`}
        />
        <ZAxis range={[50, 50]} />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload || payload.length === 0) return null
            const data = payload[0].payload
            return (
              <div
                style={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#f1f5f9',
                  padding: '8px 12px',
                }}
              >
                <p style={{ fontWeight: 600, marginBottom: '4px' }}>{data.species}</p>
                <p style={{ fontSize: '12px', color: '#94a3b8' }}>
                  {new Date(data.x).toLocaleString()}
                </p>
                <p style={{ fontSize: '14px', marginTop: '4px' }}>
                  Confidence: {data.y.toFixed(1)}%
                </p>
              </div>
            )
          }}
        />
        <Scatter data={chartData} fill="#3b82f6">
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.color} />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}

/**
 * Simple horizontal bar chart for species counts
 */
export function SpeciesBarChart({ 
  data 
}: { 
  data: { species: string; count: number }[] 
}) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No species data available</div>
  }

  // Top 10 species
  const chartData = data.slice(0, 10)

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart 
        data={chartData} 
        layout="vertical"
        margin={{ top: 10, right: 10, left: 80, bottom: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
        <XAxis 
          type="number"
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
        />
        <YAxis 
          type="category"
          dataKey="species"
          stroke="#64748b"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          width={75}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            color: '#f1f5f9',
          }}
        />
        <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/**
 * Daily activity bar chart showing count per calendar date.
 * Designed for multi-day date ranges — shows trends over days, not hours.
 * Unlike HourlyActivityChart (which groups by hour-of-day), this shows
 * one bar per date so the full selected range is always visible.
 */
export function DailyActivityChart({
  data,
}: {
  data: { date: string; count: number }[]
}) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No daily data available</div>
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="date"
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => {
            const d = new Date(value + 'T12:00:00Z')
            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
          }}
          interval={Math.max(0, Math.ceil(data.length / 10) - 1)}
          angle={-30}
          textAnchor="end"
        />
        <YAxis stroke="#64748b" tick={{ fill: '#64748b', fontSize: 10 }} />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            color: '#f1f5f9',
          }}
          labelFormatter={(value) => {
            const d = new Date(value + 'T12:00:00Z')
            return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
          }}
        />
        <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/**
 * Scatter plot for crow detections over time.
 * Shows each detection as a dot (x=timestamp, y=confidence), colored by call type.
 */
export function CrowScatterChart({
  data,
  startDate,
  endDate,
}: {
  data: Array<{ timestamp: string; call_type: string; confidence: number | null }>
  startDate?: string
  endDate?: string
}) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No crow detections in this date range — try 7 Days or 30 Days</div>
  }

  const filtered = data.filter((d) => d.confidence != null)
  if (filtered.length === 0) {
    return <div className="text-slate-500 text-center py-8">No confidence scores recorded for these detections</div>
  }

  const callTypeSet = new Set(filtered.map((d) => d.call_type))
  const callTypeColors: Record<string, string> = {}
  Array.from(callTypeSet).forEach((ct, i) => {
    callTypeColors[ct] = COLORS[i % COLORS.length]
  })

  const chartData = filtered.map((d) => ({
    x: new Date(d.timestamp).getTime(),
    y: (d.confidence as number) * 100,
    label: d.call_type,
    color: callTypeColors[d.call_type],
  }))

  // Use local-time boundaries (no 'Z' suffix) so the domain aligns with the
  // local calendar days shown by toLocaleDateString() tick labels.
  // Clamp the X-axis to 'now' so the right side isn't an empty future gap.
  const xDomain = scatterXDomain(startDate, endDate)

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          type="number"
          dataKey="x"
          domain={xDomain}
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => new Date(value).toLocaleDateString()}
        />
        <YAxis
          type="number"
          dataKey="y"
          domain={[0, 100]}
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value) => `${value}%`}
        />
        <ZAxis range={[30, 30]} />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload || payload.length === 0) return null
            const d = payload[0].payload
            return (
              <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#f1f5f9', padding: '8px 12px' }}>
                <p style={{ fontWeight: 600, marginBottom: '4px', textTransform: 'capitalize' }}>{d.label}</p>
                <p style={{ fontSize: '12px', color: '#94a3b8' }}>{new Date(d.x).toLocaleString()}</p>
                <p style={{ fontSize: '14px', marginTop: '4px' }}>Confidence: {d.y.toFixed(1)}%</p>
              </div>
            )
          }}
        />
        <Scatter data={chartData} fill="#3b82f6">
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.color} />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}

/**
 * Stacked bar chart showing category breakdown by hour
 * Used for call types or ages across time of day
 */
export function HourlyStackedBarChart({ 
  data,
  title,
}: { 
  data: { hour: number; [key: string]: number }[]
  title?: string
}) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-center py-8">No hourly data available</div>
  }

  // Get all unique category keys (excluding 'hour')
  const categories = Array.from(
    new Set(data.flatMap(d => Object.keys(d).filter(k => k !== 'hour')))
  ).sort()

  if (categories.length === 0) {
    return <div className="text-slate-500 text-center py-8">No categories to display</div>
  }

  return (
    <div>
      {title && <h3 className="text-sm font-medium text-slate-400 mb-2">{title}</h3>}
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis 
            dataKey="hour" 
            stroke="#64748b"
            tick={{ fill: '#64748b', fontSize: 10 }}
            tickFormatter={(value) => value % 4 === 0 ? `${value}` : ''}
          />
          <YAxis 
            stroke="#64748b"
            tick={{ fill: '#64748b', fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#f1f5f9',
            }}
            labelFormatter={(value) => `${value}:00`}
          />
          <Legend 
            wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }}
          />
          {categories.map((category, index) => (
            <Bar
              key={category}
              dataKey={category}
              stackId="stack"
              fill={COLORS[index % COLORS.length]}
              radius={index === categories.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

interface StoragePoint {
  day: string
  free_bytes: number | null
  total_bytes?: number | null
}

/**
 * Free-space-over-time area chart for one storage volume. The Y axis is in
 * GiB; the tooltip shows the exact free size per day.
 */
export function StorageTrendChart({ series }: { series: StoragePoint[] }) {
  const points = (series ?? []).filter((p) => p.free_bytes !== null)
  if (points.length === 0) {
    return (
      <div className="text-slate-500 text-center py-8 text-sm">
        No storage history yet — a point is recorded each day.
      </div>
    )
  }

  const GIB = 1024 ** 3
  const data = points.map((p) => ({
    day: p.day,
    freeGiB: (p.free_bytes as number) / GIB,
    free_bytes: p.free_bytes as number,
  }))

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <defs>
          <linearGradient id="freeSpaceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.5} />
            <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="day"
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          tickFormatter={(value: string) => value.slice(5)}
        />
        <YAxis
          stroke="#64748b"
          tick={{ fill: '#64748b', fontSize: 10 }}
          width={48}
          tickFormatter={(value: number) => `${value.toFixed(0)}G`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            color: '#f1f5f9',
          }}
          formatter={(value) => [formatBytes((value as number) * GIB), 'Free']}
        />
        <Area
          type="monotone"
          dataKey="freeGiB"
          stroke="#06b6d4"
          fill="url(#freeSpaceFill)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
