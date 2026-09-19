import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { ReportCard } from '../components/ReportsPanel'
import { CountUp, formatRupees } from '../components/charts/CountUp'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import {
  ApiError,
  getAudit,
  getExecutive,
  getQueue,
  type AuditEventRow,
  type ExecutiveDashboard,
} from '../lib/api'
import { useSession } from '../lib/session'
import { parseUtc } from '../lib/time'

/**
 * / — role-aware landing (spec §6.2).
 *
 * A registrar arrives at the executive figures; a steward arrives at their
 * queue. Both see the same numbers, computed from the database.
 */
/** "3 min ago", "2 h ago", "4 d ago": enough for a glance at the ledger. */
function ago(iso: string): string {
  const seconds = Math.max(0, (Date.now() - parseUtc(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

export default function Home() {
  const { user, can, loading } = useSession()
  const [summary, setSummary] = useState<ExecutiveDashboard | null>(null)
  const [pending, setPending] = useState<number | null>(null)
  const [recent, setRecent] = useState<AuditEventRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Three requests, each shown as it lands: the figures are the slow one on a
  // small host, and the queue and the ledger must not wait behind them.
  useEffect(() => {
    let alive = true
    const fail = (err: unknown) =>
      alive && setError(err instanceof ApiError ? err.message : 'Unavailable.')
    getExecutive()
      .then((exec) => alive && setSummary(exec))
      .catch(fail)
    getQueue(undefined, 0, 1)
      .then((queue) => {
        if (alive) setPending(Object.values(queue.counts).reduce((a, b) => a + b, 0))
      })
      .catch(() => alive && setPending(null))
    getAudit({ exclude: 'auth.', limit: 6 })
      .then((ledger) => alive && setRecent(ledger.events))
      .catch(() => alive && setRecent([]))
    return () => {
      alive = false
    }
  }, [])

  const isReviewer = can('steward', 'approver')
  const headline = summary?.kpis.filter((k) =>
    isReviewer
      ? ['items', 'clusters', 'duplicates'].includes(k.key)
      : ['clusters', 'duplicates', 'cnmcs', 'automation', 'savings', 'prevented'].includes(
          k.key,
        ),
  )

  return (
    <div className="space-y-8">
      <PageHeader
        section="Overview"
        title={user ? `Good to see you, ${user.name.split(' ').slice(-1)[0]}` : 'SAMAN'}
        description={
          loading
            ? 'Loading your view…'
            : isReviewer
              ? 'Your review queue and the state of the shared catalogue.'
              : 'Harmonization progress across every participating CPSE.'
        }
        actions={user ? <StatusChip tone="neutral">{user.role}</StatusChip> : undefined}
      />

      {error && <p className="text-sm text-danger">{error}</p>}

      {!summary ? (
        !error && (
          <dl
            className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card md:grid-cols-3"
            aria-busy="true"
            aria-label="Loading the figures"
          >
            {Array.from({ length: isReviewer ? 3 : 6 }, (_, i) => (
              <div key={i} className="space-y-3 bg-surface p-5">
                <div className="h-3 w-24 animate-pulse rounded bg-hairline" />
                <div className="h-6 w-16 animate-pulse rounded bg-hairline" />
              </div>
            ))}
          </dl>
        )
      ) : summary.kpis.every((k) => k.value === 0) ? (
        <EmptyState
          title="No data yet"
          description="Run make demo to seed four CPSE catalogues and run the pipeline."
        />
      ) : (
        <>
          {isReviewer && pending !== null && (
            <div className="flex flex-wrap items-center justify-between gap-4 card p-6">
              <div>
                <p className="micro-label">Your queue</p>
                <p className="font-mono text-2xl">
                  <CountUp value={pending} /> pending
                </p>
              </div>
              <Link to="/workbench">
                <Button variant="primary">Open the workbench</Button>
              </Link>
            </div>
          )}

          {user?.cpse_code && can('steward', 'approver', 'engineer') && (
            <ReportCard cpse={user.cpse_code} />
          )}

          <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card md:grid-cols-3 [&>*:last-child:nth-child(odd)]:col-span-2 md:[&>*:last-child:nth-child(odd)]:col-span-1">
            {(headline ?? []).map((kpi) => (
              <div key={kpi.key} className="space-y-2 bg-surface p-5">
                <dt className="micro-label">{kpi.label}</dt>
                <dd className="font-mono text-xl">
                  <CountUp value={kpi.value} format={kpi.format} />
                </dd>
              </div>
            ))}
          </dl>

          {recent && recent.length > 0 && (
            <section className="card p-5" aria-label="Recent on the ledger">
              <div className="flex items-baseline justify-between gap-4">
                <p className="micro-label">Recent on the ledger</p>
                <Link to="/audit" className="micro-label underline underline-offset-4 hover:text-ink">
                  Audit trail →
                </Link>
              </div>
              <ol className="mt-3 divide-y divide-hairline">
                {recent.map((event) => (
                  <li
                    key={event.seq}
                    className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2 text-sm"
                  >
                    <span className="font-mono text-xs text-muted">{ago(event.ts)}</span>
                    <span className="font-mono text-xs">{event.action}</span>
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">
                      {event.entity}
                    </span>
                    <span className="text-xs text-muted">{event.user}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="grid gap-4 md:grid-cols-2">
            <Link
              to="/dashboard/executive"
              className="space-y-2 card p-5 hover:bg-surface"
            >
              <p className="micro-label">Executive dashboard</p>
              <p className="text-sm text-ink">
                Progress by CPSE, class coverage and codes issued over time.
              </p>
            </Link>
            <Link
              to="/dashboard/opportunity"
              className="space-y-2 card p-5 hover:bg-surface"
            >
              <p className="micro-label">Opportunity</p>
              <p className="text-sm text-ink">
                {formatRupees(summary.kpis.find((k) => k.key === 'savings')?.value ?? 0)} identified
                across joint tenders, price variance and idle stock.
              </p>
            </Link>
          </section>
        </>
      )}
    </div>
  )
}
