import { motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts'

import { PageHeader } from '../components/PageHeader'
import { AXIS_PROPS, CHART_INK, GRID_PROPS, TOOLTIP_PROPS } from '../components/charts/Chrome'
import { CountUp, formatRupees } from '../components/charts/CountUp'
import { EmptyState } from '../components/primitives/EmptyState'
import { StatusChip } from '../components/primitives/Chip'
import { ApiError, getExecutive, type ExecutiveDashboard } from '../lib/api'
import { cn } from '../lib/cn'
import { listItemVariants, listVariants } from '../lib/motion'

/**
 * /dashboard/executive — spec §6.7.
 *
 * Every figure is computed from the database and reconciles with
 * `/api/metrics`; nothing here is a constant. The heatmap uses grayscale
 * intensity because §1.1 rations colour to two semantic tones.
 */
export default function DashExecutive() {
  const [data, setData] = useState<ExecutiveDashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reduce = useReducedMotion() ?? false

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

  return (
    <div className="space-y-8">
      <PageHeader
        section="Analytics"
        title="Executive dashboard"
        description="Harmonization progress across CPSEs. Every figure is computed from the database and reconciles with /api/metrics."
        actions={<StatusChip tone="neutral">{data.visibility.role}</StatusChip>}
      />

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
            className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card md:grid-cols-3"
          >
            {data.kpis.map((kpi) => (
              <motion.div
                key={kpi.key}
                variants={listItemVariants(reduce)}
                className="space-y-2 bg-surface p-5"
              >
                <dt className="micro-label">{kpi.label}</dt>
                <dd className="font-mono text-xl text-ink">
                  <CountUp value={kpi.value} format={kpi.format} />
                </dd>
                {kpi.note && <p className="text-xs text-muted">{kpi.note}</p>}
              </motion.div>
            ))}
            {/* The grid paints its gaps with the hairline colour, so a row that
                does not divide evenly leaves grey blocks that read as a
                rendering fault rather than as empty space. Seven KPIs in three
                columns left two of them. */}
            {Array.from({ length: (3 - (data.kpis.length % 3)) % 3 }).map((_, index) => (
              <div key={`filler-${index}`} aria-hidden className="hidden bg-surface md:block" />
            ))}
          </motion.dl>

          <section className="space-y-4">
            <h2 className="micro-label">Progress by CPSE</h2>
            <div className="space-y-3">
              {data.per_cpse.map((row) => (
                <div key={row.cpse} className="grid grid-cols-[5rem_1fr_9rem] items-center gap-4">
                  <span className="font-mono text-sm">{row.cpse}</span>
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

          <section className="space-y-4">
            <h2 className="micro-label">Class × CPSE coverage</h2>
            <div className="overflow-x-auto">
              <table className="border-collapse text-xs">
                <thead>
                  <tr>
                    <th className="micro-label px-3 py-2 text-left font-medium">Class</th>
                    {data.heatmap.cpses.map((cpse) => (
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
                      {data.heatmap.cpses.map((cpse) => {
                        const cell = data.heatmap.cells.find(
                          (c) => c.class_code === klass && c.cpse === cpse,
                        )
                        const intensity = cell?.intensity ?? 0
                        return (
                          <td key={cpse} className="p-0.5">
                            <div
                              title={`${klass} · ${cpse} · ${cell?.count ?? 0} rows`}
                              className={cn(
                                'flex h-8 min-w-[4rem] items-center justify-center border border-hairline font-mono',
                                intensity > 0.55 ? 'text-bg' : 'text-ink',
                              )}
                              style={{ background: `rgb(var(--ink) / ${intensity.toFixed(3)})` }}
                            >
                              {cell?.count ?? 0}
                            </div>
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
          </section>

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
        </>
      )}
    </div>
  )
}
