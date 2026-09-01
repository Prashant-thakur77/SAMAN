/**
 * Single source of truth for navigation — consumed by the sidebar and the ⌘K
 * command palette so the two can never drift apart.
 *
 * `roles: null` means every signed-in role may see the entry. Route guards
 * enforce this for real on the API side (spec §0.9); M4/M7 wire the UI guards.
 */

import type { ComponentType, SVGProps } from 'react'

import {
  IconAdmin,
  IconAudit,
  IconChart,
  IconCopilot,
  IconHome,
  IconOpportunity,
  IconSearch,
  IconUpload,
  IconWorkbench,
} from '../components/Icons'

export type Role = 'registrar' | 'admin' | 'approver' | 'steward' | 'auditor' | 'viewer'

export type NavItem = {
  label: string
  path: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
  group: string
  /** null = visible to all roles */
  roles: Role[] | null
}

export const NAV: NavItem[] = [
  { label: 'Home', path: '/', icon: IconHome, group: 'Overview', roles: null },
  { label: 'Search', path: '/search', icon: IconSearch, group: 'Overview', roles: null },

  { label: 'Workbench', path: '/workbench', icon: IconWorkbench, group: 'Review', roles: null },

  {
    label: 'Executive',
    path: '/dashboard/executive',
    icon: IconChart,
    group: 'Analytics',
    roles: null,
  },
  {
    label: 'Opportunity',
    path: '/dashboard/opportunity',
    icon: IconOpportunity,
    group: 'Analytics',
    roles: null,
  },

  { label: 'Copilot', path: '/copilot', icon: IconCopilot, group: 'Tools', roles: null },
  { label: 'Onboard', path: '/onboard', icon: IconUpload, group: 'Tools', roles: null },
  {
    label: 'Migration',
    path: '/migration',
    icon: IconUpload,
    group: 'Tools',
    roles: ['registrar', 'admin'],
  },

  { label: 'Audit', path: '/audit', icon: IconAudit, group: 'Governance', roles: null },
  {
    label: 'Admin',
    path: '/admin',
    icon: IconAdmin,
    group: 'Governance',
    roles: ['registrar', 'admin'],
  },
]

export const NAV_GROUPS = ['Overview', 'Review', 'Analytics', 'Tools', 'Governance'] as const
