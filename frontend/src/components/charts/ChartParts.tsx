import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'

import { RAMP, type Shade } from './ramp'

/**
 * The pieces every chart section on the executive page is built from: the
 * donut's `<dl>` legend, the "show as a table" twin that keeps every value
 * reachable without a pointer, a width hook so a hand-drawn SVG can lay itself
 * out in real pixels, and the number formats the captions share.
 */

/** Legend in the donut's idiom: a ramp swatch, the label, an optional figure. */
export function Legend({
  items,
  className,
}: {
  items: { key: string; label: string; shade: Shade; value?: string }[]
  className?: string
}) {
  return (
    <dl className={['flex flex-wrap gap-x-5 gap-y-1.5', className].filter(Boolean).join(' ')}>
      {items.map((item) => (
        <div key={item.key} className="flex items-baseline gap-2">
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 translate-y-px rounded-[3px]"
            style={{ background: RAMP[item.shade] }}
          />
          <dt className="text-xs text-ink">{item.label}</dt>
          {item.value !== undefined && (
            <dd className="font-mono text-xs tabular-nums text-muted">{item.value}</dd>
          )}
        </div>
      ))}
    </dl>
  )
}

/**
 * Every chart's table twin (the WCAG-clean equivalent): collapsed by default,
 * the rows always in the DOM so nothing is reachable only by hover.
 */
export function TableTwin({
  children,
  label = 'Show as a table',
  minWidth = 'min-w-[36rem]',
}: {
  children: ReactNode
  label?: string
  /** A floor on the table's width, so at phone width it scrolls sideways
   *  inside its own box rather than wrapping every cell into a tall column. */
  minWidth?: string
}) {
  return (
    <details className="group text-xs">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="inline-block transition-transform group-open:rotate-90">
          ›
        </span>
        {label}
      </summary>
      <div className="mt-3 overflow-x-auto">
        <div className={minWidth}>{children}</div>
      </div>
    </details>
  )
}

/**
 * The rendered width of an element, kept current by a ResizeObserver so a
 * chart re-lays itself out at phone width. Without an observer (jsdom) it
 * reports the fallback, which is what the tests lay out against.
 */
export function useElementWidth<T extends HTMLElement>(
  ref: RefObject<T>,
  fallback = 640,
): number {
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const node = ref.current
    if (!node || typeof ResizeObserver === 'undefined') return
    const measure = () => {
      const w = node.getBoundingClientRect().width
      if (w > 0) setWidth(w)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [ref])
  return width
}

/** Reuse the width hook without threading a ref through the caller. */
export function useMeasured<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null)
  const width = useElementWidth(ref, fallback)
  return { ref, width }
}

/**
 * Clean axis ticks from zero — 0 / 1,000 / 2,000, never 0 / 1,153 / 2,306 —
 * ending on the first clean step at or above the maximum, so the axis closes
 * on a round number.
 */
export function niceTicks(max: number, target = 5): number[] {
  if (!(max > 0)) return [0]
  const rough = max / target
  const power = 10 ** Math.floor(Math.log10(rough))
  const candidates = [1, 2, 2.5, 5, 10].map((m) => m * power)
  const step = candidates.find((c) => c >= rough) ?? candidates[candidates.length - 1]
  const last = Math.ceil(max / step - 1e-9) * step
  const ticks: number[] = []
  for (let v = 0; v <= last + 1e-9; v += step) ticks.push(Math.round(v * 1e6) / 1e6)
  return ticks
}

export const formatCount = (n: number) => Math.round(n).toLocaleString('en-IN')

/** A value in rupees as whole crore for an axis: 1,635 — the unit sits on the axis. */
export const toCrore = (inr: number) => inr / 1e7

export const formatPercent = (share: number, digits = 0) =>
  `${(share * 100).toFixed(digits)}%`

/** "2 Sep 2026" from an ISO timestamp; null-safe because a run may carry none. */
export function formatDay(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}
