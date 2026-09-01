import { useCallback, useEffect, useState } from 'react'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { Input } from '../components/primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import {
  ApiError,
  getAudit,
  verifyChain,
  type AuditResponse,
  type VerifyResponse,
} from '../lib/api'

/**
 * /audit — the hash-chained event stream, and the verify button (spec §6.10).
 *
 * Verification re-walks every link and reports the sequence number of the first
 * break, so an auditor is told where the ledger stops being trustworthy rather
 * than only that it does.
 */
export default function Audit() {
  const [data, setData] = useState<AuditResponse | null>(null)
  const [entity, setEntity] = useState('')
  const [user, setUser] = useState('')
  const [action, setAction] = useState('')
  // Held separately so choosing an action does not shrink the list of actions
  // to choose from — a filter that erases its own options is unusable.
  const [allActions, setAllActions] = useState<Record<string, number>>({})
  const [verification, setVerification] = useState<VerifyResponse | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const next = await getAudit({
        entity: entity || undefined,
        user: user || undefined,
        action: action || undefined,
        limit: 100,
      })
      setData(next)
      if (!entity && !user && !action) setAllActions(next.actions)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the ledger.')
    }
  }, [entity, user, action])

  useEffect(() => {
    void load()
  }, [load])

  async function verify() {
    setVerifying(true)
    try {
      setVerification(await verifyChain())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification could not run.')
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Governance"
        title="Audit trail"
        description="Every mutation as a hash-chained event. Each hash covers its own sequence number, so the chain detects reordering as well as tampering."
        actions={
          <Button variant="primary" onClick={() => void verify()} disabled={verifying}>
            {verifying ? 'Verifying…' : 'Verify chain'}
          </Button>
        }
      />

      {verification && (
        <div className="border border-hairline p-6">
          <div className="flex flex-wrap items-center gap-4">
            <StatusChip tone={verification.valid ? 'ok' : 'danger'}>
              {verification.valid ? 'Chain intact' : 'Chain broken'}
            </StatusChip>
            <span className="font-mono text-xs text-muted">
              {verification.events} events
              {verification.head_seq !== undefined && ` · head seq ${verification.head_seq}`}
            </span>
          </div>
          {verification.first_break ? (
            <p className="mt-3 text-sm text-danger">
              First break at sequence{' '}
              <span className="font-mono">{verification.first_break.seq}</span> —{' '}
              {verification.first_break.reason}
            </p>
          ) : (
            <p className="mt-3 text-sm text-muted">
              Every link re-walked from the genesis event; no entry has been altered,
              removed or reordered.
            </p>
          )}
          {verification.head_hash && (
            <p className="mt-2 break-all font-mono text-[11px] text-muted">
              head {verification.head_hash}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor="entity" className="micro-label block">
            Entity
          </label>
          <Input
            id="entity"
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
            placeholder="cluster: / cnmc: / review_task:"
            className="w-64 font-mono"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="user" className="micro-label block">
            User
          </label>
          <Input
            id="user"
            value={user}
            onChange={(e) => setUser(e.target.value)}
            placeholder="steward@cpcl.in"
            className="w-64 font-mono"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="action" className="micro-label block">
            Action
          </label>
          <select
            id="action"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="h-10 w-64 border border-hairline bg-bg px-3 font-mono text-sm text-ink"
          >
            <option value="">every action</option>
            {Object.entries(allActions)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([name, count]) => (
                <option key={name} value={name}>
                  {name} ({count.toLocaleString('en-IN')})
                </option>
              ))}
          </select>
        </div>
        {data && (
          <p className="pb-2 text-xs text-muted">
            {data.total.toLocaleString('en-IN')} event{data.total === 1 ? '' : 's'}
          </p>
        )}
        {(entity || user || action) && (
          <button
            type="button"
            onClick={() => {
              setEntity('')
              setUser('')
              setAction('')
            }}
            className="micro-label pb-2 underline underline-offset-4 hover:text-ink"
          >
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {data && data.events.length === 0 ? (
        <EmptyState
          title="No events match"
          description="Nothing has been recorded under that filter yet."
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setEntity('')
                setUser('')
              }}
            >
              Clear filters
            </Button>
          }
        />
      ) : (
        <Table>
          <THead>
            <TH>Seq</TH>
            <TH>When</TH>
            <TH>User</TH>
            <TH>Action</TH>
            <TH>Entity</TH>
            <TH>Hash</TH>
          </THead>
          <TBody>
            {(data?.events ?? []).map((event) => (
              <TR key={event.seq}>
                <TD mono>{event.seq}</TD>
                <TD mono>{event.ts.replace('T', ' ').slice(0, 19)}</TD>
                <TD>{event.user}</TD>
                <TD mono>{event.action}</TD>
                <TD mono>{event.entity}</TD>
                <TD mono className="text-muted">{event.hash.slice(0, 12)}…</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  )
}
