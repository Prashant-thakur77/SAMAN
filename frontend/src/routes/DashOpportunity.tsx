import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { formatRupees } from '../components/charts/CountUp'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import { ApiError, getOpportunity, type OpportunityDashboard } from '../lib/api'
import { cn } from '../lib/cn'

const TABS = [
  { key: 'tenders', label: 'Joint tenders' },
  { key: 'variance', label: 'Price variance' },
  { key: 'inventory', label: 'Inventory sharing' },
] as const

type Tab = (typeof TABS)[number]['key']

/**
 * /dashboard/opportunity — spec §6.8 and §2E.
 *
 * The what-if slider changes an *assumption*, not a measurement, so the figure
 * it produces always travels with the assumption that made it. Recomputation is
 * local: the API returns the raw spread and volume, so moving the slider
 * rescales in the browser without a refetch.
 */
export default function DashOpportunity() {
  const [data, setData] = useState<OpportunityDashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [capture, setCapture] = useState(0.6)
  const [tab, setTab] = useState<Tab>('tenders')

  useEffect(() => {
    let alive = true
    // Fetched once at the baseline assumption; the slider rescales locally.
    getOpportunity(0.6)
      .then((d) => alive && setData(d))
      .catch((err) => alive && setError(err instanceof ApiError ? err.message : 'Unavailable.'))
    return () => {
      alive = false
    }
  }, [])

  const scaled = useMemo(() => {
    if (!data) return null
    const factor = capture / data.joint_tenders.capture_assumption
    return {
      total: data.joint_tenders.total_estimated_saving * factor,
      candidates: data.joint_tenders.candidates.map((c) => ({
        ...c,
        estimated_saving: c.estimated_saving * factor,
      })),
    }
  }, [data, capture])

  if (error) {
    return (
      <div className="space-y-8">
        <PageHeader section="Analytics" title="Opportunity" description="Unavailable." />
        <EmptyState title="Could not load" description={error} />
      </div>
    )
  }
  if (!data || !scaled) {
    return (
      <div className="space-y-8">
        <PageHeader section="Analytics" title="Opportunity" description="Loading…" />
      </div>
    )
  }

  const { joint_tenders, price_variance, inventory } = data

  return (
    <div className="space-y-8">
      <PageHeader
        section="Analytics"
        title="Opportunity"
        description="Aggregation candidates, price variance per base unit, and stock that could move instead of being bought."
        actions={
          !data.visibility.sees_attributed_prices ? (
            <StatusChip tone="neutral">Prices anonymised for your role</StatusChip>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center gap-1 border-b border-hairline">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            aria-pressed={tab === entry.key}
            className={cn(
              'border-b-2 px-4 py-2 text-sm',
              tab === entry.key
                ? 'border-inverse font-medium text-ink'
                : 'border-transparent text-muted hover:text-ink',
            )}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === 'tenders' && (
        <section className="space-y-5">
          <div className="grid gap-6 border border-hairline p-6 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-2">
              <p className="micro-label">Savings identified</p>
              <p className="font-mono text-2xl text-ink">{formatRupees(scaled.total)}</p>
              <p className="max-w-prose text-xs text-muted">
                Across {joint_tenders.candidates_found.toLocaleString('en-IN')} materials bought by
                two or more CPSEs in the last {joint_tenders.window_months} months. Assumes{' '}
                <strong className="text-ink">{Math.round(capture * 100)}%</strong> of the observed
                price spread is capturable at combined volume — an assumption, not a measurement.
              </p>
            </div>
            <div className="space-y-3">
              <label htmlFor="capture" className="micro-label block">
                Discount assumption
              </label>
              <input
                id="capture"
                type="range"
                min={0.4}
                max={0.8}
                step={0.05}
                value={capture}
                onChange={(e) => setCapture(Number(e.target.value))}
                className="w-full accent-[rgb(var(--ink))]"
              />
              <div className="flex justify-between font-mono text-xs text-muted">
                <span>40%</span>
                <span className="text-ink">{Math.round(capture * 100)}%</span>
                <span>80%</span>
              </div>
            </div>
          </div>

          <Table>
            <THead>
              <TH>Material</TH>
              <TH>CPSEs</TH>
              <TH align="right">Combined qty</TH>
              <TH align="right">Spread</TH>
              <TH align="right">Est. saving</TH>
            </THead>
            <TBody>
              {scaled.candidates.map((row) => (
                <TR key={row.cluster_id}>
                  <TD>
                    <Link
                      to={`/clusters/${row.cluster_id}`}
                      className="underline underline-offset-2 hover:text-ink"
                    >
                      {row.description ?? `cluster ${row.cluster_id}`}
                    </Link>
                    {row.market_band && (
                      <p className="micro-label mt-1">{row.market_band.label}</p>
                    )}
                  </TD>
                  <TD mono>{row.cpses.join(' ')}</TD>
                  <TD mono align="right">{row.combined_qty.toLocaleString('en-IN')}</TD>
                  <TD mono align="right">{row.spread_pct}%</TD>
                  <TD mono align="right">{formatRupees(row.estimated_saving)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </section>
      )}

      {tab === 'variance' && (
        <section className="space-y-4">
          <p className="text-sm text-muted">{price_variance.note}</p>
          <Table>
            <THead>
              <TH>Material</TH>
              <TH align="right">Variance</TH>
              <TH>Lowest</TH>
              <TH>Highest</TH>
            </THead>
            <TBody>
              {price_variance.rows.map((row) => (
                <TR key={row.cluster_id}>
                  <TD>
                    <Link
                      to={`/clusters/${row.cluster_id}`}
                      className="underline underline-offset-2 hover:text-ink"
                    >
                      {row.description ?? `cluster ${row.cluster_id}`}
                    </Link>
                    {row.market_band && (
                      <p className="micro-label mt-1">{row.market_band.label}</p>
                    )}
                  </TD>
                  <TD mono align="right">{row.variance_pct}%</TD>
                  <TD mono>
                    {row.lowest.cpse}{' '}
                    {row.lowest.unit_price === null ? '—' : formatRupees(row.lowest.unit_price)}
                  </TD>
                  <TD mono>
                    {row.highest.cpse}{' '}
                    {row.highest.unit_price === null ? '—' : formatRupees(row.highest.unit_price)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </section>
      )}

      {tab === 'inventory' && (
        <section className="space-y-8">
          <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-3">
            {[
              {
                label: 'Avoidable purchases',
                value: formatRupees(inventory.transfers.total_avoided_purchase_value),
              },
              {
                label: `Dead stock (${inventory.dead_stock.months_without_movement} months idle)`,
                value: formatRupees(inventory.dead_stock.total_value),
              },
              { label: 'Total inventory', value: formatRupees(inventory.totals.total_value) },
            ].map((tile) => (
              <div key={tile.label} className="space-y-2 bg-bg p-5">
                <p className="micro-label">{tile.label}</p>
                <p className="font-mono text-lg">{tile.value}</p>
              </div>
            ))}
          </div>

          <div className="space-y-3">
            <h2 className="micro-label">Transfer suggestions</h2>
            <p className="max-w-prose text-xs text-muted">{inventory.transfers.note}</p>
            {inventory.transfers.suggestions.length === 0 ? (
              <p className="border border-hairline px-4 py-6 text-sm text-muted">
                No CPSE is holding idle surplus of a material another is short of.
              </p>
            ) : (
              <Table>
                <THead>
                  <TH>Material</TH>
                  <TH>From</TH>
                  <TH>To</TH>
                  <TH align="right">Qty</TH>
                  <TH align="right">Avoids</TH>
                </THead>
                <TBody>
                  {inventory.transfers.suggestions.map((row) => (
                    <TR key={`${row.cluster_id}-${row.from.plant}`}>
                      <TD>
                        <Link
                          to={`/clusters/${row.cluster_id}`}
                          className="underline underline-offset-2 hover:text-ink"
                        >
                          {row.description ?? `cluster ${row.cluster_id}`}
                        </Link>
                        {row.idle_since && (
                          <p className="micro-label mt-1">idle since {row.idle_since}</p>
                        )}
                      </TD>
                      <TD mono>
                        {row.from.cpse} · {row.from.plant}
                      </TD>
                      <TD mono>
                        {row.to.cpse} · {row.to.plant}
                      </TD>
                      <TD mono align="right">{row.qty.toLocaleString('en-IN')}</TD>
                      <TD mono align="right">
                        {row.avoided_purchase_value === null
                          ? '—'
                          : formatRupees(row.avoided_purchase_value)}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </div>

          <div className="space-y-3">
            <h2 className="micro-label">Slow-moving stock</h2>
            <Table>
              <THead>
                <TH>Material</TH>
                <TH align="right">Qty</TH>
                <TH align="right">Value</TH>
              </THead>
              <TBody>
                {inventory.dead_stock.rows.map((row) => (
                  <TR key={row.cluster_id}>
                    <TD>
                      <Link
                        to={`/clusters/${row.cluster_id}`}
                        className="underline underline-offset-2 hover:text-ink"
                      >
                        {row.description ?? `cluster ${row.cluster_id}`}
                      </Link>
                    </TD>
                    <TD mono align="right">{row.qty.toLocaleString('en-IN')}</TD>
                    <TD mono align="right">{formatRupees(row.value)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        </section>
      )}
    </div>
  )
}
