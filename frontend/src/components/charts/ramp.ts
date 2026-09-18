/**
 * The one ramp every chart on the executive page draws with.
 *
 * Ink at 100%, 62% and 34% over the page: the three steps HarmonisationDonut
 * validated (ΔE 23 apart for every kind of colour vision, monotone lightness,
 * the lightest step at 2.5:1 against the page — under 3:1, which is why every
 * chart that uses more than one step also carries a legend and a table twin).
 * §1.1 keeps the surface monochrome; the two semantic tones are for status
 * text only and never appear in a mark.
 */
export const RAMP = ['rgb(var(--ink))', 'rgb(var(--ink) / 0.62)', 'rgb(var(--ink) / 0.34)'] as const

/** Index into RAMP: 0 = full ink, 1 = 62%, 2 = 34%. */
export type Shade = 0 | 1 | 2
