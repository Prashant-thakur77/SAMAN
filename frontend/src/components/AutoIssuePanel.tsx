import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  ApiError,
  getAutoIssue,
  runAutoIssue,
  setAutoIssuePolicy,
  type AutoIssueRun,
  type AutoIssueStatus,
} from '../lib/api'
import { useSession } from '../lib/session'
import { Button } from './primitives/Button'
import { StatusChip } from './primitives/Chip'
import { TBody, TD, TH, THead, TR, Table } from './primitives/Table'

/**
 * Codes that issue themselves, under a policy the registrar sets per family.
 *
 * The gates are stated on the panel, not implied: anchored pairs in full
 * agreement, the class's held-out precision at or above the target, no grey
 * task pending. Off by default. The registrar who turns a family on is the
 * issuer of record for every code that follows, which is why only a
 * registrar can, and why the panel says so.
 */
export function AutoIssuePanel() {
  const { user } = useSession()
  const [status, setStatus] = useState<AutoIssueStatus | null>(null)
  const [targets, setTargets] = useState<Record<string, string>>({})
  const [result, setResult] = useState<AutoIssueRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const registrar = user?.role === 'registrar'

  const load = useCallback(async () => {
    try {
      const next = await getAutoIssue()
      setStatus(next)
      setTargets(Object.fromEntries(next.families.map((f) => [f.family, f.min_precision.toFixed(2)])))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the policy.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function act(work: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await work()
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That did not work.')
    } finally {
      setBusy(false)
    }
  }

  if (!status) return null
  const pct = (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(1)}%`)

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="micro-label">Automatic issue · by family, under policy</h2>
        <p className="max-w-prose text-xs text-muted">
          A code issues without a click only when every stored pair in the cluster is anchored
          and every attribute agrees, the class's held-out precision is at or above the family's
          target, and no grey-band task is pending. Off by default. Codes issued this way carry
          the name of the registrar who set the policy.
          {!status.has_snapshot && (
            <> No held-out snapshot is recorded, so nothing can issue until <span className="font-mono">make evaluate</span> has run.</>
          )}
        </p>
      </div>

      <Table exportAs="autoissue-policy">
        <THead>
          <TH>Family</TH>
          <TH>Classes</TH>
          <TH align="right">Held-out precision</TH>
          <TH align="right">Target</TH>
          <TH align="right">Eligible now</TH>
          <TH>Policy</TH>
        </THead>
        <TBody>
          {status.families.map((row) => (
            <TR key={row.family}>
              <TD mono>{row.family}</TD>
              <TD mono className="text-muted">
                {row.classes.join(', ')}
              </TD>
              <TD mono align="right" className="tabular-nums">
                {pct(row.precision)}
              </TD>
              <TD align="right">
                <input
                  aria-label={`Target precision for ${row.family}`}
                  value={targets[row.family] ?? ''}
                  disabled={!registrar || busy}
                  onChange={(e) => setTargets((t) => ({ ...t, [row.family]: e.target.value }))}
                  onBlur={() => {
                    const v = Number(targets[row.family])
                    if (registrar && Number.isFinite(v) && v !== row.min_precision) {
                      void act(() => setAutoIssuePolicy(row.family, row.enabled, v))
                    }
                  }}
                  className="h-8 w-16 border border-hairline bg-bg px-2 text-right font-mono text-xs"
                />
              </TD>
              <TD mono align="right" className="tabular-nums">
                {row.eligible.toLocaleString('en-IN')}
              </TD>
              <TD>
                <div className="flex items-center gap-2">
                  <StatusChip tone={row.enabled ? 'ok' : 'neutral'}>{row.enabled ? 'on' : 'off'}</StatusChip>
                  {registrar && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy}
                      onClick={() =>
                        void act(() =>
                          setAutoIssuePolicy(row.family, !row.enabled, Number(targets[row.family]) || row.min_precision),
                        )
                      }
                    >
                      {row.enabled ? 'Turn off' : 'Turn on'}
                    </Button>
                  )}
                </div>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>

      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xs text-muted">
          {status.eligible.toLocaleString('en-IN')} eligible now · {status.issued_under_policy.toLocaleString('en-IN')}{' '}
          issued under policy so far
        </span>
        {registrar && (
          <>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void act(async () => setResult(await runAutoIssue(true)))}
            >
              Dry run
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={busy || status.eligible === 0}
              onClick={() => void act(async () => setResult(await runAutoIssue(false)))}
            >
              Issue {status.eligible.toLocaleString('en-IN')} now
            </Button>
          </>
        )}
        <span className="text-xs text-muted">
          Nightly: <span className="font-mono">make autoissue APPLY=1</span> after the pipeline.
        </span>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-2 card p-4">
          <p className="text-sm">
            {result.dry_run ? 'Would issue' : 'Issued'}{' '}
            <span className="font-mono">{result.issued.length}</span> code
            {result.issued.length === 1 ? '' : 's'}
            {result.skipped.length > 0 && <> · skipped {result.skipped.length}</>}.
          </p>
          {result.issued.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-y-auto font-mono text-xs">
              {result.issued.slice(0, 50).map((row) => (
                <li key={row.cluster_id}>
                  {row.code ?? '(dry run)'} ·{' '}
                  <Link to={`/clusters/${row.cluster_id}`} className="underline-offset-2 hover:underline">
                    cluster {row.cluster_id}
                  </Link>{' '}
                  · {row.family} · {row.members} rows · <span className="text-muted">{row.std_description}</span>
                </li>
              ))}
            </ul>
          )}
          {Object.keys(result.not_eligible).length > 0 && (
            <p className="text-xs text-muted">
              Held back:{' '}
              {Object.entries(result.not_eligible)
                .sort((a, b) => b[1] - a[1])
                .map(([why, n]) => `${n.toLocaleString('en-IN')} ${why}`)
                .join(' · ')}
              .
            </p>
          )}
        </div>
      )}
    </section>
  )
}
