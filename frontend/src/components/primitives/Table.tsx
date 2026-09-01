import { motion, useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'

import { cn } from '../../lib/cn'
import { listItemVariants, listVariants } from '../../lib/motion'

/**
 * Dense data table — 40px rows, hairline dividers only (spec §1.3), rows
 * staggered in at 20ms (spec §1.5).
 */

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('w-full overflow-x-auto', className)}>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  )
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b border-hairline">
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
