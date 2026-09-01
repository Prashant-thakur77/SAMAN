import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { CodeChip, StatusChip } from '../components/primitives/Chip'
import { Field, Input } from '../components/primitives/Field'
import {
  ApiError,
  getSmartCreateStats,
  smartCreateCheck,
  smartCreateCreate,
  smartCreateReuse,
  type SmartCreateMatch,
  type SmartCreateResult,
  type SmartCreateStats,
} from '../lib/api'
import { cn } from '../lib/cn'

const ACTION_TONE = {
  reuse: 'danger',
  review: 'neutral',
  create: 'ok',
} as const

const ACTION_HEADLINE = {
  reuse: 'This material already exists',
  review: 'A possible match needs a decision',
  create: 'No match — safe to create',
} as const

/**
 * /smart-create — duplicate prevention at source (spec §5).
 *
 * The rest of SAMAN cleans up duplicates. This is the screen that stops them
 * being created, by running a description through the same matcher the pipeline
 * uses before a new material master is raised.
 */
export default function SmartCreate() {
  const [description, setDescription] = useState('')
  const [mpn, setMpn] = useState('')
  const [uom, setUom] = useState('')
  const [legacyCode, setLegacyCode] = useState('')
  const [reason, setReason] = useState('')
  const [result, setResult] = useState<SmartCreateResult | null>(null)
  const [stats, setStats] = useState<SmartCreateStats | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [resolved, setResolved] = useState(false)

  useEffect(() => {
    void getSmartCreateStats().then(setStats).catch(() => setStats(null))
  }, [])

  async function run(work: () => Promise<void>) {
    setBusy(true)
    setMessage(null)
    try {
      await work()
      setStats(await getSmartCreateStats())
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'That did not work.',
      })
    } finally {
      setBusy(false)
    }
  }

  const check = () =>
    run(async () => {
      setResolved(false)
      setResult(
        await smartCreateCheck({
          description,
          mpn: mpn || undefined,
          uom: uom || undefined,
        }),
      )
    })

  const reuse = (match: SmartCreateMatch) =>
    run(async () => {
      if (!result) return
      await smartCreateReuse(result.check_id, match.item_id)
      setResolved(true)
      setMessage({
        tone: 'ok',
        text: `Reused ${match.cnmc ?? match.description}. One duplicate prevented.`,
      })
    })

  const createAnyway = () =>
    run(async () => {
      if (!result) return
      const created = await smartCreateCreate({
        create_token: result.create_token,
        legacy_code: legacyCode,
        description,
        uom: uom || undefined,
        reason: reason || undefined,
      })
      setResolved(true)
      setMessage({ tone: 'ok', text: `${created.legacy_code} created. ${created.note}` })
    })

  const action = result?.recommendation.action
  const nothingFound =
    result &&
    result.suggestions.length === 0 &&
    result.equivalents.length === 0 &&
    result.ruled_out.length === 0

  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="Smart-Create"
        description="Check a description against the national catalogue before raising a new material code. The same matcher, veto layer and evidence the pipeline uses — applied one record early."
      />

      {stats && (
        <div className="grid gap-px border border-hairline bg-hairline sm:grid-cols-4">
          {[
            { label: 'Duplicates prevented', value: stats.prevented.toLocaleString('en-IN') },
            { label: 'Created anyway', value: stats.created_anyway.toLocaleString('en-IN') },
            { label: 'Checks run', value: stats.checks.toLocaleString('en-IN') },
            {
              label: 'Prevention rate',
              value:
                stats.prevention_rate === null
                  ? '—'
                  : `${Math.round(stats.prevention_rate * 100)}%`,
            },
          ].map((tile) => (
            <div key={tile.label} className="space-y-1 bg-bg p-4">
              <p className="micro-label">{tile.label}</p>
              <p className="font-mono text-lg">{tile.value}</p>
            </div>
          ))}
        </div>
      )}

      <section className="space-y-4 border border-hairline p-6">
        <div className="grid gap-4 md:grid-cols-[1fr_180px_120px]">
          <Field label="Material description" htmlFor="sc-description">
            <Input
              id="sc-description"
              value={description}
              placeholder="BRG,BALL,25MM BORE,52MM OD,15MM W,ZZ,SKF"
              autoFocus
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && description.trim() && !busy) void check()
              }}
            />
          </Field>
          <Field label="Part number" htmlFor="sc-mpn" hint="Optional, but decisive.">
            <Input id="sc-mpn" value={mpn} onChange={(e) => setMpn(e.target.value)} />
          </Field>
          <Field label="UoM" htmlFor="sc-uom">
            <Input
              id="sc-uom"
              value={uom}
              placeholder="NOS"
              onChange={(e) => setUom(e.target.value)}
            />
          </Field>
        </div>
        <Button variant="primary" disabled={busy || !description.trim()} onClick={() => void check()}>
          {busy ? 'Checking…' : 'Check before creating'}
        </Button>
      </section>

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

      {result && action && (
        <>
          <section className="space-y-3 border border-hairline p-6">
            <div className="flex flex-wrap items-center gap-3">
              <StatusChip tone={ACTION_TONE[action]}>{action}</StatusChip>
              <h2 className="text-lg">{ACTION_HEADLINE[action]}</h2>
            </div>
            <p className="max-w-prose text-sm text-muted">{result.recommendation.reason}</p>

            <div className="border-t border-hairline pt-3">
              <p className="micro-label pb-2">What the platform read</p>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-xs">
                <span>
                  class{' '}
                  <span className="text-muted">
                    {result.probe.class_code} ({result.probe.class_confidence})
                  </span>
                </span>
                {result.probe.mpn_norm && (
                  <span>
                    mpn <span className="text-muted">{result.probe.mpn_norm}</span>
                  </span>
                )}
                {Object.entries(result.probe.attrs).map(([key, value]) => (
                  <span key={key}>
                    {key.replace(/_/g, ' ')} <span className="text-muted">{String(value)}</span>
                  </span>
                ))}
              </div>
            </div>
          </section>

          <MatchList
            title="Already in the catalogue"
            caption="Reuse one of these instead of raising a new code."
            matches={result.suggestions}
            onReuse={resolved ? undefined : reuse}
            busy={busy}
          />
          <MatchList
            title="Interchangeable parts"
            caption="A different manufacturer's equivalent. Not the same record — but worth knowing before you buy."
            matches={result.equivalents}
            busy={busy}
          />
          <MatchList
            title="Checked and ruled out"
            caption="These looked close. The attribute that refused each one is named."
            matches={result.ruled_out}
            busy={busy}
          />

          {nothingFound && (
            <p className="border border-hairline px-4 py-3 text-sm text-muted">
              Nothing in the catalogue resembles this description closely enough to compare.
            </p>
          )}

          {!resolved && (
            <section className="space-y-4 border border-hairline p-6">
              <h2 className="micro-label">Create it anyway</h2>
              <p className="max-w-prose text-sm text-muted">
                {result.recommendation.override_requires_reason
                  ? 'You can still create this material, but the reason is recorded against the check and appears in the audit trail.'
                  : 'Nothing matched, so this needs only a code.'}
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="New legacy code" htmlFor="sc-code">
                  <Input
                    id="sc-code"
                    value={legacyCode}
                    onChange={(e) => setLegacyCode(e.target.value)}
                  />
                </Field>
                {result.recommendation.override_requires_reason && (
                  <Field label="Reason for the override" htmlFor="sc-reason">
                    <Input
                      id="sc-reason"
                      value={reason}
                      placeholder="Separate valuation class at a different plant"
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </Field>
                )}
              </div>
              <Button
                variant={action === 'create' ? 'primary' : 'secondary'}
                disabled={
                  busy ||
                  !legacyCode.trim() ||
                  (result.recommendation.override_requires_reason && !reason.trim())
                }
                onClick={() => void createAnyway()}
              >
                Create new material
              </Button>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function MatchList({
  title,
  caption,
  matches,
  onReuse,
  busy,
}: {
  title: string
  caption: string
  matches: SmartCreateMatch[]
  onReuse?: (match: SmartCreateMatch) => void
  busy: boolean
}) {
  if (matches.length === 0) return null
  return (
    <section className="space-y-3">
      <div>
        <h2 className="micro-label">{title}</h2>
        <p className="max-w-prose pt-1 text-xs text-muted">{caption}</p>
      </div>
      <ul className="divide-y divide-hairline border border-hairline">
        {matches.map((match) => (
          <li key={match.item_id} className="flex flex-wrap items-start gap-4 p-4">
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-3">
                {match.cnmc && <CodeChip code={match.cnmc} />}
                {match.cpse && <span className="micro-label">{match.cpse}</span>}
                {match.confidence > 0 && (
                  <span className="font-mono text-xs text-muted">
                    {(match.confidence * 100).toFixed(1)}%
                  </span>
                )}
              </div>
              <p className="break-words font-mono text-sm">{match.description}</p>
              <p className={cn('text-xs', match.veto ? 'text-muted' : 'text-ink')}>{match.why}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Link
                to={`/items/${match.item_id}`}
                className="micro-label underline underline-offset-4 hover:text-ink"
              >
                Open
              </Link>
              {onReuse && (
                <Button size="sm" variant="primary" disabled={busy} onClick={() => onReuse(match)}>
                  Use this
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
