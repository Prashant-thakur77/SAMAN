import type { ReactNode } from 'react'

import { cn } from '../../lib/cn'

/** A CNMC or legacy code. Always Plex Mono in a 1px-border chip (spec §1.3). */
export function CodeChip({ code, className }: { code: string; className?: string }) {
  return <span className={cn('code-chip', className)}>{code}</span>
}

export type StatusTone = 'ok' | 'danger' | 'neutral'

const DOT: Record<StatusTone, string> = {
  ok: 'bg-ok',
  danger: 'bg-danger',
  neutral: 'bg-muted',
}

const TEXT: Record<StatusTone, string> = {
  ok: 'text-ok',
  danger: 'text-danger',
  neutral: 'text-muted',
}

/** Status = a dot + text. Colour never becomes a fill (spec §1.1). */
export function StatusChip({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: StatusTone
  children: ReactNode
  className?: string
}) {
  return (
    <span className={cn('inline-flex items-center gap-2 text-xs', TEXT[tone], className)}>
      <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', DOT[tone])} />
      {children}
    </span>
  )
}
