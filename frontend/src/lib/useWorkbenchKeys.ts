import { useEffect } from 'react'

/**
 * The workbench keyboard contract (spec §6.5): `A` approve, `R` reject,
 * `J`/`K` next and previous, `M` open the cluster.
 *
 * Extracted from the route so the contract is stated in one place and can be
 * tested without mounting a screen's worth of API calls. A reviewer working a
 * queue of thousands does it from the keyboard or not at all, which makes this
 * a feature rather than a convenience.
 */
export type WorkbenchKeyHandlers = {
  approve: () => void
  reject: () => void
  next: () => void
  previous: () => void
  /** Absent when the card has no cluster to open. */
  openCluster?: () => void
}

/** Elements whose own keystrokes must never be stolen. */
const TYPING = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

export function useWorkbenchKeys(handlers: WorkbenchKeyHandlers, enabled = true) {
  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      // Typing "reject" into a search box must not reject anything.
      if (target && (TYPING.has(target.tagName) || target.isContentEditable)) return
      // A modifier means the user is talking to the browser, not the queue.
      if (event.metaKey || event.ctrlKey || event.altKey) return

      const action = {
        a: handlers.approve,
        r: handlers.reject,
        j: handlers.next,
        k: handlers.previous,
        m: handlers.openCluster,
      }[event.key.toLowerCase()]

      if (!action) return
      event.preventDefault()
      action()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handlers, enabled])
}
