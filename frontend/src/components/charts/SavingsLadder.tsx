import type { SavingsLadder as SavingsLadderData } from '../../lib/api'
import { TBody, TD, TH, THead, TR, Table } from '../primitives/Table'
import { BarRows, type BarRow } from './BarRows'
import { TableTwin, formatCount, formatPercent, toCrore } from './ChartParts'
import { formatRupees } from './CountUp'

/**
 * From last year's spend to the savings figure (spec section savings_ladder).
 *
 * Four bars on one linear scale from zero: the purchase window, the spend on
 * shared materials, the ceiling if every order had been at the best price
 * observed, and the estimate at the stated capture with a whisker across the
 * 40–80% range so the sensitivity is one mark rather than a slider. Linear is
 * honest here — the range is 16× and the smallest rung is still legible. One
 * series, one shade, no legend; the same function as the savings KPI, so the
 * two cannot disagree.
 */
export function SavingsLadder({ data }: { data: SavingsLadderData }) {
  const rungs = data.rungs
  const estimate = rungs.find((r) => r.key === 'estimate')
  const shared = rungs.find((r) => r.key === 'shared')
  const sens = estimate?.sensitivity

  const rows: BarRow[] = rungs.map((r) => {
    const parts: string[] = []
    if (r.materials !== null) parts.push(`${formatCount(r.materials)} materials`)
    if (r.orders !== null) parts.push(`${formatCount(r.orders)} orders`)
    if (r.key === 'ceiling') parts.push('upper bound, not a forecast')
    if (r.key === 'estimate' && r.sensitivity) {
      parts.push(
        `at ${formatPercent(r.sensitivity.capture_low)}–${formatPercent(r.sensitivity.capture_high)} capture: ${formatRupees(
          r.sensitivity.value_low_inr,
        )}–${formatRupees(r.sensitivity.value_high_inr)}`,
      )
    }
    return {
      key: r.key,
      label: r.key === 'ceiling' ? `${r.label} (upper bound)` : r.label,
      sublabel: parts.join(' · ') || undefined,
      segments: [{ key: r.key, value: toCrore(r.value_inr), shade: 0 }],
      tip: formatRupees(r.value_inr),
      tipNote: r.share_of_previous !== null ? `· ${formatPercent(r.share_of_previous)}` : undefined,
      title: `${r.label}: ${formatRupees(r.value_inr)}${
        r.share_of_previous !== null ? ` (${formatPercent(r.share_of_previous)} of the rung above)` : ''
      }${r.assumption ? ` — ${r.assumption}` : ''}`,
      whisker: r.sensitivity ? { from: toCrore(r.sensitivity.value_low_inr), to: toCrore(r.sensitivity.value_high_inr) } : undefined,
    }
  })

  const aria = `Savings ladder: ${rungs.map((r) => `${r.label} ${formatRupees(r.value_inr)}`).join('; ')}${
    sens ? `; at ${formatPercent(sens.capture_low)}–${formatPercent(sens.capture_high)} capture the estimate spans ${formatRupees(sens.value_low_inr)} to ${formatRupees(sens.value_high_inr)}` : ''
  }.`

  return (
    <section className="space-y-4" data-testid="savings_ladder">
      <h2 className="micro-label">From last year&apos;s spend to the savings figure</h2>
      <div className="space-y-5 card p-4 sm:p-5">
        <BarRows rows={rows} ticks={[0, 1000, 2000, 3000]} formatTick={formatCount} axisTitle="₹ Cr" ariaLabel={aria} />
        <p className="text-xs text-muted">
          The muted percentage at each tip is the rung&apos;s share of the rung above
          {sens && (
            <>
              ; the whisker on the last rung is the estimate at {formatPercent(sens.capture_low)}–
              {formatPercent(sens.capture_high)} capture instead of {formatPercent(data.capture)}
            </>
          )}
          .
        </p>
      </div>
      <TableTwin>
        <Table>
          <THead>
            <TH>Rung</TH>
            <TH align="right">₹</TH>
            <TH align="right">Share of previous</TH>
            <TH align="right">Materials</TH>
            <TH>Assumption</TH>
          </THead>
          <TBody>
            {rungs.map((r) => (
              <TR key={r.key}>
                <TD>{r.label}</TD>
                <TD mono align="right">
                  {formatRupees(r.value_inr)}
                </TD>
                <TD mono align="right" className="text-muted">
                  {r.share_of_previous === null ? '—' : formatPercent(r.share_of_previous)}
                </TD>
                <TD mono align="right">
                  {r.materials === null ? '—' : formatCount(r.materials)}
                </TD>
                <TD className="text-xs text-muted">
                  {r.assumption ?? '—'}
                  {r.sensitivity && (
                    <>
                      {' '}
                      At {formatPercent(r.sensitivity.capture_low)}–{formatPercent(r.sensitivity.capture_high)}{' '}
                      capture: {formatRupees(r.sensitivity.value_low_inr)}–{formatRupees(r.sensitivity.value_high_inr)}.
                    </>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </TableTwin>
      <p className="max-w-prose text-xs text-muted">
        Modelled money: the estimate assumes {formatPercent(data.capture)} of the observed price spread is
        capturable at combined volume; the ceiling is not a forecast. Same function as the savings tile,
        so the two cannot disagree. Seeded purchases
        {shared?.share_of_previous != null
          ? `; the ${formatPercent(shared.share_of_previous)} shared share is a property of the synthetic overlap.`
          : '.'}
      </p>
    </section>
  )
}
