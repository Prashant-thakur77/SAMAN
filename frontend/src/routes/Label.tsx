import JsBarcode from 'jsbarcode'
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { EmptyState } from '../components/primitives/EmptyState'
import { ApiError, scanLookup, type ScanMaterial } from '../lib/api'

/**
 * /labels/:code — a printable label for a coded material, so the loop closes:
 * scan → identify → code → label on the bin → scan.
 *
 * A QR and a Code 128 of the same CNMC (a phone reads the first, a gun the
 * second), the code in Plex Mono, the standardised description, and every
 * CPSE's own code for the material in small print, so the old label and the
 * new one reconcile on the shelf. Prints alone on a 100 mm × 60 mm label.
 */
export default function Label() {
  const { code = '' } = useParams<{ code: string }>()
  const [material, setMaterial] = useState<ScanMaterial | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [qr, setQr] = useState<string>('')
  const barcode = useRef<SVGSVGElement>(null)

  useEffect(() => {
    let alive = true
    setMaterial(null)
    setError(null)
    scanLookup(code)
      .then((result) => {
        if (!alive) return
        const found = result.materials.find((m) => m.cnmc) ?? null
        if (!found) setError(result.materials.length ? 'This material has no national code yet; a label needs one.' : result.note)
        setMaterial(found)
      })
      .catch((err) => alive && setError(err instanceof ApiError ? err.message : 'The label could not be loaded.'))
    return () => {
      alive = false
    }
  }, [code])

  const cnmc = material?.cnmc ?? null

  useEffect(() => {
    if (!cnmc) return
    let alive = true
    QRCode.toString(cnmc, { type: 'svg', errorCorrectionLevel: 'M', margin: 0 })
      .then((svg) => alive && setQr(svg))
      .catch(() => alive && setQr(''))
    return () => {
      alive = false
    }
  }, [cnmc])

  useEffect(() => {
    if (!cnmc || !barcode.current) return
    try {
      JsBarcode(barcode.current, cnmc, {
        format: 'CODE128',
        displayValue: false,
        margin: 0,
        height: 36,
        width: 1.2,
        lineColor: '#000',
        background: '#fff',
      })
    } catch {
      /* an unencodable string leaves the bars empty; the text still prints */
    }
  }, [cnmc])

  // The shell is hidden and the page sized to the label while this route is
  // mounted; see the `body.label-print` rules in styles/index.css.
  useEffect(() => {
    document.body.classList.add('label-print')
    return () => document.body.classList.remove('label-print')
  }, [])

  return (
    <div className="label-page mx-auto max-w-3xl space-y-8">
      <div className="no-print">
        <PageHeader
          section="Tools"
          title="Label"
          description="A QR for a phone, a Code 128 for a barcode gun, and every name the material goes by. Stick it on the bin."
          actions={
            material && (
              <Button variant="primary" className="h-11" onClick={() => window.print()}>
                Print
              </Button>
            )
          }
        />
      </div>

      {error && !material && (
        <div className="no-print">
          <EmptyState
            title="No label for that code"
            description={error}
            action={
              <Link to="/scan" className="text-sm underline underline-offset-4">
                Back to Scan
              </Link>
            }
          />
        </div>
      )}

      {material && cnmc && (
        <div className="space-y-4">
          <div className="label-sheet" data-testid="label-sheet">
            <div className="label-top">
              <div
                className="label-qr"
                data-testid="label-qr"
                aria-label={`QR code for ${cnmc}`}
                role="img"
                dangerouslySetInnerHTML={{ __html: qr }}
              />
              <div className="label-text">
                <p className="label-code">{cnmc}</p>
                <p className="label-desc">{material.std_description}</p>
                <p className="label-meta">
                  {material.family ?? '—'} · {material.class_code}
                </p>
                <ul className="label-legacy">
                  {material.members.map((m) => (
                    <li key={m.item_id}>
                      <span>{m.cpse}</span> {m.legacy_code}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <svg ref={barcode} className="label-barcode" data-testid="label-barcode" aria-label={`Barcode for ${cnmc}`} role="img" />
          </div>
          {/* @page cannot be scoped by a selector, so the label's own sheet
              size is declared only while this screen is mounted. */}
          <style>{'@media print { @page { size: 100mm 60mm; margin: 4mm } }'}</style>
          <div className="no-print flex flex-wrap items-center gap-x-6 gap-y-2">
            {material.cluster_id !== null && (
              <Link
                to={`/clusters/${material.cluster_id}`}
                className="text-sm text-muted underline underline-offset-4 hover:text-ink"
              >
                Open the full record
              </Link>
            )}
            <Link
              to="/scan"
              className="text-sm text-muted underline underline-offset-4 hover:text-ink"
            >
              Scan another
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
