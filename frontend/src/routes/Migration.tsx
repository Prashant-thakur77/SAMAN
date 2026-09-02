import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { useVirtualRows } from '../lib/useVirtualRows'
import { formatRupees } from '../components/charts/CountUp'
import { Button } from '../components/primitives/Button'
import { CodeChip, StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import {
  ApiError,
  getBatchDetail,
  getErpState,
  getMigrationBatches,
  migrationApply,
  migrationDryRun,
  migrationRollback,
  type BatchDetail,
  type ErpState,
  type MigrationBatch,
  type MigrationPlan,
} from '../lib/api'
import { cn } from '../lib/cn'
import { useSession } from '../lib/session'

const IMPACT_LABEL: Record<string, string> = {
  safe: 'safe to apply',
  open_transactions: 'held: open purchase order',
  valuation_conflict: 'review: stranded value',
}

/**
 * /migration — spec §6.12, §2C.
 *
 * Plan, dry run, apply, then a journal with rollback. The impact column is the
 * point of the screen: a record with open transactions is held rather than
 * changed underneath a live purchase order.
 */
export default function Migration() {
  const [erp, setErp] = useState<ErpState | null>(null)
  const [plan, setPlan] = useState<MigrationPlan | null>(null)
  const [batches, setBatches] = useState<MigrationBatch[]>([])
  const [detail, setDetail] = useState<BatchDetail | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const { can } = useSession()

  const load = useCallback(async () => {
    try {
      const [state, list] = await Promise.all([getErpState(), getMigrationBatches()])
      setErp(state)
      setBatches(list.batches)
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'Could not read the ERP.',
      })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function run(work: () => Promise<unknown>, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      await work()
      await load()
      setMessage({ tone: 'ok', text: success })
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'That did not work.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function turnPage(direction: 1 | -1) {
    if (!plan) return
    const size = plan.limit ?? plan.changes.length
    const next = Math.max(0, (plan.offset ?? 0) + direction * size)
    await run(
      async () => setPlan(await migrationDryRun(undefined, { offset: next, limit: size })),
      `Showing changes from ${next + 1}.`,
    )
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="ERP migration"
        description="Write the CNMC cross-reference into the material master. A record with open transactions is held; a superseded material is blocked, never deleted; every batch can be rolled back."
        actions={
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() =>
              void run(
                async () => setPlan(await migrationDryRun(undefined, { offset: 0 })),
                'Dry run complete.',
              )
            }
          >
            Run a dry run
          </Button>
        }
      />

      {message && (
        <p
          role="status"
          className={`border border-hairline px-4 py-3 text-sm ${
            message.tone === 'ok' ? 'text-ok' : 'text-danger'
          }`}
        >
          {message.text}
        </p>
      )}

      {erp && (
        <section className="space-y-3">
          <h2 className="micro-label">Target system</h2>
          <div className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card sm:grid-cols-4">
            {[
              { label: 'Materials', value: erp.counts.mara },
              { label: 'Open PO lines', value: erp.counts.ekpo },
              { label: 'Cross-referenced', value: erp.materials_cross_referenced },
              { label: 'Blocked', value: erp.materials_blocked },
            ].map((tile) => (
              <div key={tile.label} className="space-y-1 bg-surface p-4">
                <p className="micro-label">{tile.label}</p>
                <p className="font-mono text-lg">{(tile.value ?? 0).toLocaleString('en-IN')}</p>
              </div>
            ))}
          </div>
          <p className="max-w-prose text-xs text-muted">
            {erp.system} · {erp.note}
          </p>
          <p className="break-all font-mono text-[11px] text-muted">
            state {erp.fingerprint.slice(0, 24)}…
          </p>
        </section>
      )}

      {plan && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="micro-label">
              Dry run · {plan.summary.total.toLocaleString('en-IN')} changes across{' '}
              {plan.clusters.toLocaleString('en-IN')} clusters
            </h2>
            {can('registrar', 'admin') && plan.would_apply ? (
              <Button
                variant="primary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await migrationApply()
                    // The plan described the ERP as it was a moment ago; leaving
                    // it on screen would invite a second apply of the same rows.
                    setPlan(null)
                  }, 'Batch applied. The journal below can roll it back.')
                }
              >
                Apply {plan.would_apply} safe change{plan.would_apply === 1 ? '' : 's'}
              </Button>
            ) : null}
          </div>

          <div className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card sm:grid-cols-3">
            {[
              { label: 'Safe to apply', value: plan.summary.safe, tone: 'ok' as const },
              {
                label: 'Held: open POs',
                value: plan.summary.held_open_transactions,
                tone: 'neutral' as const,
              },
              {
                label: 'Review: stranded value',
                value: plan.summary.valuation_conflict,
                tone: 'danger' as const,
              },
            ].map((tile) => (
              <div key={tile.label} className="space-y-2 bg-surface p-4">
                <p className="micro-label">{tile.label}</p>
                <p className="font-mono text-lg">{tile.value}</p>
                <StatusChip tone={tile.tone}>{tile.value === 0 ? 'none' : 'see below'}</StatusChip>
              </div>
            ))}
          </div>
          {plan.thresholds && (
            <p className="max-w-prose text-xs text-muted">{plan.thresholds.note}</p>
          )}
          {plan.visibility && !plan.visibility.sees_attributed_prices && (
            <p className="max-w-prose text-xs text-muted">
              Valuations belonging to other CPSEs are withheld at your role; the rows themselves
              are not.
            </p>
          )}

          <PlanTable plan={plan} />

          {(plan.truncated || (plan.offset ?? 0) > 0) && (
            <div className="flex flex-wrap items-center justify-between gap-4 card px-4 py-3">
              <p className="font-mono text-xs text-muted">
                showing {(plan.offset ?? 0) + 1}–
                {(plan.offset ?? 0) + plan.changes.length} of{' '}
                {(plan.total_changes ?? plan.changes.length).toLocaleString('en-IN')} changes
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy || (plan.offset ?? 0) === 0}
                  onClick={() => void turnPage(-1)}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy || !plan.truncated}
                  onClick={() => void turnPage(1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="space-y-4">
        <h2 className="micro-label">Migration journal</h2>
        {batches.length === 0 ? (
          <EmptyState
            title="No batch has been applied"
            description="Run a dry run, then apply the safe changes. Every applied row is journaled with its before-image so the batch can be reversed."
          />
        ) : (
          <Table>
            <THead>
              <TH>Batch</TH>
              <TH>When</TH>
              <TH>Status</TH>
              <TH align="right">Rows</TH>
              <TH>Actions</TH>
            </THead>
            <TBody>
              {batches.map((batch) => (
                <TR key={batch.id}>
                  <TD mono>#{batch.id}</TD>
                  <TD mono>{batch.ts.replace('T', ' ').slice(0, 19)}</TD>
                  <TD>
                    <StatusChip tone={batch.status === 'applied' ? 'ok' : 'neutral'}>
                      {batch.status}
                    </StatusChip>
                  </TD>
                  <TD mono align="right">{batch.changes}</TD>
                  <TD>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          void getBatchDetail(batch.id).then(setDetail).catch(() => setDetail(null))
                        }
                      >
                        Journal
                      </Button>
                      {batch.status === 'applied' && can('registrar', 'admin') && (
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () => migrationRollback(batch.id),
                              `Batch ${batch.id} rolled back; the ERP is exactly as it was.`,
                            )
                          }
                        >
                          Roll back
                        </Button>
                      )}
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </section>

      {detail && (
        <section className="space-y-3 card p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="micro-label">Batch #{detail.id} journal</h2>
            <div className="flex items-center gap-3">
              <StatusChip tone={detail.verification.in_sync ? 'ok' : 'danger'}>
                {detail.verification.in_sync ? 'ERP matches the journal' : 'ERP has drifted'}
              </StatusChip>
              <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>
                Close
              </Button>
            </div>
          </div>
          <Table>
            <THead>
              <TH>Material</TH>
              <TH>State</TH>
              <TH>Before</TH>
              <TH>After</TH>
            </THead>
            <TBody>
              {detail.changes.slice(0, 40).map((change) => (
                <TR key={`${change.erp_key}-${change.state}`}>
                  <TD mono>{change.erp_key}</TD>
                  <TD mono>{change.state}</TD>
                  <TD mono className="text-muted">
                    {JSON.stringify({
                      lvorm: change.before.lvorm,
                      zz_cnmc: change.before.zz_cnmc,
                    })}
                  </TD>
                  <TD mono className="text-muted">
                    {change.after
                      ? JSON.stringify({
                          lvorm: change.after.lvorm,
                          zz_cnmc: change.after.zz_cnmc,
                        })
                      : '— held —'}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </section>
      )}
    </div>
  )
}

const PLAN_COLUMNS = 7
const PLAN_ROW_HEIGHT = 40

/**
 * The change set, windowed. A full rollout plans one row per catalogue row, so
 * this must stay bounded whether it is handed 20 rows or 2,000.
 */
function PlanTable({ plan }: { plan: MigrationPlan }) {
  const { scrollProps, body } = useVirtualRows({
    rows: plan.changes,
    rowHeight: PLAN_ROW_HEIGHT,
    columns: PLAN_COLUMNS,
    render: (change) => (
      <TR key={change.matnr}>
        <TD mono>
          {change.matnr}
          <Link
            to={`/clusters/${change.cluster_id}`}
            className="micro-label ml-2 underline underline-offset-2 hover:text-ink"
          >
            cluster
          </Link>
        </TD>
        <TD>
          {change.action === 'crossref' ? (
            <>
              surviving master · <CodeChip code={change.cnmc} />
            </>
          ) : (
            <span className="text-muted">block against {change.surviving_matnr}</span>
          )}
        </TD>
        <TD>
          <StatusChip
            tone={
              change.impact === 'safe'
                ? 'ok'
                : change.impact === 'valuation_conflict'
                  ? 'danger'
                  : 'neutral'
            }
          >
            {IMPACT_LABEL[change.impact]}
          </StatusChip>
        </TD>
        <TD mono align="right" className={cn(change.open_po_lines > 0 && 'text-ink')}>
          {change.open_po_lines || '—'}
        </TD>
        <TD mono align="right">
          {change.stock_qty.toLocaleString('en-IN')}
        </TD>
        <TD
          mono
          align="right"
          title={
            change.price_withheld
              ? 'Another CPSE’s valuation is not shown at your role.'
              : undefined
          }
        >
          {change.total_value === null ? 'withheld' : formatRupees(change.total_value)}
        </TD>
        <TD mono className="text-muted">
          {change.diff && Object.keys(change.diff).length > 0
            ? Object.entries(change.diff)
                .map(([field, d]) => `${field}: ${d.before || '∅'} → ${d.after}`)
                .join('; ')
            : 'no change'}
        </TD>
      </TR>
    ),
  })

  return (
    <div {...scrollProps}>
      <Table>
        <THead>
          <TH>Material</TH>
          <TH>Action</TH>
          <TH>Impact</TH>
          <TH align="right">Open POs</TH>
          <TH align="right">Stock</TH>
          <TH align="right">Value</TH>
          <TH>Change</TH>
        </THead>
        <TBody>{body}</TBody>
      </Table>
    </div>
  )
}
