import { motion, useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'

import { routeVariants } from '../lib/motion'

/**
 * Spec §1.5: outgoing route fades over 120ms, incoming slides in from the right
 * (x:24 -> 0) with opacity 0 -> 1 over 240ms on the house easing curve.
 * Wrap every route element; AnimatePresence lives in app.tsx.
 */
export function RouteTransition({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.div
      variants={routeVariants(reduce)}
      initial="initial"
      animate="animate"
      exit="exit"
      className="h-full"
    >
      {children}
    </motion.div>
  )
}
