/**
 * Below `lg` the sidebar is a drawer rather than a column, because a permanent
 * 240px column on a 390px phone leaves the page a strip. The drawer is opened
 * from the command bar, and it must close itself again: one left open over the
 * screen you just asked for is worse than no drawer at all.
 *
 * The breakpoint itself is CSS and jsdom applies none, so what is tested here
 * is the state machine: the handle exists, it opens, and every way out closes
 * it. The rendering at 390px is checked in the browser.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getHealth: vi.fn(async () => ({
      capabilities: {
        linkage: { mode: 'rapidfuzz', degraded: false },
        embedding: { mode: 'tfidf', degraded: false },
        llm: { mode: 'ollama', degraded: false },
        degraded: [],
      },
    })),
    searchItems: vi.fn(async () => ({ items: [], total: 0 })),
    getVoice: vi.fn(async () => {
      throw new Error('no api in this test')
    }),
  }
})
vi.mock('../lib/session', () => ({
  useSession: () => ({
    user: { id: 1, email: 'steward@cpcl.in', name: 'A. Ramesh', role: 'steward', cpse_code: 'CPCL' },
    loading: false,
    can: () => true,
    signOut: vi.fn(),
  }),
}))

import { Shell } from '../components/Shell'
import { ThemeProvider } from '../lib/theme'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

function renderShell() {
  return render(
    <ThemeProvider>
      <MemoryRouter future={ROUTER_FUTURE}>
        <Shell>
          <p>the page content</p>
        </Shell>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

const drawer = () => document.querySelector('aside')

describe('the navigation drawer on a narrow screen', () => {
  it('starts closed, with a handle in the command bar', async () => {
    renderShell()
    await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())

    expect(screen.getByLabelText('Open navigation')).toBeInTheDocument()
    // Off-screen and, crucially, not in the tab order: `invisible` is what
    // keeps a phone's keyboard from walking twelve links nobody can see.
    expect(drawer()).toHaveClass('invisible', '-translate-x-full')
    // On a desktop-width screen the same element is a column again.
    expect(drawer()).toHaveClass('lg:visible', 'lg:translate-x-0')
  })

  it('opens on the handle and closes on its own close button', async () => {
    const user = userEvent.setup()
    renderShell()
    await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())

    await user.click(screen.getByLabelText('Open navigation'))
    expect(drawer()).toHaveClass('visible', 'translate-x-0')

    await user.click(screen.getByLabelText('Close navigation'))
    expect(drawer()).toHaveClass('invisible', '-translate-x-full')
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    renderShell()
    await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())

    await user.click(screen.getByLabelText('Open navigation'))
    expect(drawer()).toHaveClass('translate-x-0')

    await user.keyboard('{Escape}')
    expect(drawer()).toHaveClass('-translate-x-full')
  })

  it('closes itself when a link is followed', async () => {
    const user = userEvent.setup()
    renderShell()
    await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())

    await user.click(screen.getByLabelText('Open navigation'))
    expect(drawer()).toHaveClass('translate-x-0')

    // The drawer covers the page; following a link inside it has to put the
    // page back, not leave the drawer sitting over the screen just requested.
    await user.click(screen.getByRole('link', { name: 'Workbench' }))
    await waitFor(() => expect(drawer()).toHaveClass('-translate-x-full'))
  })

  it('keeps every label in the drawer whatever the desktop rail was left at', async () => {
    // `collapsed` is persisted from desktop use; the rail would be a worse
    // drawer than the full list, so labels are hidden per breakpoint, never
    // dropped from the DOM.
    localStorage.setItem('saman.sidebar.collapsed', '1')
    try {
      renderShell()
      await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())
      const label = screen.getByRole('link', { name: 'Workbench' }).querySelector('span')
      expect(label).toHaveTextContent('Workbench')
      expect(label).toHaveClass('lg:hidden')
    } finally {
      localStorage.removeItem('saman.sidebar.collapsed')
    }
  })
})
