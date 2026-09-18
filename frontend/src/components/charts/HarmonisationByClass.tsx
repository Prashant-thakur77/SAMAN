import { useMemo } from 'react'

import type { ByClass } from '../../lib/api'
import { TBody, TD, TH, THead, TR, Table } from '../primitives/Table'
import { BarRows, type BarRow } from './BarRows'
import { Legend, TableTwin, formatCount, formatPercent } from './ChartParts'
import type { Shade } from './ramp'

/**
 * The donut's three parts, per material family (spec section by_class).
 *
 * A 100% bar per class in the donut's ramp, sorted by coded share so the
 * family that is stuck is the bottom row. A 100% bar hides size, so every
 * row carries its count and the coded share is the only direct label: at
 * 390 px nothing fits inside a segment, and the legend and tooltip carry the
 * rest. Not a heatmap (the Class × CPSE grid already has the counts) and not
 * absolute bars (the reader's question is how far, which is share).
 */
export function HarmonisationByClass({
  byClass,
  codesIssued,
}: {
  byClass: ByClass
  /** The CNMC count from the KPI row, quoted in the caption. */
  codesIssued?: number
}) {
  const rows = useMemo(
    () => [...byClass.rows].sort((a, b) => b.coded_share - a.coded_share || b.rows - a.rows),
    [byClass.rows],
  )
  const shadeOf = (i: number): Shade => (Math.min(i, 2) as Shade)
  const partLabel = (key: string) => byClass.parts.find((p) => p.key === key)?.label ?? key

  const bars: BarRow[] = rows.map((row) => {
    const values = {
      coded: row.coded,
      duplicate_pending: row.duplicate_pending,
      unique_pending: row.unique_pending,
    }
    const readout = byClass.parts
      .map((p) => {
        const v = values[p.key]
        const share = row.rows ? Math.round((v / row.rows) * 100) : 0
        return `${p.label} ${formatCount(v)} (${share}%)`
      })
      .join(' · ')
    return {
      key: row.class_code,
      label: row.class_code,
      labelNote: row.family ?? undefined,
      sublabel: `${formatCount(row.rows)} rows`,
      segments: byClass.parts.map((p, i) => ({ key: p.key, value: values[p.key], shade: shadeOf(i) })),
      tip: row.rows ? formatPercent(row.coded_share, row.coded_share < 0.1 ? 1 : 0) : undefined,
      title: `${row.class_code} · ${formatCount(row.rows)} rows — ${readout}`,
    }
  })

  const top = rows[0]
  // The family that trails: the lowest share among classes that have rows at all.
  const bottom = [...rows].reverse().find((r) => r.rows > 0)
  const aria =
    top && bottom
      ? `Harmonisation by family: ${rows.length} classes as 100% bars split into ${byClass.parts
          .map((p) => p.label.toLowerCase())
          .join(', ')}, sorted by coded share. ${top.class_code} leads at ${formatPercent(top.coded_share)} coded; ${bottom.class_code} trails at ${formatPercent(bottom.coded_share, 1)}.`
      : 'Harmonisation by family: no classes yet.'

  return (
    <section className="space-y-4" data-testid="by_class">
      <h2 className="micro-label">Harmonisation by family</h2>
      <div className="space-y-5 card p-4 sm:p-5">
        <Legend items={byClass.parts.map((p, i) => ({ key: p.key, label: p.label, shade: shadeOf(i) }))} />
        <BarRows rows={bars} ticks={[0, 25, 50, 75, 100]} formatTick={(v) => `${v}%`} percent ariaLabel={aria} />
      </div>
      <TableTwin>
        <Table>
          <THead>
            <TH>Class</TH>
            <TH>Family</TH>
            <TH align="right">Rows</TH>
            <TH align="right">{partLabel('coded')}</TH>
            <TH align="right">{partLabel('duplicate_pending')}</TH>
            <TH align="right">{partLabel('unique_pending')}</TH>
            <TH align="right">Coded share</TH>
          </THead>
          <TBody>
            {rows.map((row) => (
              <TR key={row.class_code}>
                <TD mono>{row.class_code}</TD>
                <TD mono className="text-muted">
                  {row.family ?? '—'}
                </TD>
                <TD mono align="right">
                  {formatCount(row.rows)}
                </TD>
                <TD mono align="right">
                  {formatCount(row.coded)}
                </TD>
                <TD mono align="right">
                  {formatCount(row.duplicate_pending)}
                </TD>
                <TD mono align="right">
                  {formatCount(row.unique_pending)}
                </TD>
                <TD mono align="right">
                  {formatPercent(row.coded_share, 1)}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </TableTwin>
      <p className="max-w-prose text-xs text-muted">
        Each row is one family&apos;s catalogue rows split the way the donut splits the whole
        estate; rows sum to the donut.
        {bottom && (
          <>
            {' '}
            {bottom.class_code} trails because its clusters are held in conflict (see Why pairs
            wait), not because they were missed.
          </>
        )}{' '}
        Synthetic catalogues
        {codesIssued !== undefined
          ? `; all ${formatCount(codesIssued)} codes were issued in one seeded batch.`
          : '.'}
      </p>
    </section>
  )
}
