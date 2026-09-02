import { Link } from 'react-router-dom'

import { useHealth } from '../lib/useHealth'
import { StatusChip } from './primitives/Chip'

/**
 * Spec §8A: one unobtrusive chip in the top bar when a subsystem is degraded
 * (no Ollama, TF-IDF fallback, splink missing), mirroring /api/health and the
 * admin health panel. Silent when everything is at full capability.
 */
export function DegradedChip() {
  const { health, unreachable } = useHealth()

  if (unreachable) {
    return (
      <StatusChip tone="danger" className="hidden sm:inline-flex">
        Backend unreachable
      </StatusChip>
    )
  }

  if (!health) return null

  // Defensive because this chip lives in the always-rendered command bar,
  // outside any route error boundary: a health payload missing a tier would
  // otherwise throw and take the whole shell — sidebar, nav, everything — with
  // it. A missing tier reads as "not degraded" rather than as a blank app.
  const capabilities = health.capabilities ?? {}
  const degradedTiers = (['linkage', 'embedding', 'llm'] as const).filter(
    (t) => capabilities[t]?.degraded,
  )

  if (degradedTiers.length === 0) {
    return (
      <StatusChip tone="ok" className="hidden sm:inline-flex">
        All engines active
      </StatusChip>
    )
  }

  return (
    <Link
      to="/admin"
      title={capabilities.degraded.join('\n')}
      className="hidden sm:inline-flex"
    >
      <StatusChip tone="neutral">
        Degraded mode · {degradedTiers.length} of 3
      </StatusChip>
    </Link>
  )
}
