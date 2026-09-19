/**
 * A floating control the person can put where they like.
 *
 * The assistant's launcher sits bottom-right by default, which on a phone is
 * exactly where the last row of a table or the Sign-in button lives. Rather
 * than guess a better corner, let the person drag it: the position is kept
 * per device (localStorage), clamped back inside the viewport on every
 * resize, and expressed as an offset from the bottom-right so a phone
 * rotating or a window narrowing keeps the control on screen.
 *
 * Pointer events cover mouse, pen and touch alike; a press that travels
 * fewer than `SLOP` pixels is a click, not a drag, and the caller is told
 * which it was so a tap still opens the panel.
 */

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

export type Offset = { right: number; bottom: number }

const SLOP = 6
const MARGIN = 12

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), Math.max(low, high))
}

/** Keep `offset` for an element of `size` inside the current viewport. */
export function clampOffset(offset: Offset, size: { width: number; height: number }): Offset {
  const vw = typeof window === 'undefined' ? 1024 : window.innerWidth
  const vh = typeof window === 'undefined' ? 768 : window.innerHeight
  return {
    right: clamp(offset.right, MARGIN, vw - size.width - MARGIN),
    bottom: clamp(offset.bottom, MARGIN, vh - size.height - MARGIN),
  }
}

function read(key: string): Offset | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Offset>
    if (typeof parsed.right !== 'number' || typeof parsed.bottom !== 'number') return null
    return { right: parsed.right, bottom: parsed.bottom }
  } catch {
    return null
  }
}

function write(key: string, offset: Offset | null) {
  try {
    if (offset) localStorage.setItem(key, JSON.stringify(offset))
    else localStorage.removeItem(key)
  } catch {
    /* the position still holds for this page */
  }
}

export function useDraggableCorner(key: string, fallback: Offset) {
  const [offset, setOffset] = useState<Offset>(() => read(key) ?? fallback)
  const [dragging, setDragging] = useState(false)
  const ref = useRef<HTMLElement | null>(null)
  const press = useRef<{ x: number; y: number; start: Offset; moved: boolean } | null>(null)

  const size = useCallback(() => {
    const rect = ref.current?.getBoundingClientRect()
    return { width: rect?.width ?? 48, height: rect?.height ?? 48 }
  }, [])

  // A narrower window must not leave the control off screen.
  useEffect(() => {
    const onResize = () => setOffset((o) => clampOffset(o, size()))
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [size])

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0 && event.pointerType === 'mouse') return
      press.current = { x: event.clientX, y: event.clientY, start: offset, moved: false }
      event.currentTarget.setPointerCapture(event.pointerId)
    },
    [offset],
  )

  const onPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      const p = press.current
      if (!p) return
      const dx = event.clientX - p.x
      const dy = event.clientY - p.y
      if (!p.moved && Math.hypot(dx, dy) < SLOP) return
      if (!p.moved) {
        p.moved = true
        setDragging(true)
      }
      setOffset(clampOffset({ right: p.start.right - dx, bottom: p.start.bottom - dy }, size()))
    },
    [size],
  )

  /** Ends the press; returns true when it was a drag rather than a tap. */
  const onPointerUp = useCallback(
    (event: ReactPointerEvent<HTMLElement>): boolean => {
      const p = press.current
      press.current = null
      try {
        event.currentTarget.releasePointerCapture(event.pointerId)
      } catch {
        /* capture may already be gone */
      }
      if (!p?.moved) return false
      setDragging(false)
      setOffset((o) => {
        write(key, o)
        return o
      })
      return true
    },
    [key],
  )

  return { ref, offset, dragging, onPointerDown, onPointerMove, onPointerUp }
}
