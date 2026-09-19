import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { AttributeDiff } from '../components/workbench/AttributeDiff'
import { ItemPanel } from '../components/workbench/ItemPanel'
import { TierStrip } from '../components/workbench/TierStrip'
import { useWorkbenchKeys } from '../lib/useWorkbenchKeys'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { Input } from '../components/primitives/Field'
import {
  ApiError,
  getQueue,
  postBulkDecisions,
  postDecision,
  undoDecision,
  type BulkOutcome,
  type QueueFilters,
  type QueueOrder,
  type QueueResponse,
  type TaskCard,
} from '../lib/api'
import { cn } from '../lib/cn'
import { downloadCsv, rowsToCsv } from '../lib/csv'
import { decisionCardVariants } from '../lib/motion'
import { useSession } from '../lib/session'

const BANDS = [
  { key: 'high', label: 'Auto-high' },
  { key: 'grey', label: 'Grey' },
  { key: 'low', label: 'Auto-low' },
] as const

type Band = (typeof BANDS)[number]['key']
type Action = 'approve' | 'reject'

/** The bands whose queue is a policy confirmation, worked a page at a time. */
const BULK_DEFAULT: Partial<Record<Band, Action>> = { high: 'approve', low: 'reject' }

/**
 * /workbench — keyboard-first adjudication (spec §6.5).
 *
 * A: approve   R: reject   J / K: next / previous   M: open the cluster   U: undo
 *
 * The card exits right on approve and left on reject (§1.5), and the next one
 * rises into place. Decisions post to the API, which is what enforces the role
 * gate — the disabled button here is a courtesy, not the boundary. A decision
 * can be taken back for a few minutes; the API says how long.
 */
const ADJUDICATION_TONE = {
  lean_merge: 'ok',
  lean_review: 'neutral',
  lean_split: 'danger',
  flag_conflict: 'danger',
} as const

type LastDecision = {
  decisionId: number
  taskId: number
  action: Action
  until: number
}

const SELECT =
  'h-8 rounded-full border border-hairline bg-surface px-3 text-xs text-ink focus:outline-none'

export default function Workbench() {
  const [band, setBand] = useState<Band>('grey')
  const [queue, setQueue] = useState<QueueResponse | null>(null)
  const [cursor, setCursor] = useState(0)
  const [exiting, setExiting] = useState<Action | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [decided, setDecided] = useState<Record<number, string>>({})
  // With a trained model, the queue can lead with the pairs it is least sure
  // about: the reviewer's next ten minutes then teach the system the most.
  const [order, setOrder] = useState<QueueOrder>('id')
  // Queues are worked by family: one class, one CPSE, or only what is mine.
  const [filters, setFilters] = useState<QueueFilters>({})
  const [last, setLast] = useState<LastDecision | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkAction, setBulkAction] = useState<Action>('approve')
  const [bulkNote, setBulkNote] = useState('')
  const [bulkResult, setBulkResult] = useState<BulkOutcome | null>(null)
  const shownAt = useRef(Date.now())
  const reduce = useReducedMotion() ?? false
  const navigate = useNavigate()
  const { user } = useSession()

  const load = useCallback(
    async (which: Band) => {
      setError(null)
      try {
        const next = await getQueue(which, 0, 50, order, filters)
        setQueue(next)
        setCursor(0)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load the queue.')
      }
    },
    [order, filters],
  )

  useEffect(() => {
    void load(band)
  }, [band, load])

  useEffect(() => {
    setBulkAction(BULK_DEFAULT[band] ?? 'approve')
    setBulkOpen(false)
    setBulkResult(null)
  }, [band])

  // The undo countdown; one tick a second while there is something to undo.
  useEffect(() => {
    if (!last) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [last])

  const pending = useMemo(
    () => (queue?.tasks ?? []).filter((t) => !decided[t.task_id]),
    [queue, decided],
  )
  const task: TaskCard | undefined = pending[cursor]

  // Seconds on the card: the first number a pilot is judged on.
  useEffect(() => {
    shownAt.current = Date.now()
  }, [task?.task_id])

  const undoLeft = last ? Math.max(0, Math.ceil((last.until - now) / 1000)) : 0
  useEffect(() => {
    if (last && undoLeft === 0) setLast(null)
  }, [last, undoLeft])

  const decide = useCallback(
    async (action: Action) => {
      if (!task || busy) return
      setBusy(true)
      setExiting(action)
      try {
        const seconds = Math.round((Date.now() - shownAt.current) / 100) / 10
        const outcome = await postDecision({ task_id: task.task_id, action, seconds })
        setDecided((prev) => ({ ...prev, [task.task_id]: action }))
        setCursor((c) => Math.max(0, Math.min(c, pending.length - 2)))
        setLast({
          decisionId: outcome.decision_id,
          taskId: task.task_id,
          action,
          until: outcome.undo_until
            ? new Date(outcome.undo_until).getTime()
            : Date.now() + (queue?.undo_window_s ?? 300) * 1000,
        })
        setNow(Date.now())
        setError(null)
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err.message
            : 'The decision could not be saved.',
        )
      } finally {
        setBusy(false)
        setExiting(null)
      }
    },
    [task, busy, pending.length, queue?.undo_window_s],
  )

  const undo = useCallback(async () => {
    if (!last || busy) return
    setBusy(true)
    try {
      await undoDecision(last.decisionId)
      const taskId = last.taskId
      setDecided((prev) => {
        const next = { ...prev }
        delete next[taskId]
        return next
      })
      // The card comes back where it was, in front of the reviewer.
      const index = (queue?.tasks ?? [])
        .filter((t) => !decided[t.task_id] || t.task_id === taskId)
        .findIndex((t) => t.task_id === taskId)
      if (index >= 0) setCursor(index)
      setLast(null)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The decision could not be undone.')
      setLast(null)
    } finally {
      setBusy(false)
    }
  }, [last, busy, queue, decided])

  const bulk = useCallback(async () => {
    if (!queue || busy || pending.length === 0 || !bulkNote.trim()) return
    setBusy(true)
    try {
      const result = await postBulkDecisions({
        task_ids: pending.map((t) => t.task_id),
        action: bulkAction,
        note: bulkNote.trim(),
      })
      setBulkResult(result)
      setDecided((prev) => {
        const next = { ...prev }
        for (const row of result.done) next[row.task_id] = result.action
        return next
      })
      setLast(null)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The page could not be decided.')
    } finally {
      setBusy(false)
    }
  }, [queue, busy, pending, bulkAction, bulkNote])

  useWorkbenchKeys(
    useMemo(
      () => ({
        approve: () => void decide('approve'),
        reject: () => void decide('reject'),
        next: () => setCursor((c) => Math.min(c + 1, Math.max(pending.length - 1, 0))),
        previous: () => setCursor((c) => Math.max(c - 1, 0)),
        openCluster: task?.cluster_id
          ? () => navigate(`/clusters/${task.cluster_id}`)
          : undefined,
        undo: last ? () => void undo() : undefined,
      }),
      [decide, pending.length, task, navigate, last, undo],
    ),
    !bulkOpen,
  )

  const counts = queue?.counts ?? { high: 0, grey: 0, low: 0 }
  const facets = queue?.facets
  const filtering = Boolean(filters.class || filters.cpse || filters.mine)
  // The panel stays up after a page closes so its result can be read.
  const canBulk = band in BULK_DEFAULT && (pending.length > 0 || bulkResult !== null)

  return (
    <div className="space-y-8">
      <PageHeader
        section="Review"
        title="Workbench"
        description="Adjudicate candidate matches with the evidence and any hard-constraint veto side by side."
        actions={
          <div className="hidden items-center gap-3 md:flex">
            {(['A approve', 'R reject', 'J/K move', 'M cluster', 'U undo'] as const).map(
              (hint) => (
                <kbd key={hint} className="card px-2 py-1 font-mono text-[10px] text-muted">
                  {hint}
                </kbd>
              ),
            )}
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-1 border-b border-hairline">
        {BANDS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setBand(entry.key)}
            aria-pressed={band === entry.key}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-2 text-sm',
              band === entry.key
                ? 'border-inverse font-medium text-ink'
                : 'border-transparent text-muted hover:text-ink',
            )}
          >
            {entry.label}
            <span className="font-mono text-xs">{counts[entry.key]}</span>
          </button>
        ))}
        {queue?.model_available && (
          <button
            type="button"
            onClick={() => setOrder((o) => (o === 'id' ? 'uncertainty' : 'id'))}
            aria-pressed={order === 'uncertainty'}
            title="Order the queue by how unsure the learned model is, so each decision teaches it the most. The model never decides."
            className={cn(
              'ml-auto rounded-full border px-3 py-1 text-xs',
              order === 'uncertainty'
                ? 'border-inverse bg-inverse text-bg'
                : 'border-hairline text-muted hover:text-ink',
            )}
          >
            Most informative first
          </button>
        )}
      </div>

      {/* Filters: only values that exist in this band are offered. */}
      <div className="flex flex-wrap items-center gap-2" aria-label="Queue filters">
        <label className="sr-only" htmlFor="wb-class">
          Class
        </label>
        <select
          id="wb-class"
          className={SELECT}
          value={filters.class ?? ''}
          onChange={(e) => setFilters((f) => ({ ...f, class: e.target.value || null }))}
        >
          <option value="">All classes</option>
          {facets?.classes.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} · {c.count}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="wb-cpse">
          CPSE
        </label>
        <select
          id="wb-cpse"
          className={SELECT}
          value={filters.cpse ?? ''}
          onChange={(e) =>
            setFilters((f) => ({ ...f, cpse: e.target.value ? Number(e.target.value) : null }))
          }
        >
          <option value="">All CPSEs</option>
          {facets?.cpses.map((c) => (
            <option key={c.id} value={c.id}>
              {c.code} · {c.count}
            </option>
          ))}
        </select>
        {user && (
          <button
            type="button"
            aria-pressed={Boolean(filters.mine)}
            onClick={() => setFilters((f) => ({ ...f, mine: !f.mine }))}
            className={cn(
              'h-8 rounded-full border px-3 text-xs',
              filters.mine
                ? 'border-inverse bg-inverse text-bg'
                : 'border-hairline text-muted hover:text-ink',
            )}
            title={`Only tasks assigned to your role (${user.role}).`}
          >
            Assigned to me
          </button>
        )}
        {filtering && (
          <Button size="sm" variant="ghost" onClick={() => setFilters({})}>
            Clear filters
          </Button>
        )}
        {queue && (
          <span className="ml-auto font-mono text-xs text-muted">
            {queue.total.toLocaleString('en-IN')} in view
          </span>
        )}
        {pending.length > 0 && (
          <button
            type="button"
            className="font-mono text-[11px] text-muted underline-offset-2 hover:text-ink hover:underline"
            title="Download the loaded cards as a CSV file"
            onClick={() =>
              downloadCsv(
                `queue-${band}`,
                rowsToCsv(
                  pending.map((t) => ({
                    task_id: t.task_id,
                    band: t.band,
                    verdict: t.verdict ?? '',
                    confidence: t.confidence ?? '',
                    left: t.items?.[0]?.legacy_code ?? '',
                    left_cpse: t.items?.[0]?.cpse ?? '',
                    right: t.items?.[1]?.legacy_code ?? '',
                    right_cpse: t.items?.[1]?.cpse ?? '',
                    class: t.items?.[0]?.class_code ?? '',
                    reason: t.reason ?? '',
                    why: t.why ?? '',
                    refused_on: (t.refused_because ?? []).join('; '),
                  })),
                ),
              )
            }
          >
            CSV ↓
          </button>
        )}
        {canBulk && (
          <Button size="sm" variant="secondary" onClick={() => setBulkOpen((o) => !o)}>
            {bulkOpen ? 'Close' : `Decide this page (${pending.length})`}
          </Button>
        )}
      </div>

      {bulkOpen && canBulk && (
        <section className="card space-y-3 p-4" aria-label="Decide this page">
          <p className="text-sm">
            {pending.length} loaded task{pending.length === 1 ? '' : 's'} in the{' '}
            {band === 'high' ? 'auto-high' : 'auto-low'} band, one reason, one audit event
            per row. Each can still be undone for a few minutes.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Bulk action"
              className={SELECT}
              value={bulkAction}
              onChange={(e) => setBulkAction(e.target.value as Action)}
            >
              <option value="approve">Approve all — confirm the merges</option>
              <option value="reject">Reject all — confirm the refusals</option>
            </select>
            <Input
              aria-label="Reason"
              placeholder="Reason (required) — e.g. policy confirmation, high band, page 1"
              value={bulkNote}
              onChange={(e) => setBulkNote(e.target.value)}
              className="max-w-md"
            />
            <Button
              variant={bulkAction === 'approve' ? 'primary' : 'danger'}
              disabled={busy || !bulkNote.trim() || pending.length === 0}
              onClick={() => void bulk()}
            >
              {bulkAction === 'approve' ? 'Approve' : 'Reject'} {pending.length}
            </Button>
          </div>
          {bulkResult && (
            <p className="text-xs text-muted" role="status">
              Closed {bulkResult.count}
              {bulkResult.skipped.length > 0 && (
                <>
                  {' '}
                  · skipped {bulkResult.skipped.length}:{' '}
                  {bulkResult.skipped
                    .slice(0, 3)
                    .map((s) => `task ${s.task_id} (${s.reason})`)
                    .join('; ')}
                  {bulkResult.skipped.length > 3 ? '…' : ''}
                </>
              )}
              .{' '}
              <button
                type="button"
                className="underline"
                onClick={() => {
                  setBulkResult(null)
                  void load(band)
                }}
              >
                Load the next page
              </button>
            </p>
          )}
        </section>
      )}

      {error && (
        <p role="alert" className="card px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      {last && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 border border-hairline bg-surface px-4 py-2 text-sm"
        >
          <span>
            Task {last.taskId} {last.action === 'approve' ? 'approved' : 'rejected'}.
          </span>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void undo()}>
            Undo <kbd className="font-mono text-[10px] opacity-60">U</kbd>
          </Button>
          <span className="font-mono text-xs text-muted">
            {Math.floor(undoLeft / 60)}:{String(undoLeft % 60).padStart(2, '0')}
          </span>
        </div>
      )}

      {!queue ? (
        <p className="text-sm text-muted">Loading the queue…</p>
      ) : !task ? (
        <EmptyState
          title={filtering ? 'Nothing matches these filters' : 'Nothing left in this band'}
          description={
            filtering
              ? 'Clear a filter to widen the queue.'
              : counts[band] === 0
                ? 'No pending tasks were generated for this confidence band.'
                : 'You have cleared every task loaded for this band.'
          }
          action={
            <Button variant="secondary" onClick={() => void load(band)}>
              Reload queue
            </Button>
          }
        />
      ) : (
        <AnimatePresence mode="wait">
          <motion.article
            key={task.task_id}
            variants={decisionCardVariants(reduce)}
            initial="initial"
            animate={exiting ?? 'animate'}
            className="space-y-6 card p-6"
          >
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-hairline pb-4">
              <div className="space-y-1">
                <p className="micro-label">
                  task {task.task_id} · {cursor + 1} of {pending.length}
                </p>
                <p className="text-sm text-muted">{task.reason}</p>
                {task.why && !task.adjudication && (
                  <p className="max-w-prose text-sm" title="Computed from the evidence; no model wrote this.">
                    <span className="micro-label mr-2">why</span>
                    {task.why}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-4">
                {task.verdict === 'conflict' && (
                  <StatusChip tone="danger">Specification conflict</StatusChip>
                )}
                {task.learned && (
                  <div
                    className="text-right"
                    title="The learned pairwise model, trained on reviewers' decisions. Shown beside the pipeline's confidence; it never decides."
                  >
                    <p className="micro-label">model says</p>
                    <p className="font-mono text-sm">
                      {Math.round(task.learned.probability * 100)}% {task.learned.leans}
                      {!task.learned.agrees_with_pipeline && (
                        <span className="ml-2 text-xs text-muted">disagrees</span>
                      )}
                    </p>
                  </div>
                )}
                <div className="text-right">
                  <p className="micro-label">confidence</p>
                  <p className="font-mono text-lg">
                    {task.confidence !== undefined
                      ? `${Math.round(task.confidence * 100)}%`
                      : '—'}
                  </p>
                </div>
              </div>
            </header>

            {task.adjudication && (
              <section className="card px-4 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  <p className="micro-label">Tier 3 · recommendation</p>
                  <StatusChip tone={ADJUDICATION_TONE[task.adjudication.recommendation]}>
                    {task.adjudication.recommendation.replace(/_/g, ' ')}
                  </StatusChip>
                  <span className="font-mono text-xs text-muted">
                    {(task.adjudication.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="max-w-prose pt-2 text-sm">{task.adjudication.summary}</p>
                {task.adjudication.reasons.length > 1 && (
                  <ul className="space-y-1 pt-2">
                    {task.adjudication.reasons.slice(1).map((reason) => (
                      <li key={reason} className="text-xs text-muted">
                        · {reason}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="pt-2 text-xs text-muted">
                  {task.adjudication.note}
                  {task.adjudication.prose_by === 'ollama'
                    ? ' Wording by the local model; the recommendation is not.'
                    : task.adjudication.prose_by === 'remote'
                      ? ' Wording by a remote model; the recommendation is not.'
                      : ''}
                </p>
              </section>
            )}

            {task.conflict && (
              <p className="border border-hairline bg-surface px-4 py-3 text-sm text-ink">
                {task.conflict}
              </p>
            )}

            {task.refused_because && task.refused_because.length > 0 && (
              <div className="card px-4 py-3">
                <p className="micro-label mb-2 text-danger">Not a duplicate</p>
                <ul className="space-y-1">
                  {task.refused_because.map((reason) => (
                    <li key={reason} className="font-mono text-xs text-danger">
                      {reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {task.items && (
              <div className="grid gap-4 lg:grid-cols-2">
                <ItemPanel item={task.items[0]} side="Left" />
                <ItemPanel item={task.items[1]} side="Right" />
              </div>
            )}

            <div className="grid gap-8 lg:grid-cols-[minmax(0,20rem)_1fr]">
              <section className="space-y-3">
                <h2 className="micro-label">Tier scores</h2>
                {task.tier_scores && <TierStrip scores={task.tier_scores} />}
              </section>
              <section className="min-w-0 space-y-3">
                <h2 className="micro-label">Attribute comparison</h2>
                {task.attribute_diff && <AttributeDiff diff={task.attribute_diff} />}
              </section>
            </div>

            <footer className="flex flex-wrap items-center gap-3 border-t border-hairline pt-4">
              <Button variant="primary" disabled={busy} onClick={() => void decide('approve')}>
                Approve <kbd className="font-mono text-[10px] opacity-60">A</kbd>
              </Button>
              <Button variant="danger" disabled={busy} onClick={() => void decide('reject')}>
                Reject <kbd className="font-mono text-[10px] opacity-60">R</kbd>
              </Button>
              {task.cluster_id && (
                <Button
                  variant="secondary"
                  onClick={() => navigate(`/clusters/${task.cluster_id}`)}
                >
                  Open cluster <kbd className="font-mono text-[10px] opacity-60">M</kbd>
                </Button>
              )}
              <span className="ml-auto">
                {/* Issuing a code is registrar-only; the API refuses anyone else. */}
                <Button
                  variant="secondary"
                  disabled
                  title={
                    user?.role === 'registrar'
                      ? 'Issue the CNMC from the cluster page, once the record is approved.'
                      : `Issuing a CNMC is registrar-only. You are signed in as ${user?.role ?? 'a guest'}.`
                  }
                >
                  Issue CNMC
                </Button>
              </span>
            </footer>
          </motion.article>
        </AnimatePresence>
      )}
    </div>
  )
}
