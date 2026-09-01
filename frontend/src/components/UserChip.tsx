import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { getSession, logout, type User } from '../lib/api'

/**
 * Command-bar identity (spec §1.3). Shows the signed-in user and role, or a
 * sign-in link. Never invents a user: a signed-out or unreachable backend
 * simply renders the link (spec §10).
 */
export function UserChip() {
  const [user, setUser] = useState<User | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let alive = true
    getSession()
      .then((u) => alive && setUser(u))
      .catch(() => alive && setUser(null))
    return () => {
      alive = false
    }
  }, [])

  if (!user) {
    return (
      <Link
        to="/login"
        className="flex h-8 items-center border border-hairline px-3 text-xs text-muted hover:text-ink"
      >
        Sign in
      </Link>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <div className="hidden text-right sm:block">
        <p className="text-xs leading-tight text-ink">{user.name}</p>
        <p className="micro-label leading-tight">
          {user.role}
          {user.cpse_code ? ` · ${user.cpse_code}` : ''}
        </p>
      </div>
      <button
        type="button"
        onClick={async () => {
          await logout().catch(() => undefined)
          setUser(null)
          navigate('/login')
        }}
        className="flex h-8 items-center border border-hairline px-3 text-xs text-muted hover:text-ink"
      >
        Sign out
      </button>
    </div>
  )
}
