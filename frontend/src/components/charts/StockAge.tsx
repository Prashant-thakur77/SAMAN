import type { StockAge as StockAgeData } from '../../lib/api'
import { TBody, TD, TH, THead, TR, Table } from '../primitives/Table'
import { BarRows, type BarRow, type BarRule } from './BarRows'
import { Legend, TableTwin, formatCount, formatPercent, toCrore } from './ChartParts'
import { formatRupees } from './CountUp'

/**
 * Stock that has stopped moving, and whether a sister CPSE still buys it
 * (spec section stock_age).
 *
 * One bar per six-month bin of months since the last movement, freshest at the
 * top, value on hand in ₹ Cr; each bar stacks the value another CPSE bought in
 * the demand window (full ink) over the value nobody else wants (34%), with a
 * legend. The dead-stock rule is drawn where the code applies it, read from
 * the constant, so the bars beyond it sum to the tile by construction. The
 * table twin carries positions and materials, which synthetic pricing does not
 * distort.
 */
export function StockAge({ data }: { data: StockAgeData }) {
  const bins = data.bins
  const rows: BarRow[] = bins.map((bin) => ({
    key: bin.label,
    label: `${bin.label} months`,
    segments: [
      { key: 'demand', value: toCrore(bin.demand_elsewhere_value_inr), shade: 0 },
      { key: 'none', value: toCrore(bin.no_demand_value_inr), shade: 2 },
    ],
    tip: bin.value_inr > 0 ? formatRupees(bin.value_inr) : 'nil',
    title: `${bin.label} months since last movement · ${formatCount(bin.positions)} positions · ${formatCount(
      bin.materials,
    )} materials · ${formatRupees(bin.value_inr)} on hand, of which ${formatRupees(
      bin.demand_elsewhere_value_inr,
    )} in materials a sister CPSE bought in the last ${data.demand_window_months} months`,
  }))

  // The rule sits after the last bin the code still counts as moving.
  const lastLive = bins.reduce((acc, bin, i) => (bin.idle ? acc : i), -1)
  const rules: BarRule[] =
    lastLive >= 0 && lastLive < bins.length - 1
      ? [
          {
            afterRow: lastLive,
            label: 'counted as dead stock',
            sublabel: `${data.rule_months} months without movement`,
          },
        ]
      : []

  const aria = `Stock by months since last movement: ${bins
    .map((b) => `${b.label} months ${formatRupees(b.value_inr)}`)
    .join(', ')}. ${formatRupees(data.idle.value_inr)} has not moved in ${data.rule_months} months, ${formatRupees(
    data.idle.demand_elsewhere_value_inr,
  )} of it in materials another CPSE bought in the last ${data.demand_window_months} months.`

  return (
    <section className="space-y-4" data-testid="stock_age">
      <h2 className="micro-label">Stock that has stopped moving, and whether a sister CPSE still buys it</h2>
      <div className="space-y-5 card p-4 sm:p-5">
        <p className="text-sm">
          <span className="font-mono tabular-nums">{formatRupees(data.idle.value_inr)}</span> across{' '}
          <span className="font-mono tabular-nums">{formatCount(data.idle.materials)}</span> materials has not
          moved in {data.rule_months} months;{' '}
          <span className="font-mono tabular-nums">{formatRupees(data.idle.demand_elsewhere_value_inr)}</span> of it
          is in <span className="font-mono tabular-nums">{formatCount(data.idle.demand_elsewhere_materials)}</span>{' '}
          materials another CPSE bought in the last {data.demand_window_months} months.
        </p>
        <Legend
          items={[
            { key: 'demand', label: `A sister CPSE bought this material in the last ${data.demand_window_months} months`, shade: 0 },
            { key: 'none', label: 'No demand seen elsewhere', shade: 2 },
          ]}
        />
        <BarRows
          rows={rows}
          ticks={[0, 1000, 2000, 3000, 4000]}
          formatTick={formatCount}
          rules={rules}
          axisTitle="₹ Cr on hand"
          ariaLabel={aria}
        />
      </div>
      <TableTwin>
        <Table>
          <THead>
            <TH>Months idle</TH>
            <TH align="right">Positions</TH>
            <TH align="right">Materials</TH>
            <TH align="right">On hand</TH>
            <TH align="right">Bought elsewhere</TH>
            <TH align="right">No demand</TH>
          </THead>
          <TBody>
            {bins.map((bin) => (
              <TR key={bin.label}>
                <TD mono>
                  {bin.label}
                  {bin.idle && <span className="ml-2 text-muted">dead stock</span>}
                </TD>
                <TD mono align="right">
                  {formatCount(bin.positions)}
                </TD>
                <TD mono align="right">
                  {formatCount(bin.materials)}
                </TD>
                <TD mono align="right">
                  {formatRupees(bin.value_inr)}
                </TD>
                <TD mono align="right">
                  {formatRupees(bin.demand_elsewhere_value_inr)}
                </TD>
                <TD mono align="right">
                  {formatRupees(bin.no_demand_value_inr)}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </TableTwin>
      <p className="max-w-prose text-xs text-muted">
        Book value of seeded stock positions; no assumption travels with these numbers.
        {data.top_class && (
          <>
            {' '}
            {formatPercent(data.top_class.share_of_idle_value)} of the idle value is {data.top_class.class_code}{' '}
            because synthetic pricing dwarfs the other classes; the table view shows positions per bin, which
            the pricing does not distort.
          </>
        )}{' '}
        &lsquo;A sister CPSE bought this&rsquo; is a visibility signal, not a saving; the transfer engine&apos;s
        stricter modelled figure lives on the opportunity dashboard. The data-quality table&apos;s
        &lsquo;active&rsquo; rate uses a {data.quality_stale_months}-month rule, a different definition.
        {data.excluded_positions > 0 && (
          <>
            {' '}
            {formatCount(data.excluded_positions)} positions without a movement date or quantity are not binned.
          </>
        )}
      </p>
    </section>
  )
}
