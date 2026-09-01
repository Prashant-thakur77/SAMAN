import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { cn } from '../lib/cn'
import { paletteVariants, scrimVariants } from '../lib/motion'
import { NAV } from '../lib/nav'

/**
 * ⌘K palette (spec §1.3, §1.5). In M1 it navigates; from M3 the same input also
 * runs the global item search, so /search and the palette share one entry point.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const reduce = useReducedMotion() ?? false

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return NAV
    return NAV.filter(
      (i) => i.label.toLowerCase().includes(q) || i.path.toLowerCase().includes(q),
    )
  }, [query])

  // Reset and focus each time the palette opens.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setCursor(0)
    const id = requestAnimationFrame(() => inputRef.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [open])

  useEffect(() => {
    setCursor(0)
  }, [query])

  const go = (path: string) => {
    onClose()
    navigate(path)
  }

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
            aria-hidden
          />
          <motion.div
            variants={paletteVariants(reduce)}
            initial="initial"
            animate="animate"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            className="relative w-full max-w-xl border border-hairline bg-bg shadow-sm"
          >
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') onClose()
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setCursor((c) => Math.min(c + 1, results.length - 1))
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setCursor((c) => Math.max(c - 1, 0))
                }
                if (e.key === 'Enter' && results[cursor]) go(results[cursor].path)
              }}
              placeholder="Search SAMAN — pages, items, CNMC codes"
              aria-label="Search SAMAN"
              className="h-12 w-full border-b border-hairline bg-transparent px-4 font-mono text-sm text-ink placeholder:text-muted focus-visible:ring-0"
            />
            <ul className="max-h-80 overflow-y-auto py-1" role="listbox">
              {results.map((item, i) => (
                <li key={item.path}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === cursor}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => go(item.path)}
                    className={cn(
                      'flex h-10 w-full items-center gap-3 px-4 text-left text-sm',
                      i === cursor ? 'bg-surface text-ink' : 'text-muted',
                    )}
                  >
                    <item.icon className="shrink-0" />
                    <span>{item.label}</span>
                    <span className="ml-auto font-mono text-xs text-muted">{item.path}</span>
                  </button>
                </li>
              ))}
              {results.length === 0 && (
                <li className="px-4 py-6 text-sm text-muted">
                  No page matches “{query}”. Item search arrives with the matching engine (M3).
                </li>
              )}
            </ul>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
