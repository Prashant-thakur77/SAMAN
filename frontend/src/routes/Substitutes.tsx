import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import {
  ApiError,
  decideSubstitute,
  getSubstitutes,
  type Installation,
  type SubstituteRow,
  type SubstituteSide,
  type SubstituteStatus,
  type SubstitutesResponse,
} from '../lib/api'
import { cn } from '../lib/cn'
import { useSession } from '../lib/session'

const TABS: { key: SubstituteStatus | 'all'; label: string }[] = [
  { key: 'proposed', label: 'Awaiting approval' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'all', label: 'All' },
]

/**
 * /substitutes — the engineer's queue.
 *
 * An equivalence the pipeline found is a proposal. Here it is shown with the
 * equipment each side is fitted to and the highest criticality involved, and
 * a technical authority approves or rejects it with a reason that lands in
 * the audit chain. Everyone may read the queue; the API decides who signs.
 */
export default function Substitutes() {
  const [tab, setTab] = useState<SubstituteStatus | 'all'>('proposed')
  const [data, setData] = useState<SubstitutesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [reasons, setReasons] = useState<Record<number, string>>({})
  const { can } = useSession()
  const mayDecide = can('engineer', 'registrar', 'admin')

  const load = useCallback(async (which: SubstituteStatus | 'all') => {
    setError(null)
    try {
      setData(await getSubstitutes(which))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the queue.')
    }
  }, [])

  useEffect(() => {
    void load(tab)
  }, [tab, load])

  async function decide(row: SubstituteRow, decision: 'approved' | 'rejected') {
    const reason = (reasons[row.id] ?? '').trim()
    if (!reason) {
      setMessage('Write the reason first. It is what the next engineer reads.')
      return
    }
    setBusy(row.id)
    setMessage(null)
    try {
      const result = await decideSubstitute(row.id, decision, reason)
      setMessage(`Relation ${row.id} ${result.status} by ${result.decided_by}.`)
      await load(tab)
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : 'The decision could not be saved.')
    } finally {
      setBusy(null)
    }
  }

  const counts = data?.counts

  return (
    <div className="space-y-8">
      <PageHeader
        section="Review"
        title="Substitutes"
        description="Interchangeable parts the pipeline found, with the equipment they touch. A technical authority approves each one, with a reason, before it may be fitted."
      />

      <div className="flex flex-wrap items-center gap-1 border-b border-hairline">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            aria-pressed={tab === entry.key}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-2 text-sm',
              tab === entry.key
                ? 'border-inverse font-medium text-ink'
                : 'border-transparent text-muted hover:text-ink',
            )}
          >
            {entry.label}
            {counts && entry.key !== 'all' && (
              <span className="font-mono text-xs">{counts[entry.key]}</span>
            )}
          </button>
        ))}
      </div>

      {(error || message) && (
        <p role="status" className={cn('card px-4 py-3 text-sm', error ? 'text-danger' : 'text-ink')}>
          {error ?? message}
        </p>
      )}

      {!data ? (
        <p className="text-sm text-muted">Loading the queue…</p>
      ) : data.relations.length === 0 ? (
        <EmptyState
          title="Nothing here"
          description={
            tab === 'proposed'
              ? 'Every equivalence has been decided.'
              : 'No equivalence carries this status yet.'
          }
        />
      ) : (
        <ul className="space-y-4">
          {data.relations.map((row) => (
            <li key={row.id} className="space-y-4 card p-5" data-testid="substitute">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusChip
                    tone={
                      row.status === 'approved'
                        ? 'ok'
                        : row.status === 'rejected'
                          ? 'danger'
                          : 'neutral'
                    }
                  >
                    {row.status === 'proposed' ? 'awaiting approval' : row.status}
                  </StatusChip>
                  {row.criticality !== '-' && (
                    <StatusChip tone={row.criticality === 'A' ? 'danger' : 'neutral'}>
                      criticality {row.criticality}
                    </StatusChip>
                  )}
                </div>
                <p className="micro-label">
                  relation {row.id} · {row.basis} · {Math.round(row.confidence * 100)}%
                </p>
              </div>

              <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr] md:items-start">
                <Side side={row.a} />
                <p className="self-center whitespace-nowrap px-2 text-center font-mono text-xs text-muted">
                  {row.rel_type === 'equivalent'
                    ? 'interchangeable ⇄'
                    : row.direction === 'a_to_b'
                      ? 'right ➜ can substitute left'
                      : 'left ➜ can substitute right'}
                </p>
                <Side side={row.b} />
              </div>

              {row.approval ? (
                <p className="border-t border-hairline pt-3 text-sm">
                  <span className="font-medium">
                    {row.approval.status} by {row.approval.decided_by ?? 'an engineer'}
                  </span>
                  <span className="text-muted"> · {row.approval.reason}</span>
                </p>
              ) : mayDecide ? (
                <div className="space-y-2 border-t border-hairline pt-3">
                  <label className="micro-label" htmlFor={`reason-${row.id}`}>
                    Reason, for the record
                  </label>
                  <textarea
                    id={`reason-${row.id}`}
                    rows={2}
                    value={reasons[row.id] ?? ''}
                    onChange={(e) => setReasons((r) => ({ ...r, [row.id]: e.target.value }))}
                    placeholder="Same bore and seal; load rating exceeds the pump's duty."
                    className="w-full rounded-lg border border-hairline bg-bg px-3 py-2 text-sm"
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button disabled={busy === row.id} onClick={() => void decide(row, 'approved')}>
                      Approve substitute
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={busy === row.id}
                      onClick={() => void decide(row, 'rejected')}
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="border-t border-hairline pt-3 text-xs text-muted">
                  Awaiting a technical authority. Engineers, the registrar and the admin may
                  decide.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {data && <p className="max-w-prose text-xs text-muted">{data.note}</p>}
    </div>
  )
}

function Side({ side }: { side: SubstituteSide }) {
  return (
    <div className="min-w-0 space-y-2">
      <Link
        to={`/items/${side.item_id}`}
        className="block text-sm text-ink underline-offset-2 hover:underline"
      >
        {side.description ?? side.normalized ?? `item ${side.item_id}`}
      </Link>
      <p className="micro-label">
        {side.cpse} · {side.legacy_code}
        {side.cnmc ? ` · ${side.cnmc}` : ''}
      </p>
      <Fitted installed={side.installed_on} ved={side.ved} />
    </div>
  )
}

function Fitted({ installed, ved }: { installed: Installation[]; ved: string | null }) {
  if (installed.length === 0) {
    return <p className="text-xs text-muted">Not on any equipment BOM.</p>
  }
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted">
        Fitted to {installed.length} {installed.length === 1 ? 'tag' : 'tags'}
        {ved ? ` · ${ved} spare` : ''}
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {installed.slice(0, 6).map((fit) => (
          <li
            key={`${fit.cpse}-${fit.tag}`}
            className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[11px]"
            title={`${fit.description} · criticality ${fit.criticality}`}
          >
            {fit.tag}
            <span className={cn('ml-1', fit.criticality === 'A' ? 'text-danger' : 'text-muted')}>
              {fit.criticality}
            </span>
          </li>
        ))}
        {installed.length > 6 && (
          <li className="px-1 text-[11px] text-muted">+{installed.length - 6}</li>
        )}
      </ul>
    </div>
  )
}
