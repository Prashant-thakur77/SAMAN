/**
 * Chart chrome shared by the dashboards.
 *
 * Monochrome by mandate (spec §1.1: no colour beyond the two semantic tones,
 * and never as a large fill). Series are separated by weight and dash rather
 * than by hue, which also keeps them legible in both themes and to a
 * colour-blind reader. Grid lines are hairlines only.
 */
export const CHART_INK = 'rgb(var(--ink))'
export const CHART_MUTED = 'rgb(var(--muted))'
export const CHART_HAIRLINE = 'rgb(var(--hairline))'

export const AXIS_PROPS = {
  stroke: CHART_HAIRLINE,
  tick: { fill: CHART_MUTED, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART_HAIRLINE },
} as const

export const GRID_PROPS = {
  stroke: CHART_HAIRLINE,
  strokeDasharray: '0',
  vertical: false,
} as const

export const TOOLTIP_PROPS = {
  contentStyle: {
    background: 'rgb(var(--bg))',
    border: '1px solid rgb(var(--hairline))',
    borderRadius: 0,
    fontSize: 12,
    fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
  },
  labelStyle: { color: CHART_MUTED },
  itemStyle: { color: CHART_INK },
  cursor: { stroke: CHART_HAIRLINE },
} as const
