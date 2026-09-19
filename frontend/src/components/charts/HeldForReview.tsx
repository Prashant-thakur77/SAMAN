import type { ReactNode } from 'react'

import type { HeldForReview as HeldForReviewData } from '../../lib/api'
import { StatusChip } from '../primitives/Chip'
import { formatCount, formatDay } from './ChartParts'

/**
 * Why pairs wait for a human (spec section held_for_review).
 *
 * A ladder of numbers with two rungs and a footer, not a chart: the rungs
 * count different things (a certain-but-contradictory pair, an uncertain one)
 * and a bar length would invite an apples-to-oranges comparison. Roles come
 * from the review module's constants as neutral chips; thresholds are printed
 * from the payload so the page never restates policy. No throughput, burn-down
 * or ETA — five decisions cannot support a rate.
 */
export function HeldForReview({ data }: { data: HeldForReviewData }) {
  const [conflict, review] = data.reasons
  const [highQueue, lowQueue] = data.also_queued
  const confidence = (c: { min: number | null; max: number | null }) => {
    if (c.min === null || c.max === null) return null
    return c.min === c.max ? `confidence ${c.min.toFixed(2)}` : `observed ${c.min.toFixed(2)}–${c.max.toFixed(2)}`
  }
  const lastDecision = formatDay(data.decisions.last_at)
  const NOUN: Record<string, [string, string]> = {
    approve: ['approval', 'approvals'],
    reject: ['rejection', 'rejections'],
    split: ['split', 'splits'],
    merge: ['merge', 'merges'],
  }
  const actions = Object.entries(data.decisions.by_action)
    .map(([action, n]) => `${formatCount(n)} ${(NOUN[action] ?? [action, action])[n === 1 ? 0 : 1]}`)
    .join(', ')

  return (
    <section className="space-y-4" data-testid="held_for_review">
      <h2 className="micro-label">Why {formatCount(data.total)} pairs wait for a human</h2>
      <div className="space-y-6 card p-4 sm:p-5">
        <ol className="space-y-6">
          <Rung
            label={conflict.label}
            count={conflict.pairs}
            qualifier={confidence(conflict.confidence)}
            roles={conflict.owner_roles}
          >
            <dl className="space-y-1.5 pt-1">
              {conflict.parts.map((part) => (
                <div key={part.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4">
                  <dt className="text-xs text-muted">
                    {part.label}
                    {part.equivalence_flagged !== null && (
                      <>
                        , of which{' '}
                        <span className="font-mono tabular-nums">{formatCount(part.equivalence_flagged)}</span>{' '}
                        flagged as equivalence candidates for a technical authority
                      </>
                    )}
                  </dt>
                  <dd className="font-mono text-sm tabular-nums">{formatCount(part.pairs)}</dd>
                </div>
              ))}
            </dl>
          </Rung>
          <Rung
            label={`${review.label} ${data.thresholds.t_low.toFixed(2)}–${data.thresholds.t_high.toFixed(2)}`}
            count={review.pairs}
            qualifier={confidence(review.confidence)}
            roles={review.owner_roles}
          />
        </ol>

        <ul className="space-y-1.5 border-t border-hairline pt-4 text-xs text-muted">
          <li>
            <span className="font-mono tabular-nums text-ink">{formatCount(highQueue.pending)}</span> automatic
            merges are also queued for confirmation ({highQueue.reason}): a policy question — accept above{' '}
            {data.thresholds.t_high.toFixed(2)}
            {highQueue.evidence.duplicate_precision !== null && (
              <>
                , held-out precision {highQueue.evidence.duplicate_precision.toFixed(3)} on synthetic truth
              </>
            )}{' '}
            — not steward labour.
          </li>
          <li>
            <span className="font-mono tabular-nums text-ink">{formatCount(lowQueue.pending)}</span> refusals are
            queued as an audit sample of {formatCount(lowQueue.sample_of)} ({lowQueue.reason}).
          </li>
          <li>
            Decisions so far:{' '}
            <span className="font-mono tabular-nums text-ink">{formatCount(data.decisions.total)}</span>
            {actions && <> ({actions})</>}
            {lastDecision && <>, last on {lastDecision}</>}
            {data.decisions.undone ? <>; {formatCount(data.decisions.undone)} taken back within the undo window</> : null}.
          </li>
          {data.decisions.seconds && (
            <li>
              Seconds per decision, as reported by the Workbench over{' '}
              <span className="font-mono tabular-nums text-ink">{formatCount(data.decisions.seconds.n)}</span>{' '}
              decisions: median{' '}
              <span className="font-mono tabular-nums text-ink">{data.decisions.seconds.median}</span> s, 90th
              percentile <span className="font-mono tabular-nums text-ink">{data.decisions.seconds.p90}</span> s.
              A median, not a rate: one reviewer's afternoon is not a trend.
            </li>
          )}
          <li>
            Labels feeding the learner:{' '}
            <span className="font-mono tabular-nums text-ink">{formatCount(data.labels.reviewer)}</span> by
            reviewers, <span className="font-mono tabular-nums text-ink">{formatCount(data.labels.simulated)}</span>{' '}
            simulated.
          </li>
        </ul>
      </div>
      <p className="max-w-prose text-xs text-muted">
        Band is not a function of the score: a conflict pair scores{' '}
        {conflict.confidence.max !== null ? conflict.confidence.max.toFixed(2) : 'full marks'} on the words and
        is held because an attribute disagrees; that is the veto layer working, not the matcher doubting.
        No rate or ETA is drawn from {formatCount(data.decisions.total)} decisions. Precision is on synthetic
        held-out truth.
      </p>
    </section>
  )
}

function Rung({
  label,
  count,
  qualifier,
  roles,
  children,
}: {
  label: string
  count: number
  qualifier: string | null
  roles: string[]
  children?: ReactNode
}) {
  return (
    <li className="grid grid-cols-[0.75rem_minmax(0,1fr)] gap-x-3">
      <span aria-hidden className="mt-1.5 block h-3 w-0.5 bg-ink" />
      <div className="space-y-2">
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4">
          <p className="text-sm">{label}</p>
          <p className="font-mono text-base tabular-nums">{formatCount(count)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {qualifier && <span className="font-mono tabular-nums">{qualifier} ·</span>}
          <span>closed by</span>
          {roles.map((role) => (
            <StatusChip key={role} tone="neutral">
              {role}
            </StatusChip>
          ))}
        </div>
        {children}
      </div>
    </li>
  )
}
