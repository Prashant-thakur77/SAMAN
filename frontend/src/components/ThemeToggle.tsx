import { useTheme } from '../lib/theme'
import { IconMoon, IconSun } from './Icons'

/** Command-bar theme switch (spec §1.4). The crossfade lives in ThemeProvider. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={toggle}
      title={`Switch to ${next} mode`}
      aria-label={`Switch to ${next} mode`}
      className="flex h-8 w-8 items-center justify-center border border-hairline text-muted hover:text-ink"
    >
      {theme === 'dark' ? <IconSun /> : <IconMoon />}
    </button>
  )
}
