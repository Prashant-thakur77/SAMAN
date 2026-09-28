/**
 * Load a dashboard, and keep loading it while the API says its figures are
 * stale.
 *
 * On a slow host the API answers at once with the previous figures, marked
 * `provenance.stale`, while it recomputes in the background (see
 * backend/app/cache.py). This asks again a few seconds later, and again,
 * until the fresh figures arrive, so nobody has to know to reload the page.
 */

import { useEffect, useState } from 'react'

import { ApiError, type DashboardProvenance } from './api'

const RETRY_MS = [3000, 5000, 8000, 13000, 21000]

export function useFreshData<T extends { provenance?: DashboardProvenance }>(
  load: () => Promise<T>,
  deps: unknown[],
): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    let timer: number | undefined
    const fetchOnce = (attempt: number) => {
      load()
        .then((d) => {
          if (!alive) return
          setData(d)
          setError(null)
          if (d.provenance?.stale && attempt < RETRY_MS.length) {
            timer = window.setTimeout(() => fetchOnce(attempt + 1), RETRY_MS[attempt])
          }
        })
        .catch((err) => alive && setError(err instanceof ApiError ? err.message : 'Unavailable.'))
    }
    fetchOnce(0)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
    // The caller names what the load depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error }
}
