import { motion, useReducedMotion } from 'framer-motion'
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'

import { cn } from '../../lib/cn'
import { downloadCsv, tableToCsv } from '../../lib/csv'
import { listItemVariants, listVariants } from '../../lib/motion'

/**
 * Dense data table — 40px rows, hairline dividers only (spec §1.3), rows
 * staggered in at 20ms (spec §1.5).
 *
 * `exportAs` names a CSV file and adds a small download control above the
 * table: the rows as rendered, nothing more, so a steward can take what the
 * screen showed into a spreadsheet without asking anyone.
 */

export function Table({
  children,
  className,
  exportAs,
}: {
  children: ReactNode
  className?: string
  exportAs?: string
}) {
  const ref = useRef<HTMLTableElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const scrolls = useScrollsSideways(scroller)
  return (
    <div className={cn('relative', (exportAs || scrolls) && 'pt-6')}>
      {scrolls && (
        <span
          className="no-print absolute left-0 top-0 font-mono text-[11px] text-muted"
          aria-hidden
        >
          scrolls sideways →
        </span>
      )}
      {exportAs && (
        <button
          type="button"
          className="no-print absolute right-0 top-0 font-mono text-[11px] text-muted underline-offset-2 hover:text-ink hover:underline"
          title="Download these rows, as shown, as a CSV file"
          onClick={() => ref.current && downloadCsv(exportAs, tableToCsv(ref.current))}
        >
          CSV ↓
        </button>
      )}
      <div ref={scroller} className={cn('card w-full overflow-x-auto', className)}>
        <table ref={ref} className="data-table w-full border-collapse text-sm">
          {children}
        </table>
      </div>
    </div>
  )
}

/** True while the table is wider than its card, so a phone is told the
 *  table scrolls rather than left to discover it. */
function useScrollsSideways(ref: RefObject<HTMLDivElement>): boolean {
  const [scrolls, setScrolls] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const check = () => setScrolls(el.scrollWidth > el.clientWidth + 1)
    check()
    const observer = new ResizeObserver(check)
    observer.observe(el)
    const table = el.firstElementChild
    if (table) observer.observe(table)
    return () => observer.disconnect()
  }, [ref])
  return scrolls
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b border-hairline bg-bg/60">
      <tr>{children}</tr>
    </thead>
  )
}

export function TH({
  children,
  align = 'left',
  className,
}: {
  children: ReactNode
  align?: 'left' | 'right'
  className?: string
}) {
  return (
    <th
      scope="col"
      className={cn(
        'micro-label h-row px-3 font-medium',
        align === 'right' ? 'text-right' : 'text-left',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function TBody({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.tbody variants={listVariants(reduce)} initial="initial" animate="animate">
      {children}
    </motion.tbody>
  )
}

export function TR({
  children,
  onClick,
  className,
}: {
  children: ReactNode
  onClick?: () => void
  className?: string
}) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.tr
      variants={listItemVariants(reduce)}
      onClick={onClick}
      // Deliberately no `role="button"`: that would take the element out of the
      // table's row structure and leave a screen reader unable to navigate the
      // grid at all. A clickable row is a mouse convenience; every one of them
      // also carries a real link in its first cell, which is what the keyboard
      // and the reader use.
      className={cn(
        'border-b border-hairline',
        onClick && 'cursor-pointer hover:bg-surface',
        className,
      )}
    >
      {children}
    </motion.tr>
  )
}

export function TD({
  children,
  align = 'left',
  mono,
  className,
  title,
}: {
  children: ReactNode
  align?: 'left' | 'right'
  mono?: boolean
  className?: string
  /** Native tooltip — used to explain a withheld or truncated value. */
  title?: string
}) {
  return (
    <td
      title={title}
      className={cn(
        'h-row px-3',
        align === 'right' ? 'text-right' : 'text-left',
        mono && 'font-mono text-xs',
        className,
      )}
    >
      {children}
    </td>
  )
}
