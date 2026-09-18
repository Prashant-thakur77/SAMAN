import type { ByCpseCount } from '../../lib/api'
import { TBody, TD, TH, THead, TR, Table } from '../primitives/Table'
import { BarRows, type BarRow } from './BarRows'
import { Legend, TableTwin, formatCount } from './ChartParts'

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
const word = (n: number) => WORDS[n] ?? formatCount(n)

/**
 * How many companies describe the same material (spec section by_cpse_count).
 *
 * Four bars, materials on the axis, rows in the label only, so the four-way
 * materials are never confused with the rows they cover. Two shades are
 * emphasis, not categories: the multi-CPSE bars in full ink, the singletons at
 * 34% because they exist to keep the scale honest; two shades, so a legend.
 */
export function MaterialsByCpseCount({ data }: { data: ByCpseCount }) {
  const rows = [...data.rows].sort((a, b) => a.cpses - b.cpses)
  const totalMaterials = rows.reduce((s, r) => s + r.materials, 0)
  const most = rows[rows.length - 1]
  const multi = rows.filter((r) => r.cpses >= 2)

  const bars: BarRow[] = rows.map((row) => ({
    key: String(row.cpses),
    label: `${row.cpses} ${row.cpses === 1 ? 'CPSE' : 'CPSEs'}`,
    segments: [{ key: 'materials', value: row.materials, shade: row.cpses >= 2 ? 0 : 2 }],
    tip: `${formatCount(row.materials)} materials`,
    tipNote: `· ${formatCount(row.rows)} rows`,
    title: `Described by ${row.cpses} ${row.cpses === 1 ? 'CPSE' : 'CPSEs'}: ${formatCount(row.materials)} materials across ${formatCount(row.rows)} catalogue rows`,
  }))

  const aria = `Materials by how many CPSEs describe them: ${rows
    .map((r) => `${r.cpses} ${r.cpses === 1 ? 'CPSE' : 'CPSEs'} ${formatCount(r.materials)} materials`)
    .join(', ')}. ${formatCount(data.multi_materials)} materials are described by more than one CPSE.`

  const onboarded = data.cpses_with_rows + data.cpses_empty.length

  return (
    <section className="space-y-4" data-testid="by_cpse_count">
      <h2 className="micro-label">How many companies describe the same material</h2>
      <div className="space-y-5 card p-4 sm:p-5">
        <p className="text-sm">
          <span className="font-mono tabular-nums">{formatCount(data.multi_materials)}</span> of{' '}
          <span className="font-mono tabular-nums">{formatCount(totalMaterials)}</span> materials are
          described by more than one CPSE
          {most && most.cpses >= 2 && (
            <>
              ; <span className="font-mono tabular-nums">{formatCount(most.materials)}</span> by all{' '}
              {word(most.cpses)}
            </>
          )}
          .
        </p>
        <Legend
          items={[
            { key: 'multi', label: 'Described by more than one CPSE', shade: 0 },
            { key: 'single', label: 'One CPSE only', shade: 2 },
          ]}
        />
        <BarRows
          rows={bars}
          ticks={[0, 1000, 2000, 3000, 4000, 5000]}
          formatTick={formatCount}
          axisTitle="materials"
          ariaLabel={aria}
        />
      </div>
      <TableTwin minWidth="min-w-0">
        <Table>
          <THead>
            <TH align="right">CPSEs</TH>
            <TH align="right">Materials</TH>
            <TH align="right">Rows</TH>
          </THead>
          <TBody>
            {rows.map((row) => (
              <TR key={row.cpses}>
                <TD mono align="right">
                  {row.cpses}
                </TD>
                <TD mono align="right">
                  {formatCount(row.materials)}
                </TD>
                <TD mono align="right">
                  {formatCount(row.rows)}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </TableTwin>
      <p className="max-w-prose text-xs text-muted">
        {onboarded > data.cpses_with_rows
          ? `${word(onboarded)[0].toUpperCase()}${word(onboarded).slice(1)} CPSEs are onboarded; ${data.cpses_empty.join(', ')} ${data.cpses_empty.length === 1 ? 'has' : 'have'} no rows yet, so the maximum is ${word(data.cpses_with_rows)}.`
          : `${word(data.cpses_with_rows)[0].toUpperCase()}${word(data.cpses_with_rows).slice(1)} CPSEs have rows, so the maximum is ${word(data.cpses_with_rows)}.`}{' '}
        {formatCount(data.internal_duplicate_rows)} rows are duplicated inside a single CPSE and count
        once here.
        {multi.length > 1 && (
          <>
            {' '}
            The near-flat {multi.map((r) => formatCount(r.materials)).join(' / ')} profile is the seed
            generator&apos;s (every pair of CPSEs shares a near-equal number of materials); real
            catalogues will not be this even.
          </>
        )}
      </p>
    </section>
  )
}
