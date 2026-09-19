import { useCallback, useEffect, useState } from 'react'

import {
  addAbbreviation,
  ApiError,
  getAbbreviations,
  getFacets,
  previewAbbreviations,
  retireAbbreviation,
  type HouseWords,
} from '../lib/api'
import { useSession } from '../lib/session'
import { Button } from './primitives/Button'
import { Input } from './primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from './primitives/Table'

/**
 * The house dictionary: words a steward teaches the platform (§2D).
 *
 * The built-in table knows 198 abbreviations; every CPSE's extracts carry
 * more. A word taught here is consulted before the built-in table for that
 * CPSE (or for every catalogue, if the registrar says so), is audited, and
 * applies to rows normalised from then on. The preview shows exactly what a
 * word changes before anyone commits to it.
 */
export function HouseWordsPanel() {
  const { user } = useSession()
  const [cpses, setCpses] = useState<string[]>([])
  const [words, setWords] = useState<HouseWords | null>(null)
  const [token, setToken] = useState('')
  const [expansion, setExpansion] = useState('')
  const [cpse, setCpse] = useState(user?.cpse_code ?? '')
  const [note, setNote] = useState('')
  const [sample, setSample] = useState('')
  const [preview, setPreview] = useState<{ built_in_only: string; with_house_words: string; changed: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const registrar = user?.role === 'registrar' || user?.role === 'admin'

  const load = useCallback(async () => {
    try {
      setWords(await getAbbreviations())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the dictionary.')
    }
  }, [])

  useEffect(() => {
    void load()
    getFacets()
      .then((f) => setCpses(f.cpses.map((c) => c.code)))
      .catch(() => setCpses([]))
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

  if (!words) return null

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="micro-label">House abbreviations · words the platform was taught</h2>
        <p className="max-w-prose text-xs text-muted">
          The built-in table knows {words.built_in} abbreviations. {words.note}
        </p>
      </div>

      {words.house.length > 0 ? (
        <Table exportAs="house-abbreviations">
          <THead>
            <TH>Token</TH>
            <TH>Reads as</TH>
            <TH>Scope</TH>
            <TH>Added by</TH>
            <TH>Note</TH>
            <TH> </TH>
          </THead>
          <TBody>
            {words.house.map((w) => (
              <TR key={w.id}>
                <TD mono>{w.token}</TD>
                <TD mono>
                  {w.expansion}
                  {w.overrides_built_in && (
                    <span className="ml-2 text-xs text-muted">(built-in said {w.overrides_built_in})</span>
                  )}
                </TD>
                <TD mono className="text-muted">
                  {w.cpse ?? 'every catalogue'}
                </TD>
                <TD className="text-muted">{w.added_by}</TD>
                <TD className="text-muted">{w.note ?? '—'}</TD>
                <TD>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act(() => retireAbbreviation(w.id))}
                    className="text-xs text-muted underline-offset-2 hover:text-danger hover:underline"
                  >
                    retire
                  </button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      ) : (
        <p className="text-sm text-muted">No house words yet.</p>
      )}

      <form
        className="flex flex-wrap items-end gap-2 card p-4"
        onSubmit={(e) => {
          e.preventDefault()
          void act(async () => {
            await addAbbreviation({
              token: token.trim(),
              expansion: expansion.trim(),
              cpse_code: cpse || undefined,
              note: note.trim() || undefined,
            })
            setToken('')
            setExpansion('')
            setNote('')
          })
        }}
      >
        <label className="space-y-1">
          <span className="micro-label block">Token</span>
          <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="SPWD" className="w-28 font-mono" />
        </label>
        <label className="space-y-1">
          <span className="micro-label block">Reads as</span>
          <Input value={expansion} onChange={(e) => setExpansion(e.target.value)} placeholder="SPIRAL WOUND" className="w-56 font-mono" />
        </label>
        <label className="space-y-1">
          <span className="micro-label block">Scope</span>
          <select
            value={cpse}
            onChange={(e) => setCpse(e.target.value)}
            className="h-10 border border-hairline bg-bg px-3 text-sm"
          >
            {registrar && <option value="">every catalogue</option>}
            {cpses.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-[12rem] flex-1 space-y-1">
          <span className="micro-label block">Note</span>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="where the word is used" />
        </label>
        <Button type="submit" variant="primary" disabled={busy || !token.trim() || !expansion.trim()}>
          Teach it
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="A description to preview"
          value={sample}
          onChange={(e) => setSample(e.target.value)}
          placeholder="Preview: GSKT SPWD 2IN 150#"
          className="max-w-md font-mono"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={!sample.trim()}
          onClick={() =>
            void previewAbbreviations(sample, cpse || undefined)
              .then(setPreview)
              .catch(() => setPreview(null))
          }
        >
          Preview
        </Button>
        {preview && (
          <span className="font-mono text-xs">
            <span className="text-muted">built-in:</span> {preview.built_in_only}{' '}
            <span className="text-muted">· with house words:</span>{' '}
            <span className={preview.changed ? 'text-ink' : 'text-muted'}>{preview.with_house_words}</span>
            {!preview.changed && <span className="text-muted"> (no change)</span>}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  )
}
