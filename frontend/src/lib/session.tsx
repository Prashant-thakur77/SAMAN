/**
 * Who is signed in, shared across the shell.
 *
 * Route guards and the registrar-only actions read this. The API enforces the
 * same rules independently — the UI hiding a button is a courtesy, not the
 * boundary (spec §0.9).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, getSession, logout as apiLogout, type Role, type User } from './api'

/** The last signed-in user, kept so a phone with no signal keeps its screen. */
const LAST_USER_KEY = 'saman.session.last'

function readLastUser(): User | null {
  try {
    const raw = sessionStorage.getItem(LAST_USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

function rememberUser(user: User | null) {
  try {
    if (user) sessionStorage.setItem(LAST_USER_KEY, JSON.stringify(user))
    else sessionStorage.removeItem(LAST_USER_KEY)
  } catch {
    /* private mode: the session still works online */
  }
}

type SessionValue = {
  user: User | null
  loading: boolean
  /** The API could not be reached; `user` is the last session this tab had. */
  offline: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
  can: (...roles: Role[]) => boolean
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const [offline, setOffline] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const fresh = await getSession()
      setUser(fresh)
      rememberUser(fresh)
      setOffline(false)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        // The API is unreachable (a store with no signal, the installed Scan
        // screen): keep the last session this tab had rather than bouncing
        // the person to a sign-in that cannot be reached either. The API
        // still decides every request once the signal returns.
        setUser(readLastUser())
        setOffline(true)
      } else {
        setUser(null)
        rememberUser(null)
      }
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
    rememberUser(null)
  }, [])

  const can = useCallback(
    (...roles: Role[]) => Boolean(user && roles.includes(user.role)),
    [user],
  )

  const value = useMemo(
    () => ({ user, loading, offline, refresh, signOut, can }),
    [user, loading, offline, refresh, signOut, can],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>')
  return ctx
}
