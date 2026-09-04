import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import type { ExecutiveDashboard } from '../../lib/api'

/**
 * Where the estate stands, as three disjoint parts of one whole.
 *
 * A single-hue ramp rather than three colours: the parts are ordered — through
 * the process, waiting with a duplicate found, waiting without one — and §1.1
 * keeps this surface monochrome, the same grayscale the class heatmap uses.
 * The steps are ink at 100%, 62% and 34%, which measure ΔE 23 apart for every
 * kind of colour vision. The lightest step sits under 3:1 against the page, so
 * every segment is directly labelled and legended; identity is never carried by
 * the fill alone.
 */
const STEPS = ['rgb(var(--ink))', 'rgb(var(--ink) / 0.62)', 'rgb(var(--ink) / 0.34)']

export function HarmonisationDonut({
  harmonisation,
}: {
  harmonisation: ExecutiveDashboard['harmonisation']
}) {
  const { total, parts } = harmonisation
  if (!total) return null
  const pct = (v: number) => Math.round((v / total) * 100)
  const coded = parts.find((p) => p.key === 'coded')?.value ?? 0

  return (
    <section className="space-y-4" data-testid="harmonisation">
      <h2 className="micro-label">Harmonisation of the catalogue</h2>
      <div className="grid items-center gap-6 card p-5 sm:grid-cols-[13rem_minmax(0,1fr)]">
        <div className="relative mx-auto h-52 w-52">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={parts}
                dataKey="value"
                nameKey="label"
                innerRadius="62%"
                outerRadius="100%"
                startAngle={90}
                endAngle={-270}
                /* a 2px gap of page between segments, so adjacent steps read
                   as separate marks rather than one continuous ring */
                paddingAngle={1.4}
                stroke="rgb(var(--bg))"
                strokeWidth={2}
                isAnimationActive={false}
              >
                {parts.map((part, i) => (
                  <Cell key={part.key} fill={STEPS[i % STEPS.length]} />
                ))}
              </Pie>
              <Tooltip
                cursor={false}
                contentStyle={{
                  background: 'rgb(var(--bg))',
                  border: '1px solid rgb(var(--hairline))',
                  borderRadius: 10,
                  fontSize: 12,
                  color: 'rgb(var(--ink))',
                }}
                formatter={(value: number, name: string) => [
                  `${value.toLocaleString('en-IN')} rows · ${pct(value)}%`,
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
          {/* The one number the ring is about, in the hole it leaves. */}
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <p className="font-mono text-2xl tabular-nums">{pct(coded)}%</p>
            <p className="micro-label mt-0.5">coded</p>
          </div>
        </div>

        <dl className="space-y-3">
          {parts.map((part, i) => (
            <div key={part.key} className="grid grid-cols-[0.6rem_1fr_auto] items-baseline gap-3">
              <span
                aria-hidden
                className="mt-1.5 h-2.5 w-2.5 rounded-[3px]"
                style={{ background: STEPS[i % STEPS.length] }}
              />
              <div className="min-w-0">
                <dt className="text-sm font-medium">{part.label}</dt>
                <dd className="text-xs text-muted">{part.note}</dd>
              </div>
              <dd className="text-right font-mono text-sm tabular-nums">
                {part.value.toLocaleString('en-IN')}
                <span className="ml-2 text-xs text-muted">{pct(part.value)}%</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="text-xs text-muted">
        Every catalogue row falls in exactly one part; the three sum to{' '}
        {total.toLocaleString('en-IN')}.
      </p>
    </section>
  )
}
