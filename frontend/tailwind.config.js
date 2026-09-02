/** @type {import('tailwindcss').Config} */
// SAMAN — spec §1. Monochrome, typography-first. Tokens live in
// src/styles/tokens.css and are surfaced here as the ONLY available colours,
// so an accidental `text-blue-500` simply does not exist (spec §9).
const withAlpha = (v) => `rgb(var(${v}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    // `colors` (not `extend.colors`) — Tailwind's default palette is dropped.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      bg: withAlpha('--bg'),
      surface: withAlpha('--surface'),
      ink: withAlpha('--ink'),
      muted: withAlpha('--muted'),
      hairline: withAlpha('--hairline'),
      inverse: withAlpha('--inverse'),
      ok: withAlpha('--ok'),
      danger: withAlpha('--danger'),
      // Front page only (see .landing in tokens.css). Outside it these
      // resolve to muted, so a stray use is dull rather than broken.
      earth: withAlpha('--earth'),
      forest: withAlpha('--forest'),
    },
    // Fixed scale, spec §1.3: 12 / 14 / 16 / 20 / 28 / 40 (+ 11px micro-label).
    fontSize: {
      micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.08em' }],
      xs: ['0.75rem', { lineHeight: '1rem' }],
      sm: ['0.875rem', { lineHeight: '1.25rem' }],
      base: ['1rem', { lineHeight: '1.5rem' }],
      lg: ['1.25rem', { lineHeight: '1.75rem' }],
      xl: ['1.75rem', { lineHeight: '2.125rem' }],
      '2xl': ['2.5rem', { lineHeight: '2.875rem' }],
      // Editorial sizes for the public front page only. The fixed scale above
      // is what every application screen uses and is deliberately small; a
      // landing page is read at arm's length by somebody who has not decided
      // to care yet, and needs the room. They fluid-scale so the same page
      // holds together from a phone to a projector.
      lead: ['clamp(1.0625rem, 1.4vw, 1.375rem)', { lineHeight: '1.65' }],
      headline: ['clamp(1.75rem, 3.4vw, 2.75rem)', { lineHeight: '1.12', letterSpacing: '-0.02em' }],
      display: ['clamp(2.75rem, 7vw, 5.5rem)', { lineHeight: '0.98', letterSpacing: '-0.035em' }],
    },
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      borderColor: { DEFAULT: 'rgb(var(--hairline))' },
      maxWidth: { content: 'var(--content-max)' },
      spacing: {
        sidebar: 'var(--sidebar-w)',
        rail: 'var(--sidebar-rail-w)',
        commandbar: 'var(--commandbar-h)',
        row: 'var(--row-h)',
      },
      letterSpacing: { wordmark: '0.18em' },
      transitionTimingFunction: { saman: 'cubic-bezier(0.22, 1, 0.36, 1)' },
      // Only overlays get elevation (spec §1.1).
      boxShadow: { sm: '0 1px 2px 0 rgb(0 0 0 / 0.06)' },
    },
  },
  plugins: [],
}
