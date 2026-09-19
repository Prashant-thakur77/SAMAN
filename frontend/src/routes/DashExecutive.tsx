import { motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts'

import { EvaluationTable } from '../components/charts/EvaluationTable'
import { HarmonisationByClass } from '../components/charts/HarmonisationByClass'
import { HarmonisationDonut } from '../components/charts/HarmonisationDonut'
import { HeldForReview } from '../components/charts/HeldForReview'
import { MaterialsByCpseCount } from '../components/charts/MaterialsByCpseCount'
import { PipelineLadder } from '../components/charts/PipelineLadder'
import { SavingsLadder } from '../components/charts/SavingsLadder'
import { StockAge } from '../components/charts/StockAge'
import { VetoAttributes } from '../components/charts/VetoAttributes'
import { PageHeader } from '../components/PageHeader'
import { ProvenanceLine, provenanceTitle } from '../components/charts/Provenance'
import { AXIS_PROPS, CHART_INK, GRID_PROPS, TOOLTIP_PROPS } from '../components/charts/Chrome'
import { formatDay } from '../components/charts/ChartParts'
import { CountUp, formatRupees } from '../components/charts/CountUp'
import { EmptyState } from '../components/primitives/EmptyState'
import { StatusChip } from '../components/primitives/Chip'
import { ApiError, getExecutive, type ExecutiveDashboard, type QualityRate, type QualityScorecard} from '../lib/api'
import { cn } from '../lib/cn'
import { listItemVariants, listVariants } from '../lib/motion'
import { useSession } from '../lib/session'

/** Where each tile's rows are: an executive's next question is always "which ones". */
const KPI_TARGET: Record<string, { to: string; label: string }> = {
  items: { to: '/search', label: 'Open the catalogue' },
  clusters: { to: '/search?cnmc=no', label: 'Materials not yet coded' },
  duplicates: { to: '/workbench?band=high', label: 'The merges awaiting confirmation' },
  cnmcs: { to: '/search?cnmc=yes', label: 'The coded rows' },
  automation: { to: '/workbench', label: 'What was left to people' },
  savings: { to: '/dashboard/opportunity', label: 'The ladder behind the figure' },
  prevented: { to: '/smart-create', label: 'Smart-Create' },
}

/**
 * /dashboard/executive — spec §6.7.
 *
 * Every figure is computed from the database and reconciles with
 * `/api/metrics`; nothing here is a constant. The heatmap uses grayscale
 * intensity because §1.1 rations colour to two semantic tones.
 *
 * Read top to bottom as one argument: where the estate stands (KPIs, progress,
 * the donut and its per-family and per-company breakdowns, the heatmap), how
 * the machine decided (the pipeline ladder, the vetoing attributes, what waits
 * for a human, the held-out scorecard), what it is worth (codes over time, the
 * savings ladder, inventory and stock age), and data quality to close.
 */
export default function DashExecutive() {
  const [data, setData] = useState<ExecutiveDashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reduce = useReducedMotion() ?? false
  const { user } = useSession()
  // The same page serves a steward and a ministry reader: a steward can fold
  // the per-CPSE sections down to their own company. The national figures
  // above them do not change; what they see less of is other companies.
  const own = user?.cpse_code ?? null
  const [mineOnly, setMineOnly] = useState(false)
  const showCpse = (cpse: string) => !mineOnly || !own || cpse === own

  useEffect(() => {
    let alive = true
    getExecutive()
      .then((d) => alive && setData(d))
      .catch((err) => alive && setError(err instanceof ApiError ? err.message : 'Unavailable.'))
    return () => {
      alive = false
    }
  }, [])

  if (error) {
    return (
      <div className="space-y-8">
        <PageHeader section="Analytics" title="Executive dashboard" description="Unavailable." />
        <EmptyState title="Could not load" description={error} />
      </div>
    )
  }
  if (!data) {
    return (
      <div className="space-y-8">
        <PageHeader section="Analytics" title="Executive dashboard" description="Loading…" />
      </div>
    )
  }

  const hasData = data.kpis.some((k) => k.value > 0)
  const codesIssued = data.kpis.find((k) => k.key === 'cnmcs')?.value
  const baselineRecall = data.evaluation?.rows.find((r) => r.key === 'recall')?.baseline ?? null
  // Every day on which a code was issued; one day means one seeded batch.
  const issueDays = data.trend.filter((t) => t.cnmcs_issued > 0).map((t) => t.date)

  return (
    <div className="space-y-8">
      <PageHeader
        section="Analytics"
        title="Executive dashboard"
        description="Harmonization progress across CPSEs. Every figure is computed from the database and reconciles with /api/metrics."
        actions={
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => window.print()}
              className="no-print font-mono text-[11px] text-muted underline-offset-2 hover:text-ink hover:underline"
              title="Print the page, or save it as a PDF from the print dialog"
            >
              Print / PDF
            </button>
            <StatusChip tone="neutral">{data.visibility.role}</StatusChip>
          </div>
        }
      />
      <ProvenanceLine provenance={data.provenance} />

      {!hasData ? (
        <EmptyState
          title="No data yet"
          description="Run make demo to seed the catalogues and execute the pipeline."
        />
      ) : (
        <>
          <motion.dl
            variants={listVariants(reduce)}
            initial="initial"
            animate="animate"
            className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card md:grid-cols-3 [&>*:last-child:nth-child(odd)]:col-span-2 md:[&>*:last-child:nth-child(odd)]:col-span-1 md:[&>*:last-child:nth-child(3n+1)]:col-span-3"
          >
            {data.kpis.map((kpi) => {
              const target = KPI_TARGET[kpi.key]
              return (
                <motion.div
                  key={kpi.key}
                  variants={listItemVariants(reduce)}
                  className="space-y-2 bg-surface p-5"
                >
                  <dt className="micro-label">{kpi.label}</dt>
                  <dd className="font-mono text-xl text-ink" title={provenanceTitle(data.provenance)}>
                    <CountUp value={kpi.value} format={kpi.format} />
                  </dd>
                  {kpi.note && <p className="text-xs text-muted">{kpi.note}</p>}
                  {target && (
                    <Link
                      to={target.to}
                      className="inline-block text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
                    >
                      {target.label} →
                    </Link>
                  )}
                </motion.div>
              )
            })}
            {/* The grid paints its gaps with the hairline colour, so a row that
                does not divide evenly leaves grey blocks that read as a
                rendering fault rather than as empty space. Seven KPIs in three
                columns left two of them. */}
            {Array.from({ length: (3 - (data.kpis.length % 3)) % 3 }).map((_, index) => (
              <div key={`filler-${index}`} aria-hidden className="hidden bg-surface md:block" />
            ))}
          </motion.dl>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="micro-label">Progress by CPSE</h2>
              {own && (
                <button
                  type="button"
                  aria-pressed={mineOnly}
                  onClick={() => setMineOnly((m) => !m)}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs',
                    mineOnly ? 'border-inverse bg-inverse text-bg' : 'border-hairline text-muted hover:text-ink',
                  )}
                  title={`Fold the per-CPSE sections down to ${own}. The national figures stay.`}
                >
                  Only {own}
                </button>
              )}
            </div>
            <div className="space-y-3">
              {data.per_cpse.filter((row) => showCpse(row.cpse)).map((row) => (
                <div
                  key={row.cpse}
                  className={cn(
                    'grid grid-cols-[5rem_1fr_9rem] items-center gap-4',
                    own === row.cpse && 'rounded-md bg-surface py-1 ring-1 ring-hairline',
                  )}
                >
                  <Link
                    to={`/search?cpse=${encodeURIComponent(row.cpse)}`}
                    className="font-mono text-sm underline-offset-2 hover:underline"
                    title={`Open ${row.cpse}'s rows`}
                  >
                    {row.cpse}
                  </Link>
                  <div className="h-2 w-full bg-hairline" aria-hidden>
                    <div
                      className="h-full bg-ink transition-[width] duration-500 ease-saman"
                      style={{ width: `${Math.round(row.progress * 100)}%` }}
                    />
                  </div>
                  <span className="text-right font-mono text-xs text-muted">
                    {row.coded.toLocaleString('en-IN')} / {row.items.toLocaleString('en-IN')}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted">
              Rows whose cluster carries an issued CNMC, against the whole catalogue.
            </p>
          </section>

          <HarmonisationDonut harmonisation={data.harmonisation} />

          <HarmonisationByClass byClass={data.by_class} codesIssued={codesIssued} />

          <MaterialsByCpseCount data={data.by_cpse_count} />

          <section className="space-y-4">
            <h2 className="micro-label">Class × CPSE coverage</h2>
            <div className="overflow-x-auto">
              <table className="border-collapse text-xs">
                <thead>
                  <tr>
                    <th className="micro-label px-3 py-2 text-left font-medium">Class</th>
                    {data.heatmap.cpses.filter(showCpse).map((cpse) => (
                      <th key={cpse} className="micro-label px-3 py-2 text-center font-medium">
                        {cpse}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.heatmap.classes.map((klass) => (
                    <tr key={klass}>
                      <td className="whitespace-nowrap px-3 py-1 font-mono">{klass}</td>
                      {data.heatmap.cpses.filter(showCpse).map((cpse) => {
                        const cell = data.heatmap.cells.find(
                          (c) => c.class_code === klass && c.cpse === cpse,
                        )
                        const intensity = cell?.intensity ?? 0
                        return (
                          <td key={cpse} className="p-0.5">
                            <Link
                              to={`/search?cpse=${encodeURIComponent(cpse)}&class=${encodeURIComponent(klass)}`}
                              title={`${klass} · ${cpse} · ${cell?.count ?? 0} rows — open them`}
                              className={cn(
                                'flex h-8 min-w-[4rem] items-center justify-center border border-hairline font-mono hover:outline hover:outline-1 hover:outline-ink',
                                intensity > 0.55 ? 'text-bg' : 'text-ink',
                              )}
                              style={{ background: `rgb(var(--ink) / ${intensity.toFixed(3)})` }}
                            >
                              {cell?.count ?? 0}
                            </Link>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted">
              Grayscale intensity, scaled to the busiest cell ({data.heatmap.peak.toLocaleString('en-IN')} rows).
            </p>
          </section>

          <PipelineLadder pipeline={data.pipeline} baselineRecall={baselineRecall} />

          <VetoAttributes data={data.veto_attributes} />

          <HeldForReview data={data.held_for_review} />

          <EvaluationTable evaluation={data.evaluation} />

          <section className="space-y-4">
            <h2 className="micro-label">Codes issued over time</h2>
            {data.trend.length === 0 ? (
              <p className="card px-4 py-6 text-sm text-muted">
                No CNMC has been issued yet, so there is nothing to plot. Issue one from a
                cluster page and it appears here.
              </p>
            ) : (
              <div className="h-56 w-full card p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.trend} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                    <CartesianGrid {...GRID_PROPS} />
                    <XAxis dataKey="date" {...AXIS_PROPS} />
                    <YAxis {...AXIS_PROPS} allowDecimals={false} />
                    <Tooltip {...TOOLTIP_PROPS} />
                    <Line
                      type="monotone"
                      dataKey="cnmcs_total"
                      name="CNMCs issued"
                      stroke={CHART_INK}
                      strokeWidth={1.5}
                      dot={false}
                      isAnimationActive={!reduce}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {data.trend.length > 0 && (
              <p className="text-xs text-muted">
                {issueDays.length === 1 && codesIssued !== undefined
                  ? `All ${codesIssued.toLocaleString('en-IN')} codes were issued in one seeded batch on ${formatDay(issueDays[0])}; the line is that single step.`
                  : 'Cumulative CNMCs issued, by day.'}
              </p>
            )}
          </section>

          <SavingsLadder data={data.savings_ladder} />

          <section className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card md:grid-cols-3">
            {[
              { label: 'Stock positions', value: data.inventory.positions.toLocaleString('en-IN') },
              { label: 'Inventory value', value: formatRupees(data.inventory.total_value) },
              {
                label: `Dead stock (${data.inventory.dead_stock_materials.toLocaleString('en-IN')} materials)`,
                value: formatRupees(data.inventory.dead_stock_value),
              },
            ].map((tile) => (
              <div key={tile.label} className="space-y-2 bg-surface p-5">
                <p className="micro-label">{tile.label}</p>
                <p className="font-mono text-lg">{tile.value}</p>
              </div>
            ))}
          </section>

          <StockAge data={data.stock_age} />

          <QualityTable quality={data.quality} />
        </>
      )}
    </div>
  )
}

const QUALITY_COLUMNS: { key: QualityRate; label: string }[] = [
  { key: 'classified', label: 'Classified' },
  { key: 'attributes', label: 'Attributes complete' },
  { key: 'uom', label: 'UoM canonical' },
  { key: 'mpn', label: 'MPN present' },
  { key: 'unique', label: 'No internal duplicates' },
  { key: 'active', label: 'Active' },
]

/**
 * The problem statement promises "improved material master data quality".
 * This is the promise as a number per catalogue, with the weights shown, so a
 * steward can see what to fix and a registrar can see whose needs it most.
 */
function QualityTable({ quality }: { quality: QualityScorecard }) {
  const rows = [...quality.cpses, ...(quality.national ? [quality.national] : [])]
  const pct = (v: number) => `${Math.round(v * 100)}%`
  return (
    <section className="space-y-4" data-testid="quality">
      <h2 className="micro-label">Data quality by CPSE</h2>
      <div className="overflow-x-auto rounded-xl border border-hairline shadow-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-hairline bg-surface">
              <th className="micro-label px-3 py-2 text-left font-medium">CPSE</th>
              <th className="micro-label px-3 py-2 text-right font-medium">Rows</th>
              {QUALITY_COLUMNS.map((c) => (
                <th key={c.key} className="micro-label px-3 py-2 text-right font-medium">
                  {c.label}
                  <span className="ml-1 font-mono text-[10px] text-muted">
                    ×{quality.weights[c.key].toFixed(2)}
                  </span>
                </th>
              ))}
              <th className="micro-label px-3 py-2 text-left font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.cpse}
                className={cn(
                  'border-b border-hairline last:border-0',
                  row.cpse === 'ALL' && 'bg-surface font-medium',
                )}
              >
                <td className="px-3 py-2 font-mono">{row.cpse}</td>
                <td className="px-3 py-2 text-right font-mono">
                  {row.items.toLocaleString('en-IN')}
                </td>
                {QUALITY_COLUMNS.map((c) => (
                  <td key={c.key} className="px-3 py-2 text-right font-mono tabular-nums">
                    {pct(row.rates[c.key])}
                  </td>
                ))}
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-24 overflow-hidden rounded-full bg-hairline" aria-hidden>
                      <span
                        className="block h-full bg-ink"
                        style={{ width: `${Math.round(row.score * 100)}%` }}
                      />
                    </span>
                    <span className="font-mono text-xs">{pct(row.score)}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="max-w-prose text-xs text-muted">{quality.note}</p>
    </section>
  )
}
