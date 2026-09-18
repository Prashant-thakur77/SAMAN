import type { PipelineLadder as PipelineLadderData } from '../../lib/api'
import { EmptyState } from '../primitives/EmptyState'
import { TBody, TD, TH, THead, TR } from '../primitives/Table'
import { formatCount, formatDay } from './ChartParts'

/**
 * From every possible pair to issued codes (spec section pipeline).
 *
 * A ladder of numbers, not a chart. The range spans eight orders of magnitude
 * and three units: a linear bar draws 754 at zero pixels beside 69 million and
 * a log axis makes 647k look like half of 69M. So there are no scaled marks,
 * only a fixed tick per rung, the count in tabular mono with its unit, the
 * reduction factor where the unit is unchanged, and an aside naming what left.
 * Beneath, the blocking passes in execution order, unsorted so no pass looks
 * best.
 */
export function PipelineLadder({
  pipeline,
  baselineRecall,
}: {
  pipeline: PipelineLadderData
  /** The exact-text baseline's recall from the scorecard, quoted on the text pass. */
  baselineRecall?: number | null
}) {
  if (!pipeline) {
    return (
      <section className="space-y-4" data-testid="pipeline">
        <h2 className="micro-label">From possible pairs to codes</h2>
        <EmptyState
          title="No matching run yet"
          description="The ladder is read from the last pipeline run's record, never recomputed here. Run make demo to seed the catalogues and execute the pipeline, and it appears with the run's date."
        />
      </section>
    )
  }

  const first = pipeline.rungs[0]
  const last = pipeline.rungs[pipeline.rungs.length - 1]
  const runDay = formatDay(pipeline.run_at)
  const factor = (f: number) => `÷${f >= 10 ? Math.round(f).toLocaleString('en-IN') : f.toFixed(1)}`
  const compact = (n: number) =>
    n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)} million` : formatCount(n)

  return (
    <section className="space-y-4" data-testid="pipeline">
      <h2 className="micro-label">
        From {first ? compact(first.value) : ''} possible pairs to {last ? formatCount(last.value) : ''} codes
      </h2>
      <div className="space-y-6 card p-4 sm:p-5">
        <p className="text-xs text-muted">
          Run {pipeline.run_id}
          {runDay && <> · {runDay}</>} · counts from the run record
        </p>

        <ol className="space-y-1">
          {pipeline.rungs.map((rung) => (
            <li key={rung.key} className="space-y-1">
              {rung.factor_from_previous !== null && (
                <p className="pl-5 font-mono text-[11px] tabular-nums text-muted" aria-label={`reduced ${factor(rung.factor_from_previous)}`}>
                  {factor(rung.factor_from_previous)}
                </p>
              )}
              <div className="grid grid-cols-[0.75rem_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1 sm:grid-cols-[0.75rem_minmax(0,1fr)_auto_minmax(0,16rem)]">
                {/* a 2 × 12 px tick marks position only; nothing here is scaled */}
                <span aria-hidden className="mt-1.5 block h-3 w-0.5 bg-ink" />
                <div className="min-w-0">
                  <p className="text-sm">{rung.label}</p>
                  {rung.note && <p className="text-xs text-muted">{rung.note}</p>}
                </div>
                <p className="whitespace-nowrap text-right font-mono text-sm tabular-nums sm:text-base">
                  {formatCount(rung.value)}
                  <span className="ml-1.5 text-xs text-muted">{rung.unit}</span>
                </p>
                {/* Below sm: the aside takes the row under the count, spanning the
                    label and count columns, so its width never squeezes the label. */}
                {rung.aside && (
                  <p className="col-span-2 col-start-2 text-right font-mono text-xs tabular-nums text-muted sm:col-span-1 sm:col-start-4">
                    {formatCount(rung.aside.value)} {rung.aside.label}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>

        <div className="space-y-3 border-t border-hairline pt-4">
          <p className="text-xs text-muted">
            Blocking passes in execution order, each credited with the pairs no earlier pass produced
            {pipeline.blocking.recall !== null && (
              <>
                {' '}
                · recall {pipeline.blocking.recall.toFixed(4)}
                {pipeline.blocking.missed !== null && pipeline.blocking.true_pairs !== null && (
                  <>
                    {' '}
                    ({formatCount(pipeline.blocking.missed)} of {formatCount(pipeline.blocking.true_pairs)}{' '}
                    planted true pairs missed)
                  </>
                )}
              </>
            )}
            .
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <THead>
                <TH>Pass</TH>
                <TH align="right">Pairs added</TH>
                <TH>What it matched</TH>
              </THead>
              <TBody>
                {pipeline.blocking.passes.map((pass) => (
                  <TR key={pass.pass}>
                    <TD mono>{pass.pass}</TD>
                    <TD mono align="right">
                      {formatCount(pass.added)}
                    </TD>
                    <TD className="text-xs text-muted">
                      {pass.note ?? '—'}
                      {pass.pass === 'text' && (
                        <>
                          {' '}
                          — the naive baseline
                          {baselineRecall !== null && baselineRecall !== undefined && (
                            <>; recall {baselineRecall.toFixed(3)} in the scorecard below</>
                          )}
                        </>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </table>
          </div>
        </div>
      </div>
      <p className="max-w-prose text-xs text-muted">
        Pass counts are marginal: a pair is credited to the first pass that produced it. The refused
        and held counts come from the run record; the pair table keeps only the most plausible
        refusals as evidence, so a table count would not match. Blocking recall is measured against
        planted truth groups in synthetic data.
      </p>
    </section>
  )
}
