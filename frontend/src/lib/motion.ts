/**
 * Motion spec — §1.5, implemented once and reused everywhere.
 *
 * Every variant factory takes `reduce` (from framer-motion's
 * `useReducedMotion`) and collapses to opacity-only when it is true, so
 * `prefers-reduced-motion` is honoured without duplicating component logic.
 */

import type { Transition, Variants } from 'framer-motion'

/** The house easing curve. */
export const EASE = [0.22, 1, 0.36, 1] as const

export const DUR = {
  routeOut: 0.12,
  routeIn: 0.24,
  drawer: 0.28,
  decision: 0.16,
  palette: 0.15,
  theme: 0.15,
  kpiCountUp: 400, // ms — driven by rAF, not framer
} as const

const ease = (duration: number): Transition => ({ duration, ease: EASE })

/** Route transitions: out fades 120ms; in slides x:24 -> 0 over 240ms. */
export function routeVariants(reduce: boolean): Variants {
  return {
    initial: { opacity: 0, x: reduce ? 0 : 24 },
    animate: { opacity: 1, x: 0, transition: ease(DUR.routeIn) },
    exit: { opacity: 0, transition: { duration: DUR.routeOut, ease: 'linear' } },
  }
}

/** Side panels / drawers: slide from the right edge. */
export function drawerVariants(reduce: boolean): Variants {
  return {
    initial: { opacity: 0, x: reduce ? 0 : '100%' },
    animate: { opacity: 1, x: 0, transition: ease(DUR.drawer) },
    exit: { opacity: 0, x: reduce ? 0 : '100%', transition: ease(DUR.drawer) },
  }
}

/** Scrim behind any overlay. Always opacity-only. */
export const scrimVariants: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.2, ease: 'linear' } },
  exit: { opacity: 0, transition: { duration: 0.15, ease: 'linear' } },
}

/** Tables / lists: stagger children by 20ms. */
export function listVariants(reduce: boolean): Variants {
  return {
    initial: {},
    animate: { transition: { staggerChildren: reduce ? 0 : 0.02 } },
  }
}

export function listItemVariants(reduce: boolean): Variants {
  return {
    initial: { opacity: 0, y: reduce ? 0 : 8 },
    animate: { opacity: 1, y: 0, transition: ease(0.2) },
  }
}

/** Workbench card: approve exits right, reject exits left; next card rises. */
export function decisionCardVariants(reduce: boolean): Variants {
  return {
    initial: { opacity: 0, y: reduce ? 0 : 12 },
    animate: { opacity: 1, y: 0, x: 0, transition: ease(0.2) },
    approve: { opacity: 0, x: reduce ? 0 : 320, transition: ease(DUR.decision) },
    reject: { opacity: 0, x: reduce ? 0 : -320, transition: ease(DUR.decision) },
  }
}

/** Command palette (⌘K): scale 0.98 -> 1 + fade. */
export function paletteVariants(reduce: boolean): Variants {
  return {
    initial: { opacity: 0, scale: reduce ? 1 : 0.98 },
    animate: { opacity: 1, scale: 1, transition: ease(DUR.palette) },
    exit: { opacity: 0, scale: reduce ? 1 : 0.98, transition: ease(0.12) },
  }
}

/** Login error: 4px horizontal shake (spec §5.1). */
export function shakeAnimation(reduce: boolean) {
  return reduce
    ? { opacity: [1, 0.6, 1], transition: { duration: 0.2 } }
    : { x: [0, -4, 4, -4, 4, 0], transition: { duration: 0.35, ease: 'easeInOut' as const } }
}
