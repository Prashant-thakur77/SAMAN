/**
 * The front door, on the client side. A stranger may stand on the front page
 * and the sign-in page; every screen inside the shell sends them to sign in
 * first, remembering where they were going. The API refuses the same requests
 * independently (backend tests/test_front_door.py); this is so a visitor
 * meets a sign-in form rather than a shell full of "could not load".
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

let sessionUser: { id: number; email: string; name: string; role: string; cpse_code: string | null } | null = null
let sessionLoading = false
vi.mock('../lib/session', () => ({
  useSession: () => ({
    user: sessionUser,
    loading: sessionLoading,
    can: () => true,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}))
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getHealth: vi.fn(async () => ({ capabilities: { degraded: [] } })),
    getVoice: vi.fn(async () => ({ available: false, tts: { available: false } })),
    getDemoUsers: vi.fn(async () => []),
    getLoginMode: vi.fn(async () => ({ mode: 'demo', demo: true })),
    getBootstrapStatus: vi.fn(async () => ({ empty: false })),
    searchItems: vi.fn(async () => ({ items: [], total: 0 })),
  }
})

import App from '../app'
import { ThemeProvider } from '../lib/theme'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

/** Records where the router ended up and what state it carried. */
function Probe({ onLocation }: { onLocation: (path: string, state: unknown) => void }) {
  const location = useLocation()
  onLocation(location.pathname, location.state)
  return null
}

function renderAt(path: string, onLocation = (_p: string, _s: unknown) => {}) {
  return render(
    <ThemeProvider>
      <MemoryRouter future={ROUTER_FUTURE} initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<Probe onLocation={onLocation} />} />
        </Routes>
        <App />
      </MemoryRouter>
    </ThemeProvider>,
  )
}

describe('the front door', () => {
  it('sends a stranger from an inner screen to sign in, remembering the screen', async () => {
    sessionUser = null
    const seen: [string, unknown][] = []
    renderAt('/workbench?band=grey', (p, s) => seen.push([p, s]))
    await waitFor(() => expect(seen.at(-1)?.[0]).toBe('/login'))
    expect(seen.at(-1)?.[1]).toEqual({ from: '/workbench?band=grey' })
  })

  it('lets a stranger stand on the front page', async () => {
    sessionUser = null
    renderAt('/welcome')
    expect(
      await screen.findByRole('heading', { level: 1, name: /one nation, one material code/i }),
    ).toBeInTheDocument()
  })

  it('shows nothing rather than the sign-in page while the session is still loading', () => {
    sessionUser = null
    sessionLoading = true
    try {
      const { container } = renderAt('/search')
      expect(container.querySelector('form')).toBeNull()
      expect(screen.queryByText(/sign in/i)).toBeNull()
    } finally {
      sessionLoading = false
    }
  })

  it('lets a signed-in person into the shell', async () => {
    sessionUser = { id: 1, email: 'steward@cpcl.in', name: 'A. Ramesh', role: 'steward', cpse_code: 'CPCL' }
    try {
      renderAt('/search')
      expect(await screen.findByRole('link', { name: 'Workbench' })).toBeInTheDocument()
    } finally {
      sessionUser = null
    }
  })
})
