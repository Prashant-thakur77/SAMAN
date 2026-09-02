import type { ReactNode } from 'react'

/**
 * Every page needs an empty state: one-line explanation + primary action
 * (spec §5). Hairline box, no illustration, no colour.
 */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-start gap-3 card border border-hairline bg-surface px-6 py-10">
      <h2 className="text-base font-medium text-ink">{title}</h2>
      <p className="max-w-prose text-sm text-muted">{description}</p>
      {action && <div className="pt-1">{action}</div>}
    </div>
  )
}
