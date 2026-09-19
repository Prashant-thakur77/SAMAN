import { DegradedChip } from './DegradedChip'
import { IconMenu, IconSearch } from './Icons'
import { useT } from '../lib/i18n'
import { LangToggle } from './LangToggle'
import { ThemeToggle } from './ThemeToggle'
import { UserChip } from './UserChip'

/**
 * Top command bar (spec §1.3): global search input that opens the ⌘K palette,
 * degraded-mode status chip (§8A), theme toggle, user chip.
 */
export function CommandBar({
  onOpenPalette,
  onOpenNav,
  onOpenHelp,
}: {
  onOpenPalette: () => void
  onOpenNav: () => void
  onOpenHelp?: () => void
}) {
  const t = useT()
  const isMac =
    typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')

  return (
    <header className="no-print sticky top-0 z-20 flex h-commandbar shrink-0 items-center gap-2 border-b border-hairline bg-surface px-3 sm:gap-4 sm:px-4">
      {/* Below lg the sidebar is a drawer, and this is the handle for it. */}
      <button
        type="button"
        onClick={onOpenNav}
        aria-label="Open navigation"
        className="-ml-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted hover:text-ink lg:hidden"
      >
        <IconMenu />
      </button>

      {/* Opens the palette rather than being a second, divergent search box. */}
      <button
        type="button"
        onClick={onOpenPalette}
        className="flex h-9 max-w-md flex-1 items-center gap-2 rounded-full border border-hairline bg-surface px-3.5 text-left text-sm text-muted hover:text-ink"
      >
        <IconSearch className="h-4 w-4 shrink-0" />
        <span className="truncate">{t('Search SAMAN')}</span>
        <kbd className="ml-auto hidden shrink-0 rounded border border-hairline px-1.5 py-0.5 font-mono text-[10px] text-muted sm:block">
          {isMac ? '⌘K' : 'Ctrl K'}
        </kbd>
      </button>

      <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-3">
        <DegradedChip />
        {onOpenHelp && (
          <button
            type="button"
            onClick={onOpenHelp}
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
            className="hidden h-9 w-9 items-center justify-center rounded-full border border-hairline font-mono text-xs text-muted hover:text-ink sm:flex"
          >
            ?
          </button>
        )}
        <LangToggle />
        <ThemeToggle />
        <UserChip />
      </div>
    </header>
  )
}
