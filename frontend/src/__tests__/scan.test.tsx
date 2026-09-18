/**
 * The Scan screen: one lookup behind a typed code, a barcode gun, the camera
 * and a nameplate photo. What matters is what the person at the bin reads —
 * the code, the names the material carries elsewhere, where it is, and which
 * substitute an engineer approved — and that the field is ready for the
 * gun's next scan the moment an answer lands.
 */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ScanEquipment, ScanMaterial, ScanResult } from '../lib/api'

vi.mock('../lib/session', () => ({
  useSession: () => ({
    user: { id: 2, email: 'steward@cpcl.in', name: 'A. Ramesh', role: 'steward', cpse_code: 'CPCL' },
    loading: false,
    can: () => true,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}))

const scanLookup = vi.fn<(code: string) => Promise<ScanResult>>()
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    scanLookup: (code: string) => scanLookup(code),
    getHealth: vi.fn(async () => ({
      capabilities: { degraded: [], ocr: { available: false } },
    })),
    smartCreateScan: vi.fn(),
  }
})

// Neither decoder may load its WebAssembly in jsdom.
vi.mock('@zxing/browser', () => ({
  BrowserMultiFormatReader: class {
    decodeFromVideoDevice = vi.fn()
    decodeFromImageUrl = vi.fn()
  },
}))
vi.mock('tesseract.js', () => ({ createWorker: vi.fn() }))

import Scan from '../routes/Scan'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

// ---- fixtures ---------------------------------------------------------------

const bearing: ScanMaterial = {
  cluster_id: 2199,
  golden_id: 2199,
  cnmc: 'BRNG-010-000001-3',
  status: 'approved',
  std_description: 'BEARING, BALL DEEP GROOVE, 60MM BORE, 130MM OD, 31MM W, 2RS, NTN 63122RS',
  class_code: 'bearing.ball.deep_groove',
  family: 'BRNG',
  attrs: { bore_mm: 60, brand: 'NTN', load_rating_kg: 2880, temp_max_c: 120 },
  members: [
    { item_id: 1, cpse: 'CPCL', legacy_code: 'CPCL001513', description: 'BRG,BALL,6312,2RS,NTN', mpn: '63122RS', gtin: null, scanned: false },
    { item_id: 2, cpse: 'GAIL', legacy_code: 'GAIL001561', description: 'NTN - BEARING - BALL - 6312', mpn: '63122RS', gtin: null, scanned: true },
  ],
  cpses: ['CPCL', 'GAIL'],
  stock: {
    cluster_id: 2199,
    cpse_count: 2,
    plant_count: 2,
    total_qty: 407,
    total_value: 17696.76,
    positions: [
      { cpse: 'GAIL', plant: 'PATA', qty_on_hand: 395, reserved_qty: 77.9, available: 317.1, unit_value: null, value: null, value_withheld: true, last_movement: '2025-09-09' },
      { cpse: 'CPCL', plant: 'CAUVERY', qty_on_hand: 12, reserved_qty: 0.3, available: 11.7, unit_value: 1474.73, value: 17696.76, value_withheld: false, last_movement: '2026-02-28' },
    ],
  },
  installed_on: [
    { tag: 'V-104', description: 'Pressure vessel V-104', criticality: 'A', ved: 'vital', cpse: 'GAIL', qty: 6 },
  ],
  ved: 'vital',
  substitutes: [
    {
      relation_id: 10,
      rel_type: 'equivalent',
      direction: null,
      status: 'approved',
      confidence: 0.95,
      other: { item_id: 6835, legacy_code: 'ONGC001712', description: 'BALL 6312 2RS TIMKEN', cpse: 'ONGC', cnmc: null },
      approval: { status: 'approved', decided_by: 'V. Iyer', reason: 'Same envelope, same load rating; fitted at Hazira since 2019.', ts: '2026-08-01' },
    },
    {
      relation_id: 11,
      rel_type: 'supersedes',
      direction: 'b_to_a',
      status: 'proposed',
      confidence: 0.85,
      other: { item_id: 7001, legacy_code: 'IOCL009999', description: 'BEARING 6312 2RS SKF', cpse: 'IOCL', cnmc: null },
      approval: null,
    },
  ],
}

function variant(load: number, temp: number, code: string, id: number): ScanMaterial {
  return {
    ...bearing,
    cluster_id: id,
    golden_id: id,
    cnmc: null,
    status: 'conflict',
    std_description: `BEARING, BALL DEEP GROOVE, 20MM BORE, 52MM OD, 15MM W, 2RS, FAG ${code}`,
    attrs: { bore_mm: 20, brand: 'FAG', load_rating_kg: load, temp_max_c: temp, seal_type: '2RS' },
    members: [{ item_id: id * 10, cpse: 'CPCL', legacy_code: code, description: 'x', mpn: '6304-2RS', gtin: null, scanned: true }],
    cpses: ['CPCL'],
    stock: null,
    installed_on: [],
    ved: null,
    substitutes: [],
  }
}

const single: ScanResult = {
  query: 'BRNG-010-000001-3',
  matched_by: 'cnmc',
  tried: 'cnmc',
  materials: [bearing],
  equipment: [],
  differs_on: [],
  note: 'Matched by the national code.',
  next: { action: 'open_cluster', to: '/clusters/2199' },
}

const several: ScanResult = {
  query: '6304-2RS',
  matched_by: 'mpn',
  tried: 'mpn',
  materials: [variant(988.8, 120, 'CPCL001094', 1594), variant(640, 100, 'CPCL002817', 6986)],
  equipment: [],
  differs_on: ['load_rating_kg', 'temp_max_c'],
  note: "Matched by the manufacturer's part number, which 2 distinct materials share. They differ on an attribute the matcher refused to merge across; choose by it.",
  next: { action: 'choose', to: null },
}

const nothing: ScanResult = {
  query: 'zzz-nothing',
  matched_by: null,
  tried: null,
  materials: [],
  equipment: [],
  differs_on: [],
  note: 'No catalogue row carries that code as a national code, a CPSE code, a GTIN or a part number. If it is a description, Smart-Create can match it.',
  next: { action: 'smart_create', to: '/smart-create?description=zzz-nothing' },
}

const misread: ScanResult = {
  ...nothing,
  query: 'BRNG-010-000001-4',
  tried: 'cnmc',
  note: 'That has the shape of a national code but its check digit does not verify: one digit was misread. Scan it again.',
  next: { action: 'smart_create', to: '/smart-create?description=BRNG-010-000001-4' },
}

function pump(cpse: string, id: number, criticality: 'A' | 'B' | 'C'): ScanEquipment {
  return {
    id,
    tag: 'P-101B',
    description: 'Centrifugal pump P-101B',
    criticality,
    ved: { A: 'vital', B: 'essential', C: 'desirable' }[criticality],
    cpse,
    spares: [
      { item_id: 641, cluster_id: 221, cnmc: 'PIPE-040-000011-8', legacy_code: `${cpse}000157`, description: 'PIPE,SMLS,20NB,SCH40,SS316', class_code: 'pipe.seamless', qty_fitted: 6, stock_here: 109, stock_elsewhere: 343, cpses_elsewhere: 3 },
      { item_id: 4916, cluster_id: 1758, cnmc: null, legacy_code: `${cpse}001243`, description: 'NTN - BEARING - BALL - 6005 - ZZ', class_code: 'bearing.ball.deep_groove', qty_fitted: 2, stock_here: 320, stock_elsewhere: 0, cpses_elsewhere: 0 },
    ],
  }
}

const oneSite: ScanResult = {
  query: 'P-101B',
  matched_by: 'equipment_tag',
  tried: 'equipment_tag',
  materials: [],
  equipment: [pump('CPCL', 1, 'B')],
  differs_on: [],
  note: 'Matched by the equipment tag at CPCL.',
  next: { action: 'none', to: null },
}

const threeSites: ScanResult = {
  ...oneSite,
  equipment: [pump('CPCL', 1, 'B'), pump('IOCL', 61, 'C'), pump('ONGC', 181, 'A')],
  note: 'Matched by the equipment tag, which 3 CPSEs use for different plant. Tags are local to a plant; choose the site.',
  next: { action: 'choose_site', to: null },
}

// ---- helpers ----------------------------------------------------------------

function renderScan() {
  return render(
    <MemoryRouter future={ROUTER_FUTURE} initialEntries={['/scan']}>
      <Scan />
    </MemoryRouter>,
  )
}

async function scan(code: string) {
  const field = screen.getByLabelText('Code') as HTMLInputElement
  await userEvent.clear(field)
  await userEvent.type(field, `${code}{Enter}`)
  return field
}

beforeEach(() => {
  scanLookup.mockReset()
})

// ---- tests ------------------------------------------------------------------

describe('Scan', () => {
  it('looks up a typed code on Enter and renders the material card', async () => {
    scanLookup.mockResolvedValue(single)
    renderScan()
    await scan('BRNG-010-000001-3')

    expect(scanLookup).toHaveBeenCalledWith('BRNG-010-000001-3')
    const card = await screen.findByTestId('scan-material')
    expect(within(card).getAllByText('BRNG-010-000001-3').length).toBeGreaterThan(0)
    expect(within(card).getByText('you scanned this')).toBeInTheDocument()
    // The GAIL position's value is withheld from a CPCL steward.
    expect(within(card).getByText('withheld')).toBeInTheDocument()
    expect(within(card).getByText('₹17,697')).toBeInTheDocument()
    // The signed-in person's own CPSE is listed first among the positions.
    const plants = within(card).getAllByText(/CAUVERY|PATA/).map((el) => el.textContent)
    expect(plants).toEqual(['CAUVERY', 'PATA'])
    expect(within(card).getByText('A · vital')).toBeInTheDocument()
    expect(
      within(card).getByText(/Same envelope, same load rating; fitted at Hazira since 2019\./),
    ).toBeInTheDocument()
    expect(within(card).getByText('Proposed, not yet approved')).toBeInTheDocument()
    expect(within(card).getByText('BEARING 6312 2RS SKF')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the full record' })).toHaveAttribute(
      'href',
      '/clusters/2199',
    )
    expect(screen.getByRole('link', { name: 'Print a label' })).toHaveAttribute(
      'href',
      '/labels/BRNG-010-000001-3',
    )
    expect(screen.getByText(/Matched by the national code/)).toBeInTheDocument()
  })

  it('renders a chooser for several materials with only the differing attributes', async () => {
    scanLookup.mockResolvedValue(several)
    renderScan()
    await scan('6304-2RS')

    const chooser = await screen.findByTestId('scan-chooser')
    expect(within(chooser).getByText(several.note)).toBeInTheDocument()
    const rows = within(chooser).getAllByRole('button', { name: 'This one' })
    expect(rows).toHaveLength(2)
    expect(within(chooser).getAllByText('Load rating')).toHaveLength(2)
    expect(within(chooser).getByText('988.8 kg')).toBeInTheDocument()
    expect(within(chooser).getByText('640 kg')).toBeInTheDocument()
    expect(within(chooser).getByText('100 °C')).toBeInTheDocument()
    // Attributes the materials agree on are not shown: they would not help choose.
    expect(within(chooser).queryByText('Bore')).not.toBeInTheDocument()
    expect(within(chooser).queryByText('Brand')).not.toBeInTheDocument()
    expect(within(chooser).getAllByText('no code')).toHaveLength(2)

    await userEvent.click(rows[1])
    const card = await screen.findByTestId('scan-material')
    expect(within(card).getByText(/FAG CPCL002817/)).toBeInTheDocument()
    expect(within(card).getByText('No national code yet · in review')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the full record' })).toHaveAttribute(
      'href',
      '/clusters/6986',
    )
    expect(screen.queryByTestId('scan-chooser')).not.toBeInTheDocument()
  })

  it('renders the note and the Smart-Create link when nothing is found', async () => {
    scanLookup.mockResolvedValue(nothing)
    renderScan()
    await scan('zzz-nothing')

    expect(await screen.findByText(nothing.note)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Check it as a description in Smart-Create' }),
    ).toHaveAttribute('href', '/smart-create?description=zzz-nothing')
    expect(screen.queryByTestId('scan-material')).not.toBeInTheDocument()
  })

  it('says a misread check digit is a misread and offers to scan again', async () => {
    scanLookup.mockResolvedValue(misread)
    renderScan()
    await scan('BRNG-010-000001-4')

    expect(await screen.findByText(misread.note)).toBeInTheDocument()
    const again = screen.getByRole('button', { name: 'Scan again' })
    await userEvent.click(again)
    const field = screen.getByLabelText('Code') as HTMLInputElement
    expect(field.value).toBe('')
    expect(document.activeElement).toBe(field)
  })

  it('keeps focus in the field with the text selected after an answer', async () => {
    scanLookup.mockResolvedValue(single)
    renderScan()
    const field = await scan('BRNG-010-000001-3')
    await screen.findByTestId('scan-material')

    await waitFor(() => {
      expect(document.activeElement).toBe(field)
      expect(field.selectionStart).toBe(0)
      expect(field.selectionEnd).toBe('BRNG-010-000001-3'.length)
    })
    // A gun's next scan replaces the selection rather than appending to it.
    expect(field).toHaveAttribute('enterkeyhint', 'search')
    expect(field).toHaveAttribute('autocapitalize', 'characters')
  })

  it('hides the camera button where there is no camera API', async () => {
    const original = navigator.mediaDevices
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true })
    try {
      renderScan()
      // Let the health probe settle so its state update is inside the test.
      await act(async () => {})
      expect(screen.queryByRole('button', { name: 'Scan with the camera' })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Photograph the marking' })).toBeInTheDocument()
    } finally {
      Object.defineProperty(navigator, 'mediaDevices', { value: original, configurable: true })
    }
  })

  it('shows the camera button when the API exists', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn() },
      configurable: true,
    })
    try {
      renderScan()
      await act(async () => {})
      expect(screen.getByRole('button', { name: 'Scan with the camera' })).toBeInTheDocument()
    } finally {
      Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true })
    }
  })

  it('renders an equipment tag at one site with its spares and their stock', async () => {
    scanLookup.mockResolvedValue(oneSite)
    renderScan()
    await scan('P-101B')

    const card = await screen.findByTestId('scan-equipment')
    expect(within(card).getByText('P-101B')).toBeInTheDocument()
    expect(within(card).getByText('Centrifugal pump P-101B')).toBeInTheDocument()
    expect(within(card).getByText('B · essential')).toBeInTheDocument()
    expect(within(card).getByText('PIPE-040-000011-8')).toBeInTheDocument()
    expect(within(card).getByText('no code')).toBeInTheDocument()
    expect(within(card).getByText('fitted ×6')).toBeInTheDocument()
    expect(within(card).getByText('here 109 · elsewhere 343 at 3 CPSEs')).toBeInTheDocument()
    expect(within(card).getByText('here 320 · none elsewhere')).toBeInTheDocument()
    expect(screen.getByText(/Matched by the equipment tag/)).toBeInTheDocument()

    // A spare's row is a lookup of that spare, by its CNMC when it has one.
    scanLookup.mockResolvedValue(single)
    await userEvent.click(within(card).getByRole('button', { name: 'Look up PIPE-040-000011-8' }))
    expect(scanLookup).toHaveBeenLastCalledWith('PIPE-040-000011-8')
    await screen.findByTestId('scan-material')
    expect((screen.getByLabelText('Code') as HTMLInputElement).value).toBe('PIPE-040-000011-8')
  })

  it('renders a site chooser for a tag used at several CPSEs, own CPSE first', async () => {
    scanLookup.mockResolvedValue(threeSites)
    renderScan()
    await scan('P-101B')

    const chooser = await screen.findByTestId('scan-site-chooser')
    expect(within(chooser).getByText(threeSites.note)).toBeInTheDocument()
    const sites = within(chooser).getAllByRole('button', { name: 'This site' })
    expect(sites).toHaveLength(3)
    expect(within(chooser).getAllByText(/^(CPCL|IOCL|ONGC)$/).map((el) => el.textContent)).toEqual([
      'CPCL',
      'IOCL',
      'ONGC',
    ])
    expect(within(chooser).getByText('A · vital')).toBeInTheDocument()
    expect(screen.queryByTestId('scan-equipment')).not.toBeInTheDocument()

    await userEvent.click(sites[1])
    const card = await screen.findByTestId('scan-equipment')
    expect(within(card).getByText('IOCL')).toBeInTheDocument()
    expect(within(card).getByText('C · desirable')).toBeInTheDocument()
    expect(within(card).getByText('IOCL000157')).toBeInTheDocument()
  })

  it('reports a failed lookup without losing the field', async () => {
    scanLookup.mockRejectedValue(new Error('boom'))
    renderScan()
    await scan('anything')
    expect(await screen.findByRole('status')).toHaveTextContent('The lookup did not work.')
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'again' } })
    expect((screen.getByLabelText('Code') as HTMLInputElement).value).toBe('again')
  })
})
