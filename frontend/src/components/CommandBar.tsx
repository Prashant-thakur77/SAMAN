import { useNavigate } from 'react-router-dom'

import { DegradedChip } from './DegradedChip'
import { IconSearch } from './Icons'
import { ThemeToggle } from './ThemeToggle'

/**
 * Top command bar (spec §1.3): global search input that opens the ⌘K palette,
 * degraded-mode status chip (§8A), theme toggle, user chip.
 *
 * The user chip is a placeholder until auth lands in M2 — it shows no invented
 * identity, per the "never fake data" guardrail (§10).
 */
export function CommandBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const navigate = useNavigate()
  const isMac =
    typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')

  return (
    <header className="sticky top-0 z-30 flex h-commandbar shrink-0 items-center gap-4 border-b border-hairline bg-bg px-4">
      {/* Opens the palette rather than being a second, divergent search box. */}
      <button
        type="button"
        onClick={onOpenPalette}
        className="flex h-8 max-w-md flex-1 items-center gap-2 border border-hairline px-3 text-left text-sm text-muted hover:text-ink"
      >
        <IconSearch className="h-4 w-4 shrink-0" />
        <span className="truncate">Search SAMAN</span>
        <kbd className="ml-auto shrink-0 border border-hairline px-1.5 py-0.5 font-mono text-[10px] text-muted">
          {isMac ? '⌘K' : 'Ctrl K'}
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-3">
        <DegradedChip />
        <ThemeToggle />
        <button
          type="button"
          onClick={() => navigate('/login')}
          className="h-8 border border-hairline px-3 text-xs text-muted hover:text-ink"
        >
          Sign in
        </button>
      </div>
    </header>
  )
}
