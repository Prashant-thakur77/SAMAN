import { useReducedMotion } from 'framer-motion'
import { useId } from 'react'
import { useNavigate } from 'react-router-dom'

import { useMeasured } from './ChartParts'
import { RAMP, type Shade } from './ramp'

/**
 * Horizontal bars, hand-drawn.
 *
 * One primitive under every bar chart on the executive page, so the marks are
 * the same everywhere: bars 20 px thick grown from one baseline at zero, a
 * 4 px rounded data end and a square baseline end, a 2 px gap of the surface
 * between stacked segments, solid hairline grid and axis, ticks at clean
 * numbers, the value at the tip and never inside a segment. Recharts would
 * fight every one of those; a hundred lines of SVG do not.
 *
 * Layout is in real pixels from a measured width. Wide enough, the row label
 * sits left of its bar; at phone width the label moves above the bar and
 * wraps, so neither is ever clipped. The whole row band is the hover target
 * and carries the tooltip; the table twin beside the chart is the equivalent
 * for everyone who does not hover.
 */

export type BarSegment = { key: string; value: number; shade: Shade }

export type BarRow = {
  key: string
  /** Mono, ink. */
  label: string
  /** Mono, muted, beside the label (a family prefix). */
  labelNote?: string
  /** Mono, muted, under the label — or at the row's right end at phone width. */
  sublabel?: string
  segments: BarSegment[]
  /** Ink, at the bar tip (at the row end in percent mode). */
  tip?: string
  /** Muted, after the tip. */
  tipNote?: string
  /** The tooltip for the whole row band. */
  title: string
  /** A 1.5 px ink line with 6 px end ticks across a range of the value axis. */
  whisker?: { from: number; to: number }
  /** Where the row opens: the rows behind the bar. The whole band is the target. */
  href?: string
}

/** A solid hairline across the plot after a row, with a short label above it. */
export type BarRule = { afterRow: number; label: string; sublabel?: string }

const BAR = 20
const GAP = 2
const RADIUS = 4
const FONT = 11
const LINE = 14
const CH = FONT * 0.6 // IBM Plex Mono advances 0.6 em per glyph
const ROW_GAP = 14
const AXIS_H = 22
const PAD_TOP = 4
const LABEL_PAD = 16
const TIP_PAD = 8
const MIN_PLOT = 150

const textW = (s: string | undefined) => (s ? s.length * CH : 0)

/** Greedy word wrap by the mono advance; a word longer than a line stands alone. */
function wrap(text: string, maxWidth: number): string[] {
  const words = text.split(' ')
  const lines: string[] = []
  let line = ''
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word
    if (textW(candidate) <= maxWidth || !line) line = candidate
    else {
      lines.push(line)
      line = word
    }
  }
  if (line) lines.push(line)
  return lines
}

/** A bar with a rounded data end and a square baseline end. */
function barPath(x: number, y: number, w: number, h: number, rounded: boolean): string {
  if (!rounded) return `M${x},${y} h${w} v${h} h${-w} Z`
  const r = Math.min(RADIUS, w, h / 2)
  const straight = w - r
  return [
    `M${x},${y}`,
    `h${straight}`,
    `a${r},${r} 0 0 1 ${r},${r}`,
    `v${h - 2 * r}`,
    `a${r},${r} 0 0 1 ${-r},${r}`,
    `h${-straight}`,
    'Z',
  ].join(' ')
}

/** One line of the label block: ink text, an optional muted tail, and an
 *  optional right-aligned end (ink `endInk` followed by muted `end`). */
type TextLine = { text: string; note?: string; endInk?: string; end?: string }

export function BarRows({
  rows,
  ticks,
  formatTick,
  percent = false,
  rules = [],
  axisTitle,
  ariaLabel,
  fallbackWidth = 640,
}: {
  rows: BarRow[]
  /** Clean tick values on the value axis; the domain extends to cover the data. */
  ticks: number[]
  formatTick: (v: number) => string
  /** Every row normalised to its own total; the axis reads 0–100%. */
  percent?: boolean
  rules?: BarRule[]
  /** Unit of the value axis, centred beneath the ticks. */
  axisTitle?: string
  ariaLabel: string
  fallbackWidth?: number
}) {
  const navigate = useNavigate()
  const reduce = useReducedMotion() ?? false
  const clipId = useId()
  const { ref, width } = useMeasured<HTMLDivElement>(fallbackWidth)

  // --- columns -------------------------------------------------------------
  const labelLine = (row: BarRow) => row.label + (row.labelNote ? ` ${row.labelNote}` : '')
  const tipLine = (row: BarRow) => (row.tip ?? '') + (row.tipNote ? ` ${row.tipNote}` : '')
  const widestLabel = Math.max(0, ...rows.map((r) => Math.max(textW(labelLine(r)), textW(r.sublabel))))
  const tipNeeded = Math.max(0, ...rows.map((r) => textW(tipLine(r)))) + (rows.some((r) => r.tip) ? TIP_PAD : 0)
  let labelW = widestLabel + LABEL_PAD
  const stacked = labelW > width * 0.42 || width - labelW - tipNeeded < MIN_PLOT
  if (stacked) labelW = 0
  // Stacked, the tip column may not starve the plot: a tip that then no longer
  // fits beside its bar moves to the right end of the row's label line.
  const tipW = stacked ? Math.min(tipNeeded, width * 0.45) : tipNeeded
  const x0 = labelW
  const plotW = Math.max(40, width - labelW - tipW)
  const xEnd = x0 + plotW

  // --- scale ---------------------------------------------------------------
  const totals = rows.map((r) => r.segments.reduce((s, seg) => s + Math.max(0, seg.value), 0))
  const whiskerMax = Math.max(0, ...rows.map((r) => r.whisker?.to ?? 0))
  const domain = percent ? 100 : Math.max(...ticks, ...totals, whiskerMax, 1)
  const scale = (v: number) => x0 + (v / domain) * plotW
  const tickValues = percent ? [0, 25, 50, 75, 100] : ticks.filter((t) => t <= domain + 1e-9)
  const tickLabel = (t: number) => (percent ? `${t}%` : formatTick(t))
  // At phone width the labels would collide; keep every grid line and label
  // every n-th tick, so the ticks still read as clean numbers.
  const tickSpacing = tickValues.length > 1 ? plotW / (tickValues.length - 1) : plotW
  const labelEvery = Math.max(
    1,
    Math.ceil((Math.max(...tickValues.map((t) => textW(tickLabel(t)))) + 10) / tickSpacing),
  )

  // --- rows ----------------------------------------------------------------
  const barEndOf = (i: number) => (percent ? xEnd : scale(totals[i]))
  const tipXOf = (row: BarRow, i: number) =>
    Math.max(barEndOf(i), row.whisker ? scale(row.whisker.to) + 4 : 0) + TIP_PAD
  const tipFits = (row: BarRow, i: number) => !stacked || tipXOf(row, i) + textW(tipLine(row)) <= width + 0.5

  // Inline: the label (and its sublabel beneath) in a column left of the bar.
  // Stacked: the label wraps across the full width above the bar; the
  // sublabel (and a tip that does not fit beside its bar) ride the last line
  // when there is room, or take a line of their own.
  const textLinesFor = (row: BarRow, i: number): TextLine[] => {
    if (!stacked) {
      const lines: TextLine[] = [{ text: row.label, note: row.labelNote }]
      if (row.sublabel) lines.push({ text: '', note: row.sublabel })
      return lines
    }
    const lines: TextLine[] = wrap(row.label, width).map((text) => ({ text }))
    const last = lines[lines.length - 1]
    if (row.labelNote) {
      if (textW(`${last.text} ${row.labelNote}`) <= width) last.note = row.labelNote
      else lines.push({ text: '', note: row.labelNote })
    }
    const placeAtEnd = (endInk: string | undefined, end: string | undefined) => {
      const tail = lines[lines.length - 1]
      const used = textW(tail.text) + (tail.note ? textW(` ${tail.note}`) : 0)
      const needed = textW(endInk) + (endInk && end ? CH : 0) + textW(end)
      if (!tail.end && !tail.endInk && used + LABEL_PAD + needed <= width) {
        tail.endInk = endInk
        tail.end = end
      } else if (endInk) lines.push({ text: '', endInk, end }) // a tip keeps the right end
      else lines.push({ text: '', note: end }) // a sublabel sits under the label
    }
    if (row.sublabel) placeAtEnd(undefined, row.sublabel)
    if (row.tip && !tipFits(row, i)) placeAtEnd(row.tip, row.tipNote)
    return lines
  }
  const inlineLines = Math.max(1, ...rows.map((r) => (r.sublabel ? 2 : 1)))
  const ruleAfter = new Map(rules.map((rule) => [rule.afterRow, rule]))
  const ruleTwoLine = (rule: BarRule) =>
    !!rule.sublabel && textW(`${rule.label}: ${rule.sublabel}`) > (stacked ? width : plotW + tipW)
  const ruleH = (rule: BarRule) => (ruleTwoLine(rule) ? 2 * LINE + 8 : LINE + 8)

  let cursor = PAD_TOP
  const layout = rows.map((row, i) => {
    const lines = textLinesFor(row, i)
    const rowH = stacked ? lines.length * LINE + 4 + BAR : Math.max(BAR, inlineLines * LINE)
    const top = cursor
    cursor += rowH + ROW_GAP
    const rule = ruleAfter.get(i)
    if (rule) cursor += ruleH(rule)
    const barY = stacked ? top + lines.length * LINE + 4 : top + (rowH - BAR) / 2
    // The rule sits at the foot of the extra space after its row, its label above it.
    return { row, lines, rowH, top, barY, rule, ruleY: rule ? top + rowH + ROW_GAP / 2 + ruleH(rule) : null }
  })
  const rowsBottom = cursor - ROW_GAP + ROW_GAP / 2
  const height = rowsBottom + AXIS_H + (axisTitle ? LINE : 0)
  const ruleX = stacked ? 0 : x0

  return (
    <div ref={ref} className="w-full">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        className="block overflow-visible"
      >
        <defs>
          <clipPath id={clipId}>
            <rect
              x={x0}
              y={0}
              width={plotW + tipW}
              height={height}
              className={reduce ? undefined : 'chart-reveal'}
              style={{ transformOrigin: `${x0}px 0px` }}
            />
          </clipPath>
        </defs>

        {/* grid: solid hairlines at every tick, the axis line at zero */}
        {tickValues.map((t) => (
          <line
            key={`grid-${t}`}
            x1={scale(t)}
            x2={scale(t)}
            y1={PAD_TOP}
            y2={rowsBottom}
            className="stroke-hairline"
            strokeWidth={1}
            shapeRendering="crispEdges"
          />
        ))}

        {layout.map(({ row, lines, rowH, top, barY, rule, ruleY }, i) => {
          const total = totals[i]
          const painted = row.segments.filter((seg) => seg.value > 0)
          const last = painted.length - 1
          const norm = (v: number) => (percent ? (total ? (v / total) * 100 : 0) : v)
          let cum = 0
          const segments = painted.map((seg, j) => {
            const start = scale(norm(cum))
            cum += seg.value
            const end = scale(norm(cum))
            const x = j === 0 ? start : start + GAP
            const w = end - x
            return { seg, x, w, rounded: j === last }
          })
          const barEnd = barEndOf(i)
          const whisker = row.whisker
          const tipX = tipXOf(row, i)
          const yc = barY + BAR / 2
          // Inline, a single label line centres on the bar; two lines start at the top.
          const firstLineY = stacked || lines.length > 1 ? top + LINE / 2 : top + rowH / 2
          return (
            <g
              key={row.key}
              className={row.href ? 'chart-row cursor-pointer' : 'chart-row'}
              onClick={row.href ? () => navigate(row.href!) : undefined}
            >
              <title>{row.href ? `${row.title} — open the rows` : row.title}</title>
              {/* the hit target is the whole row band, not the thin mark */}
              <rect
                x={0}
                y={top - ROW_GAP / 2}
                width={width}
                height={rowH + ROW_GAP}
                className="chart-band"
                fill="transparent"
              />

              {lines.map((line, n) => (
                <g key={n}>
                  <text
                    x={0}
                    y={firstLineY + n * LINE}
                    dominantBaseline="central"
                    className="fill-ink font-mono text-[11px]"
                  >
                    {line.text}
                    {line.note && (
                      <tspan className="fill-muted" dx={line.text ? CH : 0}>
                        {line.note}
                      </tspan>
                    )}
                  </text>
                  {(line.end || line.endInk) && (
                    <text
                      x={width}
                      y={firstLineY + n * LINE}
                      dominantBaseline="central"
                      textAnchor="end"
                      className="fill-ink font-mono text-[11px] tabular-nums"
                    >
                      {line.endInk}
                      {line.end && (
                        <tspan className="fill-muted" dx={line.endInk ? CH : 0}>
                          {line.end}
                        </tspan>
                      )}
                    </text>
                  )}
                </g>
              ))}

              <g clipPath={`url(#${clipId})`}>
                {segments.map(({ seg, x, w, rounded }) =>
                  w > 0.5 ? (
                    <path
                      key={seg.key}
                      d={barPath(x, barY, w, BAR, rounded)}
                      fill={RAMP[seg.shade]}
                      className="chart-bar"
                    />
                  ) : null,
                )}
                {whisker && (
                  <g>
                    {/* one 1.5 px line with 6 px end ticks: ink beyond the bar, and the
                        surface colour where it crosses the bar, so it stays one thin mark */}
                    <line x1={scale(whisker.from)} x2={scale(whisker.to)} y1={yc} y2={yc} stroke={RAMP[0]} strokeWidth={1.5} />
                    <line x1={scale(whisker.from)} x2={scale(whisker.from)} y1={yc - 3} y2={yc + 3} stroke={RAMP[0]} strokeWidth={1.5} />
                    <line x1={scale(whisker.to)} x2={scale(whisker.to)} y1={yc - 3} y2={yc + 3} stroke={RAMP[0]} strokeWidth={1.5} />
                    {scale(whisker.from) < barEnd && (
                      <>
                        <line
                          x1={scale(whisker.from)}
                          x2={Math.min(scale(whisker.to), barEnd)}
                          y1={yc}
                          y2={yc}
                          className="stroke-surface"
                          strokeWidth={1.5}
                        />
                        <line
                          x1={scale(whisker.from)}
                          x2={scale(whisker.from)}
                          y1={yc - 3}
                          y2={yc + 3}
                          className="stroke-surface"
                          strokeWidth={1.5}
                        />
                      </>
                    )}
                  </g>
                )}
                {row.tip && (total > 0 || !percent) && tipFits(row, i) && (
                  <text
                    x={tipX}
                    y={yc}
                    dominantBaseline="central"
                    className="fill-ink font-mono text-[11px] tabular-nums"
                  >
                    {row.tip}
                    {row.tipNote && (
                      <tspan className="fill-muted" dx={CH}>
                        {row.tipNote}
                      </tspan>
                    )}
                  </text>
                )}
              </g>

              {rule && ruleY !== null && (
                <g aria-hidden>
                  <line
                    x1={ruleX}
                    x2={width}
                    y1={ruleY}
                    y2={ruleY}
                    className="stroke-muted"
                    strokeWidth={1}
                    shapeRendering="crispEdges"
                  />
                  <text x={ruleX} y={ruleY - 8} className="fill-muted font-mono text-[11px]">
                    {ruleTwoLine(rule) ? (
                      <>
                        <tspan x={ruleX} dy={-LINE}>
                          {rule.label}
                        </tspan>
                        <tspan x={ruleX} dy={LINE}>
                          {rule.sublabel}
                        </tspan>
                      </>
                    ) : rule.sublabel ? (
                      `${rule.label}: ${rule.sublabel}`
                    ) : (
                      rule.label
                    )}
                  </text>
                </g>
              )}
            </g>
          )
        })}

        {/* axis: the baseline, tick labels at clean numbers, the unit beneath */}
        <line x1={x0} x2={x0} y1={PAD_TOP} y2={rowsBottom} className="stroke-hairline" strokeWidth={1} shapeRendering="crispEdges" />
        <line x1={x0} x2={xEnd} y1={rowsBottom} y2={rowsBottom} className="stroke-hairline" strokeWidth={1} shapeRendering="crispEdges" />
        {tickValues.map((t, i) => {
          if (i % labelEvery !== 0) return null
          const x = scale(t)
          const atEnd = Math.abs(x - xEnd) < 1
          const anchor = i === 0 ? 'start' : atEnd ? 'end' : 'middle'
          return (
            <text
              key={`tick-${t}`}
              x={x}
              y={rowsBottom + AXIS_H - 4}
              textAnchor={anchor}
              className="fill-muted font-mono text-[11px] tabular-nums"
            >
              {tickLabel(t)}
            </text>
          )
        })}
        {axisTitle && (
          <text
            x={x0 + plotW / 2}
            y={rowsBottom + AXIS_H + LINE - 4}
            textAnchor="middle"
            className="fill-muted font-mono text-[11px]"
          >
            {axisTitle}
          </text>
        )}
      </svg>
    </div>
  )
}
