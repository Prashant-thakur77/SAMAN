import type { TierScores } from '../../lib/api'
import { cn } from '../../lib/cn'

/**
 * Per-tier contribution as horizontal mono bars (spec §6.4, §6.5).
 *
 * Modelled on splink's match-weight waterfall (§9): show what each comparison
 * contributed, not a single opaque number.
 */
const TIERS: { key: keyof TierScores; label: string; hint: string }[] = [
  { key: 'tier0_anchor', label: 'Tier 0 · anchor', hint: 'exact MPN, GTIN or text key' },
  { key: 'tier1_fuzzy', label: 'Tier 1 · linkage', hint: 'probabilistic / fuzzy similarity' },
  { key: 'tier2_semantic', label: 'Tier 2 · semantic', hint: 'embedding cosine' },
  { key: 'attribute_agreement', label: 'Attributes', hint: 'share of comparable attributes agreeing' },
]

export function TierStrip({ scores }: { scores: TierScores }) {
  return (
    <div className="space-y-2">
      {TIERS.map(({ key, label, hint }) => {
        const raw = scores[key]
        const value = typeof raw === 'number' ? raw : null
        return (
          <div key={key} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3" title={hint}>
            <span className="micro-label truncate">{label}</span>
            <div className="h-1.5 w-full bg-hairline" aria-hidden>
              <div
                className="h-full bg-ink"
                style={{ width: `${Math.round((value ?? 0) * 100)}%` }}
              />
            </div>
            <span className={cn('text-right font-mono text-xs', value === null && 'text-muted')}>
              {value === null ? '—' : value.toFixed(2)}
            </span>
          </div>
        )
      })}
      {scores.tier0_key && (
        <p className="micro-label pt-1">matched on {scores.tier0_key}</p>
      )}
      {scores.tier1_engine && (
        <p className="micro-label">tier 1 engine · {scores.tier1_engine}</p>
      )}
    </div>
  )
}
