import type { AttrDiff } from '../../lib/api'
import { cn } from '../../lib/cn'

/**
 * Attribute-by-attribute comparison (spec §6.5): matching attributes plain,
 * conflicting attributes marked. An identity-critical mismatch is the reason a
 * pair was refused, so it is called out rather than left for the reader to spot.
 */
function render(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

export function AttributeDiff({ diff }: { diff: AttrDiff[] }) {
  const comparable = diff.filter((d) => d.result !== 'unknown')
  if (comparable.length === 0) {
    return (
      <p className="text-xs text-muted">
        No attribute could be compared on both sides; the decision rests on text
        similarity alone.
      </p>
    )
  }

  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-hairline">
          <th className="micro-label py-1 text-left font-medium">Attribute</th>
          <th className="micro-label py-1 text-left font-medium">Left</th>
          <th className="micro-label py-1 text-left font-medium">Right</th>
          <th className="micro-label py-1 text-left font-medium">Result</th>
        </tr>
      </thead>
      <tbody>
        {comparable.map((entry) => {
          const blocking = !entry.agrees && entry.role === 'identity_critical'
          return (
            <tr key={entry.attr} className="border-b border-hairline last:border-0">
              <td className="py-1.5 pr-3 align-top">
                <span className={cn('font-mono', blocking && 'text-danger')}>{entry.attr}</span>
                {entry.role === 'identity_critical' && (
                  <span className="micro-label ml-2">critical</span>
                )}
              </td>
              <td className="py-1.5 pr-3 align-top font-mono">{render(entry.a)}</td>
              <td className="py-1.5 pr-3 align-top font-mono">{render(entry.b)}</td>
              <td
                className={cn(
                  'py-1.5 align-top',
                  entry.agrees ? 'text-muted' : blocking ? 'text-danger' : 'text-ink',
                )}
              >
                {entry.agrees ? entry.detail || 'agrees' : entry.detail}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
