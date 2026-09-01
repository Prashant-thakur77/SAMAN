import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'

import { DUR } from '../../lib/motion'

/** KPI count-up on mount (spec §1.5), skipped under prefers-reduced-motion. */
export function CountUp({
  value,
  format,
}: {
  value: number
  format?: 'percent' | 'currency'
}) {
  const reduce = useReducedMotion() ?? false
  const [shown, setShown] = useState(reduce ? value : 0)
  const frame = useRef<number>(0)

  useEffect(() => {
    if (reduce) {
      setShown(value)
      return
    }
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min((now - start) / DUR.kpiCountUp, 1)
      // Ease-out so the number settles rather than stopping dead.
      setShown(value * (1 - (1 - progress) ** 3))
      if (progress < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  }, [value, reduce])

  return <span className="tabular-nums">{formatValue(shown, format)}</span>
}

export function formatValue(value: number, format?: 'percent' | 'currency'): string {
  if (format === 'percent') return `${(value * 100).toFixed(1)}%`
  if (format === 'currency') return formatRupees(value)
  return Math.round(value).toLocaleString('en-IN')
}

/** Indian numbering, abbreviated — ₹7.2 Cr reads better than ₹71,80,92,548. */
export function formatRupees(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e7) return `₹${(value / 1e7).toFixed(2)} Cr`
  if (abs >= 1e5) return `₹${(value / 1e5).toFixed(2)} L`
  return `₹${Math.round(value).toLocaleString('en-IN')}`
}
