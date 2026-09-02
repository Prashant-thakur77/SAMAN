import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { searchItems, type SearchHit } from '../lib/api'
import { cn } from '../lib/cn'
import { paletteVariants, scrimVariants } from '../lib/motion'
import { NAV } from '../lib/nav'

/**
 * ⌘K palette (spec §1.3, §1.5, §6.3).
 *
 * One input for both jumping between screens and searching the catalogue, so
 * /search and the palette are the same entry point rather than two behaviours
 * that can drift apart.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [hits, setHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const reduce = useReducedMotion() ?? false

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return NAV
    return NAV.filter(
      (i) => i.label.toLowerCase().includes(q) || i.path.toLowerCase().includes(q),
    )
  }, [query])

  // Reset and focus each time the palette opens, and give focus back to
  // whatever opened it on close. Without the second half, dismissing the
  // palette drops a keyboard user at the top of the document.
  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    setQuery('')
    setCursor(0)
    const id = requestAnimationFrame(() => inputRef.current?.focus())
    return () => {
      cancelAnimationFrame(id)
      opener?.focus?.()
    }
  }, [open])

  // Keep Tab inside the dialog. A modal the keyboard can walk out of is not
  // modal — the reader ends up narrating the page behind it.
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const dialog = dialogRef.current
      if (!dialog) return
      const focusable = dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [open])

  useEffect(() => {
    setCursor(0)
  }, [query])

  // Search the catalogue alongside the page list. Debounced, and stale
  // responses are discarded so a slow reply cannot overwrite a newer one.
  useEffect(() => {
    const term = query.trim()
    if (term.length < 2) {
      setHits([])
      return
    }
    let alive = true
    setSearching(true)
    const timer = window.setTimeout(() => {
      searchItems({ search: term, limit: 6 })
        .then((response) => alive && setHits(response.items))
        .catch(() => alive && setHits([]))
        .finally(() => alive && setSearching(false))
    }, 180)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [query])

  const go = (path: string) => {
    onClose()
    navigate(path)
  }

  // One flat list so the arrow keys move through pages and results alike.
  const options: { key: string; path: string; label: string; hint: string; kind: string }[] = [
    ...results.map((item) => ({
      key: `nav-${item.path}`,
      path: item.path,
      label: item.label,
      hint: item.path,
      kind: 'page',
    })),
    ...hits.map((hit) => ({
      key: `item-${hit.item_id}`,
      path: `/items/${hit.item_id}`,
      label: hit.description,
      hint: `${hit.cpse} · ${hit.legacy_code}`,
      kind: 'item',
    })),
  ]

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
            ref={dialogRef}
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
                  setCursor((c) => Math.min(c + 1, options.length - 1))
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setCursor((c) => Math.max(c - 1, 0))
                }
                if (e.key === 'Enter' && options[cursor]) go(options[cursor].path)
              }}
              placeholder="Search SAMAN: pages, items, CNMC codes"
              aria-label="Search SAMAN"
              role="combobox"
              aria-expanded
              aria-controls="palette-results"
              aria-activedescendant={options[cursor] ? `palette-option-${cursor}` : undefined}
              aria-autocomplete="list"
              className="h-12 w-full border-b border-hairline bg-transparent px-4 font-mono text-sm text-ink placeholder:text-muted focus-visible:ring-0"
            />
            <ul
              id="palette-results"
              className="max-h-80 overflow-y-auto py-1"
              role="listbox"
              aria-label="Results"
            >
              {options.map((option, i) => (
                <li key={option.key}>
                  <button
                    id={`palette-option-${i}`}
                    type="button"
                    role="option"
                    aria-selected={i === cursor}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => go(option.path)}
                    className={cn(
                      'flex h-10 w-full items-center gap-3 px-4 text-left text-sm',
                      i === cursor ? 'bg-surface text-ink' : 'text-muted',
                    )}
                  >
                    <span className="micro-label w-10 shrink-0">{option.kind}</span>
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    <span className="ml-auto shrink-0 font-mono text-xs text-muted">
                      {option.hint}
                    </span>
                  </button>
                </li>
              ))}
              {options.length === 0 && (
                <li className="px-4 py-6 text-sm text-muted">
                  {searching ? 'Searching…' : `Nothing matches “${query}”.`}
                </li>
              )}
            </ul>
            <p aria-live="polite" className="sr-only">
              {searching
                ? 'Searching'
                : `${options.length} result${options.length === 1 ? '' : 's'}`}
            </p>
            {hits.length > 0 && (
              <button
                type="button"
                onClick={() => go(`/search?q=${encodeURIComponent(query.trim())}`)}
                className="w-full border-t border-hairline px-4 py-2 text-left text-xs text-muted hover:text-ink"
              >
                See all results for “{query.trim()}”
              </button>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
