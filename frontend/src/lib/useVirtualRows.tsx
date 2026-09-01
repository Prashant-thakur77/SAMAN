import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type UIEvent,
} from 'react'

/**
 * Render only the rows a scroll position can actually see (spec §8A).
 *
 * A national migration plan is one row per catalogue row — 11,778 on the demo
 * profile, 150,000 on the benchmark one. Handing that many `<tr>` elements to
 * the browser costs seconds of layout, and the demo is over. This keeps the DOM
 * at roughly a screenful plus an overscan margin, with two spacer rows standing
 * in for the height above and below so the scrollbar still tells the truth.
 *
 * Deliberately not a dependency: uniform row heights are what makes this a
 * thirty-line problem, and every table here has them.
 */
export function useVirtualRows<T>({
  rows,
  rowHeight,
  render,
  columns,
  maxHeight = 640,
  overscan = 8,
}: {
  rows: T[]
  /** Must match the rendered row height, or the scrollbar lies. */
  rowHeight: number
  render: (row: T, index: number) => ReactNode
  /** Column count, so the spacer rows span the table correctly. */
  columns: number
  maxHeight?: number
  overscan?: number
}) {
  const container = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewport, setViewport] = useState(maxHeight)

  const measure = useCallback(() => {
    const node = container.current
    if (node) setViewport(node.clientHeight || maxHeight)
  }, [maxHeight])

  useEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  // A shorter list after a filter change can leave the container scrolled past
  // its own end, which would window an empty slice.
  useEffect(() => {
    if (container.current) container.current.scrollTop = 0
    setScrollTop(0)
  }, [rows])

  const windowed = rows.length * rowHeight > maxHeight
  const visible = Math.ceil(viewport / rowHeight) + overscan * 2
  const first = windowed ? Math.max(0, Math.floor(scrollTop / rowHeight) - overscan) : 0
  const last = windowed ? Math.min(rows.length, first + visible) : rows.length
  const above = first * rowHeight
  const below = Math.max(0, (rows.length - last) * rowHeight)

  const scrollProps = {
    ref: container,
    style: windowed ? { maxHeight } : undefined,
    className: windowed ? 'overflow-y-auto' : undefined,
    onScroll: (event: UIEvent<HTMLDivElement>) => setScrollTop(event.currentTarget.scrollTop),
  }

  const body = (
    <>
      {above > 0 && (
        <tr aria-hidden style={{ height: above }}>
          <td colSpan={columns} />
        </tr>
      )}
      {rows.slice(first, last).map((row, index) => render(row, first + index))}
      {below > 0 && (
        <tr aria-hidden style={{ height: below }}>
          <td colSpan={columns} />
        </tr>
      )}
    </>
  )

  return { scrollProps, body, windowed, rendered: last - first }
}
