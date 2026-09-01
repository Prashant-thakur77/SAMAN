import { Link } from 'react-router-dom'

import type { Role } from '../lib/api'
import { useSession } from '../lib/session'
import { Button } from './primitives/Button'
import { EmptyState } from './primitives/EmptyState'
import { PageHeader } from './PageHeader'

/**
 * Route guard (spec §0.9: "Enforce on API (dependency) and UI (route guards)").
 *
 * The API refuses the same request independently — this exists so a user is
 * told plainly why a screen is closed to them, rather than meeting a wall of
 * 403s once they are inside it.
 */
export function RequireRole({
  roles,
  children,
}: {
  roles: Role[]
  children: React.ReactNode
}) {
  const { user, loading, can } = useSession()

  if (loading) return <p className="text-sm text-muted">Checking your permissions…</p>

  if (!user) {
    return (
      <div className="space-y-8">
        <PageHeader
          section="Restricted"
          title="Sign in to continue"
          description="This screen is limited to particular roles."
        />
        <EmptyState
          title="Not signed in"
          description="Sign in with a seeded account to see this screen."
          action={
            <Link to="/login">
              <Button variant="primary">Go to sign in</Button>
            </Link>
          }
        />
      </div>
    )
  }

  if (!can(...roles)) {
    return (
      <div className="space-y-8">
        <PageHeader
          section="Restricted"
          title="Not available to your role"
          description={`This screen is limited to ${roles.join(' or ')}.`}
        />
        <EmptyState
          title={`Signed in as ${user.role}`}
          description={`Only ${roles.join(' or ')} may open this screen. The API enforces the same rule independently.`}
          action={
            <Link to="/">
              <Button variant="secondary">Back to home</Button>
            </Link>
          }
        />
      </div>
    )
  }

  return <>{children}</>
}
