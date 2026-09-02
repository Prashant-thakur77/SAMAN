/**
 * The public front page.
 *
 * Two promises are worth a test. The first is §8A's: a visitor arriving before
 * `make demo`, or with the API down entirely, gets a page that explains itself
 * rather than a blank one. The second is §0.9b's: this page is served to
 * anybody, so no attributed price may reach it.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getHealth = vi.fn()
const getExecutive = vi.fn()
const getMetrics = vi.fn()

vi.mock('../lib/api', () => ({
  getHealth: (...args: unknown[]) => getHealth(...args),
  getExecutive: (...args: unknown[]) => getExecutive(...args),
  getMetrics: (...args: unknown[]) => getMetrics(...args),
}))

import Landing from '../routes/Landing'
import { ThemeProvider } from '../lib/theme'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

const HEALTH = {
  version: '0.1.0',
  capabilities: {
    linkage: { mode: 'splink', engine: 'splink', degraded: false },
    embedding: { mode: 'tfidf', engine: 'tf-idf', degraded: true },
    llm: { mode: 'deterministic', engine: 'templates', degraded: true },
    degraded: ['TF-IDF fallback'],
  },
}

const DASHBOARD = {
  kpis: [
    { key: 'items', label: 'Catalogue rows', value: 11778 },
    { key: 'clusters', label: 'Materials identified', value: 7142 },
    { key: 'duplicates', label: 'Duplicates confirmed', value: 4636 },
    { key: 'cnmcs', label: 'CNMCs issued', value: 754 },
    { key: 'savings', label: 'Savings identified', value: 2334014728.72, format: 'currency' },
  ],
}

const METRICS = {
  counts: { items_total: 11778, items_holdout: 4664, clusters: 7142 },
  duplicate: { pairwise: { precision: 0.9973, recall: 0.9595, f1: 0.978 } },
  baseline_exact_text: { pairwise: { precision: 1, recall: 0.0287 } },
  veto: { precision: 1, traps_refused: 380, traps_total: 380 },
  equivalence: { status: 'measured', precision: 0.927, recall: 0.944, direction_accuracy: 0.9898 },
  automation: { automation_rate: 0.9942, auto_decided: 643651, needs_review: 3778 },
  gate: {
    duplicate_precision: { value: 0.9973, target: 0.92, pass: true },
    blocking_recall: { value: 0.9944, target: 0.97, pass: true },
  },
  gate_passed: true,
  worst_class: 'bearing.ball.deep_groove',
}

function renderLanding() {
  return render(
    <ThemeProvider>
      <MemoryRouter future={ROUTER_FUTURE}>
        <Landing />
      </MemoryRouter>
    </ThemeProvider>,
  )
}

describe('the landing page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getHealth.mockResolvedValue(HEALTH)
    getExecutive.mockResolvedValue(DASHBOARD)
    getMetrics.mockResolvedValue(METRICS)
  })

  it('leads with the claim and a way in', async () => {
    renderLanding()
    expect(
      screen.getByRole('heading', { level: 1, name: /one nation, one material code/i }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /sign in/i }).length).toBeGreaterThan(0)
    // Let the three page loads settle before the test ends, so their state
    // updates land inside it rather than after it.
    await screen.findByText('11,778')
  })

  it('reports the engines this instance is actually running', async () => {
    renderLanding()
    const status = await screen.findByRole('complementary', { name: /system status/i })
    expect(within(status).getByText('splink')).toBeInTheDocument()
    expect(within(status).getByText('tfidf')).toBeInTheDocument()
    expect(within(status).getByText('Fully offline')).toBeInTheDocument()
  })

  it('shows the counts held in this instance', async () => {
    renderLanding()
    expect(await screen.findByText('11,778')).toBeInTheDocument()
    expect(screen.getByText('754')).toBeInTheDocument()
  })

  it('never shows a price on a page anybody can read', async () => {
    renderLanding()
    await screen.findByText('11,778')
    // §0.9b: the executive payload carries a modelled savings figure. It is a
    // price-derived number, and this page has no signed-in reader to scope it
    // to, so it must not appear here whatever the API is willing to return.
    expect(screen.queryByText(/savings/i)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/₹/)
  })

  it('publishes the held-out results with their targets', async () => {
    renderLanding()
    expect(await screen.findByText(/measured on data it was not tuned on/i)).toBeInTheDocument()
    expect(screen.getByText('duplicate precision')).toBeInTheDocument()
    expect(screen.getAllByText('pass').length).toBe(2)
    expect(screen.getByText(/bearing\.ball\.deep_groove/)).toBeInTheDocument()
  })

  it('says the estate is empty rather than showing zeros', async () => {
    getExecutive.mockResolvedValue({
      kpis: DASHBOARD.kpis.map((kpi) => ({ ...kpi, value: 0 })),
    })
    renderLanding()
    expect(await screen.findByText(/no catalogue is loaded/i)).toBeInTheDocument()
    expect(screen.queryByText('11,778')).not.toBeInTheDocument()
  })

  it('keeps its sentences when nothing answers', async () => {
    getHealth.mockRejectedValue(new Error('connection refused'))
    getExecutive.mockRejectedValue(new Error('connection refused'))
    getMetrics.mockRejectedValue(new Error('connection refused'))
    renderLanding()

    expect(
      screen.getByRole('heading', { level: 1, name: /one nation, one material code/i }),
    ).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('API unreachable')).toBeInTheDocument())
    expect(screen.getByText(/the backend is not answering/i)).toBeInTheDocument()
    expect(screen.getByText(/the evaluation report needs a loaded catalogue/i)).toBeInTheDocument()
    // Whatever fails, the description of the system is still there to read.
    expect(screen.getByText(/a refusal outranks a score/i)).toBeInTheDocument()
  })

  it('states that it is a prototype, not an official service', async () => {
    renderLanding()
    expect(
      await screen.findByText(/not an official service of the government of india/i),
    ).toBeInTheDocument()
    await screen.findByText('11,778')
  })
})
