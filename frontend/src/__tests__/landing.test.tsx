/**
 * The public front page.
 *
 * It explains how the system decides and shows no measurements, so what is
 * worth protecting is the explanation itself: the five stages in order, the
 * sentence the veto layer exists for, and the fact that the page needs no
 * backend to say any of it.
 */

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  // The assistant widget asks the API about voice when it mounts. That is the
  // widget's business; the page itself must still fetch nothing.
  return { ...actual, getVoice: vi.fn(async () => ({ available: false, tts: { available: false } })) }
})

import Landing from '../routes/Landing'
import { ThemeProvider } from '../lib/theme'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

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
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('no network in a test'))
  })
  afterEach(() => vi.restoreAllMocks())

  it('leads with the claim and a way in', () => {
    renderLanding()
    expect(
      screen.getByRole('heading', { level: 1, name: /one nation, one material code/i }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /sign in|open the demo/i }).length,
    ).toBeGreaterThan(0)
  })

  it('asks nothing of the backend', () => {
    renderLanding()
    // The page carries no live figure, so it has nothing to fetch. Rendering
    // it with the API stopped must be indistinguishable from rendering it with
    // the API up.
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('shows one real cluster, raw rows through to the issued code', () => {
    renderLanding()
    // These are rows from the demo database, not copy written for the page, so
    // the front page cannot describe a system that does not exist (spec §10).
    for (const cpse of ['CPCL', 'GAIL', 'IOCL']) {
      expect(screen.getByText(cpse)).toBeInTheDocument()
    }
    expect(
      screen.getByText('BRG,BALL,85MM BORE,150MM OD,28MM W,ZZ,2720 KG,150 C,FAG,6217-2ZR/H150'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'BEARING, BALL DEEP GROOVE, 85MM BORE, 150MM OD, 28MM W, ZZ, FAG 6217-2ZR',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/one 85 mm bearing/i)).toBeInTheDocument()
  })

  it('shows a code in the issued format, check digit and all', () => {
    renderLanding()
    // CCCC-SSS-NNNNNN-K. A code on the front page that could not have been
    // issued is the sort of detail an assessor checks first.
    expect(screen.getByText(/^[A-Z]{4}-\d{3}-\d{6}-\d$/)).toBeInTheDocument()
  })

  it('pairs each problem with the mechanism that closes it', () => {
    renderLanding()
    const fixes = screen.getByRole('list', { name: /twelve problems/i })
    // Every row must carry both halves. A problem with no named mechanism is a
    // complaint; a mechanism with no named problem is a feature list.
    const rows = within(fixes).getAllByRole('listitem')
    expect(rows).toHaveLength(12)
    for (const row of rows) {
      // index, problem, mechanism: three cells, none of them empty.
      const cells = Array.from(row.querySelectorAll('span')).map((el) => el.textContent?.trim())
      expect(cells).toHaveLength(3)
      expect(cells.every(Boolean)).toBe(true)
    }
    expect(rows[0]).toHaveTextContent(/one material, many codes/i)
    expect(rows[11]).toHaveTextContent(/no network call at runtime/i)
  })

  it('gives the pipeline as five ordered steps', () => {
    renderLanding()
    const steps = screen.getByRole('list', { name: /cheap certainty first/i })
    const items = within(steps).getAllByRole('listitem')
    expect(items).toHaveLength(5)
    expect(items[0]).toHaveTextContent(/exact anchors/i)
    expect(items[4]).toHaveTextContent(/a person, with the evidence/i)
  })

  it('states the rule the veto layer exists for', () => {
    renderLanding()
    expect(screen.getByText('25 mm is not 30 mm.')).toBeInTheDocument()
    expect(screen.getByText(/no score overrules it/i)).toBeInTheDocument()
  })

  it('takes a real issued code apart', () => {
    renderLanding()
    // BRNG-010-000003-7 is a code this system issues, not an invented shape.
    expect(screen.getAllByText(/BRNG/).length).toBeGreaterThan(0)
    expect(screen.getByText(/damm digit/i)).toBeInTheDocument()
  })

  it('states that it is a prototype, not an official service', () => {
    renderLanding()
    expect(
      screen.getByText(/not an official service of the government of india/i),
    ).toBeInTheDocument()
  })
})
