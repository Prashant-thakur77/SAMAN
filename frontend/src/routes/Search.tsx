import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ItemDrawer } from '../components/ItemDrawer'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { CodeChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { Input } from '../components/primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import {
  ApiError,
  getFacets,
  searchItems,
  type Facets,
  type SearchResponse,
  type SearchSort,
} from '../lib/api'
import { cn } from '../lib/cn'

const PAGE = 25

/** The last few searches, kept in this browser only; a convenience, never state. */
const RECENT_KEY = 'saman.search.recent'
const RECENT_MAX = 8

function readRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    const list = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(list) ? list.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function remember(term: string): string[] {
  const next = [term, ...readRecent().filter((t) => t !== term)].slice(0, RECENT_MAX)
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    /* not persisting is survivable */
  }
  return next
}

/**
 * /search — spec §6.3.
 *
 * Paginated server-side: the estate is 12k rows on the demo profile and 150k on
 * the benchmark one, so filtering in the browser is not an option (§8A).
 */
export default function Search() {
  const [params, setParams] = useSearchParams()
  const [facets, setFacets] = useState<Facets | null>(null)
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [term, setTerm] = useState(params.get('q') ?? '')
  const [recent, setRecent] = useState<string[]>(() => readRecent())
  //  A row opens the item beside the results rather than navigating away (§6.3).
  const [drawerItem, setDrawerItem] = useState<number | null>(null)

  const cpse = params.get('cpse') ?? ''
  const klass = params.get('class') ?? ''
  const coded = params.get('cnmc') ?? ''
  const sort = (params.get('sort') as SearchSort | null) ?? 'relevance'
  const offset = Number(params.get('offset') ?? 0)
  const q = params.get('q') ?? ''

  // A search that was actually run is worth remembering; typing is not.
  useEffect(() => {
    if (q.trim()) setRecent(remember(q.trim()))
  }, [q])

  useEffect(() => {
    getFacets().then(setFacets).catch(() => setFacets(null))
  }, [])

  const load = useCallback(async () => {
    try {
      setResults(
        await searchItems({
          search: params.get('q') ?? undefined,
          cpse: cpse || undefined,
          class: klass || undefined,
          has_cnmc: coded === '' ? undefined : coded === 'yes',
          sort,
          limit: PAGE,
          offset,
        }),
      )
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Search failed.')
    }
  }, [params, cpse, klass, coded, sort, offset])

  useEffect(() => {
    void load()
  }, [load])

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params)
    for (const [key, value] of Object.entries(next)) {
      if (value) merged.set(key, value)
      else merged.delete(key)
    }
    if (!('offset' in next)) merged.delete('offset')
    setParams(merged)
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Overview"
        title="Search"
        description="Every CPSE catalogue, searched on the normalized text, so an abbreviated row is findable by its spelled-out form and the other way round."
      />

      <form
        onSubmit={(event) => {
          event.preventDefault()
          update({ q: term })
        }}
        className="flex gap-3"
      >
        <Input
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="6205, SS316 gasket, KTZ-GV50-300…"
          aria-label="Search the catalogue"
          className="font-mono text-base"
        />
        <Button type="submit" variant="primary">
          Search
        </Button>
      </form>

      {recent.length > 0 && !q && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Recent searches">
          <span className="micro-label">recent</span>
          {recent.map((entry) => (
            <button
              key={entry}
              type="button"
              onClick={() => {
                setTerm(entry)
                update({ q: entry })
              }}
              className="rounded-full border border-hairline px-3 py-1 font-mono text-xs text-muted hover:text-ink"
            >
              {entry}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              try {
                localStorage.removeItem(RECENT_KEY)
              } catch {
                /* nothing to clear */
              }
              setRecent([])
            }}
            className="text-xs text-muted underline-offset-2 hover:underline"
          >
            clear
          </button>
        </div>
      )}

      {results?.read_as && (
        <p className="text-sm text-muted" role="status">
          Read as <span className="font-mono text-ink">{results.read_as}</span>
          {results.rewritten && results.rewritten.length > 0 && (
            <>
              {' '}
              ({results.rewritten.map((r) => `${r.from} → ${r.to}`).join(', ')})
            </>
          )}
          .
        </p>
      )}

      <div className="flex flex-wrap items-end gap-4">
        <label className="space-y-2">
          <span className="micro-label block">CPSE</span>
          <select
            value={cpse}
            onChange={(e) => update({ cpse: e.target.value })}
            className="h-10 border border-hairline bg-bg px-3 text-sm"
          >
            <option value="">All</option>
            {(facets?.cpses ?? []).map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.code} ({entry.items.toLocaleString('en-IN')})
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-2">
          <span className="micro-label block">Class</span>
          <select
            value={klass}
            onChange={(e) => update({ class: e.target.value })}
            className="h-10 max-w-[16rem] border border-hairline bg-bg px-3 text-sm"
          >
            <option value="">All</option>
            {(facets?.classes ?? []).map((entry) => (
              <option key={entry.class_code} value={entry.class_code}>
                {entry.label} ({entry.items.toLocaleString('en-IN')})
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-2">
          <span className="micro-label block">CNMC</span>
          <select
            value={coded}
            onChange={(e) => update({ cnmc: e.target.value })}
            className="h-10 border border-hairline bg-bg px-3 text-sm"
          >
            <option value="">Any</option>
            <option value="yes">Coded</option>
            <option value="no">Not yet coded</option>
          </select>
        </label>
        <label className="space-y-2">
          <span className="micro-label block">Sort</span>
          <select
            value={sort}
            onChange={(e) => update({ sort: e.target.value === 'relevance' ? '' : e.target.value })}
            className="h-10 border border-hairline bg-bg px-3 text-sm"
            title="Relevance: the whole phrase first, then part-number hits, then the shortest text."
          >
            <option value="relevance">Relevance</option>
            <option value="shortest">Shortest first</option>
            <option value="newest">Newest first</option>
          </select>
        </label>
        {results && (
          <p className="pb-2.5 text-xs text-muted">
            {results.total.toLocaleString('en-IN')} match
            {results.total === 1 ? '' : 'es'}
          </p>
        )}
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {results && results.items.length === 0 ? (
        <EmptyState
          title="Nothing matched"
          description={
            results.did_you_mean
              ? 'Every word you type must appear in the row. The catalogue spells it differently.'
              : 'Every word you type must appear in the row. Try fewer words, or clear the filters.'
          }
          action={
            <div className="flex flex-wrap items-center justify-center gap-3">
              {results.did_you_mean && (
                <Button
                  variant="primary"
                  onClick={() => {
                    setTerm(results.did_you_mean!)
                    update({ q: results.did_you_mean! })
                  }}
                >
                  Did you mean <span className="font-mono">{results.did_you_mean}</span>?
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => {
                  setTerm('')
                  setParams(new URLSearchParams())
                }}
              >
                Clear search
              </Button>
            </div>
          }
        />
      ) : (
        <>
          <Table exportAs="search-results">
            <THead>
              <TH>Description</TH>
              <TH>CPSE</TH>
              <TH>Legacy code</TH>
              <TH>Class</TH>
              <TH>CNMC</TH>
            </THead>
            <TBody>
              {(results?.items ?? []).map((hit) => (
                <TR key={hit.item_id} onClick={() => setDrawerItem(hit.item_id)}>
                  <TD>
                    <Link
                      to={`/items/${hit.item_id}`}
                      className="block max-w-xl truncate hover:underline hover:underline-offset-4"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {hit.description}
                    </Link>
                    {hit.cluster_size > 1 && (
                      <span className="micro-label">
                        shared with {hit.cluster_size - 1} other row
                        {hit.cluster_size === 2 ? '' : 's'}
                      </span>
                    )}
                  </TD>
                  <TD mono>{hit.cpse}</TD>
                  <TD mono>{hit.legacy_code}</TD>
                  <TD mono className="text-muted">{hit.class_code}</TD>
                  <TD>{hit.cnmc ? <CodeChip code={hit.cnmc} /> : <span className="text-muted">—</span>}</TD>
                </TR>
              ))}
            </TBody>
          </Table>

          {results && results.total > PAGE && (
            <div className="flex items-center justify-between">
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => update({ offset: String(Math.max(offset - PAGE, 0)) })}
              >
                Previous
              </Button>
              <span className={cn('font-mono text-xs text-muted')}>
                {offset + 1}–{Math.min(offset + PAGE, results.total)} of{' '}
                {results.total.toLocaleString('en-IN')}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset + PAGE >= results.total}
                onClick={() => update({ offset: String(offset + PAGE) })}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}

      <ItemDrawer itemId={drawerItem} onClose={() => setDrawerItem(null)} />
    </div>
  )
}
