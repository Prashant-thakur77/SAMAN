import { useCallback, useEffect, useRef, useState } from 'react'

import {
  addAttachment,
  ApiError,
  attachmentUrl,
  getAttachments,
  voidAttachment,
  type AttachmentListing,
} from '../lib/api'
import { useSession } from '../lib/session'
import { parseUtc } from '../lib/time'
import { Button } from './primitives/Button'

/**
 * Datasheets, drawings and photographs on a golden record (§6.6).
 *
 * Approvers ask for the datasheet first. Files are stored by their hash and
 * served back checked; withdrawing one voids the row and keeps the file, so
 * the audit can still find what was looked at.
 */
const CAN_ATTACH = ['steward', 'approver', 'engineer', 'registrar', 'admin']

function human(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function Attachments({ clusterId }: { clusterId: number }) {
  const { user } = useSession()
  const [listing, setListing] = useState<AttachmentListing | null>(null)
  const [kind, setKind] = useState('datasheet')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const mayAttach = Boolean(user && CAN_ATTACH.includes(user.role))

  const load = useCallback(async () => {
    try {
      setListing(await getAttachments(clusterId))
    } catch {
      setListing(null)
    }
  }, [clusterId])

  useEffect(() => {
    void load()
  }, [load])

  async function upload(file: File) {
    setBusy(true)
    setError(null)
    try {
      const result = await addAttachment(clusterId, file, kind, note.trim() || undefined)
      setListing((prev) => (prev ? { ...prev, attachments: result.attachments } : prev))
      setNote('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The file could not be attached.')
    } finally {
      setBusy(false)
    }
  }

  async function withdraw(id: number) {
    setBusy(true)
    try {
      await voidAttachment(id, 'withdrawn from the cluster page')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The attachment could not be withdrawn.')
    } finally {
      setBusy(false)
    }
  }

  if (!listing) return null

  return (
    <section className="space-y-3 card p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="micro-label">Attachments · datasheets, drawings, photographs</h2>
        <span className="text-xs text-muted">
          Stored by content hash, served back checked, withdrawn never deleted.
        </span>
      </div>

      {listing.attachments.length === 0 ? (
        <p className="text-sm text-muted">Nothing attached yet.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {listing.attachments.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <span className="micro-label w-20 shrink-0">{a.kind}</span>
              <a
                href={attachmentUrl(a.id)}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 flex-1 truncate underline underline-offset-4 hover:text-ink"
                title={`sha256 ${a.sha256}`}
              >
                {a.filename}
              </a>
              <span className="font-mono text-xs text-muted">{human(a.size)}</span>
              <span className="text-xs text-muted">
                {a.uploaded_by} · {parseUtc(a.uploaded_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                {a.note && ` · ${a.note}`}
              </span>
              {mayAttach && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void withdraw(a.id)}
                  className="text-xs text-muted underline-offset-2 hover:text-danger hover:underline"
                >
                  withdraw
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {mayAttach && (
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline pt-3">
          <select
            aria-label="Kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="h-9 rounded-full border border-hairline bg-surface px-3 text-xs"
          >
            {listing.kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <input
            aria-label="Note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional): revision, source…"
            className="h-9 min-w-[12rem] flex-1 rounded-lg border border-hairline bg-surface px-3 text-sm"
          />
          <input
            ref={picker}
            type="file"
            accept={listing.accepts.join(',')}
            className="sr-only"
            aria-label="Choose a file to attach"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) void upload(file)
            }}
          />
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => picker.current?.click()}>
            {busy ? 'Working…' : 'Attach a file'}
          </Button>
          <span className="text-xs text-muted">
            PDF or an image, up to {human(listing.max_bytes)}.
          </span>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  )
}
