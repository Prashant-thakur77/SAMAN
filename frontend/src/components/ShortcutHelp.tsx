import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

import { paletteVariants, scrimVariants } from '../lib/motion'

/**
 * `?` on any screen: the keyboard contract for where you are.
 *
 * The global keys are the same everywhere; the per-screen block lists what
 * that screen adds. Kept as data so the help cannot drift from the handlers
 * it describes without someone noticing the mismatch here.
 */
type Shortcut = { keys: string; does: string }

const GLOBAL: Shortcut[] = [
  { keys: 'Ctrl K', does: 'Command palette: jump to a screen or search the catalogue' },
  { keys: '?', does: 'This help' },
  { keys: 'Esc', does: 'Close a drawer, dialog or the navigation' },
  { keys: 'Tab', does: 'Move between controls; the first Tab offers "Skip to content"' },
]

const BY_SCREEN: { prefix: string; title: string; keys: Shortcut[] }[] = [
  {
    prefix: '/workbench',
    title: 'Workbench',
    keys: [
      { keys: 'A', does: 'Approve the card' },
      { keys: 'R', does: 'Reject the card' },
      { keys: 'J / K', does: 'Next / previous card' },
      { keys: 'M', does: 'Open the cluster behind the card' },
      { keys: 'U', does: 'Undo the last decision while the window is open' },
    ],
  },
  {
    prefix: '/search',
    title: 'Search',
    keys: [
      { keys: 'Enter', does: 'Search' },
      { keys: '↑ / ↓', does: 'Move along the results (in the palette)' },
    ],
  },
  {
    prefix: '/scan',
    title: 'Scan',
    keys: [
      { keys: 'Enter', does: 'Look the typed code up' },
      { keys: 'Esc', does: 'Stop the camera' },
    ],
  },
  {
    prefix: '/copilot',
    title: 'Copilot',
    keys: [{ keys: 'Enter', does: 'Ask; Shift Enter for a new line' }],
  },
]

export function shortcutsFor(pathname: string) {
  return BY_SCREEN.find((s) => pathname.startsWith(s.prefix)) ?? null
}

export function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { pathname } = useLocation()
  const reduce = useReducedMotion() ?? false
  const screen = shortcutsFor(pathname)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh]">
          <motion.div
            variants={scrimVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            onClick={onClose}
            className="absolute inset-0 bg-ink/20"
          />
          <motion.div
            variants={paletteVariants(reduce)}
            initial="initial"
            animate="animate"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-labelledby="shortcut-help-title"
            className="relative w-full max-w-lg space-y-5 border border-hairline bg-bg p-6 shadow-sm"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="shortcut-help-title" className="text-lg font-medium">
                  Keyboard shortcuts
                </h2>
                <p className="text-xs text-muted">
                  Keys are ignored while you are typing in a field.
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="font-mono text-xs text-muted hover:text-ink"
                aria-label="Close"
              >
                Esc
              </button>
            </div>
            {screen && <ShortcutList title={screen.title} keys={screen.keys} />}
            <ShortcutList title="Everywhere" keys={GLOBAL} />
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}

function ShortcutList({ title, keys }: { title: string; keys: Shortcut[] }) {
  return (
    <section className="space-y-2">
      <h3 className="micro-label">{title}</h3>
      <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5">
        {keys.map((k) => (
          <div key={k.keys} className="contents">
            <dt>
              <kbd className="card px-2 py-0.5 font-mono text-[11px] text-muted">{k.keys}</kbd>
            </dt>
            <dd className="text-sm">{k.does}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
