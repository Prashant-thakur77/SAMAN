import type { VetoAttributes as VetoAttributesData, VetoRole } from '../../lib/api'
import { TBody, TD, TH, THead, TR, Table } from '../primitives/Table'
import { BarRows, type BarRow } from './BarRows'
import { Legend, TableTwin, formatCount, niceTicks } from './ChartParts'
import type { Shade } from './ramp'

const ROLE_LABEL: Record<VetoRole, string> = {
  identity_critical: 'Identity-critical attribute differs',
  performance: 'Performance rating out of band',
}
const ROLE_SHADE: Record<VetoRole, Shade> = { identity_critical: 0, performance: 1 }
const OTHER_SHADE: Shade = 2

/**
 * What kept look-alikes apart (spec section veto_attributes).
 *
 * The ten attributes that vetoed the most pairs, the tail folded into other,
 * sorted by count because attributes are nominal. Two shades tell the roles
 * apart: a dimension that defines the part at full ink, a rating out of its
 * tolerance band at 62%; the folded tail, which mixes both, at 34%. Every bar
 * carries a real example from the veto in its tooltip and its table row, and
 * the strip beneath says bars sum to attributes, not pairs.
 */
export function VetoAttributes({ data }: { data: VetoAttributesData }) {
  const attrs = [...data.by_attribute].sort((a, b) => b.pairs - a.pairs)
  const rows: BarRow[] = attrs.map((a) => ({
    key: a.attr,
    label: a.label,
    segments: [{ key: a.attr, value: a.pairs, shade: ROLE_SHADE[a.role] }],
    tip: formatCount(a.pairs),
    title: `${a.label} · ${ROLE_LABEL[a.role].toLowerCase()} · ${formatCount(a.pairs)} pairs${
      a.example ? ` · e.g. ${a.example.reason}` : ''
    }`,
  }))
  if (data.other.pairs > 0) {
    rows.push({
      key: 'other',
      label: `${formatCount(data.other.attributes)} other attributes`,
      segments: [{ key: 'other', value: data.other.pairs, shade: OTHER_SHADE }],
      tip: formatCount(data.other.pairs),
      title: `${formatCount(data.other.attributes)} other attributes, either role · ${formatCount(data.other.pairs)} pairs between them`,
    })
  }
  const max = Math.max(0, ...rows.map((r) => r.segments[0].value))
  const top = attrs[0]

  const aria = `Pairs vetoed by attribute: ${attrs
    .slice(0, 3)
    .map((a) => `${a.label} ${formatCount(a.pairs)}`)
    .join(', ')}${attrs.length > 3 ? ', and ' + (attrs.length - 3) + ' more' : ''}; ${formatCount(
    data.pairs_with_veto,
  )} pairs carried at least one veto.`

  const legend = [
    { key: 'identity_critical', label: ROLE_LABEL.identity_critical, shade: ROLE_SHADE.identity_critical },
    { key: 'performance', label: ROLE_LABEL.performance, shade: ROLE_SHADE.performance },
    ...(data.other.pairs > 0
      ? [{ key: 'other', label: `Other attributes (${formatCount(data.other.attributes)}, either role)`, shade: OTHER_SHADE }]
      : []),
  ]

  const cosmetic = data.cosmetic_never_vetoes
  const cosmeticList =
    cosmetic.length <= 1
      ? cosmetic.join('')
      : `${cosmetic.slice(0, -1).join(', ')} and ${cosmetic[cosmetic.length - 1]}`

  return (
    <section className="space-y-4" data-testid="veto_attributes">
      <h2 className="micro-label">What kept look-alikes apart</h2>
      <div className="space-y-5 card p-4 sm:p-5">
        {top && (
          <p className="text-sm">
            <span className="font-mono tabular-nums">{formatCount(data.pairs_with_veto)}</span> pairs were
            refused on at least one attribute; {top.label.toLowerCase()} broke the most
            {top.example && (
              <>
                {' '}
                (e.g. <span className="font-mono text-xs">{top.example.reason}</span>)
              </>
            )}
            .
          </p>
        )}
        <Legend items={legend} />
        <BarRows rows={rows} ticks={niceTicks(max)} formatTick={formatCount} axisTitle="pairs" ariaLabel={aria} />
        <p className="font-mono text-[11px] text-muted">
          vetoing attributes per pair —{' '}
          {data.attrs_per_pair.map((d) => `${d.n}: ${formatCount(d.pairs)}`).join(' · ')}
          <span className="font-sans"> (bars sum to attributes, not pairs)</span>
        </p>
        {cosmetic.length > 0 && (
          <p className="border-t border-hairline pt-3 text-xs text-muted">
            {cosmeticList[0].toUpperCase() + cosmeticList.slice(1)} differences never block a merge; a
            same-specification, different-brand pair becomes an equivalence question instead.
          </p>
        )}
      </div>
      <TableTwin>
        <Table>
          <THead>
            <TH>Attribute</TH>
            <TH>Role</TH>
            <TH align="right">Pairs</TH>
            <TH>Example</TH>
          </THead>
          <TBody>
            {attrs.map((a) => (
              <TR key={a.attr}>
                <TD>{a.label}</TD>
                <TD className="text-xs text-muted">{ROLE_LABEL[a.role]}</TD>
                <TD mono align="right">
                  {formatCount(a.pairs)}
                </TD>
                <TD mono className="text-muted">
                  {a.example ? a.example.reason : '—'}
                </TD>
              </TR>
            ))}
            {data.other.pairs > 0 && (
              <TR>
                <TD>{formatCount(data.other.attributes)} other attributes</TD>
                <TD className="text-xs text-muted">Either role</TD>
                <TD mono align="right">
                  {formatCount(data.other.pairs)}
                </TD>
                <TD mono className="text-muted">
                  —
                </TD>
              </TR>
            )}
          </TBody>
        </Table>
      </TableTwin>
      <p className="max-w-prose text-xs text-muted">
        {data.source === 'run'
          ? 'Counted over every pair the veto refused in the last run.'
          : `Counted over the ${formatCount(data.coverage.conflict)} conflicts and the ${formatCount(
              data.coverage.refused,
            )} most plausible refusals whose evidence was kept, not all ${formatCount(
              data.coverage.refused_total,
            )}.`}{' '}
        A pair can differ on more than one attribute, so bars sum to more than the pair count.
        Brand never vetoes by design. The mix of attributes is the seed&apos;s planted traps; the
        mechanism is the point, and veto precision on held-out traps (scorecard below) is the number
        that matters.
      </p>
    </section>
  )
}
