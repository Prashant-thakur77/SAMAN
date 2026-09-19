import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { CodeChip, StatusChip } from '../components/primitives/Chip'
import { EmptyState } from '../components/primitives/EmptyState'
import { Input } from '../components/primitives/Field'
import {
  ApiError,
  bindBin,
  getCountSession,
  getPlants,
  postCount,
  reportWrongItem,
  scanLookup,
  smartCreateScan,
  type CountSession,
  type ScanEquipment,
  type ScanMaterial,
  type ScanResult,
  type ScanSubstitute,
} from '../lib/api'
import { cn } from '../lib/cn'
import { downloadCsv, rowsToCsv } from '../lib/csv'
import { useHealth } from '../lib/useHealth'
import { useSession } from '../lib/session'

/**
 * /scan — what a code names (spec §5, the floor).
 *
 * One question from a bin, a plant floor or the store gate: what is this
 * thing, do we hold it under any name in any CPSE, and what is its national
 * code. Three ways in — a typed or gun-scanned code, the phone's camera on a
 * barcode, a photograph of a nameplate read by OCR — and one lookup behind
 * them. The server resolves; it does not guess. Several materials sharing a
 * part number are put to the person to choose by the attribute that differs.
 */
/** The last scans on this device: what was scanned, when, and what it was. */
type ScanRecord = { code: string; at: number; found: boolean; label: string | null }
const HISTORY_KEY = 'saman.scan.history'
const HISTORY_MAX = 12

function readHistory(): ScanRecord[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    const list = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(list) ? (list as ScanRecord[]).filter((r) => r && typeof r.code === 'string') : []
  } catch {
    return []
  }
}

function pushHistory(record: ScanRecord): ScanRecord[] {
  const next = [record, ...readHistory().filter((r) => r.code !== record.code)].slice(0, HISTORY_MAX)
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  } catch {
    /* a phone in private mode still scans */
  }
  return next
}

function labelFor(result: ScanResult): string | null {
  const m = result.materials[0]
  if (result.equipment.length > 0) return `equipment · ${result.equipment.length} site${result.equipment.length === 1 ? '' : 's'}`
  if (!m) return null
  if (result.materials.length > 1) return `${result.materials.length} materials share this code`
  return m.cnmc ?? m.std_description ?? m.members[0]?.description ?? null
}

/** Counts taken with no signal wait here until it returns; then they post in order. */
type QueuedCount = { session_id: string; code: string; counted_qty: number; plant: string; at: number }
const QUEUE_KEY = 'saman.scan.count-queue'

function readQueue(): QueuedCount[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY)
    const list = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(list) ? (list as QueuedCount[]) : []
  } catch {
    return []
  }
}

function writeQueue(queue: QueuedCount[]) {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue))
  } catch {
    /* nothing to be done; the count is still on screen */
  }
}

/** One walk through the store: a session id kept on the device until "New walk". */
const SESSION_KEY = 'saman.scan.count-session'

function newSession(): string {
  const d = new Date()
  const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}-${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`
  return `walk-${stamp}`
}

function readSession(): string {
  try {
    return localStorage.getItem(SESSION_KEY) || newSession()
  } catch {
    return newSession()
  }
}

export default function Scan() {
  const [code, setCode] = useState('')
  const [result, setResult] = useState<ScanResult | null>(null)
  const [chosen, setChosen] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<ScanRecord[]>(() => readHistory())
  // Stock-count mode: the storekeeper's real daily job. Scan, count, next.
  const [mode, setMode] = useState<'lookup' | 'count'>('lookup')
  const [plants, setPlants] = useState<string[]>([])
  const [plant, setPlant] = useState('')
  const [session, setSession] = useState(() => readSession())
  const [walk, setWalk] = useState<CountSession | null>(null)
  const [queued, setQueued] = useState<QueuedCount[]>(() => readQueue())
  const [online, setOnline] = useState(() => (typeof navigator === 'undefined' ? true : navigator.onLine))
  const field = useRef<HTMLInputElement>(null)
  const { user: me } = useSession()

  // Counts taken offline post themselves, in order, when the signal returns.
  const flushQueue = useCallback(async () => {
    const pending = readQueue()
    if (pending.length === 0) return
    const rest = [...pending]
    while (rest.length) {
      const next = rest[0]
      try {
        await postCount(next)
        rest.shift()
        writeQueue(rest)
        setQueued([...rest])
      } catch (err) {
        // Unreachable still: keep the queue as it is and try later. A refused
        // line (an unknown code) would block the rest, so drop it and say so.
        if (err instanceof ApiError && err.status !== 0) {
          rest.shift()
          writeQueue(rest)
          setQueued([...rest])
          setError(`A queued count for ${next.code} was refused: ${err.message}`)
          continue
        }
        return
      }
    }
    getCountSession(session).then(setWalk).catch(() => undefined)
  }, [session])

  useEffect(() => {
    const up = () => {
      setOnline(true)
      void flushQueue()
    }
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    if (navigator.onLine) void flushQueue()
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [flushQueue])

  // Plants are remembered on the device so the count screen still has them
  // in a store with no signal.
  useEffect(() => {
    if (!me?.cpse_code) return
    try {
      const cached = JSON.parse(localStorage.getItem('saman.scan.plants') ?? '[]') as string[]
      if (cached.length) {
        setPlants(cached)
        setPlant((p) => p || localStorage.getItem('saman.scan.plant') || cached[0] || '')
      }
    } catch {
      /* fall through to the API */
    }
    getPlants()
      .then((r) => {
        setPlants(r.plants)
        setPlant((p) => p || r.plants[0] || '')
        try {
          localStorage.setItem('saman.scan.plants', JSON.stringify(r.plants))
        } catch {
          /* fine */
        }
      })
      .catch(() => undefined)
  }, [me?.cpse_code])

  useEffect(() => {
    try {
      if (plant) localStorage.setItem('saman.scan.plant', plant)
    } catch {
      /* fine */
    }
  }, [plant])

  useEffect(() => {
    try {
      localStorage.setItem(SESSION_KEY, session)
    } catch {
      /* the walk still counts */
    }
    if (mode === 'count') getCountSession(session).then(setWalk).catch(() => setWalk(null))
  }, [session, mode])

  const lookup = useCallback(async (raw: string) => {
    const query = raw.trim()
    if (!query) return
    setBusy(true)
    setError(null)
    setChosen(null)
    try {
      const found = await scanLookup(query)
      setResult(found)
      setHistory(
        pushHistory({
          code: query,
          at: Date.now(),
          found: found.materials.length > 0 || found.equipment.length > 0,
          label: labelFor(found),
        }),
      )
    } catch (err) {
      setResult(null)
      setError(err instanceof ApiError ? err.message : 'The lookup did not work.')
    } finally {
      setBusy(false)
    }
  }, [])

  // The gun types into whatever has focus, so the field takes it a frame
  // after mount: later than `autoFocus`, and later than the route announcer
  // moving focus to the main landmark on the same navigation.
  useEffect(() => {
    const id = requestAnimationFrame(() => field.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [])

  // A barcode gun scans many parts in a row: after every answer the field
  // keeps focus with its text selected, so the next scan replaces the last.
  useEffect(() => {
    if (!result && !error) return
    // In a stock count the answer is followed by a quantity, so the count
    // bar takes focus instead; the code field gets it back after "Record".
    if (mode === 'count' && result && result.materials.length > 0) return
    const el = field.current
    if (!el) return
    el.focus()
    el.select()
  }, [result, error, mode])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!busy) void lookup(code)
  }

  const scanAgain = () => {
    setResult(null)
    setError(null)
    setCode('')
    field.current?.focus()
  }

  const decoded = (text: string) => {
    setCode(text)
    void lookup(text)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <PageHeader
        section="Tools"
        title="Scan"
        description="What is this part, do we already hold it under any name in any CPSE, and what is its national code. A barcode, a bin label, a GTIN or a part number all resolve here."
      />

      {me?.cpse_code && (
        <div className="flex flex-wrap items-center gap-2">
          {(['lookup', 'count'] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                'h-9 rounded-full border px-4 text-sm',
                mode === m ? 'border-inverse bg-inverse text-bg' : 'border-hairline text-muted hover:text-ink',
              )}
            >
              {m === 'lookup' ? 'Look up' : 'Stock count'}
            </button>
          ))}
          {mode === 'count' && (
            <>
              <select
                aria-label="Plant"
                value={plant}
                onChange={(e) => setPlant(e.target.value)}
                className="h-9 rounded-full border border-hairline bg-surface px-3 text-sm"
              >
                {plants.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              <span className="font-mono text-xs text-muted">{session}</span>
              <button
                type="button"
                className="text-xs text-muted underline-offset-2 hover:underline"
                onClick={() => {
                  setSession(newSession())
                  setWalk(null)
                }}
              >
                new walk
              </button>
            </>
          )}
        </div>
      )}

      <section className="space-y-4 card p-4 sm:p-6">
        <form onSubmit={submit} className="space-y-2">
          <label htmlFor="scan-code" className="micro-label block">
            {mode === 'count' ? 'Scan the bin label or the part' : 'Code'}
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              ref={field}
              id="scan-code"
              value={code}
              autoFocus
              inputMode="text"
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
              placeholder="BRNG-010-000001-3"
              className="h-12 font-mono text-base"
              onChange={(e) => setCode(e.target.value)}
            />
            <Button
              type="submit"
              variant="primary"
              disabled={busy || !code.trim()}
              className="h-12 shrink-0 sm:px-6"
            >
              {busy ? 'Looking…' : 'Look up'}
            </Button>
          </div>
          <p className="text-sm text-muted">
            Type a code, or point a barcode scanner here and pull the trigger.
          </p>
        </form>

        <div className="flex flex-col gap-3 border-t border-hairline pt-4 sm:flex-row sm:flex-wrap">
          <CameraScanner disabled={busy} onDecoded={decoded} />
          <NameplateReader disabled={busy} />
          <PhotoDecoder disabled={busy} onDecoded={decoded} />
        </div>
      </section>

      {error && (
        <p role="status" className="border border-hairline px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      {result && mode === 'count' && result.materials.length > 0 && plant && (
        <CountBar
          key={result.query}
          result={result}
          chosen={chosen}
          plant={plant}
          session={session}
          disabled={busy}
          onRecorded={(next) => {
            setWalk(next)
            scanAgain()
          }}
          onQueued={(line) => {
            const next = [...readQueue(), line]
            writeQueue(next)
            setQueued(next)
            scanAgain()
          }}
        />
      )}

      {result && (
        <>
          <ScanOutcome
            result={result}
            chosen={chosen}
            onChoose={setChosen}
            onScanAgain={scanAgain}
            onLookup={decoded}
          />
          {(result.materials.length > 0 || result.equipment.length > 0) && (
            <WrongItem result={result} chosen={chosen} />
          )}
          {mode === 'count' && result.materials.length > 0 && plant && (
            <BindBin result={result} plant={plant} />
          )}
        </>
      )}

      {mode === 'count' && (queued.length > 0 || !online) && (
        <p role="status" className="border border-hairline bg-surface px-4 py-2 text-sm">
          {online ? '' : 'No signal. '}
          {queued.length > 0
            ? `${queued.length} count${queued.length === 1 ? '' : 's'} waiting on this device; they post in order when the signal returns.`
            : 'Counts you take now are kept on this device and post when it returns.'}
        </p>
      )}

      {mode === 'count' && walk && walk.lines.length > 0 && (
        <section className="space-y-2" aria-label="This walk">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="micro-label">This walk · {walk.totals.lines} lines</h2>
            <p className="font-mono text-xs text-muted">
              {walk.totals.exact} exact · {walk.totals.over} over · {walk.totals.short} short
              {walk.totals.unknown_to_system > 0 && ` · ${walk.totals.unknown_to_system} not in the system here`}
              {' · '}
              <button
                type="button"
                className="underline-offset-2 hover:text-ink hover:underline"
                title="This walk's lines with their variances, as a CSV file for reconciliation"
                onClick={() =>
                  downloadCsv(
                    walk.session_id,
                    rowsToCsv(
                      walk.lines.map((l) => ({
                        counted_at: l.counted_at,
                        plant: l.plant,
                        bin: l.bin_code ?? '',
                        code: l.code,
                        legacy_code: l.legacy_code ?? '',
                        description: l.description ?? '',
                        counted: l.counted_qty,
                        system: l.system_qty ?? '',
                        variance: l.variance ?? '',
                        note: l.note ?? '',
                      })),
                    ),
                  )
                }
              >
                CSV ↓
              </button>
            </p>
          </div>
          <ul className="card divide-y divide-hairline">
            {[...walk.lines].reverse().map((line) => (
              <li key={line.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                <span className="font-mono text-xs">{line.bin_code ?? line.code}</span>
                <span className="min-w-0 flex-1 truncate text-muted">{line.description ?? line.legacy_code}</span>
                <span className="font-mono text-xs tabular-nums">
                  {line.counted_qty} / {line.system_qty ?? '—'}
                </span>
                <span
                  className={cn(
                    'w-14 text-right font-mono text-xs tabular-nums',
                    line.variance === null ? 'text-muted' : line.variance === 0 ? 'text-ok' : 'text-danger',
                  )}
                >
                  {line.variance === null ? '?' : line.variance > 0 ? `+${line.variance}` : line.variance}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">{walk.note}</p>
        </section>
      )}

      {!result && history.length > 0 && (
        <section className="space-y-2" aria-label="Recent scans">
          <div className="flex items-center justify-between">
            <h2 className="micro-label">Recent scans on this device</h2>
            <button
              type="button"
              className="text-xs text-muted underline-offset-2 hover:underline"
              onClick={() => {
                try {
                  localStorage.removeItem(HISTORY_KEY)
                } catch {
                  /* nothing to clear */
                }
                setHistory([])
              }}
            >
              clear
            </button>
          </div>
          <ul className="card divide-y divide-hairline">
            {history.map((entry) => (
              <li key={entry.code}>
                <button
                  type="button"
                  onClick={() => decoded(entry.code)}
                  className="flex h-12 w-full items-center gap-3 px-4 text-left hover:bg-bg"
                >
                  <span className="font-mono text-sm">{entry.code}</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-muted">
                    {entry.found ? (entry.label ?? 'found') : 'nothing carried that code'}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] text-muted">
                    {new Date(entry.at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/** The scan resolved, but the part in hand is not the one on screen. */
function WrongItem({ result, chosen }: { result: ScanResult; chosen: number | null }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const material = result.materials[chosen ?? 0]

  // A new lookup is a new question; the last report does not carry over.
  useEffect(() => {
    setOpen(false)
    setNote('')
    setState('idle')
    setMessage(null)
  }, [result])

  async function send() {
    setState('sending')
    try {
      const reply = await reportWrongItem({
        code: result.query,
        matched_by: result.matched_by,
        cluster_id: material?.cluster_id ?? null,
        item_id: material?.members[0]?.item_id ?? null,
        cnmc: material?.cnmc ?? null,
        note: note.trim() || undefined,
      })
      setState('sent')
      setMessage(reply.note)
    } catch (err) {
      setState('failed')
      setMessage(err instanceof ApiError ? err.message : 'The report could not be sent.')
    }
  }

  if (state === 'sent') {
    return (
      <p role="status" className="text-sm text-muted">
        Reported. {message}
      </p>
    )
  }
  return (
    <div className="space-y-2">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="h-11 text-sm text-muted underline underline-offset-4 hover:text-ink"
        >
          Wrong item? The part in hand is not this one
        </button>
      ) : (
        <div className="card space-y-3 p-4">
          <p className="text-sm">
            Tell the steward what you are holding instead. The record is not changed by this;
            the report goes on the ledger with the code and what it resolved to.
          </p>
          <Input
            aria-label="What is in hand"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. the bin holds the 30 mm bore, the label says 25 mm"
            className="h-11"
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" className="h-11" disabled={state === 'sending'} onClick={() => void send()}>
              {state === 'sending' ? 'Sending…' : 'Report'}
            </Button>
            <Button variant="ghost" className="h-11" onClick={() => setOpen(false)}>
              Never mind
            </Button>
            {state === 'failed' && <span className="text-sm text-danger">{message}</span>}
          </div>
        </div>
      )}
    </div>
  )
}

// ---- the result area -------------------------------------------------------

function ScanOutcome({
  result,
  chosen,
  onChoose,
  onScanAgain,
  onLookup,
}: {
  result: ScanResult
  chosen: number | null
  onChoose: (index: number | null) => void
  onScanAgain: () => void
  onLookup: (code: string) => void
}) {
  const { materials } = result
  const equipment = result.equipment ?? []

  if (equipment.length > 0) {
    const single = equipment.length === 1 || chosen !== null
    return (
      <div className="space-y-3">
        {single && chosen !== null && (
          <button
            type="button"
            onClick={() => onChoose(null)}
            className="h-11 text-sm text-muted underline underline-offset-4 hover:text-ink"
          >
            ← Back to the {equipment.length} sites that use this tag
          </button>
        )}
        {single ? (
          <EquipmentCard equipment={equipment[chosen ?? 0]} onLookup={onLookup} />
        ) : (
          <SiteChooser result={result} onChoose={onChoose} />
        )}
        <MatchedBy result={result} />
      </div>
    )
  }

  if (materials.length === 0) {
    return (
      <div className="space-y-3">
        <EmptyState
          title={result.tried === 'cnmc' ? 'Scan it again' : 'Nothing carries that code'}
          description={result.note}
          action={
            <div className="flex flex-wrap gap-3">
              {result.tried === 'cnmc' && (
                <Button variant="primary" className="h-11" onClick={onScanAgain}>
                  Scan again
                </Button>
              )}
              {result.next.action === 'smart_create' && result.next.to && (
                <Link
                  to={result.next.to}
                  className={cn(
                    'inline-flex h-11 items-center justify-center rounded-full border px-4 text-sm font-medium',
                    result.tried === 'cnmc'
                      ? 'border-hairline bg-surface text-ink hover:bg-bg'
                      : 'border-inverse bg-inverse text-bg hover:opacity-90',
                  )}
                >
                  Check it as a description in Smart-Create
                </Link>
              )}
            </div>
          }
        />
        <MatchedBy result={result} />
      </div>
    )
  }

  if (materials.length === 1 || chosen !== null) {
    const material = materials[chosen ?? 0]
    const to =
      chosen === null
        ? result.next.to
        : material.cluster_id !== null
          ? `/clusters/${material.cluster_id}`
          : `/items/${material.members[0]?.item_id}`
    return (
      <div className="space-y-3">
        {chosen !== null && (
          <button
            type="button"
            onClick={() => onChoose(null)}
            className="h-11 text-sm text-muted underline underline-offset-4 hover:text-ink"
          >
            ← Back to the {materials.length} that share this code
          </button>
        )}
        <MaterialCard material={material} to={to} />
        <MatchedBy result={result} />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <Chooser result={result} onChoose={onChoose} />
      <MatchedBy result={result} />
    </div>
  )
}

const METHOD_NAMES: Record<NonNullable<ScanResult['matched_by']>, string> = {
  cnmc: 'the national code',
  legacy_code: "a CPSE's own material code",
  gtin: 'the GTIN',
  mpn: "the manufacturer's part number",
  bin: 'a bin label bound to this material',
  equipment_tag: 'the equipment tag',
}

function MatchedBy({ result }: { result: ScanResult }) {
  return (
    <p className="text-sm text-muted">
      {result.matched_by ? `Matched by ${METHOD_NAMES[result.matched_by]}` : 'Nothing matched'}
      {' · '}
      <span className="font-mono">{result.query}</span>
    </p>
  )
}

// ---- one material ----------------------------------------------------------

function MaterialCard({ material, to }: { material: ScanMaterial; to: string | null }) {
  const { user } = useSession()
  const own = user?.cpse_code ?? null

  const members = [...material.members].sort(
    (a, b) => Number(b.scanned) - Number(a.scanned) || a.cpse.localeCompare(b.cpse),
  )
  // The signed-in person's own CPSE first: it is the shelf they can walk to.
  const positions = [...(material.stock?.positions ?? [])].sort(
    (a, b) => Number(b.cpse === own) - Number(a.cpse === own) || a.cpse.localeCompare(b.cpse),
  )
  const approved = dedupe(material.substitutes.filter((s) => s.status === 'approved'))
  const proposed = dedupe(material.substitutes.filter((s) => s.status === 'proposed'))

  return (
    <article className="card divide-y divide-hairline" data-testid="scan-material">
      <header className="space-y-3 p-4 sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          {material.cnmc ? (
            <CodeChip code={material.cnmc} className="text-sm" />
          ) : (
            <StatusChip tone="neutral">No national code yet · in review</StatusChip>
          )}
          {material.family && <span className="micro-label">{material.family}</span>}
        </div>
        <h2 className="break-words font-mono text-base text-ink">
          {material.std_description ?? material.members[0]?.description ?? 'Unnamed material'}
        </h2>
        <p className="text-sm text-muted">
          {material.class_code}
          {material.cpses.length > 0 && ` · held by ${material.cpses.join(', ')}`}
        </p>
      </header>

      <Block title="Also called">
        <ul className="space-y-2">
          {members.map((m) => (
            <li key={m.item_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
              <span className="micro-label w-12 shrink-0">{m.cpse}</span>
              <CodeChip code={m.legacy_code} />
              <span className="min-w-0 flex-1 break-words text-muted">{m.description}</span>
              {m.scanned && <span className="text-xs text-ok">you scanned this</span>}
            </li>
          ))}
        </ul>
      </Block>

      <Block title="Where it is">
        {material.stock && positions.length > 0 ? (
          <div className="space-y-3">
            <p className="text-sm">
              <span className="font-mono">{qty(material.stock.total_qty)}</span> on hand across{' '}
              {material.stock.plant_count} {material.stock.plant_count === 1 ? 'plant' : 'plants'}
            </p>
            <ul className="space-y-2">
              {positions.map((p) => (
                <li
                  key={`${p.cpse}-${p.plant}`}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm"
                >
                  <span className="micro-label w-12 shrink-0">
                    {p.cpse}
                    {p.cpse === own && <span className="sr-only"> (your CPSE)</span>}
                  </span>
                  <span className="min-w-0 flex-1">{p.plant}</span>
                  <span className="font-mono">
                    {qty(p.available)}
                    <span className="text-muted"> of {qty(p.qty_on_hand)}</span>
                  </span>
                  <span className="w-24 text-right font-mono">
                    {p.value_withheld ? (
                      <span className="text-muted">withheld</span>
                    ) : p.value !== null ? (
                      rupees(p.value)
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-muted">No stock position recorded.</p>
        )}
      </Block>

      <Block title="Fitted to">
        {material.installed_on.length > 0 ? (
          <ul className="space-y-2">
            {material.installed_on.map((fit) => (
              <li
                key={`${fit.cpse}-${fit.tag}`}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
              >
                <span className="micro-label w-12 shrink-0">{fit.cpse}</span>
                <span className="font-mono">{fit.tag}</span>
                <span className="min-w-0 flex-1 text-muted">{fit.description}</span>
                <StatusChip tone="neutral">
                  {fit.criticality} · {CRITICALITY[fit.criticality] ?? fit.ved ?? 'unrated'}
                </StatusChip>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Not on any equipment BOM.</p>
        )}
      </Block>

      <Block title="Approved substitutes">
        {approved.length === 0 && proposed.length === 0 && (
          <p className="text-sm text-muted">No substitute has been proposed for this material.</p>
        )}
        {approved.length > 0 && (
          <ul className="space-y-3">
            {approved.map((s) => (
              <li key={s.relation_id} className="space-y-1 text-sm">
                <SubstituteLine substitute={s} />
                {s.approval?.reason && (
                  <p className="text-sm text-muted">
                    {s.approval.decided_by ?? 'An engineer'}: {s.approval.reason}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {approved.length === 0 && proposed.length > 0 && (
          <p className="text-sm text-muted">None approved yet.</p>
        )}
        {proposed.length > 0 && (
          <div className="space-y-2 pt-3">
            <p className="micro-label">Proposed, not yet approved</p>
            <ul className="space-y-1 text-muted">
              {proposed.map((s) => (
                <li key={s.relation_id} className="text-sm">
                  <SubstituteLine substitute={s} muted />
                </li>
              ))}
            </ul>
          </div>
        )}
      </Block>

      <footer className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 sm:p-6">
        {to && (
          <Link
            to={to}
            className="inline-flex h-11 items-center text-sm font-medium text-ink underline underline-offset-4"
          >
            Open the full record
          </Link>
        )}
        {material.cnmc && (
          <Link
            to={`/labels/${material.cnmc}`}
            className="inline-flex h-11 items-center text-sm text-muted underline underline-offset-4 hover:text-ink"
          >
            Print a label
          </Link>
        )}
      </footer>
    </article>
  )
}

const CRITICALITY: Record<string, string> = { A: 'vital', B: 'essential', C: 'desirable' }

function SubstituteLine({ substitute, muted }: { substitute: ScanSubstitute; muted?: boolean }) {
  const { other } = substitute
  const relation =
    substitute.rel_type === 'supersedes'
      ? substitute.direction === 'b_to_a'
        ? 'supersedes this'
        : 'superseded by this'
      : 'equivalent'
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {other.cpse && <span className="micro-label">{other.cpse}</span>}
        {(other.cnmc || other.legacy_code) && (
          <CodeChip code={other.cnmc ?? other.legacy_code ?? ''} />
        )}
        <span className="text-xs text-muted">{relation}</span>
      </div>
      <Link
        to={`/items/${other.item_id}`}
        className={cn(
          'block break-words underline-offset-4 hover:underline',
          muted ? 'text-muted' : 'text-ink',
        )}
      >
        {other.description ?? other.normalized ?? `item ${other.item_id}`}
      </Link>
    </div>
  )
}

/** The server returns one relation per member; the person wants one row per
 *  other material. */
function dedupe(subs: ScanSubstitute[]): ScanSubstitute[] {
  const seen = new Set<string>()
  return subs.filter((s) => {
    const key = `${s.other.item_id}-${s.rel_type}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 p-4 sm:p-6">
      <h3 className="micro-label">{title}</h3>
      {children}
    </section>
  )
}

// ---- a piece of equipment: the maintenance engineer's starting point --------

/** "Scan the pump, see its spares": one tag at one site, with what is fitted
 *  to it and where each spare is held. A row is a lookup of that spare. */
function EquipmentCard({
  equipment,
  onLookup,
}: {
  equipment: ScanEquipment
  onLookup: (code: string) => void
}) {
  return (
    <article className="card divide-y divide-hairline" data-testid="scan-equipment">
      <header className="space-y-3 p-4 sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-lg text-ink">{equipment.tag}</span>
          <span className="micro-label">{equipment.cpse}</span>
          <StatusChip tone="neutral">
            {equipment.criticality} ·{' '}
            {CRITICALITY[equipment.criticality] ?? equipment.ved ?? 'unrated'}
          </StatusChip>
        </div>
        <h2 className="text-base text-ink">{equipment.description}</h2>
      </header>
      <section className="space-y-3 p-4 sm:p-6">
        <h3 className="micro-label">
          Spares · {equipment.spares.length}
        </h3>
        {equipment.spares.length === 0 ? (
          <p className="text-sm text-muted">No spare is recorded on this equipment's BOM.</p>
        ) : (
          <ul className="-mx-2 divide-y divide-hairline">
            {equipment.spares.map((spare) => (
              <li key={spare.item_id}>
                <button
                  type="button"
                  onClick={() => onLookup(spare.cnmc ?? spare.legacy_code)}
                  className="flex min-h-[44px] w-full flex-col gap-1 rounded-lg px-2 py-3 text-left hover:bg-bg focus-visible:bg-bg"
                  aria-label={`Look up ${spare.cnmc ?? spare.legacy_code}`}
                >
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {spare.cnmc ? (
                      <CodeChip code={spare.cnmc} />
                    ) : (
                      <span className="micro-label">no code</span>
                    )}
                    <span className="font-mono text-xs text-muted">{spare.legacy_code}</span>
                    <span className="text-xs text-muted">fitted ×{qty(spare.qty_fitted)}</span>
                  </span>
                  <span className="break-words text-sm text-ink">{spare.description}</span>
                  <span className="font-mono text-xs text-muted">
                    here {qty(spare.stock_here)} ·{' '}
                    {spare.stock_elsewhere > 0
                      ? `elsewhere ${qty(spare.stock_elsewhere)} at ${spare.cpses_elsewhere} ${
                          spare.cpses_elsewhere === 1 ? 'CPSE' : 'CPSEs'
                        }`
                      : 'none elsewhere'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  )
}

/** A tag is local to a plant: the same tag names different plant at each
 *  CPSE, so the person chooses the site. Own CPSE is already first. */
function SiteChooser({
  result,
  onChoose,
}: {
  result: ScanResult
  onChoose: (index: number) => void
}) {
  return (
    <section className="space-y-3" data-testid="scan-site-chooser">
      <p className="max-w-prose text-sm text-muted">{result.note}</p>
      <ul className="card divide-y divide-hairline">
        {result.equipment.map((equipment, index) => (
          <li key={equipment.id}>
            <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:p-5">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="micro-label">{equipment.cpse}</span>
                  <StatusChip tone="neutral">
                    {equipment.criticality} ·{' '}
                    {CRITICALITY[equipment.criticality] ?? equipment.ved ?? 'unrated'}
                  </StatusChip>
                </div>
                <p className="text-sm text-ink">{equipment.description}</p>
                <p className="text-xs text-muted">
                  {equipment.spares.length} {equipment.spares.length === 1 ? 'spare' : 'spares'}
                </p>
              </div>
              <Button
                variant="secondary"
                className="h-11 shrink-0"
                onClick={() => onChoose(index)}
              >
                This site
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---- several materials -----------------------------------------------------

function Chooser({
  result,
  onChoose,
}: {
  result: ScanResult
  onChoose: (index: number) => void
}) {
  return (
    <section className="space-y-3" data-testid="scan-chooser">
      <p className="max-w-prose text-sm text-muted">{result.note}</p>
      <ul className="card divide-y divide-hairline">
        {result.materials.map((material, index) => (
          <li key={material.cluster_id ?? `item-${material.members[0]?.item_id ?? index}`}>
            <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:p-5">
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  {material.cnmc ? (
                    <CodeChip code={material.cnmc} />
                  ) : (
                    <span className="micro-label">no code</span>
                  )}
                  <span className="micro-label">{material.cpses.join(' · ')}</span>
                </div>
                <p className="break-words font-mono text-sm">{material.std_description}</p>
                <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  {result.differs_on.map((key) => {
                    const shown = formatAttr(key, material.attrs[key])
                    return (
                      <div key={key} className="flex gap-1">
                        <dt className="text-muted">{shown.label}</dt>
                        <dd className="font-mono">{shown.value}</dd>
                      </div>
                    )
                  })}
                </dl>
              </div>
              <Button
                variant="secondary"
                className="h-11 shrink-0 sm:self-center"
                onClick={() => onChoose(index)}
              >
                This one
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** `load_rating_kg: 640` → { label: 'Load rating', value: '640 kg' }. The unit
 *  suffix on an attribute key is the unit of its value. */
const UNITS: Record<string, string> = {
  mm: 'mm',
  cm: 'cm',
  m: 'm',
  kg: 'kg',
  g: 'g',
  c: '°C',
  v: 'V',
  a: 'A',
  w: 'W',
  kw: 'kW',
  bar: 'bar',
  l: 'L',
  pct: '%',
  rpm: 'rpm',
}

export function formatAttr(key: string, value: unknown): { label: string; value: string } {
  const parts = key.split('_')
  const last = parts[parts.length - 1]
  const unit = parts.length > 1 ? UNITS[last] : undefined
  const words = unit ? parts.slice(0, -1) : parts
  const label = words.join(' ').replace(/^./, (c) => c.toUpperCase())
  if (value === null || value === undefined || value === '') return { label, value: '—' }
  const shown =
    typeof value === 'number'
      ? value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
      : String(value)
  return { label, value: unit ? `${shown} ${unit}` : shown }
}

const qty = (n: number) => n.toLocaleString('en-IN', { maximumFractionDigits: 1 })
const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`

// ---- the camera ------------------------------------------------------------

type CameraState = 'off' | 'starting' | 'on' | 'denied' | 'failed'

/**
 * A live viewfinder decoding barcodes and QR codes continuously. The decoder
 * is loaded on first use so the main bundle does not carry it; the button is
 * absent where there is no camera API at all (plain http on a LAN).
 */
function CameraScanner({
  disabled,
  onDecoded,
}: {
  disabled: boolean
  onDecoded: (text: string) => void
}) {
  const [state, setState] = useState<CameraState>('off')
  // Dim stores: the back camera's light, where the browser lets a page turn
  // it on (Chrome on Android does; iOS Safari does not, and shows no button).
  const [torch, setTorch] = useState<'unknown' | 'off' | 'on' | 'none'>('unknown')
  const video = useRef<HTMLVideoElement>(null)
  const controls = useRef<{ stop: () => void } | null>(null)
  const supported =
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function'

  const videoTrack = () => {
    const stream = video.current?.srcObject as MediaStream | null | undefined
    return stream && typeof stream.getVideoTracks === 'function' ? stream.getVideoTracks()[0] : undefined
  }

  const toggleTorch = async () => {
    const track = videoTrack()
    if (!track) return
    const next = torch !== 'on'
    try {
      await track.applyConstraints({ advanced: [{ torch: next } as MediaTrackConstraintSet] })
      setTorch(next ? 'on' : 'off')
    } catch {
      setTorch('none')
    }
  }

  const stop = useCallback(() => {
    controls.current?.stop()
    controls.current = null
    // Duck-typed: `MediaStream` is not a global everywhere the screen renders.
    const stream = video.current?.srcObject as MediaStream | null | undefined
    if (stream && typeof stream.getTracks === 'function') stream.getTracks().forEach((t) => t.stop())
    if (video.current) video.current.srcObject = null
  }, [])

  useEffect(() => {
    if (state !== 'starting') return
    let cancelled = false
    ;(async () => {
      try {
        const { BrowserMultiFormatReader } = await import('@zxing/browser')
        const el = video.current
        if (!el || cancelled) return
        const reader = new BrowserMultiFormatReader()
        // No device id: the reader asks for `{ facingMode: 'environment' }`,
        // the back camera on a phone.
        const c = await reader.decodeFromVideoDevice(undefined, el, (found, _err, ctl) => {
          if (!found) return
          ctl.stop()
          controls.current = null
          stop()
          if (typeof navigator.vibrate === 'function') navigator.vibrate(40)
          setState('off')
          onDecoded(found.getText())
        })
        if (cancelled) {
          c.stop()
          return
        }
        controls.current = c
        setState('on')
        // Ask the track, once it is live, whether it has a light at all.
        const track = videoTrack()
        const caps = track && typeof track.getCapabilities === 'function' ? track.getCapabilities() : undefined
        setTorch(caps && (caps as MediaTrackCapabilities & { torch?: boolean }).torch ? 'off' : 'none')
      } catch (err) {
        if (cancelled) return
        const name = err instanceof Error ? err.name : ''
        setState(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'failed')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [state, stop, onDecoded])

  useEffect(() => stop, [stop])

  if (!supported) return null

  const live = state === 'starting' || state === 'on'
  return (
    <div className={cn('flex flex-col items-stretch gap-3 sm:items-start', live && 'w-full')}>
      {!live && (
        <Button
          variant="secondary"
          className="h-11 w-full sm:w-auto"
          disabled={disabled}
          onClick={() => setState('starting')}
        >
          Scan with the camera
        </Button>
      )}
      {state === 'denied' && (
        <p className="text-sm text-danger">Allow the camera, or type the code.</p>
      )}
      {state === 'failed' && (
        <p className="text-sm text-danger">The camera could not start. Type the code instead.</p>
      )}
      {live && (
        <div className="w-full space-y-3">
          <div className="relative w-full overflow-hidden rounded-lg border border-hairline bg-ink">
            {/* The stream is muted and inline so iOS does not go full-screen. */}
            <video
              ref={video}
              muted
              playsInline
              autoPlay
              aria-label="Camera viewfinder"
              className="block aspect-[4/3] w-full object-cover"
            />
            {/* The frame sits on a camera image, not the page, so it is the
                light token's white in both themes, as the label is paper. */}
            <div aria-hidden className="pointer-events-none absolute inset-4 text-[rgb(255_255_255)]">
              <span className="absolute left-0 top-0 h-6 w-6 border-l border-t border-current" />
              <span className="absolute right-0 top-0 h-6 w-6 border-r border-t border-current" />
              <span className="absolute bottom-0 left-0 h-6 w-6 border-b border-l border-current" />
              <span className="absolute bottom-0 right-0 h-6 w-6 border-b border-r border-current" />
              <span className="absolute inset-x-6 top-1/2 border-t border-current opacity-60" />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              className="h-11"
              onClick={() => {
                stop()
                setState('off')
              }}
            >
              Cancel
            </Button>
            {state === 'on' && (torch === 'off' || torch === 'on') && (
              <Button
                variant={torch === 'on' ? 'primary' : 'secondary'}
                className="h-11"
                aria-pressed={torch === 'on'}
                onClick={() => void toggleTorch()}
              >
                {torch === 'on' ? 'Torch on' : 'Torch'}
              </Button>
            )}
            <span className="text-sm text-muted">
              {state === 'starting' ? 'Starting the camera…' : 'Hold the code inside the frame.'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- a still photograph of a barcode ----------------------------------------

/** A laptop without a camera, or a photograph somebody sent: decode the still. */
function PhotoDecoder({
  disabled,
  onDecoded,
}: {
  disabled: boolean
  onDecoded: (text: string) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function decode(file: File) {
    setBusy(true)
    setMessage(null)
    const url = URL.createObjectURL(file)
    try {
      const { BrowserMultiFormatReader } = await import('@zxing/browser')
      const found = await new BrowserMultiFormatReader().decodeFromImageUrl(url)
      onDecoded(found.getText())
    } catch {
      setMessage('No barcode or QR code could be read from that photo.')
    } finally {
      URL.revokeObjectURL(url)
      setBusy(false)
    }
  }

  return (
    <div className="hidden sm:flex sm:flex-col sm:gap-2">
      <input
        ref={input}
        type="file"
        accept="image/*"
        className="sr-only"
        aria-label="Decode a photo of a barcode"
        data-testid="scan-photo-decode"
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) void decode(file)
        }}
      />
      <Button
        variant="ghost"
        className="h-11"
        disabled={disabled || busy}
        onClick={() => input.current?.click()}
      >
        {busy ? 'Decoding…' : 'Decode a photo of a barcode'}
      </Button>
      {message && <p className="text-sm text-danger">{message}</p>}
    </div>
  )
}

// ---- a nameplate, read as text ----------------------------------------------

type OcrLine = { text: string; confidence: number }
type ReaderState =
  | { phase: 'idle' }
  | { phase: 'working'; message: string }
  | { phase: 'read'; text: string; lines: OcrLine[] }
  | { phase: 'failed'; message: string }

const LOW_CONFIDENCE = 0.75

/**
 * Photograph the stamped marking and read it as text. The server's OCR reads
 * it when the API has one; otherwise tesseract.js runs in the browser from
 * files on our own origin (public/ocr), nothing from the internet. Either way
 * the text ends up in Smart-Create, the one place that shows a duplicate check.
 */
function NameplateReader({ disabled }: { disabled: boolean }) {
  const navigate = useNavigate()
  const { health } = useHealth()
  const input = useRef<HTMLInputElement>(null)
  const worker = useRef<Promise<TesseractWorker> | null>(null)
  const [state, setState] = useState<ReaderState>({ phase: 'idle' })
  const [text, setText] = useState('')
  const serverOcr = health?.capabilities.ocr?.available === true

  // The worker holds a WebAssembly engine and a language model: one per
  // screen, gone with it.
  useEffect(
    () => () => {
      void worker.current?.then((w) => w.terminate()).catch(() => undefined)
      worker.current = null
    },
    [],
  )

  async function read(file: File) {
    if (serverOcr) {
      setState({ phase: 'working', message: 'Reading…' })
      try {
        const scanned = await smartCreateScan(file)
        const seen = scanned.ocr?.text?.trim() ?? ''
        if (!seen) {
          setState({ phase: 'failed', message: 'The reader saw no text. Move closer, or type it.' })
          return
        }
        navigate(`/smart-create?description=${encodeURIComponent(seen)}`)
      } catch (err) {
        setState({
          phase: 'failed',
          message: err instanceof ApiError ? err.message : 'The reader did not answer.',
        })
      }
      return
    }

    setState({ phase: 'working', message: 'Loading the reader…' })
    try {
      const w = await getWorker(worker, (m) => setState({ phase: 'working', message: m }))
      setState({ phase: 'working', message: 'Preparing the photo…' })
      const prepared = await prepare(file)
      setState({ phase: 'working', message: 'Reading…' })
      const { data } = await w.recognize(prepared, {}, { text: true, blocks: true })
      const lines: OcrLine[] = (data.blocks ?? [])
        .flatMap((b) => b.paragraphs)
        .flatMap((p) => p.lines)
        .map((l) => ({ text: l.text.trim(), confidence: l.confidence / 100 }))
        .filter((l) => l.text.length > 0)
      const seen = lines.length > 0 ? lines.map((l) => l.text).join('\n') : data.text.trim()
      if (!seen) {
        setState({ phase: 'failed', message: 'The reader saw no text. Move closer, or type it.' })
        return
      }
      setText(seen)
      setState({ phase: 'read', text: seen, lines })
    } catch {
      worker.current = null
      setState({
        phase: 'failed',
        message: 'The reader could not start on this device. Type what the nameplate says instead.',
      })
    }
  }

  return (
    <div
      className={cn(
        'flex flex-col items-stretch gap-3 sm:items-start',
        state.phase === 'read' && 'w-full',
      )}
    >
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        aria-label="Photograph the marking"
        data-testid="scan-nameplate"
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) void read(file)
        }}
      />
      <Button
        variant="secondary"
        className="h-11 w-full sm:w-auto"
        disabled={disabled || state.phase === 'working'}
        onClick={() => input.current?.click()}
      >
        Photograph the marking
      </Button>
      {state.phase === 'working' && (
        <p role="status" className="text-sm text-muted">
          {state.message}
        </p>
      )}
      {state.phase === 'failed' && (
        <p role="status" className="text-sm text-danger">
          {state.message}
        </p>
      )}
      {state.phase === 'read' && (
        <div className="w-full space-y-3" data-testid="scan-ocr">
          <div className="space-y-2">
            <label htmlFor="scan-ocr-text" className="micro-label block">
              What the reader saw
            </label>
            <textarea
              id="scan-ocr-text"
              value={text}
              rows={Math.min(8, Math.max(3, state.lines.length + 1))}
              onChange={(e) => setText(e.target.value)}
              className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 font-mono text-sm text-ink"
            />
          </div>
          {state.lines.some((l) => l.confidence < LOW_CONFIDENCE) && (
            <ul className="flex flex-wrap gap-2">
              {state.lines.map((line, index) => (
                <li
                  key={`${line.text}-${index}`}
                  title={`${Math.round(line.confidence * 100)}% confident`}
                  className={cn(
                    'border border-hairline px-2 py-1 font-mono text-xs',
                    line.confidence < LOW_CONFIDENCE ? 'text-danger' : 'text-muted',
                  )}
                >
                  {line.text}
                  {line.confidence < LOW_CONFIDENCE && (
                    <span className="sr-only"> (uncertain)</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="text-sm text-muted">
            {state.lines.some((l) => l.confidence < LOW_CONFIDENCE)
              ? 'Lines in the warning tone read below 75% confidence. Correct the text, then check it.'
              : 'Correct anything the reader misread, then check it.'}
          </p>
          <Button
            variant="primary"
            className="h-11"
            disabled={!text.trim()}
            onClick={() =>
              navigate(`/smart-create?description=${encodeURIComponent(text.trim())}`)
            }
          >
            Check this description
          </Button>
        </div>
      )}
    </div>
  )
}

type TesseractWorker = Awaited<ReturnType<typeof import('tesseract.js').createWorker>>

/** One worker per screen, created on first use from files on our own origin. */
function getWorker(
  slot: { current: Promise<TesseractWorker> | null },
  onProgress: (message: string) => void,
): Promise<TesseractWorker> {
  if (!slot.current) {
    slot.current = (async () => {
      const { createWorker } = await import('tesseract.js')
      return createWorker('eng', 1, {
        workerPath: '/ocr/worker.min.js',
        corePath: '/ocr/tesseract-core-simd-lstm.wasm.js',
        langPath: '/ocr',
        gzip: true,
        logger: (m) => {
          const pct = Math.round((m.progress ?? 0) * 100)
          onProgress(
            m.status === 'recognizing text'
              ? `Reading… ${pct}%`
              : `Loading the reader… ${pct}%`,
          )
        },
      })
    })()
  }
  return slot.current
}

/**
 * Downscale to a longest edge of 1600 px and convert to greyscale before
 * recognising. Nameplates are stamped metal: colour is noise to the reader,
 * and a 12-megapixel photograph is slower to read and no more legible.
 */
async function prepare(file: File): Promise<Blob | File> {
  if (typeof createImageBitmap !== 'function') return file
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close()
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const px = image.data
    for (let i = 0; i < px.length; i += 4) {
      const grey = Math.round(0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2])
      px[i] = px[i + 1] = px[i + 2] = grey
    }
    ctx.putImageData(image, 0, 0)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    return blob ?? file
  } catch {
    return file
  }
}


/** Scan, count, next: the counted quantity beside what the system holds here. */
function CountBar({
  result,
  chosen,
  plant,
  session,
  disabled = false,
  onRecorded,
  onQueued,
}: {
  result: ScanResult
  chosen: number | null
  plant: string
  session: string
  /** A lookup is in flight: the bar belongs to the previous scan until it lands. */
  disabled?: boolean
  onRecorded: (walk: CountSession) => void
  /** The network was away: the line is kept on the device for later. */
  onQueued: (line: QueuedCount) => void
}) {
  const [qty, setQty] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'failed'>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const box = useRef<HTMLInputElement>(null)
  const material = result.materials[chosen ?? 0]
  const { user } = useSession()
  const here = (material?.stock?.positions ?? []).filter(
    (p) => p.cpse === user?.cpse_code && p.plant === plant,
  )
  const systemQty = here.reduce((sum, p) => sum + p.qty_on_hand, 0)

  // Keyed by the scanned code, so a new scan is a fresh bar; this only
  // moves focus to the quantity once the bar is on screen.
  useEffect(() => {
    const id = requestAnimationFrame(() => box.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [])

  if (result.materials.length > 1 && chosen === null) {
    return (
      <p className="text-sm text-muted">Several materials share this code; choose one below to count it.</p>
    )
  }

  const record = async () => {
    const n = Number(qty)
    if (disabled || !Number.isFinite(n) || n < 0) return
    setState('sending')
    try {
      await postCount({ session_id: session, code: result.query, counted_qty: n, plant })
      onRecorded(await getCountSession(session))
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        // The store has no signal: keep the line and move on to the next bin.
        onQueued({ session_id: session, code: result.query, counted_qty: n, plant, at: Date.now() })
        return
      }
      setState('failed')
      setMessage(err instanceof ApiError ? err.message : 'The count could not be recorded.')
    }
  }

  return (
    <section className="card space-y-3 p-4" aria-label="Count">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm">
          <span className="micro-label mr-2">system says</span>
          <span className="font-mono text-lg">{here.length ? systemQty : '—'}</span>
          <span className="ml-2 text-xs text-muted">
            at {plant}
            {!here.length && ' (no position here)'}
          </span>
        </p>
        {result.matched_by === 'bin' && (
          <span className="micro-label" data-testid="count-bin">
            bin {result.query}
          </span>
        )}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void record()
        }}
        className="flex flex-col gap-2 sm:flex-row"
      >
        <Input
          ref={box}
          aria-label="Counted quantity"
          inputMode="decimal"
          placeholder="Counted quantity"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          className="h-12 font-mono text-lg"
        />
        <Button
          type="submit"
          variant="primary"
          className="h-12 shrink-0 sm:px-6"
          disabled={disabled || state === 'sending' || qty === ''}
        >
          {state === 'sending' ? 'Recording…' : 'Record & next'}
        </Button>
      </form>
      {state === 'failed' && <p className="text-sm text-danger">{message}</p>}
    </section>
  )
}

/** "This bin holds this material": bind the shelf's own label once. */
function BindBin({ result, plant }: { result: ScanResult; plant: string }) {
  const [open, setOpen] = useState(false)
  const [bin, setBin] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  useEffect(() => {
    setOpen(false)
    setBin('')
    setMessage(null)
  }, [result])
  if (result.matched_by === 'bin' || result.materials.length !== 1) return null
  const bind = async () => {
    try {
      const row = await bindBin({ plant, bin_code: bin.trim(), code: result.query })
      setMessage(
        `Bin ${row.bin_code} at ${plant} now answers with ${row.legacy_code ?? 'this material'}${row.replaced ? ' (replaced an earlier binding)' : ''}.`,
      )
      setOpen(false)
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : 'The bin could not be bound.')
    }
  }
  return (
    <div className="space-y-2">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="h-11 text-sm text-muted underline underline-offset-4 hover:text-ink"
        >
          Bind a bin label to this material
        </button>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bind()
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <Input
            aria-label="Bin label"
            placeholder="Bin label, e.g. A-04-17"
            value={bin}
            onChange={(e) => setBin(e.target.value)}
            className="h-11 font-mono"
            autoFocus
          />
          <Button type="submit" variant="secondary" className="h-11" disabled={!bin.trim()}>
            Bind at {plant}
          </Button>
        </form>
      )}
      {message && (
        <p role="status" className="text-sm text-muted">
          {message}
        </p>
      )}
    </div>
  )
}
