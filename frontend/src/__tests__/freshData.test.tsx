/**
 * A dashboard served stale says so, and fetches again until it is fresh.
 */

import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ProvenanceLine } from '../components/charts/Provenance'
import type { DashboardProvenance } from '../lib/api'
import { useFreshData } from '../lib/useFreshData'

const provenance = (stale: boolean, audit_seq: number): DashboardProvenance =>
  ({
    stale,
    computed_at: '2026-09-28T10:00:00+00:00',
    seconds: 0.4,
    audit_seq,
    match_run: 2,
    rows: { items: 11786, cnmcs: 754, decisions: 105, stock_rows: 1, purchases: 1, relations: 1, substitute_approvals: 0, labels: 0 },
    note: 'computed from the database',
  }) as DashboardProvenance

function Probe({ load }: { load: () => Promise<{ n: number; provenance: DashboardProvenance }> }) {
  const { data } = useFreshData(load, [])
  return data ? (
    <div>
      <p data-testid="n">{data.n}</p>
      <ProvenanceLine provenance={data.provenance} />
    </div>
  ) : null
}

describe('stale dashboards', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => vi.useRealTimers())

  it('labels stale figures and replaces them when fresh ones arrive', async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({ n: 1, provenance: provenance(true, 990) })
      .mockResolvedValueOnce({ n: 2, provenance: provenance(false, 991) })
    render(<Probe load={load} />)

    expect(await screen.findByRole('status')).toHaveTextContent('updating · these are the figures at audit #990')
    expect(screen.getByTestId('n')).toHaveTextContent('1')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100)
    })
    expect(load).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('n')).toHaveTextContent('2')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not ask again when the figures are fresh', async () => {
    const load = vi.fn().mockResolvedValue({ n: 5, provenance: provenance(false, 1) })
    render(<Probe load={load} />)
    expect(await screen.findByTestId('n')).toHaveTextContent('5')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000)
    })
    expect(load).toHaveBeenCalledTimes(1)
  })
})
