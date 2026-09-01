/**
 * Theme controller — spec §1.4.
 *
 * Class strategy (`<html class="dark">`), persisted to localStorage, defaulting
 * to `prefers-color-scheme`. The swap is animated by a single full-screen
 * overlay that fades 1 -> 0 over 150ms while painted in the *outgoing*
 * background, so the new theme is revealed underneath. No per-element
 * transitions (they produce the smeared, staggered repaint the spec forbids).
 */

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'saman.theme'

function readStoredTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'dark' || v === 'light' ? v : null
  } catch {
    return null // private mode / storage blocked
  }
}

function systemTheme(): Theme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

/** Current computed --bg as a paintable colour, for the crossfade overlay. */
function currentBackground(): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
  return raw ? `rgb(${raw})` : 'transparent'
}

type ThemeContextValue = {
  theme: Theme
  toggle: () => void
  setTheme: (t: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  // The inline script in index.html already applied the class before paint;
  // read back from the DOM so we never disagree with it.
  const [theme, setThemeState] = useState<Theme>(() =>
    typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
      ? 'dark'
      : 'light',
  )
  const [fadeFrom, setFadeFrom] = useState<string | null>(null)
  const reduceMotion = useReducedMotion()

  const setTheme = useCallback(
    (next: Theme) => {
      setThemeState((prev) => {
        if (prev === next) return prev
        if (!reduceMotion) setFadeFrom(currentBackground())
        applyTheme(next)
        try {
          localStorage.setItem(STORAGE_KEY, next)
        } catch {
          /* not persisting is survivable */
        }
        return next
      })
    },
    [reduceMotion],
  )

  const toggle = useCallback(
    () => setTheme(document.documentElement.classList.contains('dark') ? 'light' : 'dark'),
    [setTheme],
  )

  // Follow the OS only while the user has expressed no explicit preference.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      if (!readStoredTheme()) {
        applyTheme(systemTheme())
        setThemeState(systemTheme())
      }
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const value = useMemo(() => ({ theme, toggle, setTheme }), [theme, toggle, setTheme])

  return (
    <ThemeContext.Provider value={value}>
      {children}
      <AnimatePresence>
        {fadeFrom && (
          <motion.div
            key="theme-crossfade"
            aria-hidden
            className="pointer-events-none fixed inset-0 z-[100]"
            style={{ background: fadeFrom }}
            initial={{ opacity: 1 }}
            animate={{ opacity: 0 }}
            transition={{ duration: 0.15, ease: 'linear' }}
            onAnimationComplete={() => setFadeFrom(null)}
          />
        )}
      </AnimatePresence>
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
