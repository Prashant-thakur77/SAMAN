/**
 * §6.4's price-history sparkline. The interesting property is the axis: it is
 * deliberately not zero-based, and the labels have to state the range so the
 * exaggeration cannot mislead.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Sparkline } from '../components/charts/Sparkline'

const series = [
  { po_date: '2025-03-11', unit_price: 20838 },
  { po_date: '2025-05-18', unit_price: 22934 },
  { po_date: '2025-06-23', unit_price: 21464 },
  { po_date: '2026-05-19', unit_price: 20407 },
]

describe('the price sparkline', () => {
  it('draws a point per order plus a marker on the latest', () => {
    const { container } = render(<Sparkline points={series} />)
    expect(container.querySelectorAll('circle')).toHaveLength(series.length + 1)
    expect(container.querySelector('path')).toBeInTheDocument()
  })

  it('states the range it is drawing, because the axis is not zero-based', () => {
    render(<Sparkline points={series} />)
    expect(screen.getByText(/20,407/)).toBeInTheDocument()
    expect(screen.getByText(/22,934/)).toBeInTheDocument()
  })

  it('describes itself to a screen reader', () => {
    render(<Sparkline points={series} />)
    const label = screen.getByRole('img').getAttribute('aria-label') ?? ''
    expect(label).toMatch(/4 orders/)
    expect(label).toMatch(/20,407/)
  })

  it('orders by date, not by the order the rows arrived', () => {
    const shuffled = [series[2], series[0], series[3], series[1]]
    const { container: a } = render(<Sparkline points={series} />)
    const { container: b } = render(<Sparkline points={shuffled} />)
    expect(b.querySelector('path')?.getAttribute('d')).toBe(
      a.querySelector('path')?.getAttribute('d'),
    )
  })

  it('renders nothing for a single order', () => {
    const { container } = render(<Sparkline points={series.slice(0, 1)} />)
    expect(container.querySelector('svg')).toBeNull()
  })

  it('survives a perfectly flat price without dividing by zero', () => {
    const flat = series.map((p) => ({ ...p, unit_price: 500 }))
    const { container } = render(<Sparkline points={flat} />)
    const d = container.querySelector('path')?.getAttribute('d') ?? ''
    expect(d).not.toMatch(/NaN/)
  })

  it('ignores a row with no usable price', () => {
    const withHole = [...series, { po_date: '2026-06-01', unit_price: Number.NaN }]
    const { container } = render(<Sparkline points={withHole} />)
    expect(container.querySelector('path')?.getAttribute('d')).not.toMatch(/NaN/)
  })
})
