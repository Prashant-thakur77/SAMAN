/**
 * The per-CPSE catalogue report on the two screens that offer it: the
 * Administration table (every CPSE, contact email editable, Preview and
 * Send) and the steward's Home card (their own CPSE only). A send must say
 * where the message went, because without SMTP it lands in the outbox.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReportListing, ReportSendResult } from '../lib/api'

const listing: ReportListing = {
  delivery: 'outbox',
  outbox_dir: '/srv/saman/data/outbox',
  cpses: [
    {
      code: 'CPCL',
      name: 'Chennai Petroleum Corporation Limited',
      contact_email: 'materials@cpcl.example',
      items: 2889,
      last_sent: null,
    },
    {
      code: 'IOCL',
      name: 'Indian Oil Corporation Limited',
      contact_email: null,
      items: 2940,
      last_sent: { at: '2026-09-15T07:00:00', mode: 'outbox', to: ['x@iocl.example'] },
    },
  ],
}

const sent: ReportSendResult = {
  mode: 'outbox',
  host: null,
  path: '/srv/saman/data/outbox/20260919T070000Z-CPCL.eml',
  cpse: 'CPCL',
  to: ['materials@cpcl.example'],
  sha256: 'abc',
  sent_at: '2026-09-19T07:00:00+00:00',
  note: 'No SMTP relay is configured; the message was written to the outbox.',
}

const getReports = vi.fn(async () => listing)
const sendReport = vi.fn(async (_code: string, _to: string[] | null) => sent)
const patchCpse = vi.fn(async (code: string, body: { contact_email?: string | null }) => ({
  code,
  name: 'x',
  contact_email: body.contact_email ?? null,
}))

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getReports: () => getReports(),
    sendReport: (code: string, to: string[] | null = null) => sendReport(code, to),
    patchCpse: (code: string, body: { contact_email?: string | null }) => patchCpse(code, body),
    // The rest of the Administration page, quiet.
    getUsers: vi.fn(async () => ({ roles: ['steward'], count: 0, users: [] })),
    getHealthPanel: vi.fn(async () => {
      throw new Error('not in this test')
    }),
    getLearnStatus: vi.fn(async () => {
      throw new Error('not in this test')
    }),
    // The rest of Home, quiet.
    getExecutive: vi.fn(async () => ({
      kpis: [{ key: 'items', label: 'Catalogue rows', value: 2889 }],
    })),
    getQueueCounts: vi.fn(async () => ({ counts: { high: 1, grey: 2, low: 3 }, total: 6 })),
    getAudit: vi.fn(async () => ({ total: 0, offset: 0, actions: {}, events: [] })),
  }
})

const session = {
  user: { id: 4, email: 'steward@cpcl.in', name: 'A. Ramesh', role: 'steward', cpse_code: 'CPCL' },
  loading: false,
  can: (...roles: string[]) => roles.includes('steward'),
  refresh: vi.fn(),
  signOut: vi.fn(),
}
vi.mock('../lib/session', () => ({ useSession: () => session }))

import { ReportsSection } from '../components/ReportsPanel'
import Home from '../routes/Home'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

describe("the Administration page's Reports section", () => {
  beforeEach(() => vi.clearAllMocks())

  it('lists every CPSE with its contact, last sent, and a preview link; a send says where it went', async () => {
    render(<ReportsSection />)
    const table = await screen.findByTestId('reports')
    expect(table).toHaveTextContent('CPCL')
    expect(table).toHaveTextContent('IOCL')
    expect(table).toHaveTextContent('never')
    expect(table).toHaveTextContent('outbox')
    expect(table).toHaveTextContent('/srv/saman/data/outbox')

    const previews = screen.getAllByRole('link', { name: 'Preview' })
    expect(previews[0]).toHaveAttribute('href', '/api/reports/cpse/CPCL?format=html')
    expect(previews[0]).toHaveAttribute('target', '_blank')

    fireEvent.click(screen.getAllByRole('button', { name: 'Send' })[0])
    await waitFor(() => expect(sendReport).toHaveBeenCalledWith('CPCL', null))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Written to the outbox at /srv/saman/data/outbox/20260919T070000Z-CPCL.eml',
    )
  })

  it('saves an edited contact email through the PATCH', async () => {
    render(<ReportsSection />)
    const field = await screen.findByLabelText('Contact email for IOCL')
    fireEvent.change(field, { target: { value: 'stores@iocl.example' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(patchCpse).toHaveBeenCalledWith('IOCL', { contact_email: 'stores@iocl.example' }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent("IOCL's contact email saved")
  })
})

describe("the steward's Home card", () => {
  beforeEach(() => vi.clearAllMocks())

  it('offers their own report only, with Preview and Send', async () => {
    render(
      <MemoryRouter future={ROUTER_FUTURE}>
        <Home />
      </MemoryRouter>,
    )
    const card = await screen.findByTestId('report-card')
    expect(card).toHaveTextContent('Your catalogue report')
    expect(card).toHaveTextContent("CPCL's catalogue")
    expect(card).not.toHaveTextContent('IOCL')
    expect(card).toHaveTextContent('goes to materials@cpcl.example')
    expect(screen.getByRole('link', { name: 'Preview' })).toHaveAttribute(
      'href',
      '/api/reports/cpse/CPCL?format=html',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(sendReport).toHaveBeenCalledWith('CPCL', null))
    expect(await screen.findByRole('status')).toHaveTextContent('Written to the outbox at')
  })
})
