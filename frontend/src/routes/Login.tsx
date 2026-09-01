import { motion, useAnimationControls, useReducedMotion } from 'framer-motion'
import { useState, type FormEvent } from 'react'

import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import { Field, Input } from '../components/primitives/Field'
import { ApiError, api } from '../lib/api'
import { shakeAnimation } from '../lib/motion'

/**
 * /login — spec §6.1. The wordmark is expanded exactly once, here, with the
 * tagline beneath it (spec §1.2).
 *
 * The user picker is populated from the seeded users endpoint once auth exists
 * (M2). Until then this page does not invent a user list (spec §10); the form
 * posts to the real endpoint, and a failure shakes the card by 4px.
 */
export default function Login() {
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const controls = useAnimationControls()
  const reduce = useReducedMotion() ?? false

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api.post('/auth/login', { email, password })
      window.location.assign('/')
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 404
          ? 'Sign-in is not available yet — the authentication layer lands in M2.'
          : err instanceof ApiError
            ? err.message
            : 'Sign-in failed.'
      setError(message)
      controls.start(shakeAnimation(reduce))
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <div className="flex justify-end p-4">
        <ThemeToggle />
      </div>

      <main className="flex flex-1 items-center justify-center px-6 pb-24">
        <motion.div animate={controls} className="w-full max-w-sm space-y-8">
          <div className="space-y-3">
            <h1 className="font-sans text-lg font-medium uppercase tracking-wordmark text-ink">
              SAMAN
            </h1>
            <p className="text-sm text-muted">Standardised Asset &amp; Material Analysis Network</p>
            <p className="text-sm text-ink">One Nation, One Material Code</p>
          </div>

          <hr />

          <form onSubmit={onSubmit} className="space-y-5">
            <Field label="User" htmlFor="email" hint="Seeded demo users are listed from M2 onward.">
              <Input
                id="email"
                type="email"
                autoComplete="username"
                placeholder="steward@cpcl.in"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </Field>

            <Field label="Password" htmlFor="password" hint="All seeded demo users use “demo”.">
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

            <Button type="submit" variant="primary" className="w-full">
              Sign in
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
