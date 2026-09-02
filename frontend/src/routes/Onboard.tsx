import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { Input } from '../components/primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import {
  ApiError,
  createCpse,
  getCpses,
  getPipelineStatus,
  ingestCsv,
  runPipeline,
  type IngestReport,
  type PipelineStatus,
} from '../lib/api'
import { cn } from '../lib/cn'
import { EASE } from '../lib/motion'
import { useSession } from '../lib/session'

const FIELDS = ['legacy_code', 'description', 'uom', 'plant', 'price', 'qty_on_hand'] as const
const STEPS = ['Upload', 'Map columns', 'Dry run'] as const

/**
 * /onboard — spec §6.11.
 *
 * Three steps that slide horizontally. The dry run is the same code path as the
 * real ingest with nothing written, so what it reports is what will happen —
 * not a separate estimate that could drift from it.
 */
export default function Onboard() {
  const [step, setStep] = useState(0)
  const [direction, setDirection] = useState(1)
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [cpses, setCpses] = useState<{ code: string; name: string; items: number }[]>([])
  const [cpse, setCpse] = useState('')
  const [newCode, setNewCode] = useState('')
  const [newName, setNewName] = useState('')
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [report, setReport] = useState<IngestReport | null>(null)
  const [status, setStatus] = useState<PipelineStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const poll = useRef<number | null>(null)
  const reduce = useReducedMotion() ?? false
  const navigate = useNavigate()
  const { can } = useSession()

  useEffect(() => {
    getCpses().then((d) => setCpses(d.cpses)).catch(() => setCpses([]))
    return () => {
      if (poll.current) window.clearInterval(poll.current)
    }
  }, [])

  const go = (next: number) => {
    setDirection(next > step ? 1 : -1)
    setStep(next)
    setError(null)
  }

  async function readHeaders(chosen: File) {
    const text = await chosen.slice(0, 64_000).text()
    const first = text.split(/\r?\n/)[0] ?? ''
    const parsed = first.split(',').map((h) => h.trim().replace(/^"|"$/g, ''))
    setHeaders(parsed)
    // Pre-fill the obvious ones; the API guesses too, this just shows the guess.
    const guessed: Record<string, string> = {}
    for (const field of FIELDS) {
      const hit = parsed.find(
        (h) => h.toLowerCase().replace(/[_ ]/g, '') === field.replace(/_/g, ''),
      )
      if (hit) guessed[field] = hit
    }
    setMapping(guessed)
  }

  async function dryRun() {
    if (!file || !cpse) return
    setBusy(true)
    setError(null)
    try {
      setReport(await ingestCsv(file, cpse, true, mapping))
      go(2)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The dry run failed.')
    } finally {
      setBusy(false)
    }
  }

  const watchPipeline = useCallback(() => {
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      try {
        const next = await getPipelineStatus()
        setStatus(next)
        if (next.state !== 'running' && poll.current) {
          window.clearInterval(poll.current)
          poll.current = null
        }
      } catch {
        if (poll.current) window.clearInterval(poll.current)
      }
    }, 700)
  }, [])

  async function commit() {
    if (!file || !cpse) return
    setBusy(true)
    setError(null)
    try {
      await ingestCsv(file, cpse, false, mapping)
      await runPipeline()
      watchPipeline()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The ingest failed.')
    } finally {
      setBusy(false)
    }
  }

  const canEdit = can('registrar', 'admin', 'steward')

  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="Onboard a CPSE"
        description="Upload a catalogue, confirm how its columns map, review a dry run, then ingest and run the pipeline."
      />

      <ol className="flex flex-wrap items-center gap-1 border-b border-hairline">
        {STEPS.map((label, index) => (
          <li key={label}>
            <button
              type="button"
              onClick={() => index < step && go(index)}
              disabled={index > step}
              className={cn(
                'border-b-2 px-4 py-2 text-sm disabled:cursor-not-allowed',
                index === step
                  ? 'border-inverse font-medium text-ink'
                  : 'border-transparent text-muted',
                index < step && 'hover:text-ink',
              )}
            >
              <span className="font-mono text-xs">{index + 1}</span> {label}
            </button>
          </li>
        ))}
      </ol>

      {error && (
        <p role="alert" className="border border-hairline px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      <AnimatePresence mode="wait" initial={false} custom={direction}>
        <motion.section
          key={step}
          custom={direction}
          initial={reduce ? { opacity: 0 } : { opacity: 0, x: direction * 32 }}
          animate={{ opacity: 1, x: 0 }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, x: direction * -32 }}
          transition={{ duration: 0.24, ease: EASE }}
          className="space-y-6"
        >
          {step === 0 && (
            <>
              <div className="space-y-3">
                <label htmlFor="csv" className="micro-label block">
                  Catalogue file (CSV)
                </label>
                <input
                  id="csv"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => {
                    const chosen = e.target.files?.[0] ?? null
                    setFile(chosen)
                    setReport(null)
                    if (chosen) void readHeaders(chosen)
                  }}
                  className="block w-full border border-hairline px-3 py-2 text-sm file:mr-4 file:border-0 file:bg-inverse file:px-3 file:py-1.5 file:text-xs file:text-bg"
                />
                {file && (
                  <p className="text-xs text-muted">
                    {file.name} · {(file.size / 1024).toFixed(0)} KB · {headers.length} columns
                  </p>
                )}
              </div>

              <div className="space-y-3">
                <label htmlFor="cpse" className="micro-label block">
                  Which CPSE is this catalogue from?
                </label>
                <select
                  id="cpse"
                  value={cpse}
                  onChange={(e) => setCpse(e.target.value)}
                  className="h-10 w-full max-w-sm border border-hairline bg-bg px-3 text-sm"
                >
                  <option value="">Choose…</option>
                  {cpses.map((entry) => (
                    <option key={entry.code} value={entry.code}>
                      {entry.code} · {entry.name} ({entry.items.toLocaleString('en-IN')} rows)
                    </option>
                  ))}
                </select>
              </div>

              {canEdit && (
                <div className="space-y-3 border border-hairline p-4">
                  <p className="micro-label">Or register a new one</p>
                  <div className="flex flex-wrap gap-3">
                    <Input
                      value={newCode}
                      onChange={(e) => setNewCode(e.target.value.toUpperCase())}
                      placeholder="BPCL"
                      className="max-w-[8rem] font-mono"
                      aria-label="New CPSE code"
                    />
                    <Input
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="Bharat Petroleum Corporation Limited"
                      className="max-w-md"
                      aria-label="New CPSE name"
                    />
                    <Button
                      variant="secondary"
                      disabled={!newCode.trim() || busy}
                      onClick={async () => {
                        try {
                          const created = await createCpse(newCode.trim(), newName.trim())
                          setCpses((prev) => [...prev, { ...created, items: 0 }])
                          setCpse(created.code)
                          setNewCode('')
                          setNewName('')
                        } catch (err) {
                          setError(
                            err instanceof ApiError ? err.message : 'Could not register the CPSE.',
                          )
                        }
                      }}
                    >
                      Register
                    </Button>
                  </div>
                </div>
              )}

              <Button variant="primary" disabled={!file || !cpse} onClick={() => go(1)}>
                Next: map the columns
              </Button>
            </>
          )}

          {step === 1 && (
            <>
              <p className="max-w-prose text-sm text-muted">
                SAMAN guesses these from the header row, including SAP field names like MATNR and
                MAKTX. Correct anything it read wrongly. Only a code and a description are required.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {FIELDS.map((field) => (
                  <label key={field} className="space-y-2">
                    <span className="micro-label block">
                      {field.replace(/_/g, ' ')}
                      {['legacy_code', 'description'].includes(field) && ' · required'}
                    </span>
                    <select
                      value={mapping[field] ?? ''}
                      onChange={(e) =>
                        setMapping((prev) => ({ ...prev, [field]: e.target.value }))
                      }
                      className="h-10 w-full border border-hairline bg-bg px-3 text-sm"
                    >
                      <option value="">— not present —</option>
                      {headers.map((header) => (
                        <option key={header} value={header}>
                          {header}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <div className="flex gap-3">
                <Button variant="secondary" onClick={() => go(0)}>
                  Back
                </Button>
                <Button
                  variant="primary"
                  disabled={busy || !mapping.legacy_code || !mapping.description}
                  onClick={() => void dryRun()}
                >
                  {busy ? 'Checking…' : 'Run the dry run'}
                </Button>
              </div>
            </>
          )}

          {step === 2 && report && (
            <>
              <div className="grid gap-px border border-hairline bg-hairline sm:grid-cols-4">
                {[
                  { label: 'Rows read', value: report.rows_read },
                  { label: 'Will be ingested', value: report.rows_accepted },
                  { label: 'Rejected', value: report.rows_rejected },
                  { label: 'Already present', value: report.already_present },
                ].map((tile) => (
                  <div key={tile.label} className="space-y-1 bg-bg p-4">
                    <p className="micro-label">{tile.label}</p>
                    <p className="font-mono text-lg">{tile.value.toLocaleString('en-IN')}</p>
                  </div>
                ))}
              </div>

              {report.samples.length > 0 && (
                <div className="space-y-3">
                  <h2 className="micro-label">What normalization will do</h2>
                  <Table>
                    <THead>
                      <TH>Original</TH>
                      <TH>Normalized</TH>
                      <TH>Class</TH>
                    </THead>
                    <TBody>
                      {report.samples.map((sample) => (
                        <TR key={sample.legacy_code}>
                          <TD mono>{sample.original}</TD>
                          <TD mono>{sample.normalized}</TD>
                          <TD mono className="text-muted">{sample.class_code}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </div>
              )}

              {report.rejected.length > 0 && (
                <div className="space-y-3">
                  <h2 className="micro-label">Rejected rows</h2>
                  <ul className="space-y-1">
                    {report.rejected.slice(0, 8).map((row) => (
                      <li key={row.row_number} className="font-mono text-xs text-danger">
                        row {row.row_number}: {row.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {status ? (
                <div className="space-y-3 border border-hairline p-6">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="micro-label">
                      pipeline · {status.stage ?? status.state}
                    </p>
                    <StatusChip tone={status.state === 'error' ? 'danger' : status.state === 'done' ? 'ok' : 'neutral'}>
                      {status.state}
                    </StatusChip>
                  </div>
                  <div className="h-2 w-full bg-hairline" aria-hidden>
                    <div
                      className="h-full bg-ink transition-[width] duration-300"
                      style={{ width: `${status.percent}%` }}
                    />
                  </div>
                  <p className="font-mono text-xs text-muted">
                    {status.rows_done.toLocaleString('en-IN')} /{' '}
                    {status.rows_total.toLocaleString('en-IN')}
                    {status.eta_seconds !== null && ` · about ${Math.round(status.eta_seconds)}s left`}
                    {status.stages_done.length > 0 && ` · done: ${status.stages_done.join(', ')}`}
                  </p>
                  {status.error && <p className="text-sm text-danger">{status.error}</p>}
                  {status.state === 'done' && (
                    <Button variant="primary" onClick={() => navigate('/workbench')}>
                      Go to the workbench
                    </Button>
                  )}
                </div>
              ) : (
                <div className="flex gap-3">
                  <Button variant="secondary" onClick={() => go(1)}>
                    Back
                  </Button>
                  <Button
                    variant="primary"
                    disabled={busy || report.rows_accepted === 0}
                    onClick={() => void commit()}
                  >
                    Ingest {report.rows_accepted.toLocaleString('en-IN')} rows and run the pipeline
                  </Button>
                </div>
              )}
            </>
          )}
        </motion.section>
      </AnimatePresence>
    </div>
  )
}
