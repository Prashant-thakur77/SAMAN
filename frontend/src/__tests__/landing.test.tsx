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

  it('shows the same bearing as four catalogues write it', () => {
    renderLanding()
    expect(screen.getByText('BRG BALL DG 6205 ZZ SKF')).toBeInTheDocument()
    expect(screen.getByText('BEARING,BALL,DEEP GROOVE 25X52X15')).toBeInTheDocument()
    expect(screen.getByText(/every one of those is a 25 mm/i)).toBeInTheDocument()
  })

  it('gives the pipeline as five ordered steps', () => {
    renderLanding()
    const steps = screen.getByRole('list', { name: /cheap certainty first/i })
    const items = within(steps).getAllByRole('listitem')
    expect(items).toHaveLength(5)
    expect(items[0]).toHaveTextContent(/start with what is certain/i)
    expect(items[4]).toHaveTextContent(/hand the rest to a person/i)
  })

  it('states the rule the veto layer exists for', () => {
    renderLanding()
    expect(screen.getByText('25 mm is not 30 mm.')).toBeInTheDocument()
    expect(screen.getByText(/no score is permitted to overrule it/i)).toBeInTheDocument()
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
