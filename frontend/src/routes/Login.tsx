import { motion, useAnimationControls, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import { Field, Input } from '../components/primitives/Field'
import {
  ApiError,
  getDemoUsers,
  getLoginMode,
  getPipelineStatus,
  loadDemoData,
  login,
  type DemoUser,
  type PipelineStatus,
} from '../lib/api'
import { cn } from '../lib/cn'
import { shakeAnimation } from '../lib/motion'
import { useSession } from '../lib/session'

/**
 * /login — spec §6.1. The wordmark is expanded exactly once, here, with the
 * tagline beneath it (spec §1.2).
 *
 * The picker lists the seeded users returned by the API — it invents nobody
 * (spec §10). A failed sign-in shakes the card by 4px, collapsing to an
 * opacity pulse under prefers-reduced-motion.
 */
export default function Login() {
  const [users, setUsers] = useState<DemoUser[]>([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const controls = useAnimationControls()
  const reduce = useReducedMotion() ?? false
  const navigate = useNavigate()
  const { refresh } = useSession()
  const [seeding, setSeeding] = useState<PipelineStatus | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)

  // Demo picker or email field: the API decides (SAMAN_DEMO_LOGIN).
  const [mode, setMode] = useState<{ demo_login: boolean; has_users: boolean } | null>(null)

  const loadUsers = useCallback(async () => {
    try {
      const [list, loginMode] = await Promise.all([getDemoUsers(), getLoginMode()])
      setUsers(list)
      setMode(loginMode)
      setEmail((current) => current || list[0]?.email || '')
      return loginMode.has_users ? Math.max(list.length, 1) : 0
    } catch {
      // No seeded users yet is a normal first-run state, not an error.
      setUsers([])
      return 0
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  // While a first-run seed is running, poll until it finishes and then bring
  // the accounts in behind it, so nobody has to know to reload the page.
  useEffect(() => {
    if (!seeding || seeding.state === 'done' || seeding.state === 'failed') return
    const timer = window.setInterval(async () => {
      try {
        const next = await getPipelineStatus()
        setSeeding(next)
        if (next.state === 'done') {
          window.clearInterval(timer)
          await loadUsers()
        }
      } catch {
        /* the API restarting mid-seed is survivable; the next tick retries */
      }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [seeding, loadUsers])

  async function seedDemoData() {
    setSeedError(null)
    try {
      await loadDemoData()
      setSeeding(await getPipelineStatus())
    } catch (err) {
      setSeedError(
        err instanceof ApiError ? err.message : 'Could not start the demo load.',
      )
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password)
      await refresh()
      navigate('/')
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? 'Incorrect user or password.'
          : err instanceof ApiError
            ? err.message
            : 'Sign-in failed.',
      )
      controls.start(shakeAnimation(reduce))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <div className="flex justify-end p-4">
        <ThemeToggle />
      </div>

      <main className="flex flex-1 items-start justify-center px-6 pb-24 pt-8">
        <motion.div animate={controls} className="w-full max-w-md space-y-8">
          <div className="space-y-3">
            {/* The way back to the front page, where the wordmark already is. */}
            <Link to="/welcome" className="inline-block">
              <h1 className="font-sans text-lg font-medium uppercase tracking-wordmark text-ink">
                SAMAN
              </h1>
            </Link>
            <p className="text-sm text-muted">Standardised Asset &amp; Material Analysis Network</p>
            <p className="text-sm text-ink">One Nation, One Material Code</p>
          </div>

          <hr />

          <form onSubmit={onSubmit} className="space-y-6">
            <Field
              label="Sign in as"
              htmlFor={mode && !mode.demo_login ? 'email' : undefined}
              hint={mode && !mode.demo_login ? 'Your account email.' : 'Seeded demo accounts.'}
            >
              {mode && !mode.demo_login && mode.has_users ? (
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              ) : users.length > 0 ? (
                <ul className="card divide-y divide-hairline overflow-hidden">
                  {users.map((u) => (
                    <li key={u.email}>
                      <button
                        type="button"
                        onClick={() => setEmail(u.email)}
                        aria-pressed={email === u.email}
                        className={cn(
                          'flex w-full items-center gap-3 px-3 py-2 text-left text-sm',
                          email === u.email ? 'bg-surface text-ink' : 'text-muted hover:text-ink',
                        )}
                      >
                        <span
                          aria-hidden
                          className={cn(
                            'h-1.5 w-1.5 shrink-0 rounded-full',
                            email === u.email ? 'bg-ink' : 'bg-hairline',
                          )}
                        />
                        <span className="min-w-0 flex-1 truncate">{u.name}</span>
                        <span className="micro-label shrink-0">
                          {u.role}
                          {u.cpse_code ? ` · ${u.cpse_code}` : ''}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="space-y-3 card px-3 py-4">
                  <p className="text-sm text-muted">
                    This database is empty. Load the demo estate (four CPSEs, about 12,000
                    catalogue rows), or run{' '}
                    <span className="font-mono text-xs">make demo</span> from the repository.
                  </p>
                  {seeding && seeding.state !== 'done' ? (
                    <div className="space-y-2">
                      <p className="font-mono text-xs">
                        {seeding.stage} · {seeding.rows_done.toLocaleString('en-IN')} of{' '}
                        {seeding.rows_total.toLocaleString('en-IN')}
                      </p>
                      <div className="h-1 w-full bg-hairline">
                        <div
                          className="h-1 bg-ink transition-[width] duration-300 ease-saman"
                          style={{
                            width: `${
                              seeding.rows_total
                                ? Math.min(100, (seeding.rows_done / seeding.rows_total) * 100)
                                : 5
                            }%`,
                          }}
                        />
                      </div>
                      <p className="text-xs text-muted">
                        About a minute. The page picks up the accounts when it finishes.
                      </p>
                    </div>
                  ) : (
                    <Button type="button" variant="primary" onClick={() => void seedDemoData()}>
                      Load demo data
                    </Button>
                  )}
                  {seedError && <p className="text-xs text-danger">{seedError}</p>}
                </div>
              )}
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              hint={mode && !mode.demo_login ? undefined : 'Every seeded account uses “demo”.'}
            >
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>

            {error && (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            )}

            <Button type="submit" variant="primary" className="w-full" disabled={busy || !email}>
              {busy ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </motion.div>
      </main>

      <footer className="border-t border-hairline px-6 py-4 text-center">
        <p className="text-xs text-muted">
          SIH 2026 · SIH26099 · Ministry of Petroleum &amp; Natural Gas
        </p>
      </footer>
    </div>
  )
}
