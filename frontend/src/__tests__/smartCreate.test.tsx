/**
 * Smart-Create, arrived at from Scan: `?description=` is checked at once, and
 * an interchangeable part says whether an engineer has ruled on it.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { SmartCreateResult } from '../lib/api'

vi.mock('../lib/session', () => ({
  useSession: () => ({
    user: { id: 2, email: 'steward@cpcl.in', name: 'A. Ramesh', role: 'steward', cpse_code: 'CPCL' },
    loading: false,
    can: () => true,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}))

const match = {
  item_id: 8651,
  confidence: 0,
  band: 'low',
  verdict: 'distinct',
  description: 'BRG,BALL,25MM BORE,52MM OD,15MM W,ZZ,1200 KG,150 C,NTN',
  cpse: 'CPCL',
  cnmc: null,
  class_code: 'bearing.ball.deep_groove',
  tier_scores: {},
  veto: { verdict: 'veto' },
  why: 'A higher-rated item that can substitute for this one.',
}

const result: SmartCreateResult = {
  check_id: 1,
  probe: {
    norm_text: 'BEARING BALL 6205 ZZ 800 KG 150 C KOYO',
    class_code: 'bearing.ball.deep_groove',
    class_confidence: 0.9,
    mpn_norm: '6205ZZ',
    gtin: null,
    uom_base: null,
    pack_qty: null,
    attrs: {},
  },
  suggestions: [],
  equivalents: [
    { ...match, approval: { status: 'proposed', relation_id: 5, with_item_id: 1 } },
    {
      ...match,
      item_id: 8652,
      approval: { status: 'approved', decided_by: 'V. Iyer', reason: 'Same envelope, higher rating.' },
    },
    { ...match, item_id: 8653, approval: { status: 'none', note: 'No equivalence on record yet.' } },
  ],
  ruled_out: [],
  recommendation: { action: 'create', reason: 'Nothing matched.', override_requires_reason: false },
  create_token: 't',
  token_expires_in: 600,
}

const smartCreateCheck = vi.fn(async (_body: unknown) => result)
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getHealth: vi.fn(async () => ({ capabilities: { degraded: [] } })),
    getSmartCreateStats: vi.fn(async () => null),
    smartCreateCheck: (body: unknown) => smartCreateCheck(body as never),
  }
})

import SmartCreate from '../routes/SmartCreate'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

describe('Smart-Create from Scan', () => {
  it('checks a handed-over description at once and labels each equivalence decision', async () => {
    render(
      <MemoryRouter
        future={ROUTER_FUTURE}
        initialEntries={['/smart-create?description=BRG%2CBALL%2C6205%2CZZ%2C800%20KG%2C150%20C%2CKOYO']}
      >
        <SmartCreate />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(smartCreateCheck).toHaveBeenCalledWith(
        expect.objectContaining({ description: 'BRG,BALL,6205,ZZ,800 KG,150 C,KOYO' }),
      ),
    )
    expect((screen.getByLabelText('Material description') as HTMLInputElement).value).toBe(
      'BRG,BALL,6205,ZZ,800 KG,150 C,KOYO',
    )
    expect(await screen.findByText('Proposed, not yet approved by an engineer')).toBeInTheDocument()
    expect(screen.getByText('Approved substitute')).toBeInTheDocument()
    expect(screen.getByText(/V\. Iyer: Same envelope, higher rating\./)).toBeInTheDocument()
    expect(screen.getByText('No equivalence on record yet.')).toBeInTheDocument()
  })
})
