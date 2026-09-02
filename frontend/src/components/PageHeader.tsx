import type { ReactNode } from 'react'

/**
 * The page header pattern from spec §1.3, used on every route:
 *   uppercase micro-label (section) -> H1 -> one-line description -> actions right
 */
export function PageHeader({
  section,
  title,
  description,
  actions,
}: {
  section: string
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <header className="border-b border-hairline pb-6">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0 space-y-2">
          <p className="micro-label text-accent">{section}</p>
          <h1 className="text-xl font-medium tracking-tight text-ink">{title}</h1>
          <p className="max-w-prose text-sm text-muted">{description}</p>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2 pt-1">{actions}</div>}
      </div>
    </header>
  )
}
