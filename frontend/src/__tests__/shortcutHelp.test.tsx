/**
 * `?` help: the per-screen block matches the screen, and Escape closes it.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ShortcutHelp, shortcutsFor } from '../components/ShortcutHelp'

describe('shortcut help', () => {
  it('knows the workbench keys and nothing screen-specific for the home page', () => {
    expect(shortcutsFor('/workbench')?.keys.map((k) => k.keys)).toEqual([
      'A',
      'R',
      'J / K',
      'M',
      'U',
    ])
    expect(shortcutsFor('/')).toBeNull()
  })

  it('renders the current screen first and the global keys always', () => {
    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <ShortcutHelp open onClose={() => {}} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByText('Workbench')).toBeTruthy()
    expect(screen.getByText('Everywhere')).toBeTruthy()
    expect(screen.getByText(/Undo the last decision/)).toBeTruthy()
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(
      <MemoryRouter>
        <ShortcutHelp open onClose={onClose} />
      </MemoryRouter>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
