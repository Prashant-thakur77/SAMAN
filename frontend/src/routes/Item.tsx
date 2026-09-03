import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { ItemPanel } from '../components/workbench/ItemPanel'
import { formatRupees } from '../components/charts/CountUp'
import { Sparkline } from '../components/charts/Sparkline'
import { CodeChip, StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import { ApiError, getItem, type ItemDetail, type StandardCode, type Standards } from '../lib/api'
import { cn } from '../lib/cn'

/**
 * /items/:id — the golden record, every CPSE's legacy code, and §2B's two
 * distinct blocks: duplicates merged into this CNMC, and equivalents that keep
 * their own code and carry a substitution link.
 */
export default function Item() {
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<ItemDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    getItem(Number(id))
      .then((d) => alive && setDetail(d))
      .catch((err) => alive && setError(err instanceof ApiError ? err.message : 'Not found.'))
    return () => {
      alive = false
    }
  }, [id])

  if (error) {
    return (
      <div className="space-y-8">
        <PageHeader section="Catalogue" title={`Item ${id}`} description="Could not be loaded." />
        <EmptyState title="Not found" description={error} />
      </div>
    )
  }
  if (!detail) {
    return (
      <div className="space-y-8">
        <PageHeader section="Catalogue" title={`Item ${id}`} description="Loading…" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Catalogue"
        title={detail.golden?.std_description ?? detail.normalized}
        description={`${detail.cpse} · ${detail.legacy_code} · ${detail.class_code}`}
        actions={detail.cnmc ? <CodeChip code={detail.cnmc.code} /> : undefined}
      />

      <section className="grid gap-4 lg:grid-cols-2">
        <ItemPanel item={detail} side="This record" />
        <div className="space-y-3 card p-4">
          <p className="micro-label">Golden record</p>
          {detail.golden ? (
            <>
              <p className="font-mono text-sm">{detail.golden.std_description}</p>
              <StatusChip tone={detail.golden.status === 'approved' ? 'ok' : 'neutral'}>
                {detail.golden.status}
              </StatusChip>
              {detail.cluster && (
                <Link
                  to={`/clusters/${detail.cluster.id}`}
                  className="block text-xs text-muted underline underline-offset-2 hover:text-ink"
                >
                  open cluster {detail.cluster.id}
                </Link>
              )}
            </>
          ) : (
            <p className="text-sm text-muted">Not yet standardized.</p>
          )}
          <StandardsBlock standards={detail.standards} />
        </div>
      </section>

      {/* §2E: stock across every CPSE, visible as one position */}
      {detail.consolidated_stock && detail.consolidated_stock.positions.length > 0 && (
        <section className="space-y-4">
          <h2 className="micro-label">Consolidated stock across CPSEs</h2>
          <div className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card sm:grid-cols-3">
            <div className="space-y-1 bg-surface p-4">
              <p className="micro-label">Total on hand</p>
              <p className="font-mono text-lg">
                {detail.consolidated_stock.total_qty.toLocaleString('en-IN')}
              </p>
            </div>
            <div className="space-y-1 bg-surface p-4">
              <p className="micro-label">Held across</p>
              <p className="font-mono text-lg">
                {detail.consolidated_stock.cpse_count} CPSEs ·{' '}
                {detail.consolidated_stock.plant_count} plants
              </p>
            </div>
            <div className="space-y-1 bg-surface p-4">
              <p className="micro-label">Tied-up value</p>
              <p className="font-mono text-lg">
                {formatRupees(detail.consolidated_stock.total_value)}
              </p>
            </div>
          </div>
          <Table>
            <THead>
              <TH>CPSE</TH>
              <TH>Plant</TH>
              <TH align="right">On hand</TH>
              <TH align="right">Available</TH>
              <TH align="right">Value</TH>
              <TH>Last movement</TH>
            </THead>
            <TBody>
              {detail.consolidated_stock.positions.map((position) => (
                <TR key={`${position.cpse}-${position.plant}`}>
                  <TD mono>{position.cpse}</TD>
                  <TD mono>{position.plant}</TD>
                  <TD mono align="right">{position.qty_on_hand.toLocaleString('en-IN')}</TD>
                  <TD mono align="right">{position.available.toLocaleString('en-IN')}</TD>
                  <TD mono align="right">
                    {position.value === null ? (
                      <span className="text-muted" title="Another CPSE's valuation is registrar and auditor scope (§0.9b)">
                        withheld
                      </span>
                    ) : (
                      formatRupees(position.value)
                    )}
                  </TD>
                  <TD mono>{position.last_movement ?? '—'}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </section>
      )}

      {/* §9A(c): last purchase price and its direction */}
      {detail.purchase_history.orders > 0 && (
        <section className="space-y-3">
          <h2 className="micro-label">Purchase history</h2>
          {detail.purchase_history.last ? (
            <div className="flex flex-wrap items-baseline gap-6 card p-4">
              <div>
                <p className="micro-label">Last purchase</p>
                <p className="font-mono text-lg">
                  {formatRupees(detail.purchase_history.last.unit_price)}
                </p>
                <p className="micro-label mt-1">
                  {detail.purchase_history.last.po_date} · {detail.purchase_history.last.vendor}
                </p>
              </div>
              {detail.purchase_history.abc && (
                <div title="ABC by 12-month consumption value, ranked within this CPSE: A carries 70% of spend, B the next 20%, C the rest.">
                  <p className="micro-label">ABC class</p>
                  <p className="font-mono text-lg">{detail.purchase_history.abc}</p>
                  <p className="micro-label mt-1">consumption at {detail.cpse}</p>
                </div>
              )}
              {detail.purchase_history.history.length > 1 && (
                <div className="ml-auto">
                  <p className="micro-label mb-1">Price per base unit</p>
                  <Sparkline points={detail.purchase_history.history} />
                </div>
              )}
              {detail.purchase_history.trend && (
                <div>
                  <p className="micro-label">Trend</p>
                  <p
                    className={cn(
                      'font-mono text-lg',
                      detail.purchase_history.trend.direction === 'up' ? 'text-danger' : 'text-ok',
                    )}
                  >
                    {detail.purchase_history.trend.change_pct > 0 ? '+' : ''}
                    {detail.purchase_history.trend.change_pct}%
                  </p>
                  <p className="micro-label mt-1">
                    over {detail.purchase_history.orders} orders
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="card px-4 py-3 text-sm text-muted">
              {detail.purchase_history.price_band?.label ??
                'Prices for this CPSE are outside your visibility scope.'}
            </p>
          )}
        </section>
      )}

      {detail.installed_on.length > 0 && (
        <section className="space-y-3" data-testid="installed-on">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="micro-label">Installed on</h2>
            {detail.ved && (
              <StatusChip tone={detail.ved === 'vital' ? 'danger' : 'neutral'}>
                {detail.ved} spare
              </StatusChip>
            )}
          </div>
          <ul className="flex flex-wrap gap-2">
            {detail.installed_on.map((fit) => (
              <li
                key={`${fit.cpse}-${fit.tag}`}
                className="card px-3 py-1.5 text-xs"
                title={`${fit.description} · criticality ${fit.criticality} · qty ${fit.qty}`}
              >
                <span className="font-mono">{fit.tag}</span>
                <span className="text-muted"> · {fit.cpse} · </span>
                <span className={cn('font-mono', fit.criticality === 'A' && 'text-danger')}>
                  {fit.criticality}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">
            The plant's own criticality (A, B, C), read as VED for the material. A substitute
            for a vital spare needs an engineer's approval before it is fitted.
          </p>
        </section>
      )}

      {/* §2B: two separate blocks, deliberately */}
      <section className="space-y-4">
        <h2 className="micro-label">Duplicates: merged into this CNMC</h2>
        {detail.duplicates.length === 0 ? (
          <p className="text-sm text-muted">No other CPSE catalogues this item.</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {detail.duplicates.map((item) => (
              <ItemPanel key={item.item_id} item={item} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="micro-label">Equivalents: separate CNMC, interchangeable</h2>
        {detail.equivalents.length === 0 ? (
          <p className="text-sm text-muted">No interchangeable item has been identified.</p>
        ) : (
          <ul className="space-y-3">
            {detail.equivalents.map((entry) => (
              <li
                key={entry.counterpart.item_id}
                className="flex flex-wrap items-start gap-4 card p-4"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink">{entry.counterpart.description}</p>
                  <p className="micro-label mt-1">
                    {entry.counterpart.cpse} · {entry.counterpart.legacy_code}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="font-mono text-xs">
                    {entry.rel_type === 'equivalent'
                      ? 'interchangeable ⇄'
                      : entry.substitutes_this
                        ? 'that ➜ can substitute this'
                        : 'this ➜ can substitute that'}
                  </p>
                  <p className="micro-label mt-1">
                    {entry.basis} · {Math.round(entry.confidence * 100)}%
                  </p>
                  <div className="mt-2 flex justify-end">
                    <StatusChip
                      tone={
                        entry.status === 'approved'
                          ? 'ok'
                          : entry.status === 'rejected'
                            ? 'danger'
                            : 'neutral'
                      }
                    >
                      {entry.status === 'approved'
                        ? `approved by ${entry.approval?.decided_by ?? 'an engineer'}`
                        : entry.status === 'rejected'
                          ? 'rejected'
                          : 'awaiting engineering approval'}
                    </StatusChip>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

/**
 * The public codes a class maps to. UNSPSC is what GeM and tenders categorise
 * by; the HSN heading is what every purchase order needs for GST. Both are
 * class defaults with a stated level, not a per-item determination, and the
 * block says so.
 */
function StandardsBlock({ standards }: { standards?: Standards }) {
  const rows = [
    standards?.unspsc && { scheme: 'UNSPSC', ...standards.unspsc },
    standards?.hsn && { scheme: 'HSN', ...standards.hsn },
  ].filter(Boolean) as (StandardCode & { scheme: string })[]
  if (rows.length === 0) return null
  return (
    <div className="space-y-2 border-t border-hairline pt-3" data-testid="standards">
      <p className="micro-label">Classification codes</p>
      <dl className="space-y-1">
        {rows.map((row) => (
          <div key={row.scheme} className="flex flex-wrap items-baseline gap-x-3 text-sm">
            <dt className="w-16 shrink-0 text-muted">{row.scheme}</dt>
            <dd className="font-mono">{row.code}</dd>
            <dd className="text-muted">
              {row.title} <span className="text-xs">({row.level})</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted">
        Assigned per class; confirm the HSN with your taxation cell before invoicing.
      </p>
    </div>
  )
}
