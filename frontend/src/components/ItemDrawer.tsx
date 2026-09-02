import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, getItem, type ItemDetail } from '../lib/api'
import { drawerVariants, scrimVariants } from '../lib/motion'
import { Button } from './primitives/Button'
import { CodeChip } from './primitives/Chip'
import { ItemPanel } from './workbench/ItemPanel'

/**
 * The item drawer (spec §6.3, §6.4): a search result opens here rather than
 * navigating away, so a reviewer can check a row and keep their result list.
 *
 * Slides from the right in 280ms on the house easing (§1.5) — the variants
 * have existed in `motion.ts` since M1 and nothing used them, which was the
 * tell that this was missing. The full page at `/items/:id` stays: the drawer
 * is for a look, the page is for a link you can send someone.
 */
export function ItemDrawer({ itemId, onClose }: { itemId: number | null; onClose: () => void }) {
  const [detail, setDetail] = useState<ItemDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const panel = useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion() ?? false

  useEffect(() => {
    if (itemId === null) return
    let alive = true
    setDetail(null)
    setError(null)
    getItem(itemId)
      .then((d) => alive && setDetail(d))
      .catch(
        (err) =>
          alive && setError(err instanceof ApiError ? err.message : 'Could not load that item.'),
      )
    return () => {
      alive = false
    }
  }, [itemId])

  // Escape closes, and focus goes into the panel so the next Tab is inside it
  // rather than back in the result list behind.
  useEffect(() => {
    if (itemId === null) return
    const opener = document.activeElement as HTMLElement | null
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const frame = requestAnimationFrame(() => panel.current?.focus())
    return () => {
      document.removeEventListener('keydown', onKey)
      cancelAnimationFrame(frame)
      opener?.focus?.()
    }
  }, [itemId, onClose])

  return (
    <AnimatePresence>
      {itemId !== null && (
        <div className="fixed inset-0 z-40 flex justify-end">
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
            ref={panel}
            tabIndex={-1}
            variants={drawerVariants(reduce)}
            initial="initial"
            animate="animate"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-label="Item detail"
            className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-hairline bg-bg focus-visible:outline-none"
          >
            <header className="sticky top-0 flex items-start justify-between gap-4 border-b border-hairline bg-bg px-6 py-4">
              <div className="min-w-0 space-y-1">
                <p className="micro-label">Catalogue</p>
                <p className="break-words font-mono text-sm">
                  {detail?.golden?.std_description ?? detail?.normalized ?? `Item ${itemId}`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {detail?.cnmc && <CodeChip code={detail.cnmc.code} />}
                <Button size="sm" variant="ghost" onClick={onClose}>
                  Close
                </Button>
              </div>
            </header>

            <div className="space-y-6 p-6">
              {error && <p className="text-sm text-danger">{error}</p>}
              {!detail && !error && <p className="text-sm text-muted">Loading…</p>}
              {detail && (
                <>
                  <ItemPanel item={detail} side="This record" />
                  {detail.golden && (
                    <section className="space-y-2 border border-hairline p-4">
                      <p className="micro-label">Golden record</p>
                      <p className="break-words font-mono text-sm">
                        {detail.golden.std_description}
                      </p>
                      <p className="text-xs text-muted">{detail.golden.status}</p>
                    </section>
                  )}
                  <Link
                    to={`/items/${itemId}`}
                    className="micro-label underline underline-offset-4 hover:text-ink"
                  >
                    Open the full page
                  </Link>
                </>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
