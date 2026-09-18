/**
 * The bin label: the CNMC as a QR for a phone, as Code 128 for a gun, in
 * print for a person, and every CPSE's own code beneath so the old label and
 * the new one reconcile. The encoders are mocked; what is asserted is that
 * each one is asked for the CNMC and given an SVG to draw into.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ScanResult } from '../lib/api'

const toString = vi.fn(async (text: string) => `<svg data-qr="${text}"><rect /></svg>`)
vi.mock('qrcode', () => ({ default: { toString: (...args: unknown[]) => toString(...(args as [string])) } }))

const jsbarcode = vi.fn((el: SVGElement, text: string) => {
  el.setAttribute('data-barcode', text)
  el.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'rect'))
})
vi.mock('jsbarcode', () => ({ default: (...args: unknown[]) => jsbarcode(...(args as [SVGElement, string])) }))

const result: ScanResult = {
  query: 'BRNG-010-000001-3',
  matched_by: 'cnmc',
  tried: 'cnmc',
  equipment: [],
  differs_on: [],
  note: 'Matched by the national code.',
  next: { action: 'open_cluster', to: '/clusters/2199' },
  materials: [
    {
      cluster_id: 2199,
      golden_id: 2199,
      cnmc: 'BRNG-010-000001-3',
      status: 'approved',
      std_description: 'BEARING, BALL DEEP GROOVE, 60MM BORE, 130MM OD, 31MM W, 2RS, NTN 63122RS',
      class_code: 'bearing.ball.deep_groove',
      family: 'BRNG',
      attrs: {},
      members: [
        { item_id: 1, cpse: 'CPCL', legacy_code: 'CPCL001513', description: 'x', mpn: null, gtin: null, scanned: false },
        { item_id: 2, cpse: 'GAIL', legacy_code: 'GAIL001561', description: 'y', mpn: null, gtin: null, scanned: false },
      ],
      cpses: ['CPCL', 'GAIL'],
      stock: null,
      installed_on: [],
      ved: null,
      substitutes: [],
    },
  ],
}

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return { ...actual, scanLookup: vi.fn(async () => result) }
})

import Label from '../routes/Label'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

describe('Label', () => {
  it('renders the CNMC, a QR SVG, a Code 128 SVG and the legacy codes', async () => {
    render(
      <MemoryRouter future={ROUTER_FUTURE} initialEntries={['/labels/BRNG-010-000001-3']}>
        <Routes>
          <Route path="/labels/:code" element={<Label />} />
        </Routes>
      </MemoryRouter>,
    )

    const sheet = await screen.findByTestId('label-sheet')
    expect(sheet).toHaveTextContent('BRNG-010-000001-3')
    expect(sheet).toHaveTextContent('BEARING, BALL DEEP GROOVE')
    expect(sheet).toHaveTextContent('BRNG')
    expect(sheet).toHaveTextContent('CPCL001513')
    expect(sheet).toHaveTextContent('GAIL001561')

    await waitFor(() => {
      expect(screen.getByTestId('label-qr').querySelector('svg')).not.toBeNull()
    })
    expect(toString).toHaveBeenCalledWith(
      'BRNG-010-000001-3',
      expect.objectContaining({ type: 'svg', errorCorrectionLevel: 'M', margin: 0 }),
    )
    const barcode = screen.getByTestId('label-barcode')
    expect(barcode.tagName.toLowerCase()).toBe('svg')
    expect(barcode).toHaveAttribute('data-barcode', 'BRNG-010-000001-3')
    const [element, text, options] = jsbarcode.mock.calls[0] as unknown as [SVGElement, string, Record<string, unknown>]
    expect(element).toBe(barcode)
    expect(text).toBe('BRNG-010-000001-3')
    expect(options).toMatchObject({ format: 'CODE128', displayValue: false })
    // The shell is hidden in print while the label is mounted.
    expect(document.body.classList.contains('label-print')).toBe(true)
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument()
  })
})
