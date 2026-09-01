import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { CountUp, formatRupees } from '../components/charts/CountUp'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { ApiError, getExecutive, getQueue, type ExecutiveDashboard } from '../lib/api'
import { useSession } from '../lib/session'

/**
 * / — role-aware landing (spec §6.2).
 *
 * A registrar arrives at the executive figures; a steward arrives at their
 * queue. Both see the same numbers, computed from the database.
 */
export default function Home() {
  const { user, can, loading } = useSession()
  const [summary, setSummary] = useState<ExecutiveDashboard | null>(null)
  const [pending, setPending] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    Promise.all([getExecutive(), getQueue(undefined, 0, 1)])
      .then(([exec, queue]) => {
        if (!alive) return
        setSummary(exec)
        setPending(Object.values(queue.counts).reduce((a, b) => a + b, 0))
      })
      .catch((err) => alive && setError(err instanceof ApiError ? err.message : 'Unavailable.'))
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
        !error && <p className="text-sm text-muted">Loading…</p>
      ) : summary.kpis.every((k) => k.value === 0) ? (
        <EmptyState
          title="No data yet"
          description="Run make demo to seed four CPSE catalogues and run the pipeline."
        />
      ) : (
        <>
          {isReviewer && pending !== null && (
            <div className="flex flex-wrap items-center justify-between gap-4 border border-hairline p-6">
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

          <dl className="grid grid-cols-2 gap-px border border-hairline bg-hairline md:grid-cols-3">
            {(headline ?? []).map((kpi) => (
              <div key={kpi.key} className="space-y-2 bg-bg p-5">
                <dt className="micro-label">{kpi.label}</dt>
                <dd className="font-mono text-xl">
                  <CountUp value={kpi.value} format={kpi.format} />
                </dd>
              </div>
            ))}
          </dl>

          <section className="grid gap-4 md:grid-cols-2">
            <Link
              to="/dashboard/executive"
              className="space-y-2 border border-hairline p-5 hover:bg-surface"
            >
              <p className="micro-label">Executive dashboard</p>
              <p className="text-sm text-ink">
                Progress by CPSE, class coverage and codes issued over time.
              </p>
            </Link>
            <Link
              to="/dashboard/opportunity"
              className="space-y-2 border border-hairline p-5 hover:bg-surface"
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
