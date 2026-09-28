/**
 * The sign-in page. What matters: in demo mode an account signs in with one
 * click and there is no password to type; with demo login off there is no
 * picker to click, only an email and a password.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const demoLogin = vi.fn()
const login = vi.fn()
let demoMode = true

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getDemoUsers: vi.fn(async () =>
      demoMode
        ? [
            { email: 'registrar@min.gov.in', name: 'R. Krishnan', role: 'registrar', cpse_code: null },
            { email: 'steward@cpcl.in', name: 'A. Ramesh', role: 'steward', cpse_code: 'CPCL' },
          ]
        : [],
    ),
    getLoginMode: vi.fn(async () => ({ demo_login: demoMode, has_users: true })),
    demoLogin: (...args: unknown[]) => demoLogin(...args),
    login: (...args: unknown[]) => login(...args),
  }
})

const refresh = vi.fn(async () => {})
vi.mock('../lib/session', () => ({
  useSession: () => ({ user: null, loading: false, can: () => false, refresh, signOut: vi.fn() }),
}))

// The assistant and the theme switch have their own tests; keep them out of the way.
vi.mock('../components/Assistant', () => ({ Assistant: () => null }))
vi.mock('../components/ThemeToggle', () => ({ ThemeToggle: () => null }))

import { getDemoUsers, getLoginMode } from '../lib/api'
import Login from '../routes/Login'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']} future={ROUTER_FUTURE}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the sign-in page', () => {
  beforeEach(() => {
    demoLogin.mockReset()
    login.mockReset()
    refresh.mockClear()
  })

  it('signs in with one click in demo mode, with no password field', async () => {
    demoMode = true
    demoLogin.mockResolvedValue({ email: 'steward@cpcl.in', role: 'steward' })
    renderLogin()

    const account = await screen.findByRole('button', { name: /sign in as a\. ramesh/i })
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument()

    fireEvent.click(account)
    await waitFor(() => expect(demoLogin).toHaveBeenCalledWith('steward@cpcl.in'))
    expect(login).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/'))
    expect(refresh).toHaveBeenCalled()
  })

  it('says so when a one-click sign-in is refused', async () => {
    demoMode = true
    const { ApiError } = await import('../lib/api')
    demoLogin.mockRejectedValue(new ApiError(401, 'No such account.'))
    renderLogin()

    fireEvent.click(await screen.findByRole('button', { name: /sign in as r\. krishnan/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/incorrect user or password/i)
  })

  it('falls back to the shared password against an API without one-click sign-in', async () => {
    demoMode = true
    const { ApiError } = await import('../lib/api')
    demoLogin.mockRejectedValue(new ApiError(404, 'Not Found'))
    login.mockResolvedValue({ email: 'steward@cpcl.in', role: 'steward' })
    renderLogin()

    fireEvent.click(await screen.findByRole('button', { name: /sign in as a\. ramesh/i }))
    await waitFor(() => expect(login).toHaveBeenCalledWith('steward@cpcl.in', 'demo'))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/'))
  })

  it('asks for an email and a password when demo login is off', async () => {
    demoMode = false
    login.mockResolvedValue({ email: 'steward@cpcl.in', role: 'steward' })
    renderLogin()

    const email = await screen.findByLabelText(/sign in as/i)
    const password = screen.getByLabelText(/password/i)
    fireEvent.change(email, { target: { value: 'steward@cpcl.in' } })
    fireEvent.change(password, { target: { value: 's3cret' } })
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    await waitFor(() => expect(login).toHaveBeenCalledWith('steward@cpcl.in', 's3cret'))
    expect(demoLogin).not.toHaveBeenCalled()
  })

  describe('before the API has answered', () => {
    beforeEach(() => {
      demoMode = true
      vi.useFakeTimers({ shouldAdvanceTime: true })
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('waits, and says the server is waking once the wait is long', async () => {
      vi.mocked(getDemoUsers).mockImplementationOnce(() => new Promise(() => {}))
      renderLogin()

      expect(screen.getByRole('status')).toHaveTextContent(/loading accounts/i)
      expect(screen.queryByText(/database is empty/i)).not.toBeInTheDocument()
      await act(() => vi.advanceTimersByTimeAsync(2500))
      expect(screen.getByRole('status')).toHaveTextContent(/waking the server/i)
      expect(screen.queryByRole('button', { name: /load demo data/i })).not.toBeInTheDocument()
    })

    it('never calls a sleeping host an empty database, and signs in once it wakes', async () => {
      const { ApiError } = await import('../lib/api')
      vi.mocked(getDemoUsers).mockRejectedValueOnce(new ApiError(429, 'Too Many Requests'))
      renderLogin()

      expect(await screen.findByText(/waking the server/i)).toBeInTheDocument()
      expect(screen.queryByText(/database is empty/i)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /load demo data/i })).not.toBeInTheDocument()

      await act(() => vi.advanceTimersByTimeAsync(4000))
      expect(
        await screen.findByRole('button', { name: /sign in as a\. ramesh/i }),
      ).toBeInTheDocument()
    })
  })

  it('offers the demo estate only when the API answers that there is nobody', async () => {
    demoMode = true
    vi.mocked(getDemoUsers).mockResolvedValueOnce([])
    vi.mocked(getLoginMode).mockResolvedValueOnce({ demo_login: true, has_users: false })
    renderLogin()

    expect(await screen.findByRole('button', { name: /load demo data/i })).toBeInTheDocument()
    expect(screen.getByText(/database is empty/i)).toBeInTheDocument()
  })
})
