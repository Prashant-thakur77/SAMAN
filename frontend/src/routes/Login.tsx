import { motion, useAnimationControls, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { Assistant } from '../components/Assistant'
import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import { Field, Input } from '../components/primitives/Field'
import {
  ApiError,
  getDemoUsers,
  getLoginMode,
  getPipelineStatus,
  demoLogin,
  loadDemoData,
  login,
  type DemoUser,
  type PipelineStatus,
} from '../lib/api'
import { cn } from '../lib/cn'
import { shakeAnimation } from '../lib/motion'
import { useSession } from '../lib/session'

// A first answer slower than this is a sleeping host waking up, and the page
// says so; after a failed answer it asks again this often.
const SLOW_MS = 2500
const RETRY_MS = 4000

/**
 * /login — spec §6.1. The wordmark is expanded exactly once, here, with the
 * tagline beneath it (spec §1.2).
 *
 * The picker lists the seeded users returned by the API — it invents nobody
 * (spec §10). In demo mode a click on an account signs in at once: the
 * picker already listed everyone and the shared password was printed under
 * the field, so asking for it protected nothing. With demo login off the
 * page is an email and a password, and the one-click door is shut on the
 * server too. A failed sign-in shakes the card by 4px, collapsing to an
 * opacity pulse under prefers-reduced-motion.
 */
export default function Login() {
  const [users, setUsers] = useState<DemoUser[]>([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The account being signed into by one click, so only its row says so.
  const [signingIn, setSigningIn] = useState<string | null>(null)
  const controls = useAnimationControls()
  const reduce = useReducedMotion() ?? false
  const navigate = useNavigate()
  const location = useLocation()
  // A visitor sent here from a screen inside the app goes back to it; the
  // app shell puts that screen in the router state (see App).
  const cameFrom = (location.state as { from?: string } | null)?.from ?? '/'
  const { refresh } = useSession()
  const [seeding, setSeeding] = useState<PipelineStatus | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)
  // Where the account list stands. Only an answer from the API can say the
  // database is empty; until one arrives the page says it is waiting.
  const [accounts, setAccounts] = useState<'loading' | 'ready' | 'waking' | 'unreachable'>(
    'loading',
  )
  const [failures, setFailures] = useState(0)
  // A first answer slower than a page load is a host waking up.
  const [slow, setSlow] = useState(false)

  // Demo picker or email field: the API decides (SAMAN_DEMO_LOGIN).
  const [mode, setMode] = useState<{ demo_login: boolean; has_users: boolean } | null>(null)

  const loadUsers = useCallback(async () => {
    try {
      const [list, loginMode] = await Promise.all([getDemoUsers(), getLoginMode()])
      setUsers(list)
      setMode(loginMode)
      setAccounts('ready')
      setEmail((current) => current || list[0]?.email || '')
      return loginMode.has_users ? Math.max(list.length, 1) : 0
    } catch (err) {
      // An empty database answers with an empty list, so a failure never
      // means "no accounts" and must not offer to seed. No answer at all is
      // the connection; any other is the host (one that sleeps when idle
      // answers 429 or 503 while it wakes) or the API still starting.
      setAccounts(err instanceof ApiError && err.status === 0 ? 'unreachable' : 'waking')
      setFailures((n) => n + 1)
      return 0
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  useEffect(() => {
    if (accounts !== 'loading') return
    const timer = window.setTimeout(() => setSlow(true), SLOW_MS)
    return () => window.clearTimeout(timer)
  }, [accounts])

  // Until the API answers, ask again every few seconds, so a visitor who
  // arrives while the host sleeps never has to know to reload.
  useEffect(() => {
    if (accounts !== 'waking' && accounts !== 'unreachable') return
    const timer = window.setTimeout(() => void loadUsers(), RETRY_MS)
    return () => window.clearTimeout(timer)
  }, [accounts, failures, loadUsers])

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

  function signInFailed(err: unknown) {
    setError(
      err instanceof ApiError && err.status === 401
        ? 'Incorrect user or password.'
        : err instanceof ApiError
          ? err.message
          : 'Sign-in failed.',
    )
    controls.start(shakeAnimation(reduce))
  }

  async function signInAs(account: string) {
    if (signingIn) return
    setError(null)
    setEmail(account)
    setSigningIn(account)
    try {
      try {
        await demoLogin(account)
      } catch (err) {
        // An API from before one-click sign-in has no such route and answers
        // 404; its seeded accounts all take the shared password, so sign in
        // that way. The frontend can then deploy before the API or after it.
        if (err instanceof ApiError && err.status === 404) await login(account, 'demo')
        else throw err
      }
      await refresh()
      navigate(cameFrom)
    } catch (err) {
      signInFailed(err)
    } finally {
      setSigningIn(null)
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password)
      await refresh()
      navigate(cameFrom)
    } catch (err) {
      signInFailed(err)
    } finally {
      setBusy(false)
    }
  }

  // Demo mode is the API's call. Until it answers, assume the picker, which
  // is what an empty or demo database shows.
  const oneClick = !mode || mode.demo_login

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
              hint={
                mode && !mode.demo_login
                  ? 'Your account email.'
                  : 'Seeded demo accounts. Click one to sign in.'
              }
            >
              {accounts === 'ready' && mode && !mode.demo_login && mode.has_users ? (
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              ) : accounts === 'unreachable' ? (
                <p role="status" className="card px-3 py-4 text-sm text-muted">
                  The server cannot be reached from here. Check the connection; this page
                  tries again by itself, and nothing can be signed in to until it answers.
                </p>
              ) : accounts !== 'ready' ? (
                <WaitingForAccounts waking={accounts === 'waking' || slow} />
              ) : users.length > 0 ? (
                <ul className="card divide-y divide-hairline overflow-hidden">
                  {users.map((u) => (
                    <li key={u.email}>
                      <button
                        type="button"
                        onClick={() => void signInAs(u.email)}
                        disabled={signingIn !== null}
                        aria-label={`Sign in as ${u.name}, ${u.role}${u.cpse_code ? `, ${u.cpse_code}` : ''}`}
                        className={cn(
                          'flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors',
                          'hover:bg-surface hover:text-ink focus-visible:bg-surface focus-visible:text-ink',
                          'disabled:cursor-wait',
                          signingIn === u.email ? 'bg-surface text-ink' : 'text-muted',
                        )}
                      >
                        <span
                          aria-hidden
                          className={cn(
                            'h-1.5 w-1.5 shrink-0 rounded-full',
                            signingIn === u.email ? 'animate-pulse bg-ink' : 'bg-hairline',
                          )}
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {signingIn === u.email ? 'Signing in…' : u.name}
                        </span>
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

            {!oneClick && (
              <Field label="Password" htmlFor="password">
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
            )}

            {error && (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            )}

            {!oneClick && (
              <Button type="submit" variant="primary" className="w-full" disabled={busy || !email}>
                {busy ? 'Signing in…' : 'Sign in'}
              </Button>
            )}
          </form>
        </motion.div>
      </main>

      <footer className="border-t border-hairline px-6 py-4 text-center">
        <p className="text-xs text-muted">One Nation, One Material Code</p>
      </footer>

      {/* The assistant meets people here too. Ask it to open a screen and it
          says to sign in first; once signed in, it takes you there. */}
      <Assistant />
    </div>
  )
}

/** The account list before the API has answered: placeholder rows where the
 *  accounts will be and, once the wait is longer than a page load, why. Never
 *  the empty-database offer, which only an answer can justify. */
function WaitingForAccounts({ waking }: { waking: boolean }) {
  return (
    <div role="status" className="card overflow-hidden">
      {waking ? (
        <p className="border-b border-hairline px-3 py-3 text-sm text-muted">
          Waking the server. It sleeps when nobody has used it for a while and can take up
          to a minute to answer; the accounts appear here as soon as it does.
        </p>
      ) : (
        <span className="sr-only">Loading accounts</span>
      )}
      <ul aria-hidden className="divide-y divide-hairline">
        {[0, 1, 2, 3].map((row) => (
          <li key={row} className="flex items-center gap-3 px-3 py-3">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-hairline" />
            <span className="h-3 w-32 animate-pulse rounded bg-hairline" />
            <span className="ml-auto h-3 w-16 animate-pulse rounded bg-hairline" />
          </li>
        ))}
      </ul>
    </div>
  )
}
