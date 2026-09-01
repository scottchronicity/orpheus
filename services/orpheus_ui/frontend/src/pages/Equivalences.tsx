import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchWithAuth } from '../lib/utils'
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  Sparkles,
  RefreshCw,
} from 'lucide-react'
import {
  Card,
  LoadingSpinner,
  PageHeader,
  StatCard,
  ErrorMessage,
} from '../components/ui'

/**
 * Layer 3 — TaxonomyEquivalence review page.
 *
 * Surfaces what the auto-discovery worker has learned about cross-
 * classifier identity (BirdNET ↔ PANNs etc.) and provides accept /
 * reject controls for pending proposals.
 *
 * See docs/designs/cross-classifier-identity.md §5.
 */

interface TaxRef {
  namespace: string
  id: string
}

interface AcceptedRow {
  a: TaxRef
  b: TaxRef
  confidence: number
  source: string
  status: string
  created_at: string
  notes?: string | null
}

interface NonEquivalenceRow {
  a: TaxRef
  b: TaxRef
  source: string
  notes?: string | null
  created_at: string
}

interface EquivalencesResponse {
  accepted: AcceptedRow[]
  pending_review: AcceptedRow[]
  non_equivalences: NonEquivalenceRow[]
  counts: {
    accepted: number
    pending_review: number
    non_equivalences: number
  }
}

interface DiagnoseResponse {
  lookback_days: number
  min_cooccurrences: number
  propose_threshold: number
  total_detections: number
  total_detections_with_taxonomy: number
  distinct_taxa_observed: number
  taxa_by_count: Array<{ namespace: string; id: string; count: number }>
  near_miss_below_min_cooc: Array<{
    a: TaxRef
    b: TaxRef
    jaccard: number
    cooccurrence: number
    n_a: number
    n_b: number
  }>
  near_miss_below_propose_threshold: Array<{
    a: TaxRef
    b: TaxRef
    jaccard: number
    cooccurrence: number
    n_a: number
    n_b: number
  }>
}

interface AutoDiscoveryStatus {
  status?: 'never_run' | 'ok'
  ran_at?: string
  total_proposals?: number
  recorded?: number
  promoted?: number
  skipped_existing?: number
  skipped_blocked?: number
  lifetime_runs?: number
  lifetime_proposals?: number
}

function refLabel(ref: TaxRef): string {
  return `${ref.namespace}:${ref.id}`
}

export default function EquivalencesPage() {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery<EquivalencesResponse>({
    queryKey: ['equivalences'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/equivalences')
      if (!res.ok) throw new Error('Failed to load equivalences')
      return res.json()
    },
    // Keep showing the previous data while a refetch is in flight,
    // so the page doesn't blank out after accept/reject + refetch.
    placeholderData: (previousData) => previousData,
  })

  const [diagnoseOpen, setDiagnoseOpen] = useState(false)
  const { data: diagnose, isLoading: diagnoseLoading } = useQuery<DiagnoseResponse>({
    queryKey: ['equivalences-diagnose'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/equivalences/diagnose?lookback_days=7')
      if (!res.ok) throw new Error('Failed to load diagnose data')
      return res.json()
    },
    enabled: diagnoseOpen,  // lazy — only fetch when user opens the panel
  })

  const { data: workerStatus } = useQuery<AutoDiscoveryStatus>({
    queryKey: ['auto-discovery-status'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/auto-discovery/status')
      if (!res.ok) throw new Error('Failed to load worker status')
      return res.json()
    },
    refetchInterval: 30_000,  // poll every 30s for fresh background-scan status
  })

  const acceptMutation = useMutation({
    mutationFn: async (pair: { a: TaxRef; b: TaxRef }) => {
      const res = await fetchWithAuth('/api/equivalences/accept', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pair),
      })
      if (!res.ok) {
        const detail = await res.text()
        throw new Error(`accept failed: ${detail}`)
      }
      return res.json()
    },
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['equivalences'] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const scanMutation = useMutation({
    mutationFn: async () => {
      const res = await fetchWithAuth('/api/equivalences/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) {
        const detail = await res.text()
        throw new Error(`scan failed: ${detail}`)
      }
      return res.json()
    },
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['equivalences'] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const rejectMutation = useMutation({
    mutationFn: async (pair: { a: TaxRef; b: TaxRef; notes?: string }) => {
      const res = await fetchWithAuth('/api/equivalences/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pair),
      })
      if (!res.ok) {
        const detail = await res.text()
        throw new Error(`reject failed: ${detail}`)
      }
      return res.json()
    },
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['equivalences'] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  if (isLoading) return <LoadingSpinner />
  if (error) {
    return (
      <ErrorMessage
        title="Equivalences"
        description="Cross-classifier identity review"
        message="Failed to load equivalences"
      />
    )
  }

  const accepted = data?.accepted ?? []
  const pending = data?.pending_review ?? []
  const nonEqs = data?.non_equivalences ?? []
  const counts = data?.counts ?? {
    accepted: 0,
    pending_review: 0,
    non_equivalences: 0,
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Equivalences"
          description="Cross-classifier identity — what auto-discovery has learned"
        />
        <button
          onClick={() => scanMutation.mutate()}
          disabled={scanMutation.isPending}
          className="flex items-center gap-2 px-3 py-2 rounded bg-blue-600/80 hover:bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
          title="Run an auto-discovery scan immediately (default cadence is every 6h)"
        >
          <RefreshCw
            className={`w-4 h-4 ${scanMutation.isPending ? 'animate-spin' : ''}`}
          />
          {scanMutation.isPending ? 'Scanning…' : 'Scan now'}
        </button>
      </div>

      {scanMutation.data && (
        <Card className="p-3 border-blue-500/30 bg-blue-500/5">
          <p className="text-sm text-slate-200">
            Last scan: <span className="font-mono">{scanMutation.data.ran_at}</span>
            <span className="mx-2 text-slate-500">·</span>
            <span className="text-emerald-400">
              {scanMutation.data.recorded} recorded
            </span>
            <span className="mx-2 text-slate-500">·</span>
            <span className="text-sky-400">
              {scanMutation.data.promoted ?? 0} promoted
            </span>
            <span className="mx-2 text-slate-500">·</span>
            <span className="text-slate-400">
              {scanMutation.data.skipped_existing} existing
            </span>
            <span className="mx-2 text-slate-500">·</span>
            <span className="text-slate-400">
              {scanMutation.data.skipped_blocked} blocked
            </span>
          </p>
        </Card>
      )}

      <Card className="p-4 flex items-start gap-3">
        <Sparkles className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-slate-300">
          The taxonomy equivalence graph maps cross-classifier identity (e.g.
          BirdNET&apos;s <code>ioc:Corvus brachyrhynchos</code> ≡ PANNs&apos;{' '}
          <code>audioset:/m/04s8yn</code>). Built by the auto-discovery worker
          observing co-occurrence on shared audio.motion events. Pending
          proposals await your review.
        </div>
      </Card>

      {/* Background worker status — pulled every 30s from /api/auto-discovery/status,
          which is populated by the correlator's MQTT health publishes. */}
      {workerStatus && (
        <Card className="p-3">
          <p className="text-xs text-slate-400">
            <span className="text-slate-500">Background worker — </span>
            {workerStatus.status === 'never_run' || !workerStatus.ran_at ? (
              <span className="text-slate-500">
                no scan observed yet (cadence is every 6h by default; use
                &ldquo;Scan now&rdquo; to kick one off)
              </span>
            ) : (
              <>
                <span>Last scan: </span>
                <span className="font-mono text-slate-300">
                  {workerStatus.ran_at}
                </span>
                <span className="mx-2 text-slate-600">·</span>
                <span className="text-emerald-400">
                  {workerStatus.recorded ?? 0} recorded
                </span>
                <span className="mx-2 text-slate-600">·</span>
                <span className="text-sky-400">
                  {workerStatus.promoted ?? 0} promoted
                </span>
                <span className="mx-2 text-slate-600">·</span>
                <span>
                  lifetime: {workerStatus.lifetime_runs ?? 0} runs,{' '}
                  {workerStatus.lifetime_proposals ?? 0} proposals
                </span>
              </>
            )}
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          title="Accepted equivalences"
          value={counts.accepted}
          icon={CheckCircle2}
          color="green"
        />
        <StatCard
          title="Pending review"
          value={counts.pending_review}
          icon={AlertCircle}
          color="amber"
        />
        <StatCard
          title="Non-equivalences"
          value={counts.non_equivalences}
          icon={XCircle}
          color="red"
        />
      </div>

      {actionError && (
        <Card className="p-3 border-red-500/50 bg-red-500/10">
          <p className="text-sm text-red-300">{actionError}</p>
        </Card>
      )}

      {/* Pending review — primary action area */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-2 flex items-center gap-2">
          <AlertCircle className="w-5 h-5 text-amber-400" />
          Pending review ({pending.length})
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          Auto-discovery proposed these pairs based on co-occurrence (Jaccard
          in [0.6, 0.9)). Approve to make them active in
          <code className="mx-1">equivalent_taxa()</code> queries, or reject
          to permanently block re-proposal.
        </p>
        {pending.length === 0 ? (
          <p className="text-slate-500 text-sm py-2">
            Nothing awaiting review.
          </p>
        ) : (
          <div className="space-y-2">
            {pending.map((row, i) => (
              <div
                key={i}
                className="border border-amber-500/30 rounded-lg p-3 bg-amber-500/5"
              >
                <div className="flex items-baseline gap-2 mb-2 flex-wrap">
                  <span className="text-sm font-mono text-amber-200">
                    {refLabel(row.a)}
                  </span>
                  <span className="text-slate-500">≡</span>
                  <span className="text-sm font-mono text-amber-200">
                    {refLabel(row.b)}
                  </span>
                  <span className="text-xs text-slate-500 ml-auto">
                    confidence {(row.confidence * 100).toFixed(0)}% · {row.source}
                  </span>
                </div>
                {row.notes && (
                  <p className="text-xs text-slate-400 font-mono mb-2">
                    {row.notes}
                  </p>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={() =>
                      acceptMutation.mutate({ a: row.a, b: row.b })
                    }
                    disabled={acceptMutation.isPending}
                    className="px-3 py-1 text-xs rounded bg-green-600/80 hover:bg-green-600 text-white font-medium disabled:opacity-50"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() =>
                      rejectMutation.mutate({
                        a: row.a,
                        b: row.b,
                        notes: 'Rejected via UI',
                      })
                    }
                    disabled={rejectMutation.isPending}
                    className="px-3 py-1 text-xs rounded bg-red-600/80 hover:bg-red-600 text-white font-medium disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Accepted equivalences */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-2 flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-green-400" />
          Accepted ({accepted.length})
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          These pairs are live — <code>equivalent_taxa()</code> walks
          them when queries / corollary discharge / the Bird Correlation
          dashboard ask &quot;is this the same animal?&quot;.
        </p>
        {accepted.length === 0 ? (
          <p className="text-slate-500 text-sm py-2">
            No accepted equivalences yet. Auto-discovery populates these as
            it observes co-occurrence at Jaccard ≥ 0.9 over the last 7 days
            of operation.
          </p>
        ) : (
          <div className="space-y-1 max-h-96 overflow-y-auto">
            {accepted.map((row, i) => (
              <div
                key={i}
                className="flex items-center text-sm py-1.5 border-b border-slate-700/40"
              >
                <span className="font-mono text-green-200 flex-1">
                  {refLabel(row.a)}
                </span>
                <span className="text-slate-500 px-2">≡</span>
                <span className="font-mono text-green-200 flex-1">
                  {refLabel(row.b)}
                </span>
                <span className="text-xs text-slate-500 ml-2">
                  {(row.confidence * 100).toFixed(0)}% · {row.source}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Auto-discovery debug panel — lazy, opens on demand */}
      <Card>
        <button
          onClick={() => setDiagnoseOpen((v) => !v)}
          className="w-full flex items-center justify-between text-left"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-400" />
            <h2 className="text-lg font-medium text-white">
              Debug auto-discovery
            </h2>
          </div>
          <span className="text-xs text-slate-400">
            {diagnoseOpen ? 'Hide' : 'Show'}
          </span>
        </button>
        {diagnoseOpen && (
          <div className="mt-4 space-y-4">
            <p className="text-xs text-slate-500">
              Read-only snapshot of what auto-discovery sees in the last 7 days.
              Use this to decide whether to lower
              <code className="mx-1">min_cooccurrences</code> or
              <code className="mx-1">propose_threshold</code> in
              <code className="mx-1">orpheus.yaml</code>.
            </p>
            {diagnoseLoading || !diagnose ? (
              <p className="text-xs text-slate-500">Loading diagnostics…</p>
            ) : (
              <div className="space-y-4 text-sm">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div>
                    <p className="text-slate-500">Detections (7d)</p>
                    <p className="text-slate-200">{diagnose.total_detections}</p>
                  </div>
                  <div>
                    <p className="text-slate-500">With taxonomy</p>
                    <p className="text-slate-200">
                      {diagnose.total_detections_with_taxonomy}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500">Distinct taxa</p>
                    <p className="text-slate-200">
                      {diagnose.distinct_taxa_observed}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-500">Threshold</p>
                    <p className="text-slate-200 font-mono">
                      ≥{diagnose.propose_threshold} J,{' '}
                      ≥{diagnose.min_cooccurrences} co-occur
                    </p>
                  </div>
                </div>

                {diagnose.taxa_by_count.length > 0 && (
                  <div>
                    <p className="text-xs text-slate-500 mb-1">
                      Top taxa by frequency
                    </p>
                    <div className="space-y-0.5">
                      {diagnose.taxa_by_count.slice(0, 10).map((t, i) => (
                        <p
                          key={i}
                          className="text-xs font-mono text-slate-400"
                        >
                          <span className="text-slate-200">{t.count}</span>{' '}
                          ×{' '}
                          <span className="text-slate-300">
                            {t.namespace}:{t.id}
                          </span>
                        </p>
                      ))}
                    </div>
                  </div>
                )}

                {diagnose.near_miss_below_min_cooc.length > 0 && (
                  <div>
                    <p className="text-xs text-amber-300 mb-1">
                      Near miss — high Jaccard, not enough co-occurrences yet:
                    </p>
                    <div className="space-y-1">
                      {diagnose.near_miss_below_min_cooc
                        .slice(0, 10)
                        .map((p, i) => (
                          <p key={i} className="text-xs text-slate-400">
                            <span className="font-mono text-slate-300">
                              {p.a.namespace}:{p.a.id} ≡ {p.b.namespace}:{p.b.id}
                            </span>
                            <span className="text-slate-500 mx-2">·</span>
                            J={p.jaccard} ({p.cooccurrence}/{p.n_a}/{p.n_b})
                          </p>
                        ))}
                    </div>
                  </div>
                )}

                {diagnose.near_miss_below_propose_threshold.length > 0 && (
                  <div>
                    <p className="text-xs text-amber-300 mb-1">
                      Near miss — enough co-occurrences but Jaccard too low:
                    </p>
                    <div className="space-y-1">
                      {diagnose.near_miss_below_propose_threshold
                        .slice(0, 10)
                        .map((p, i) => (
                          <p key={i} className="text-xs text-slate-400">
                            <span className="font-mono text-slate-300">
                              {p.a.namespace}:{p.a.id} ≡ {p.b.namespace}:{p.b.id}
                            </span>
                            <span className="text-slate-500 mx-2">·</span>
                            J={p.jaccard} ({p.cooccurrence}/{p.n_a}/{p.n_b})
                          </p>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Non-equivalences */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-2 flex items-center gap-2">
          <XCircle className="w-5 h-5 text-red-400" />
          Non-equivalences ({nonEqs.length})
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          Pairs explicitly asserted as NOT the same. Auto-discovery
          won&apos;t re-propose these even if they co-occur. Useful for
          correcting false positives.
        </p>
        {nonEqs.length === 0 ? (
          <p className="text-slate-500 text-sm py-2">No non-equivalences.</p>
        ) : (
          <div className="space-y-1">
            {nonEqs.map((row, i) => (
              <div
                key={i}
                className="flex items-center text-sm py-1.5 border-b border-slate-700/40"
              >
                <span className="font-mono text-red-200 flex-1">
                  {refLabel(row.a)}
                </span>
                <span className="text-slate-500 px-2">≢</span>
                <span className="font-mono text-red-200 flex-1">
                  {refLabel(row.b)}
                </span>
                {row.notes && (
                  <span className="text-xs text-slate-500 ml-2 italic">
                    {row.notes}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
