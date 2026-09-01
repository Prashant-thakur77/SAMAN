import { motion, useAnimationControls, useReducedMotion } from 'framer-motion'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import { Field, Input } from '../components/primitives/Field'
import { ApiError, getDemoUsers, login, type DemoUser } from '../lib/api'
import { cn } from '../lib/cn'
import { shakeAnimation } from '../lib/motion'

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

  useEffect(() => {
    let alive = true
    getDemoUsers()
      .then((list) => {
        if (!alive) return
        setUsers(list)
        setEmail((current) => current || list[0]?.email || '')
      })
      // No seeded users yet is a normal first-run state, not an error.
      .catch(() => alive && setUsers([]))
    return () => {
      alive = false
    }
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password)
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
            <h1 className="font-sans text-lg font-medium uppercase tracking-wordmark text-ink">
              SAMAN
            </h1>
            <p className="text-sm text-muted">Standardised Asset &amp; Material Analysis Network</p>
            <p className="text-sm text-ink">One Nation, One Material Code</p>
          </div>

          <hr />

          <form onSubmit={onSubmit} className="space-y-6">
            <Field label="Sign in as" hint="Seeded demo accounts.">
              {users.length > 0 ? (
                <ul className="divide-y divide-hairline border border-hairline">
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
                <p className="border border-hairline px-3 py-4 text-sm text-muted">
                  No users yet. Run <span className="font-mono text-xs">make seed</span> to create
                  the demo accounts.
                </p>
              )}
            </Field>

            <Field label="Password" htmlFor="password" hint="Every seeded account uses “demo”.">
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
