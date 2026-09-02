import { useEffect, useState } from 'react'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { Field, Input } from '../components/primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import {
  ApiError,
  getCpses,
  getPprlKey,
  getPprlModes,
  pprlCompare,
  pprlEncode,
  pprlEvaluate,
  type PprlEvaluation,
  type PprlModes,
  type PprlPayload,
  type PprlReport,
} from '../lib/api'
import { useSession } from '../lib/session'

const LIMIT = 300

/**
 * /pprl — restricted mode (spec §5, M10).
 *
 * The screen exists to make one claim inspectable: two CPSEs can find their
 * common materials without either seeing the other's catalogue. So the
 * encodings are shown, in full, as the opaque bitstrings they are — the
 * evidence for the claim is that there is nothing legible in them.
 */
export default function Pprl() {
  const { user } = useSession()
  const [cpses, setCpses] = useState<{ code: string; name: string }[]>([])
  const [modes, setModes] = useState<PprlModes | null>(null)
  const [mode, setMode] = useState('attribute')
  const [left, setLeft] = useState('')
  const [right, setRight] = useState('')
  const [key, setKey] = useState('')
  const [payloads, setPayloads] = useState<{ left: PprlPayload; right: PprlPayload } | null>(
    null,
  )
  const [report, setReport] = useState<PprlReport | null>(null)
  const [cost, setCost] = useState<PprlEvaluation | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void Promise.all([getCpses(), getPprlModes(), getPprlKey()])
      .then(([list, available, minted]) => {
        setCpses(list.cpses)
        setModes(available)
        setMode(available.default)
        setKey(minted.key)
        const own = user?.cpse_code
        setLeft(own ?? list.cpses[0]?.code ?? '')
        setRight(list.cpses.find((c) => c.code !== (own ?? list.cpses[0]?.code))?.code ?? '')
      })
      .catch(() => setMessage({ tone: 'danger', text: 'Could not reach restricted mode.' }))
  }, [user?.cpse_code])

  async function run() {
    setBusy(true)
    setMessage(null)
    setReport(null)
    setCost(null)
    try {
      // Each side encodes its own catalogue. In a real exchange these two calls
      // happen inside two different organisations; only the encodings travel.
      const [a, b] = await Promise.all([
        pprlEncode({ cpse: left, key, mode, limit: LIMIT }),
        pprlEncode({ cpse: right, key, mode, limit: LIMIT }),
      ])
      setPayloads({ left: a, right: b })
      setReport(await pprlCompare({ left: a.encodings, right: b.encodings, mode }))
      // National roles can also see what the privacy guarantee costs.
      try {
        setCost(await pprlEvaluate(left, right, mode))
      } catch {
        setCost(null)
      }
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'That comparison did not run.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="Restricted mode"
        description="Find what two CPSEs have in common without either handing over a catalogue. Each side encodes its own descriptions locally; only the encodings are compared."
        actions={<StatusChip tone="neutral">Restricted mode</StatusChip>}
      />

      {message && (
        <p role="status" className="card px-4 py-3 text-sm text-danger">
          {message.text}
        </p>
      )}

      <section className="space-y-4 card p-6">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="This catalogue" htmlFor="pprl-left">
            <Select id="pprl-left" value={left} onChange={setLeft} options={cpses} />
          </Field>
          <Field label="Their catalogue" htmlFor="pprl-right">
            <Select id="pprl-right" value={right} onChange={setRight} options={cpses} />
          </Field>
          <Field
            label="Feature mode"
            htmlFor="pprl-mode"
            hint={modes?.modes[mode]?.description}
          >
            <select
              id="pprl-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="h-10 w-full border border-hairline bg-bg px-3 text-sm text-ink"
            >
              {Object.keys(modes?.modes ?? {}).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field
          label="Exchange key"
          htmlFor="pprl-key"
          hint="Shared out of band between the two CPSEs. Encodings made under different keys cannot be compared, and the key is the only thing keeping them from being inverted."
        >
          <Input id="pprl-key" value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>

        <Button
          variant="primary"
          disabled={busy || !left || !right || left === right || key.length < 16}
          onClick={() => void run()}
        >
          {busy ? 'Encoding and comparing…' : `Compare ${left} and ${right}`}
        </Button>
        {left === right && (
          <p className="text-xs text-muted">Pick two different catalogues.</p>
        )}
      </section>

      {report && payloads && (
        <>
          <section className="space-y-3">
            <h2 className="micro-label">Overlap</h2>
            <div className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card sm:grid-cols-4">
              {[
                {
                  label: `${payloads.left.cpse} matched`,
                  value: `${report.overlap_records_left} of ${report.left_records}`,
                  sub: `${report.overlap_pct_left}%`,
                },
                {
                  label: `${payloads.right.cpse} matched`,
                  value: `${report.overlap_records_right} of ${report.right_records}`,
                  sub: `${report.overlap_pct_right}%`,
                },
                {
                  label: 'Comparisons made',
                  value: report.comparisons.toLocaleString('en-IN'),
                  sub: 'no blocking is possible without plaintext',
                },
                {
                  label: 'Needing a look',
                  value: report.possible_matches.toLocaleString('en-IN'),
                  sub: `below the ${report.threshold} threshold`,
                },
              ].map((tile) => (
                <div key={tile.label} className="space-y-1 bg-surface p-4">
                  <p className="micro-label">{tile.label}</p>
                  <p className="font-mono text-lg">{tile.value}</p>
                  <p className="text-xs text-muted">{tile.sub}</p>
                </div>
              ))}
            </div>
            <p className="max-w-prose text-xs text-muted">{report.note}</p>
          </section>

          {cost && (
            <section className="space-y-3">
              <h2 className="micro-label">What the privacy costs</h2>
              <p className="max-w-prose text-sm text-muted">
                Scored against the same ground truth the main engine is scored on, so the
                trade-off is a number rather than an impression. The full matcher reads
                attributes, units and a veto layer; restricted mode reads hashes.
              </p>
              <div className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline shadow-card sm:grid-cols-4">
                {[
                  ['Precision', cost.precision],
                  ['Recall', cost.recall],
                  ['F1', cost.f1],
                  ['Threshold', cost.threshold],
                ].map(([label, value]) => (
                  <div key={String(label)} className="space-y-1 bg-surface p-4">
                    <p className="micro-label">{label}</p>
                    <p className="font-mono text-lg">{Number(value).toFixed(3)}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-3">
            <h2 className="micro-label">What actually crossed the wire</h2>
            <p className="max-w-prose text-xs text-muted">
              The first rows of {payloads.left.cpse}&rsquo;s payload, exactly as sent:{' '}
              {payloads.left.filter_bits}-bit filters, {payloads.left.hashes_per_feature} bits
              per feature. There is no description, legacy code, attribute value or price in
              it, and the reference is a pseudonym only {payloads.left.cpse} can resolve.
            </p>
            <div className="space-y-1 overflow-x-auto card p-4 font-mono text-[11px] text-muted">
              {payloads.left.encodings.slice(0, 4).map((encoding) => (
                <p key={encoding.ref} className="whitespace-nowrap">
                  {encoding.ref} · {encoding.bloom.slice(0, 96)}…
                </p>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="micro-label">Matched pairs</h2>
            <Table>
              <THead>
                <TH>{payloads.left.cpse} reference</TH>
                <TH>{payloads.right.cpse} reference</TH>
                <TH align="right">Dice</TH>
                <TH>Verdict</TH>
              </THead>
              <TBody>
                {report.matches.slice(0, 40).map((match) => (
                  <TR key={`${match.left_ref}-${match.right_ref}`}>
                    <TD mono>{match.left_ref}</TD>
                    <TD mono>{match.right_ref}</TD>
                    <TD mono align="right">{match.dice.toFixed(3)}</TD>
                    <TD>
                      <StatusChip tone={match.verdict === 'match' ? 'ok' : 'neutral'}>
                        {match.verdict}
                      </StatusChip>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            {report.matches.length === 0 && (
              <p className="card px-4 py-3 text-sm text-muted">
                Nothing scored above {report.report_threshold}. If that is a surprise, check
                that both sides encoded under the same key: a mismatched key produces
                silence rather than a wrong answer.
              </p>
            )}
          </section>
        </>
      )}

      <section className="space-y-2 card p-6">
        <h2 className="micro-label">What this protects, and what it does not</h2>
        <p className="max-w-prose text-sm text-muted">
          Restricted mode removes plaintext from the exchange, which is the requirement. It is
          not anonymity. Bloom-filter linkage is known to be vulnerable to frequency and
          pattern analysis by an adversary holding many encodings, and the keyed hash raises
          the cost of a dictionary attack without eliminating it. Treat the exchange key as
          the secret it is.
        </p>
      </section>
    </div>
  )
}

function Select({
  id,
  value,
  onChange,
  options,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  options: { code: string; name: string }[]
}) {
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-10 w-full border border-hairline bg-bg px-3 text-sm text-ink"
    >
      {options.map((option) => (
        <option key={option.code} value={option.code}>
          {option.code} · {option.name}
        </option>
      ))}
    </select>
  )
}
