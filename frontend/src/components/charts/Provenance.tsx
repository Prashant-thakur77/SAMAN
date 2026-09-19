import type { DashboardProvenance } from '../../lib/api'

/**
 * Where a dashboard's figures came from: computed when, from how many rows,
 * at which point in the audit chain. One line under the header, and the
 * same text as a tooltip on every figure that carries it. A reader who asks
 * "as of when?" is answered by the page.
 */
export function provenanceTitle(p: DashboardProvenance | undefined): string | undefined {
  if (!p) return undefined
  const when = new Date(p.computed_at).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
  return `Computed ${when} in ${p.seconds}s from ${p.rows.items.toLocaleString('en-IN')} items, ${p.rows.decisions.toLocaleString('en-IN')} decisions and ${p.rows.purchases.toLocaleString('en-IN')} purchase lines · audit #${p.audit_seq} · match run ${p.match_run} · synthetic estate`
}

export function ProvenanceLine({ provenance }: { provenance: DashboardProvenance | undefined }) {
  if (!provenance) return null
  const when = new Date(provenance.computed_at).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
  return (
    <p className="font-mono text-[11px] text-muted" title={provenance.note}>
      computed {when} · {provenance.seconds}s · {provenance.rows.items.toLocaleString('en-IN')}{' '}
      items · {provenance.rows.decisions.toLocaleString('en-IN')} decisions · audit #
      {provenance.audit_seq} · run {provenance.match_run} · synthetic
    </p>
  )
}
