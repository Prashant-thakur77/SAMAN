import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { ItemPanel } from '../components/workbench/ItemPanel'
import { CodeChip, StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { ApiError, getItem, type ItemDetail } from '../lib/api'

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
        <div className="space-y-3 border border-hairline p-4">
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
        </div>
      </section>

      {/* §2B: two separate blocks, deliberately */}
      <section className="space-y-4">
        <h2 className="micro-label">Duplicates — merged into this CNMC</h2>
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
        <h2 className="micro-label">Equivalents — separate CNMC, interchangeable</h2>
        {detail.equivalents.length === 0 ? (
          <p className="text-sm text-muted">No interchangeable item has been identified.</p>
        ) : (
          <ul className="space-y-3">
            {detail.equivalents.map((entry) => (
              <li
                key={entry.counterpart.item_id}
                className="flex flex-wrap items-start gap-4 border border-hairline p-4"
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
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
