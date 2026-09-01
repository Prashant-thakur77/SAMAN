import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { CommandBar } from './CommandBar'
import { CommandPalette } from './CommandPalette'
import { RouteAnnouncer } from './RouteAnnouncer'
import { Sidebar } from './Sidebar'

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
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

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
      <Sidebar collapsed={collapsed} onToggle={toggleSidebar} />
      <div className="flex min-w-0 flex-1 flex-col">
        <CommandBar onOpenPalette={() => setPaletteOpen(true)} />
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 px-6 py-8 focus-visible:outline-none"
        >
          <div className="mx-auto w-full max-w-content">{children}</div>
        </main>
        <footer className="border-t border-hairline px-6 py-4">
          <p className="mx-auto max-w-content text-xs text-muted">
            SAMAN · Standardised Asset &amp; Material Analysis Network — issues the CNMC.
          </p>
        </footer>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
