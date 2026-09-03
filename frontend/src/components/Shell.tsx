import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

import { useHealth } from '../lib/useHealth'

import { CommandBar } from './CommandBar'
import { Assistant } from './Assistant'
import { CommandPalette } from './CommandPalette'
import { RouteAnnouncer } from './RouteAnnouncer'
import { Sidebar } from './Sidebar'
import { Button } from './primitives/Button'
import { EmptyState } from './primitives/EmptyState'

const COLLAPSE_KEY = 'saman.sidebar.collapsed'

/**
 * Application shell (spec §1.3): sidebar + command bar + content column capped
 * at the 1280px content width. Owns the ⌘K binding for the whole app.
 */
export function Shell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch {
      return false
    }
  })
  const [paletteOpen, setPaletteOpen] = useState(false)
  // Below lg the sidebar is a drawer rather than a column; this is whether it
  // is out. Closed on every navigation, because a drawer that stays open over
  // the page you just asked for is a drawer in the way.
  const [navOpen, setNavOpen] = useState(false)
  const { unreachable } = useHealth()
  const location = useLocation()

  const toggleSidebar = useCallback(() => {
    setCollapsed((c) => {
      const next = !c
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0')
      } catch {
        /* not persisting is survivable */
      }
      return next
    })
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      }
      if (e.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => setNavOpen(false), [location.pathname])

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      {/* Twelve sidebar links stand between the keyboard and the page on every
          route; this is the way past them. Visible only while focused. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-hairline focus:bg-bg focus:px-4 focus:py-2 focus:text-sm focus:text-ink"
      >
        Skip to content
      </a>
      <RouteAnnouncer />
      {/* The drawer's backdrop: it dims the page it is covering and is the
          obvious way back out of it. Nothing below lg, nothing on desktop. */}
      {navOpen && (
        // A scrim, not a control: the drawer's own close button and Escape are
        // the accessible ways out, so this stays out of the a11y tree rather
        // than becoming a second thing called "Close navigation".
        <div
          aria-hidden
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-30 bg-ink/40 lg:hidden"
        />
      )}
      <Sidebar
        collapsed={collapsed}
        onToggle={toggleSidebar}
        open={navOpen}
        onClose={() => setNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <CommandBar onOpenPalette={() => setPaletteOpen(true)} onOpenNav={() => setNavOpen(true)} />
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 px-4 py-6 focus-visible:outline-none sm:px-6 sm:py-8"
        >
          <div className="mx-auto w-full max-w-content">
            {/* A blank content column is not a crash, but it is not an
                explanation either. With the API down every screen renders
                nothing at all, so say why once here rather than sixteen times
                in sixteen routes (spec §8A). */}
            {unreachable ? (
              <EmptyState
                title="SAMAN cannot reach its API"
                description="Every screen needs the backend on :8000. Start it with `make dev`, or `docker compose up` for both services, then reload. Nothing has been lost; the database is on disk."
                action={
                  <Button variant="primary" onClick={() => window.location.reload()}>
                    Reload
                  </Button>
                }
              />
            ) : (
              children
            )}
          </div>
        </main>
        <footer className="border-t border-hairline px-4 py-4 sm:px-6">
          <p className="mx-auto max-w-content text-xs text-muted">
            SAMAN · Standardised Asset &amp; Material Analysis Network · issues the CNMC
          </p>
        </footer>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Assistant />
    </div>
  )
}
