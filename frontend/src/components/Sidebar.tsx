import { NavLink } from 'react-router-dom'

import { cn } from '../lib/cn'
import { NAV, NAV_GROUPS } from '../lib/nav'
import { useSession } from '../lib/session'
import { IconChevronLeft, IconChevronRight } from './Icons'

/**
 * Left sidebar — 240px, collapsible to a 64px icon rail (spec §1.3).
 * Hairlines only, no fills; the active item is marked by an inverse left rule
 * plus ink text rather than a background block.
 */
export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const { can, loading } = useSession()
  // Entries a role cannot open are hidden rather than shown and refused. The
  // route guard still stands behind this for anyone who types the address.
  const visible = NAV.filter((item) => !item.roles || loading || can(...item.roles))

  return (
    <aside
      className={cn(
        'sticky top-0 flex h-screen shrink-0 flex-col border-r border-hairline bg-bg',
        'transition-[width] duration-200 ease-saman',
        collapsed ? 'w-rail' : 'w-sidebar',
      )}
    >
      {/* Wordmark: SAMAN, Plex Sans, uppercase, 20px, tracking 0.18em (spec §1.2) */}
      <div className="flex h-commandbar shrink-0 items-center border-b border-hairline px-4">
        <span
          className={cn(
            'select-none font-sans text-lg font-medium uppercase tracking-wordmark text-ink',
            collapsed && 'text-sm',
          )}
        >
          {collapsed ? 'SM' : 'SAMAN'}
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto py-4" aria-label="Main">
        {NAV_GROUPS.map((group) => {
          const items = visible.filter((i) => i.group === group)
          if (items.length === 0) return null
          return (
            <div key={group} className="mb-5">
              {!collapsed && <p className="micro-label px-4 pb-2">{group}</p>}
              <ul>
                {items.map((item) => (
                  <li key={item.path}>
                    <NavLink
                      to={item.path}
                      end={item.path === '/'}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) =>
                        cn(
                          'flex h-10 items-center gap-3 border-l-2 px-4 text-sm',
                          collapsed && 'justify-center px-0',
                          isActive
                            ? 'border-inverse font-medium text-ink'
                            : 'border-transparent text-muted hover:text-ink',
                        )
                      }
                    >
                      <item.icon className="shrink-0" />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </nav>

      <div className="shrink-0 border-t border-hairline p-2">
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
