import { useEffect, useState } from 'react'

import { getHealth, type Health } from './api'

/**
 * Reads GET /api/health once on mount. A failure is a normal state, not an
 * error boundary: the backend being down must degrade to a chip, never a blank
 * screen (spec §8A "failure banners", §10 "never crash").
 */
export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null)
  const [unreachable, setUnreachable] = useState(false)

  useEffect(() => {
    let alive = true
    getHealth()
      .then((h) => alive && setHealth(h))
      .catch(() => alive && setUnreachable(true))
    return () => {
      alive = false
    }
  }, [])

  return { health, unreachable }
}
