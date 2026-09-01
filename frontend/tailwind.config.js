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
