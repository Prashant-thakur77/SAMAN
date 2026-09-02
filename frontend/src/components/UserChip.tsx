import { Link, useNavigate } from 'react-router-dom'

import { useSession } from '../lib/session'

/**
 * Command-bar identity (spec §1.3). Reads the shared session so the whole shell
 * agrees on who is signed in. Never invents a user (spec §10).
 */
export function UserChip() {
  const { user, loading, signOut } = useSession()
  const navigate = useNavigate()

  if (loading) return <span className="micro-label">…</span>

  if (!user) {
    return (
      <Link
        to="/login"
        className="flex h-8 items-center rounded-full border border-hairline bg-surface px-3 text-xs text-muted hover:text-ink"
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
          await signOut()
          navigate('/login')
        }}
        className="flex h-8 items-center rounded-full border border-hairline bg-surface px-3 text-xs text-muted hover:text-ink"
      >
        Sign out
      </button>
    </div>
  )
}
