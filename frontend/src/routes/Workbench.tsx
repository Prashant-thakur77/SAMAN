import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { AttributeDiff } from '../components/workbench/AttributeDiff'
import { ItemPanel } from '../components/workbench/ItemPanel'
import { TierStrip } from '../components/workbench/TierStrip'
import { useWorkbenchKeys } from '../lib/useWorkbenchKeys'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { ApiError, getQueue, postDecision, type QueueResponse, type TaskCard } from '../lib/api'
import { cn } from '../lib/cn'
import { decisionCardVariants } from '../lib/motion'
import { useSession } from '../lib/session'

const BANDS = [
  { key: 'high', label: 'Auto-high' },
  { key: 'grey', label: 'Grey' },
  { key: 'low', label: 'Auto-low' },
] as const

type Band = (typeof BANDS)[number]['key']

/**
 * /workbench — keyboard-first adjudication (spec §6.5).
 *
 * A: approve   R: reject   J / K: next / previous   M: open the cluster
 *
 * The card exits right on approve and left on reject (§1.5), and the next one
 * rises into place. Decisions post to the API, which is what enforces the role
 * gate — the disabled button here is a courtesy, not the boundary.
 */
const ADJUDICATION_TONE = {
  lean_merge: 'ok',
  lean_review: 'neutral',
  lean_split: 'danger',
  flag_conflict: 'danger',
} as const

export default function Workbench() {
  const [band, setBand] = useState<Band>('grey')
  const [queue, setQueue] = useState<QueueResponse | null>(null)
  const [cursor, setCursor] = useState(0)
  const [exiting, setExiting] = useState<'approve' | 'reject' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [decided, setDecided] = useState<Record<number, string>>({})
  const reduce = useReducedMotion() ?? false
  const navigate = useNavigate()
  const { user } = useSession()

  const load = useCallback(
    async (which: Band) => {
      setError(null)
      try {
        const next = await getQueue(which, 0, 50)
        setQueue(next)
        setCursor(0)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load the queue.')
      }
    },
    [],
  )

  useEffect(() => {
    void load(band)
  }, [band, load])

  const pending = useMemo(
    () => (queue?.tasks ?? []).filter((t) => !decided[t.task_id]),
    [queue, decided],
  )
  const task: TaskCard | undefined = pending[cursor]

  const decide = useCallback(
    async (action: 'approve' | 'reject') => {
      if (!task || busy) return
      setBusy(true)
      setExiting(action)
      try {
        await postDecision({ task_id: task.task_id, action })
        setDecided((prev) => ({ ...prev, [task.task_id]: action }))
        setCursor((c) => Math.max(0, Math.min(c, pending.length - 2)))
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
    [task, busy, pending.length],
  )

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
      }),
      [decide, pending.length, task, navigate],
    ),
  )

  const counts = queue?.counts ?? { high: 0, grey: 0, low: 0 }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Review"
        title="Workbench"
        description="Adjudicate candidate matches with the evidence and any hard-constraint veto side by side."
        actions={
          <div className="hidden items-center gap-3 md:flex">
            {(['A approve', 'R reject', 'J/K move', 'M cluster'] as const).map((hint) => (
              <kbd
                key={hint}
                className="border border-hairline px-2 py-1 font-mono text-[10px] text-muted"
              >
                {hint}
              </kbd>
            ))}
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
      </div>

      {error && (
        <p role="alert" className="border border-hairline px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      {!queue ? (
        <p className="text-sm text-muted">Loading the queue…</p>
      ) : !task ? (
        <EmptyState
          title="Nothing left in this band"
          description={
            counts[band] === 0
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
            className="space-y-6 border border-hairline p-6"
          >
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-hairline pb-4">
              <div className="space-y-1">
                <p className="micro-label">
                  task {task.task_id} · {cursor + 1} of {pending.length}
                </p>
                <p className="text-sm text-muted">{task.reason}</p>
              </div>
              <div className="flex items-center gap-4">
                {task.verdict === 'conflict' && (
                  <StatusChip tone="danger">Specification conflict</StatusChip>
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
              <section className="border border-hairline px-4 py-3">
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
              <div className="border border-hairline px-4 py-3">
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
