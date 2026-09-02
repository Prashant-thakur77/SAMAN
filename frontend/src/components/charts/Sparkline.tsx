import { useMemo } from 'react'

import { formatRupees } from './CountUp'

export type SparkPoint = { po_date: string; unit_price: number }

/**
 * Price history as one line (spec §6.4).
 *
 * Hand-drawn SVG rather than Recharts: it is forty lines, it carries no
 * library into the item page's bundle, and the monochrome hairline treatment
 * of §1.1 is easier to hold exactly here than to talk a charting library into.
 *
 * The y-axis is deliberately *not* zero-based. A material's price moving from
 * ₹20,838 to ₹22,934 is a 10% move that a zero-based axis would render as a
 * flat line — the shape a buyer needs to see is the variation, and the axis
 * labels state the range so the exaggeration cannot mislead.
 */
export function Sparkline({
  points,
  height = 56,
  width = 260,
}: {
  points: SparkPoint[]
  height?: number
  width?: number
}) {
  const model = useMemo(() => {
    const sorted = [...points]
      .filter((p) => Number.isFinite(p.unit_price))
      .sort((a, b) => a.po_date.localeCompare(b.po_date))
    if (sorted.length < 2) return null

    const prices = sorted.map((p) => p.unit_price)
    const low = Math.min(...prices)
    const high = Math.max(...prices)
    // A perfectly flat series would divide by zero; draw it down the middle.
    const span = high - low || 1
    const pad = 4
    const usable = height - pad * 2

    const coords = sorted.map((point, index) => ({
      ...point,
      x: (index / (sorted.length - 1)) * width,
      y: pad + usable - ((point.unit_price - low) / span) * usable,
    }))
    return { coords, low, high, last: coords[coords.length - 1] }
  }, [points, height, width])

  if (!model) return null

  const path = model.coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ')

  return (
    <figure className="space-y-1">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Price per base unit across ${model.coords.length} orders, ranging from ${formatRupees(model.low)} to ${formatRupees(model.high)}.`}
        className="overflow-visible"
      >
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
        {model.coords.map((c) => (
          <circle key={c.po_date + c.x} cx={c.x} cy={c.y} r="1.5" fill="currentColor" />
        ))}
        {/* The most recent order, marked — it is the one a buyer acts on. */}
        <circle
          cx={model.last.x}
          cy={model.last.y}
          r="3"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>
      <figcaption className="flex justify-between font-mono text-[11px] text-muted">
        <span>{formatRupees(model.low)}</span>
        <span>{formatRupees(model.high)}</span>
      </figcaption>
    </figure>
  )
}
