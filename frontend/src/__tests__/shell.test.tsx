/**
 * §8A: never a crash or an infinite spinner. A blank content column is neither
 * of those and is still not an explanation — with the API down, every screen
 * rendered nothing at all.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getHealth = vi.fn()
vi.mock('../lib/api', async () => {
  // Everything else real: the shell mounts the assistant, which asks the API
  // about voice on mount, and a mock that lacks those functions crashes the
  // render for a reason that has nothing to do with the shell.
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getHealth: (...args: unknown[]) => getHealth(...args),
    searchItems: vi.fn(async () => ({ items: [], total: 0 })),
    getVoice: vi.fn(async () => {
      throw new Error('no api in this test')
    }),
  }
})
vi.mock('../lib/session', () => ({
  useSession: () => ({ user: null, loading: false, can: () => false }),
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

describe('the shell when the API is down', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders its children when the API answers', async () => {
    getHealth.mockResolvedValue({
      capabilities: {
        linkage: { mode: 'rapidfuzz', degraded: false },
        embedding: { mode: 'tfidf', degraded: true },
        llm: { mode: 'deterministic', degraded: true },
        degraded: ['TF-IDF fallback', 'no local model'],
      },
    })
    renderShell()
    await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())
  })

  it('explains the outage instead of rendering an empty column', async () => {
    getHealth.mockRejectedValue(new Error('connection refused'))
    renderShell()
    await waitFor(() =>
      expect(screen.getByText('SAMAN cannot reach its API')).toBeInTheDocument(),
    )
    expect(screen.queryByText('the page content')).not.toBeInTheDocument()
  })

  it('says what to do about it, and that nothing was lost', async () => {
    getHealth.mockRejectedValue(new Error('connection refused'))
    renderShell()
    await waitFor(() => expect(screen.getByText(/make dev/)).toBeInTheDocument())
    expect(screen.getByText(/database is on disk/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('keeps the shell standing either way', async () => {
    getHealth.mockRejectedValue(new Error('connection refused'))
    renderShell()
    await waitFor(() => expect(screen.getByLabelText('Main')).toBeInTheDocument())
    expect(screen.getByText('Skip to content')).toBeInTheDocument()
  })
})


describe('the degraded chip', () => {
  it('survives a health payload that is missing a tier', async () => {
    // It lives in the always-rendered command bar, outside any route error
    // boundary, so throwing here would blank the whole application.
    getHealth.mockResolvedValue({ capabilities: {} })
    renderShell()
    await waitFor(() => expect(screen.getByText('the page content')).toBeInTheDocument())
    expect(screen.getByLabelText('Main')).toBeInTheDocument()
  })
})
