/**
 * Hand-drawn 20px line icons — no icon library (spec §9).
 * All strokes are `currentColor` at 1.5px so they read as hairlines and inherit
 * ink/muted from the surrounding text.
 */

import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function Svg({ children, ...props }: IconProps) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden
      {...props}
    >
      {children}
    </svg>
  )
}

export const IconHome = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 8.5 10 3l7 5.5V17H3V8.5Z" />
    <path d="M8 17v-5h4v5" />
  </Svg>
)

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="9" cy="9" r="5.5" />
    <path d="m13 13 4 4" />
  </Svg>
)

export const IconWorkbench = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="4" width="6" height="12" />
    <rect x="11.5" y="4" width="6" height="12" />
  </Svg>
)

export const IconChart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 17h14" />
    <path d="M5.5 17V9M10 17V4m4.5 13v-6" />
  </Svg>
)

export const IconOpportunity = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 14 8 8l3.5 3.5L17 5" />
    <path d="M13 5h4v4" />
  </Svg>
)

export const IconCopilot = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 4h14v9H8l-5 4V4Z" />
  </Svg>
)

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 13V3.5M6.5 7 10 3.5 13.5 7" />
    <path d="M3.5 13v4h13v-4" />
  </Svg>
)

export const IconMigration = (p: IconProps) => (
  <Svg {...p}>
    {/* two systems, an arrow each way: the migration is reversible */}
    <path d="M2.5 5.5h7M7 3l2.5 2.5L7 8" />
    <path d="M17.5 14.5h-7M13 12l-2.5 2.5L13 17" />
  </Svg>
)

export const IconSmartCreate = (p: IconProps) => (
  <Svg {...p}>
    {/* a new record, checked before it is written */}
    <path d="M4 3h8l4 4v10H4z" />
    <path d="M7 11.5l2 2 4-4.5" />
  </Svg>
)

export const IconRestricted = (p: IconProps) => (
  <Svg {...p}>
    {/* a closed padlock: the catalogue stays where it is */}
    <path d="M4 9h12v8H4z" />
    <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
  </Svg>
)

export const IconAudit = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 3h9l3 3v11H4V3Z" />
    <path d="M7 9h6M7 12.5h6" />
  </Svg>
)

export const IconAdmin = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10" cy="7" r="3" />
    <path d="M4 17c0-3.3 2.7-5 6-5s6 1.7 6 5" />
  </Svg>
)

export const IconSun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="3.5" />
    <path d="M10 2v2m0 12v2M2 10h2m12 0h2M4.7 4.7l1.4 1.4m7.8 7.8 1.4 1.4m0-10.6-1.4 1.4M6.1 13.9l-1.4 1.4" />
  </Svg>
)

export const IconMoon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M16 11.5A6.5 6.5 0 0 1 8.5 4a6.5 6.5 0 1 0 7.5 7.5Z" />
  </Svg>
)

export const IconChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="m12 4-5 6 5 6" />
  </Svg>
)

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="m8 4 5 6-5 6" />
  </Svg>
)

/** Two materials that can stand in for each other: opposed arrows. */
export const IconSubstitute = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 7h12m0 0-3-3m3 3-3 3" />
    <path d="M17 13H5m0 0 3-3m-3 3 3 3" />
  </Svg>
)

/** Hamburger: opens the navigation drawer on a narrow screen. */
export const IconMenu = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 5h14M3 10h14M3 15h14" />
  </Svg>
)

/** Close: dismisses the navigation drawer. */
export const IconClose = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 5l10 10M15 5L5 15" />
  </Svg>
)
