/**
 * The assistant's launcher can be put where the person likes. What matters:
 * a tap is still a tap, a drag moves it and is remembered on this device,
 * and a smaller window pulls it back inside the screen.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { clampOffset, useDraggableCorner } from '../lib/useDraggableCorner'

function Launcher({ onTap }: { onTap: () => void }) {
  const corner = useDraggableCorner('test.pos', { right: 20, bottom: 20 })
  return (
    <button
      ref={(el) => {
        corner.ref.current = el
      }}
      type="button"
      data-testid="fab"
      data-dragging={corner.dragging}
      style={{ right: corner.offset.right, bottom: corner.offset.bottom }}
      onPointerDown={corner.onPointerDown}
      onPointerMove={corner.onPointerMove}
      onPointerUp={(event) => {
        if (!corner.onPointerUp(event)) onTap()
      }}
    >
      move me
    </button>
  )
}

describe('a draggable corner control', () => {
  beforeEach(() => {
    localStorage.clear()
    Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true })
    HTMLElement.prototype.setPointerCapture = () => {}
    HTMLElement.prototype.releasePointerCapture = () => {}
  })

  it('starts where the caller says and treats a short press as a tap', () => {
    let taps = 0
    render(<Launcher onTap={() => (taps += 1)} />)
    const fab = screen.getByTestId('fab')
    expect(fab.style.right).toBe('20px')
    fireEvent.pointerDown(fab, { clientX: 700, clientY: 500, pointerId: 1, button: 0 })
    fireEvent.pointerMove(fab, { clientX: 702, clientY: 501, pointerId: 1 })
    fireEvent.pointerUp(fab, { clientX: 702, clientY: 501, pointerId: 1 })
    expect(taps).toBe(1)
    expect(fab.style.right).toBe('20px')
    expect(localStorage.getItem('test.pos')).toBeNull()
  })

  it('moves with a drag, is not a tap, and remembers the spot', () => {
    let taps = 0
    render(<Launcher onTap={() => (taps += 1)} />)
    const fab = screen.getByTestId('fab')
    fireEvent.pointerDown(fab, { clientX: 700, clientY: 500, pointerId: 1, button: 0 })
    fireEvent.pointerMove(fab, { clientX: 600, clientY: 300, pointerId: 1 })
    expect(fab.dataset.dragging).toBe('true')
    fireEvent.pointerUp(fab, { clientX: 600, clientY: 300, pointerId: 1 })
    expect(taps).toBe(0)
    expect(fab.style.right).toBe('120px')
    expect(fab.style.bottom).toBe('220px')
    expect(JSON.parse(localStorage.getItem('test.pos') ?? '{}')).toEqual({
      right: 120,
      bottom: 220,
    })
  })

  it('comes back where it was left, inside the screen', () => {
    localStorage.setItem('test.pos', JSON.stringify({ right: 5000, bottom: 30 }))
    render(<Launcher onTap={() => {}} />)
    const fab = screen.getByTestId('fab')
    // jsdom reports a zero-size element; the clamp keeps the margin.
    expect(parseInt(fab.style.right, 10)).toBeLessThanOrEqual(800)
    expect(fab.style.bottom).toBe('30px')
  })

  it('clamps an offset to the viewport for the element size given', () => {
    expect(clampOffset({ right: -40, bottom: 9999 }, { width: 50, height: 48 })).toEqual({
      right: 12,
      bottom: 600 - 48 - 12,
    })
  })
})
