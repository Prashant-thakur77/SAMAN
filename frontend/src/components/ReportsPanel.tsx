import { useCallback, useEffect, useState } from 'react'

import {
  ApiError,
  getReports,
  patchCpse,
  reportHtmlUrl,
  sendReport,
  type ReportListing,
  type ReportSendResult,
} from '../lib/api'
import { Button } from './primitives/Button'
import { StatusChip } from './primitives/Chip'
import { Input } from './primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from './primitives/Table'

/**
 * The per-CPSE catalogue report: what SAMAN found in one catalogue and what
 * it is worth to that CPSE, as one printable page, on demand or by mail.
 *
 * Two faces of the same thing. The Administration page lists every CPSE with
 * its contact address (editable in place), when it last received a report,
 * and Preview and Send; the steward's Home carries one card for their own.
 * A send says where the message went, because an installation without SMTP
 * writes it to the outbox instead and must not pretend otherwise.
 */

function sentNote(result: ReportSendResult): string {
  return result.mode === 'smtp'
    ? `Sent to ${result.to.join(', ')}.`
    : `Written to the outbox at ${result.path}.`
}

function whenSent(row: ReportListing['cpses'][number]): string {
  if (!row.last_sent?.at) return 'never'
  return `${new Date(row.last_sent.at).toLocaleString('en-IN')} · ${row.last_sent.mode}`
}

export function ReportsSection() {
  const [listing, setListing] = useState<ReportListing | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await getReports()
      setListing(data)
      setDrafts(Object.fromEntries(data.cpses.map((c) => [c.code, c.contact_email ?? ''])))
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'Could not load the reports.',
      })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function run(code: string, work: () => Promise<string>) {
    setBusy(code)
    setMessage(null)
    try {
      const text = await work()
      await load()
      setMessage({ tone: 'ok', text })
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'That did not work.',
      })
    } finally {
      setBusy(null)
    }
  }

  if (!listing) return null

  return (
    <section className="space-y-4" data-testid="reports">
      <h2 className="micro-label">Reports</h2>
      <p className="max-w-prose text-sm text-muted">
        One document per CPSE: what the platform found in their catalogue and what it is worth
        to them, every figure from the database and redacted as their own steward would see it.
        {listing.delivery === 'smtp'
          ? ' Sent by SMTP.'
          : ` No SMTP relay is configured, so a send is written to the outbox at ${listing.outbox_dir}.`}
      </p>
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
      <Table>
        <THead>
          <TH>CPSE</TH>
          <TH>Contact email</TH>
          <TH>Last sent</TH>
          <TH>Report</TH>
        </THead>
        <TBody>
          {listing.cpses.map((row) => {
            const draft = drafts[row.code] ?? ''
            const dirty = draft.trim() !== (row.contact_email ?? '')
            return (
              <TR key={row.code}>
                <TD>
                  <span className="font-mono">{row.code}</span>
                  <span className="block text-xs text-muted">{row.name}</span>
                </TD>
                <TD>
                  <div className="flex items-center gap-2">
                    <Input
                      value={draft}
                      aria-label={`Contact email for ${row.code}`}
                      placeholder="materials@cpse.in"
                      className="h-8 max-w-[16rem] font-mono text-xs"
                      onChange={(e) => setDrafts({ ...drafts, [row.code]: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && dirty)
                          void run(row.code, async () => {
                            await patchCpse(row.code, { contact_email: draft.trim() || null })
                            return `${row.code}'s contact email saved.`
                          })
                      }}
                    />
                    {dirty && (
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={busy !== null}
                        onClick={() =>
                          void run(row.code, async () => {
                            await patchCpse(row.code, { contact_email: draft.trim() || null })
                            return `${row.code}'s contact email saved.`
                          })
                        }
                      >
                        Save
                      </Button>
                    )}
                  </div>
                </TD>
                <TD>
                  <StatusChip tone={row.last_sent ? 'ok' : 'neutral'}>{whenSent(row)}</StatusChip>
                </TD>
                <TD>
                  <div className="flex flex-wrap items-center gap-2">
                    <a href={reportHtmlUrl(row.code)} target="_blank" rel="noreferrer">
                      <Button size="sm" variant="secondary" disabled={row.items === 0}>
                        Preview
                      </Button>
                    </a>
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={busy !== null || row.items === 0}
                      title={
                        row.contact_email
                          ? `Send to ${row.contact_email}`
                          : 'Set a contact email first.'
                      }
                      onClick={() =>
                        void run(row.code, async () => sentNote(await sendReport(row.code)))
                      }
                    >
                      {busy === row.code ? 'Sending…' : 'Send'}
                    </Button>
                  </div>
                </TD>
              </TR>
            )
          })}
        </TBody>
      </Table>
    </section>
  )
}

/** The steward's Home card: their own CPSE's report, Preview and Send. */
export function ReportCard({ cpse }: { cpse: string }) {
  const [row, setRow] = useState<ReportListing['cpses'][number] | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await getReports()
      setRow(data.cpses.find((c) => c.code === cpse) ?? null)
    } catch {
      setRow(null)
    }
  }, [cpse])

  useEffect(() => {
    void load()
  }, [load])

  if (!row) return null

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 card p-6" data-testid="report-card">
      <div className="max-w-prose space-y-1">
        <p className="micro-label">Your catalogue report</p>
        <p className="text-sm text-ink">
          What SAMAN found in {row.code}'s catalogue and what it is worth to you, on one page.
        </p>
        <p className="text-xs text-muted">
          Last sent {whenSent(row)}
          {row.contact_email ? ` · goes to ${row.contact_email}` : ' · no contact email set'}
        </p>
        {message && (
          <p role="status" className={`text-xs ${message.tone === 'ok' ? 'text-ok' : 'text-danger'}`}>
            {message.text}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <a href={reportHtmlUrl(row.code)} target="_blank" rel="noreferrer">
          <Button variant="secondary">Preview</Button>
        </a>
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            setMessage(null)
            sendReport(row.code)
              .then((result) => {
                setMessage({ tone: 'ok', text: sentNote(result) })
                return load()
              })
              .catch((err) =>
                setMessage({
                  tone: 'danger',
                  text: err instanceof ApiError ? err.message : 'That did not work.',
                }),
              )
              .finally(() => setBusy(false))
          }}
        >
          {busy ? 'Sending…' : 'Send'}
        </Button>
      </div>
    </div>
  )
}
