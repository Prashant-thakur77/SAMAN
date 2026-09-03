import { NavLink } from 'react-router-dom'

import { cn } from '../lib/cn'
import { NAV, NAV_GROUPS } from '../lib/nav'
import { useSession } from '../lib/session'
import { IconChevronLeft, IconChevronRight, IconClose } from './Icons'

/**
 * Left sidebar — 240px, collapsible to a 64px icon rail (spec §1.3).
 * Hairlines only, no fills; the active item is marked by an inverse left rule
 * plus ink text rather than a background block.
 *
 * Below `lg` there is no room for a permanent 240px column beside the content,
 * so the same markup becomes an off-canvas drawer: slid out of frame until the
 * command bar's menu button opens it, over a backdrop, and closed again by the
 * next navigation. `collapsed` is a desktop idea only — the rail would be a
 * worse drawer than the full list — so every label stays in the DOM and is
 * hidden with `lg:hidden` rather than by a branch, which keeps the drawer
 * readable whatever the desktop was last left at.
 */
export function Sidebar({
  collapsed,
  onToggle,
  open,
  onClose,
}: {
  collapsed: boolean
  onToggle: () => void
  open: boolean
  onClose: () => void
}) {
  const { can, loading } = useSession()
  // Entries a role cannot open are hidden rather than shown and refused. The
  // route guard still stands behind this for anyone who types the address.
  const visible = NAV.filter((item) => !item.roles || loading || can(...item.roles))

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-40 flex h-screen w-sidebar shrink-0 flex-col',
        'border-r border-hairline bg-surface',
        'transition-[transform,visibility] duration-200 ease-saman',
        // `invisible` rather than only a transform: an off-screen drawer that
        // is merely translated still takes keyboard focus and is still read
        // out, so tabbing from a phone's command bar would walk twelve links
        // nobody can see. Visibility is also the one way to say this per
        // breakpoint without asking JavaScript how wide the window is.
        open ? 'visible translate-x-0' : 'invisible -translate-x-full',
        // From lg it is a column in the flow again, always on screen, and the
        // rail width returns.
        'lg:visible lg:sticky lg:inset-y-auto lg:top-0 lg:z-auto lg:translate-x-0',
        'lg:transition-[width]',
        collapsed ? 'lg:w-rail' : 'lg:w-sidebar',
      )}
    >
      {/* Wordmark: SAMAN, Plex Sans, uppercase, 20px, tracking 0.18em (spec §1.2) */}
      <div className="flex h-commandbar shrink-0 items-center gap-2 border-b border-hairline px-4">
        {/* The wordmark is the way back to the front page from anywhere. */}
        <NavLink
          to="/welcome"
          title="SAMAN front page"
          className={cn(
            'select-none font-sans font-medium uppercase tracking-wordmark text-ink hover:text-accent',
            'text-lg',
            collapsed && 'lg:text-sm',
          )}
        >
          <span className={cn(collapsed && 'lg:hidden')}>SAMAN</span>
          <span className={cn('hidden', collapsed && 'lg:inline')}>SM</span>
        </NavLink>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close navigation"
          className="ml-auto flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:text-ink lg:hidden"
        >
          <IconClose />
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto py-4" aria-label="Main">
        {NAV_GROUPS.map((group) => {
          const items = visible.filter((i) => i.group === group)
          if (items.length === 0) return null
          return (
            <div key={group} className="mb-5">
              <p className={cn('micro-label px-4 pb-2', collapsed && 'lg:hidden')}>{group}</p>
              <ul>
                {items.map((item) => (
                  <li key={item.path}>
                    <NavLink
                      to={item.path}
                      end={item.path === '/'}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) =>
                        cn(
                          'mx-2 flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors duration-150',
                          collapsed && 'lg:justify-center lg:px-0',
                          isActive
                            ? 'bg-accent-soft font-medium text-accent'
                            : 'text-muted hover:bg-surface hover:text-ink',
                        )
                      }
                    >
                      <item.icon className="shrink-0" />
                      <span className={cn('truncate', collapsed && 'lg:hidden')}>{item.label}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </nav>

      {/* Collapsing to the rail is a desktop affordance; the drawer closes. */}
      <div className="hidden shrink-0 border-t border-hairline p-2 lg:block">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="flex h-8 w-full items-center justify-center text-muted hover:text-ink"
        >
          {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
        </button>
      </div>
    </aside>
  )
}
