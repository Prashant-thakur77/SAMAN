import type { Evaluation } from '../../lib/api'
import { StatusChip } from '../primitives/Chip'
import { EmptyState } from '../primitives/EmptyState'
import { TBody, TD, TH, THead, TR } from '../primitives/Table'
import { formatCount } from './ChartParts'

/**
 * Measured on data the thresholds never saw (spec section evaluation).
 *
 * A table, not a chart. Every value sits between 0.90 and 1.00, so a full 0–1
 * axis would compress eight families into a tenth of the width and a truncated
 * one would turn a 0.02 gap into a cliff; two decimals are the message. The
 * pass/fail chips are the one place on this page colour is allowed, because
 * there it means a status. The snapshot is what the pipeline wrote at run end,
 * with its run id, timestamp and the decisions since, never computed here.
 */
export function EvaluationTable({ evaluation }: { evaluation: Evaluation }) {
  if (!evaluation) {
    return (
      <section className="space-y-4" data-testid="evaluation">
        <h2 className="micro-label">Measured on data the thresholds never saw</h2>
        <EmptyState
          title="No held-out scorecard recorded"
          description="The pipeline writes an evaluation snapshot into the run record when it finishes; the latest run has none. GET /api/metrics computes the scorecard on demand, and the next pipeline run records it here."
        />
      </section>
    )
  }

  const recall = evaluation.rows.find((r) => r.key === 'recall')
  const perClass = [...evaluation.per_class].sort((a, b) => a.f1 - b.f1)
  const worst = perClass.find((c) => c.class_code === evaluation.worst_class) ?? perClass[0]
  const three = (v: number | null) => (v === null ? '—' : v.toFixed(3))
  const when = (() => {
    const d = new Date(evaluation.computed_at)
    return Number.isNaN(d.getTime())
      ? evaluation.computed_at
      : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  })()
  const vetoPrecision = evaluation.rows.find((r) => r.key === 'veto_precision')

  return (
    <section className="space-y-4" data-testid="evaluation">
      <h2 className="micro-label">Measured on data the thresholds never saw</h2>
      <div className="space-y-5 card p-4 sm:p-5">
        {recall && (
          <p className="text-sm">
            Recall <span className="font-mono tabular-nums">{recall.value.toFixed(3)}</span>
            {recall.baseline !== null && (
              <>
                {' '}
                vs <span className="font-mono tabular-nums">{recall.baseline.toFixed(3)}</span> for exact-text
                matching
              </>
            )}
            {worst && (
              <>
                ; <span className="font-mono">{worst.class_code}</span> is the weakest family (recall{' '}
                <span className="font-mono tabular-nums">{worst.recall.toFixed(3)}</span>,{' '}
                <span className="font-mono tabular-nums">{formatCount(worst.false_negatives)}</span> missed pairs)
              </>
            )}
            .
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] border-collapse text-sm">
            <THead>
              <TH>Measure</TH>
              <TH align="right">Value</TH>
              <TH align="right">Target</TH>
              <TH align="right">Baseline</TH>
              <TH>Status</TH>
            </THead>
            <TBody>
              {evaluation.rows.map((row) => (
                <TR key={row.key}>
                  <TD>
                    <span>{row.label}</span>
                    {row.detail && <span className="block text-xs text-muted">{row.detail}</span>}
                  </TD>
                  <TD mono align="right" className="text-sm">
                    {three(row.value)}
                  </TD>
                  <TD mono align="right" className="text-muted">
                    {row.target === null ? '—' : `≥ ${row.target.toFixed(2)}`}
                  </TD>
                  <TD mono align="right" className="text-muted">
                    {three(row.baseline)}
                  </TD>
                  <TD>
                    {row.pass === null ? (
                      <span className="text-xs text-muted">no target</span>
                    ) : row.pass ? (
                      <StatusChip tone="ok">meets target</StatusChip>
                    ) : (
                      <StatusChip tone="danger">below target</StatusChip>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </table>
        </div>
        <p className="text-xs text-muted">Baseline — {evaluation.baseline_note}</p>

        <div className="space-y-2 border-t border-hairline pt-4">
          <p className="text-xs text-muted">
            Per family on the held-out split ({formatCount(evaluation.items_holdout)} rows), weakest first
            {worst && (
              <>
                : <span className="font-mono">{worst.class_code}</span>
              </>
            )}
            .
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] border-collapse text-sm">
              <THead>
                <TH>Class</TH>
                <TH align="right">Held-out rows</TH>
                <TH align="right">Precision</TH>
                <TH align="right">Recall</TH>
                <TH align="right">F1</TH>
                <TH align="right">Missed pairs</TH>
              </THead>
              <TBody>
                {perClass.map((c) => (
                  <TR key={c.class_code}>
                    <TD mono>{c.class_code}</TD>
                    <TD mono align="right">
                      {formatCount(c.items)}
                    </TD>
                    <TD mono align="right">
                      {c.precision.toFixed(3)}
                    </TD>
                    <TD mono align="right">
                      {c.recall.toFixed(3)}
                    </TD>
                    <TD mono align="right">
                      {c.f1.toFixed(3)}
                    </TD>
                    <TD mono align="right">
                      {formatCount(c.false_negatives)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </table>
          </div>
        </div>
      </div>
      <p className="max-w-prose text-xs text-muted">
        {evaluation.note}{' '}
        {vetoPrecision && (
          <>
            The traps that give veto precision {vetoPrecision.value.toFixed(2)} are planted, so this measures
            the rule&apos;s behaviour, not field precision.{' '}
          </>
        )}
        Snapshot from run {evaluation.run_id} at {when}; {formatCount(evaluation.decisions_since)}{' '}
        {evaluation.decisions_since === 1 ? 'decision' : 'decisions'} since. Recall is not share coded: the
        weakest family&apos;s missed pairs here and its trailing row in Harmonisation by family (clusters left
        for review) are two different facts.
      </p>
    </section>
  )
}
