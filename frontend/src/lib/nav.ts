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
  IconMigration,
  IconOpportunity,
  IconRestricted,
  IconSearch,
  IconSmartCreate,
  IconSubstitute,
  IconUpload,
  IconWorkbench,
} from '../components/Icons'

export type Role =
  | 'registrar'
  | 'admin'
  | 'approver'
  | 'steward'
  | 'engineer'
  | 'auditor'
  | 'viewer'

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
    label: 'Substitutes',
    path: '/substitutes',
    icon: IconSubstitute,
    group: 'Review',
    // Everyone may read the queue; only an engineer, registrar or admin signs.
    roles: null,
  },

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

  {
    label: 'Smart-Create',
    path: '/smart-create',
    icon: IconSmartCreate,
    group: 'Tools',
    roles: ['registrar', 'admin', 'approver', 'steward'],
  },
  {
    label: 'Restricted mode',
    path: '/pprl',
    icon: IconRestricted,
    group: 'Tools',
    roles: ['registrar', 'admin', 'approver', 'steward', 'auditor'],
  },
  { label: 'Copilot', path: '/copilot', icon: IconCopilot, group: 'Tools', roles: null },
  { label: 'Onboard', path: '/onboard', icon: IconUpload, group: 'Tools', roles: null },
  {
    label: 'Migration',
    path: '/migration',
    icon: IconMigration,
    group: 'Tools',
    // Visible to all: a steward may inspect the plan, but the apply and
    // rollback controls and other CPSEs' valuations are withheld.
    roles: null,
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
