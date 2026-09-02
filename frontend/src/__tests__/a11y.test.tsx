/**
 * Accessibility behaviours that are easy to break and invisible when broken:
 * a modal the keyboard can walk out of, a route change nothing announces, a
 * skip link that skips to nowhere.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CommandPalette } from '../components/CommandPalette'
//—matches main.tsx, so the tests exercise the router the app actually uses.
const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

import { RouteAnnouncer } from '../components/RouteAnnouncer'

vi.mock('../lib/api', () => ({
  searchItems: vi.fn(async () => ({ items: [], total: 0 })),
}))

function renderPalette(onClose = vi.fn()) {
  const result = render(
    <MemoryRouter future={ROUTER_FUTURE}>
      <button type="button">opener</button>
      <CommandPalette open onClose={onClose} />
    </MemoryRouter>,
  )
  return { ...result, onClose }
}

describe('the command palette', () => {
  beforeEach(() => vi.clearAllMocks())

  it('is a labelled modal dialog', () => {
    renderPalette()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleName('Command palette')
  })

  it('takes focus when it opens', async () => {
    renderPalette()
    await waitFor(() => expect(screen.getByLabelText('Search SAMAN')).toHaveFocus())
  })

  it('points assistive technology at the active option', async () => {
    renderPalette()
    const input = screen.getByLabelText('Search SAMAN')
    await waitFor(() => expect(input).toHaveAttribute('aria-activedescendant'))
    const active = input.getAttribute('aria-activedescendant')
    expect(document.getElementById(active!)).toHaveAttribute('aria-selected', 'true')
  })

  it('moves the active option with the arrow keys', async () => {
    const user = userEvent.setup()
    renderPalette()
    const input = screen.getByLabelText('Search SAMAN')
    await waitFor(() => expect(input).toHaveFocus())
    const before = input.getAttribute('aria-activedescendant')
    await user.keyboard('{ArrowDown}')
    expect(input.getAttribute('aria-activedescendant')).not.toBe(before)
    await user.keyboard('{ArrowUp}')
    expect(input.getAttribute('aria-activedescendant')).toBe(before)
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const { onClose } = renderPalette()
    await waitFor(() => expect(screen.getByLabelText('Search SAMAN')).toHaveFocus())
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps Tab inside the dialog', async () => {
    const user = userEvent.setup()
    renderPalette()
    await waitFor(() => expect(screen.getByLabelText('Search SAMAN')).toHaveFocus())
    const dialog = screen.getByRole('dialog')
    for (let i = 0; i < 40; i += 1) {
      await user.tab()
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
    }
  })

  it('gives focus back to whatever opened it', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()

    const { unmount } = render(
      <MemoryRouter future={ROUTER_FUTURE}>
        <CommandPalette open onClose={vi.fn()} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByLabelText('Search SAMAN')).toHaveFocus())
    unmount()
    expect(opener).toHaveFocus()
    opener.remove()
  })

  it('counts its results in a live region', async () => {
    renderPalette()
    await waitFor(() => expect(screen.getByLabelText('Search SAMAN')).toHaveFocus())
    const live = document.querySelector('[aria-live="polite"]')
    expect(live?.textContent).toMatch(/\d+ results?/)
  })
})

describe('the route announcer', () => {
  it('says nothing on first load, since the browser already did', () => {
    render(
      <MemoryRouter future={ROUTER_FUTURE} initialEntries={['/search']}>
        <RouteAnnouncer />
      </MemoryRouter>,
    )
    expect(document.querySelector('[aria-live="polite"]')?.textContent).toBe('')
  })

  it('is a polite, atomic live region so it is not read mid-sentence', () => {
    render(
      <MemoryRouter future={ROUTER_FUTURE}>
        <RouteAnnouncer />
      </MemoryRouter>,
    )
    const live = document.querySelector('[aria-live="polite"]')
    expect(live).toHaveAttribute('aria-atomic', 'true')
    expect(live).toHaveClass('sr-only')
  })
})
