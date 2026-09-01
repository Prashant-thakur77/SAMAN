/**
 * Who is signed in, shared across the shell.
 *
 * Route guards and the registrar-only actions read this. The API enforces the
 * same rules independently — the UI hiding a button is a courtesy, not the
 * boundary (spec §0.9).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { getSession, logout as apiLogout, type Role, type User } from './api'

type SessionValue = {
  user: User | null
  loading: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
  can: (...roles: Role[]) => boolean
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await getSession())
    } catch {
      // Signed out, or the backend is unreachable. Both render as signed out.
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const signOut = useCallback(async () => {
    await apiLogout().catch(() => undefined)
    setUser(null)
  }, [])

  const can = useCallback(
    (...roles: Role[]) => Boolean(user && roles.includes(user.role)),
    [user],
  )

  const value = useMemo(
    () => ({ user, loading, refresh, signOut, can }),
    [user, loading, refresh, signOut, can],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>')
  return ctx
}
