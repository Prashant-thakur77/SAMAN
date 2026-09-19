import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { ItemPanel } from '../components/workbench/ItemPanel'
import { Button } from '../components/primitives/Button'
import { CodeChip, StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { Input } from '../components/primitives/Field'
import {
  ApiError,
  editGolden,
  getCluster,
  issueCnmc,
  mergeCluster,
  splitMember,
  type ClusterDetail,
} from '../lib/api'
import { useSession } from '../lib/session'

/**
 * /clusters/:id — members, the proposed golden record with its provenance, and
 * split / merge (spec §6.6). Every mutation writes an audit event.
 */
export default function Cluster() {
  const { id } = useParams<{ id: string }>()
  const clusterId = Number(id)
  const [detail, setDetail] = useState<ClusterDetail | null>(null)
  const [draft, setDraft] = useState('')
  const [mergeSource, setMergeSource] = useState('')
  // Two members ticked for a side-by-side comparison; the newest two win.
  const [picked, setPicked] = useState<number[]>([])
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const { user, can } = useSession()

  const load = useCallback(async () => {
    try {
      const next = await getCluster(clusterId)
      setDetail(next)
      setDraft(next.golden?.std_description ?? '')
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'Could not load the cluster.',
      })
    }
  }, [clusterId])

  useEffect(() => {
    if (Number.isFinite(clusterId)) void load()
  }, [clusterId, load])

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

  if (!detail) {
    return (
      <div className="space-y-8">
        <PageHeader section="Review" title={`Cluster ${id ?? ''}`} description="Loading…" />
        {message && <p className="text-sm text-danger">{message.text}</p>}
      </div>
    )
  }

  const locked = Boolean(detail.cnmc)
  const approved = detail.golden?.status === 'approved'

  return (
    <div className="space-y-8">
      <PageHeader
        section="Review"
        title={`Cluster ${detail.cluster_id}`}
        description={`${detail.member_count} member${detail.member_count === 1 ? '' : 's'} · ${detail.class_code}`}
        actions={
          <div className="flex items-center gap-3">
            {detail.cnmc ? (
              <>
                <CodeChip code={detail.cnmc.code} />
                <Link
                  to={`/labels/${detail.cnmc.code}`}
                  className="text-sm text-muted underline underline-offset-4 hover:text-ink"
                >
                  Print label
                </Link>
              </>
            ) : (
              <Button
                variant="primary"
                disabled={!can('registrar') || busy || detail.status === 'conflict'}
                title={
                  can('registrar')
                    ? detail.status === 'conflict'
                      ? 'Resolve the specification conflict before issuing a code.'
                      : 'Issue the Common National Material Code'
                    : `Issuing a CNMC is registrar-only. You are signed in as ${user?.role ?? 'a guest'}.`
                }
                onClick={() =>
                  detail.golden &&
                  void run(() => issueCnmc(detail.golden!.id), 'CNMC issued.')
                }
              >
                Issue CNMC
              </Button>
            )}
          </div>
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

      {detail.status === 'conflict' && (
        <div className="card px-4 py-3">
          <p className="micro-label mb-2 text-danger">Blocked from approval</p>
          <ul className="space-y-1 text-sm">
            {detail.conflicts
              .filter((c) => c.blocking)
              .map((conflict) => (
                <li key={conflict.attr} className="font-mono text-xs">
                  {conflict.attr}: {conflict.values.join(' vs ')}
                </li>
              ))}
            {detail.conflicts.filter((c) => c.blocking).length === 0 && (
              <li className="text-sm text-muted">
                A member shares a part number with an item whose specification disagrees.
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Golden record (§2D) */}
      <section className="space-y-4 card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="micro-label">Golden record</h2>
          <StatusChip tone={approved ? 'ok' : detail.status === 'conflict' ? 'danger' : 'neutral'}>
            {detail.golden?.status ?? 'none'}
          </StatusChip>
        </div>

        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={approved || locked || !can('steward', 'approver', 'registrar', 'admin')}
          className="font-mono"
          aria-label="Proposed standardized description"
        />
        <p className="text-xs text-muted">
          Rendered from <span className="font-mono">{detail.golden?.template}</span>
        </p>

        {!approved && !locked && (
          <Button
            variant="secondary"
            disabled={busy || draft === detail.golden?.std_description}
            onClick={() => void run(() => editGolden(clusterId, draft), 'Description updated.')}
          >
            Save description
          </Button>
        )}

        {detail.provenance.length > 0 && (
          <div className="pt-2">
            <h3 className="micro-label mb-2">Field provenance</h3>
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-hairline">
                  <th className="micro-label py-1 text-left font-medium">Field</th>
                  <th className="micro-label py-1 text-left font-medium">From item</th>
                  <th className="micro-label py-1 text-left font-medium">Rule</th>
                  <th className="micro-label py-1 text-left font-medium">Candidates</th>
                </tr>
              </thead>
              <tbody>
                {detail.provenance.map((entry) => (
                  <tr key={entry.field} className="border-b border-hairline last:border-0">
                    <td className="py-1.5 pr-3 font-mono">{entry.field}</td>
                    <td className="py-1.5 pr-3 font-mono">{entry.source_member_id ?? '—'}</td>
                    <td className="py-1.5 pr-3 text-muted">{entry.rule.replace(/_/g, ' ')}</td>
                    <td className="py-1.5 font-mono text-muted">
                      {[...new Set(entry.candidates.map((c) => c.value))].join(' · ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Members, with split */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="micro-label">Members</h2>
          {locked && (
            <p className="text-xs text-muted">
              An issued code is immutable; membership can no longer change.
            </p>
          )}
        </div>
        {detail.member_count > 1 && (
          <p className="text-xs text-muted">
            Tick two members to see them side by side, scored by the matcher.
            {picked.length === 2 && (
              <>
                {' '}
                <Link
                  to={`/compare?a=${picked[0]}&b=${picked[1]}`}
                  className="font-medium text-ink underline underline-offset-4"
                >
                  Compare {picked[0]} and {picked[1]} →
                </Link>
              </>
            )}
          </p>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          {detail.members.map((member) => {
            const delta = detail.standardization_delta.find(
              (d) => d.member_id === member.item_id,
            )
            return (
              <div key={member.item_id} className="space-y-2">
                {detail.member_count > 1 && (
                  <label className="flex items-center gap-2 px-1 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={picked.includes(member.item_id)}
                      onChange={(e) =>
                        setPicked((prev) =>
                          e.target.checked
                            ? [...prev.filter((id) => id !== member.item_id), member.item_id].slice(-2)
                            : prev.filter((id) => id !== member.item_id),
                        )
                      }
                    />
                    compare
                  </label>
                )}
                <ItemPanel item={member} />
                {delta && !delta.unchanged && (
                  <p className="px-1 text-xs text-muted">
                    standardization dropped{' '}
                    <span className="font-mono">{delta.tokens_dropped.slice(0, 6).join(', ') || '—'}</span>
                  </p>
                )}
                {detail.member_count > 1 && !locked && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => splitMember(clusterId, member.item_id),
                        `Item ${member.item_id} split into its own cluster.`,
                      )
                    }
                  >
                    Split out
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Merge */}
      {!locked && (
        <section className="space-y-3 card p-6">
          <h2 className="micro-label">Merge another cluster into this one</h2>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              value={mergeSource}
              onChange={(e) => setMergeSource(e.target.value)}
              placeholder="cluster id"
              inputMode="numeric"
              className="max-w-[12rem] font-mono"
              aria-label="Cluster to merge in"
            />
            <Button
              variant="secondary"
              disabled={busy || !mergeSource.trim()}
              onClick={() =>
                void run(
                  () => mergeCluster(clusterId, Number(mergeSource)),
                  `Cluster ${mergeSource} merged in.`,
                ).then(() => setMergeSource(''))
              }
            >
              Merge in
            </Button>
          </div>
          <p className="text-xs text-muted">
            Both clusters must be free of an issued code. The merge is recorded in the audit trail.
          </p>
        </section>
      )}

      {detail.member_count === 0 && (
        <EmptyState title="Empty cluster" description="This cluster has no members." />
      )}
    </div>
  )
}
