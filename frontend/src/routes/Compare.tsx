import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { AttributeDiff } from '../components/workbench/AttributeDiff'
import { ItemPanel } from '../components/workbench/ItemPanel'
import { TierStrip } from '../components/workbench/TierStrip'
import { ApiError, compareItems, type Comparison } from '../lib/api'

const VERDICT_TONE: Record<string, 'ok' | 'neutral' | 'danger'> = {
  duplicate: 'ok',
  review: 'neutral',
  conflict: 'danger',
  distinct: 'danger',
}

const VERDICT_WORDS: Record<string, string> = {
  duplicate: 'The same material',
  review: 'Too close to call automatically',
  conflict: 'One part number, two specifications',
  distinct: 'Two different materials',
}

/**
 * /compare?a=&b= — any two rows side by side (spec §6.5).
 *
 * The Workbench shows the pairs the pipeline chose to ask about. Approvers
 * ask about others: two rows in one cluster that look wrong together, two
 * rows in different clusters that look the same. This scores them now, with
 * the same matcher, and shows the same evidence. It decides nothing; the
 * cluster page is where a merge or split happens.
 */
export default function Compare() {
  const [params] = useSearchParams()
  const a = Number(params.get('a'))
  const b = Number(params.get('b'))
  const [data, setData] = useState<Comparison | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!a || !b) return
    setData(null)
    setError(null)
    compareItems(a, b)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not compare.'))
  }, [a, b])

  if (!a || !b) {
    return (
      <div className="space-y-8">
        <PageHeader section="Review" title="Compare" description="Two rows, side by side." />
        <EmptyState
          title="Pick two rows"
          description="Open a cluster and choose two members, or open an item and pick a sibling."
        />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Review"
        title="Compare"
        description="Any two rows, scored now by the same matcher the pipeline uses. Nothing is stored or decided here."
        actions={
          data && (
            <StatusChip tone={VERDICT_TONE[data.verdict] ?? 'neutral'}>
              {VERDICT_WORDS[data.verdict] ?? data.verdict}
            </StatusChip>
          )
        }
      />

      {error && (
        <p role="alert" className="card px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}
      {!data && !error && <p className="text-sm text-muted">Scoring…</p>}

      {data && (
        <article className="space-y-6 card p-6">
          <header className="flex flex-wrap items-start justify-between gap-4 border-b border-hairline pb-4">
            <div className="space-y-1">
              <p className="max-w-prose text-sm">
                <span className="micro-label mr-2">why</span>
                {data.why}
              </p>
              <p className="text-xs text-muted">
                {data.pipeline.paired
                  ? `The pipeline scored this pair too and called it ${data.pipeline.verdict}. `
                  : 'The pipeline never paired these two rows: blocking did not put them in one bucket. '}
                {data.pipeline.same_cluster
                  ? 'They sit in the same cluster today.'
                  : 'They sit in different clusters today.'}
              </p>
            </div>
            <div className="text-right">
              <p className="micro-label">confidence · {data.band} band</p>
              <p className="font-mono text-lg">{Math.round(data.confidence * 100)}%</p>
            </div>
          </header>

          {data.refused_because.length > 0 && (
            <div className="card px-4 py-3">
              <p className="micro-label mb-2 text-danger">Not a duplicate</p>
              <ul className="space-y-1">
                {data.refused_because.map((reason) => (
                  <li key={reason} className="font-mono text-xs text-danger">
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.equivalence && (
            <p className="border border-hairline bg-surface px-4 py-3 text-sm">
              Flagged as an equivalence candidate ({data.equivalence.basis}
              {data.equivalence.direction ? `, ${data.equivalence.direction}` : ''}): interchangeable,
              perhaps, but not the same record.
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <ItemPanel item={data.items[0]} side="A" />
            <ItemPanel item={data.items[1]} side="B" />
          </div>

          <div className="grid gap-8 lg:grid-cols-[minmax(0,20rem)_1fr]">
            <section className="space-y-3">
              <h2 className="micro-label">Tier scores</h2>
              <TierStrip scores={data.tier_scores} />
            </section>
            <section className="min-w-0 space-y-3">
              <h2 className="micro-label">Attribute comparison</h2>
              <AttributeDiff diff={data.attribute_diff} />
            </section>
          </div>

          <footer className="flex flex-wrap items-center gap-4 border-t border-hairline pt-4 text-sm">
            {data.items.map((item) =>
              item.cluster_id ? (
                <Link
                  key={item.item_id}
                  to={`/clusters/${item.cluster_id}`}
                  className="underline underline-offset-4 hover:text-ink"
                >
                  Open {item.legacy_code}'s cluster →
                </Link>
              ) : null,
            )}
            <span className="ml-auto text-xs text-muted">{data.note}</span>
          </footer>
        </article>
      )}
    </div>
  )
}
