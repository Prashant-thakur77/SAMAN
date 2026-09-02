/**
 * The §6.5 keyboard contract. A reviewer working a queue of thousands does it
 * from the keyboard or not at all, so these are a feature rather than a
 * convenience — and they were implemented but never verified.
 */

import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkbenchKeys, type WorkbenchKeyHandlers } from '../lib/useWorkbenchKeys'

function Harness({
  handlers,
  enabled = true,
  withInput = false,
}: {
  handlers: WorkbenchKeyHandlers
  enabled?: boolean
  withInput?: boolean
}) {
  useWorkbenchKeys(handlers, enabled)
  return withInput ? <input aria-label="notes" /> : <p>queue</p>
}

function spies(openCluster = true): WorkbenchKeyHandlers & Record<string, unknown> {
  return {
    approve: vi.fn(),
    reject: vi.fn(),
    next: vi.fn(),
    previous: vi.fn(),
    openCluster: openCluster ? vi.fn() : undefined,
  }
}

describe('the workbench keyboard contract', () => {
  let handlers: ReturnType<typeof spies>

  beforeEach(() => {
    handlers = spies()
  })

  it.each([
    ['a', 'approve'],
    ['r', 'reject'],
    ['j', 'next'],
    ['k', 'previous'],
    ['m', 'openCluster'],
  ] as const)('%s triggers %s', async (key, name) => {
    const user = userEvent.setup()
    render(<Harness handlers={handlers} />)
    await user.keyboard(key)
    expect(handlers[name]).toHaveBeenCalledTimes(1)
  })

  it('accepts the shortcuts in upper case too', async () => {
    const user = userEvent.setup()
    render(<Harness handlers={handlers} />)
    await user.keyboard('{Shift>}A{/Shift}')
    expect(handlers.approve).toHaveBeenCalled()
  })

  it('ignores a key with no action bound to it', async () => {
    const user = userEvent.setup()
    render(<Harness handlers={handlers} />)
    await user.keyboard('z')
    for (const fn of ['approve', 'reject', 'next', 'previous'] as const) {
      expect(handlers[fn]).not.toHaveBeenCalled()
    }
  })

  it('does nothing for M when the card has no cluster', async () => {
    const user = userEvent.setup()
    const withoutCluster = spies(false)
    render(<Harness handlers={withoutCluster} />)
    await user.keyboard('m')
    expect(withoutCluster.approve).not.toHaveBeenCalled()
  })

  it('keeps its hands off a text field', async () => {
    // Typing "reject" into a search box must not reject anything.
    const user = userEvent.setup()
    render(<Harness handlers={handlers} withInput />)
    const field = document.querySelector('input') as HTMLInputElement
    await user.click(field)
    await user.type(field, 'reject a job')
    expect(handlers.reject).not.toHaveBeenCalled()
    expect(handlers.approve).not.toHaveBeenCalled()
    expect(field.value).toBe('reject a job')
  })

  it('leaves browser shortcuts alone', async () => {
    const user = userEvent.setup()
    render(<Harness handlers={handlers} />)
    await user.keyboard('{Control>}r{/Control}')
    await user.keyboard('{Meta>}a{/Meta}')
    expect(handlers.reject).not.toHaveBeenCalled()
    expect(handlers.approve).not.toHaveBeenCalled()
  })

  it('stops listening when disabled', async () => {
    const user = userEvent.setup()
    render(<Harness handlers={handlers} enabled={false} />)
    await user.keyboard('a')
    expect(handlers.approve).not.toHaveBeenCalled()
  })

  it('detaches its listener on unmount', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Harness handlers={handlers} />)
    unmount()
    await user.keyboard('a')
    expect(handlers.approve).not.toHaveBeenCalled()
  })
})
