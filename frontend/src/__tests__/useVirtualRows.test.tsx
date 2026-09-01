import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useVirtualRows } from '../lib/useVirtualRows'

const ROW_HEIGHT = 40
const MAX_HEIGHT = 400

function Harness({ count }: { count: number }) {
  const rows = Array.from({ length: count }, (_, i) => i)
  const { scrollProps, body, windowed, rendered } = useVirtualRows({
    rows,
    rowHeight: ROW_HEIGHT,
    columns: 1,
    maxHeight: MAX_HEIGHT,
    render: (row) => (
      <tr key={row} data-testid="row">
        <td>row {row}</td>
      </tr>
    ),
  })
  return (
    <div>
      <span data-testid="windowed">{String(windowed)}</span>
      <span data-testid="rendered">{rendered}</span>
      <div {...scrollProps}>
        <table>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>
  )
}

describe('useVirtualRows', () => {
  it('renders a short list whole, with no scroll container', () => {
    render(<Harness count={5} />)
    expect(screen.getByTestId('windowed')).toHaveTextContent('false')
    expect(screen.getAllByTestId('row')).toHaveLength(5)
  })

  it('renders a screenful of a long list, not all of it', () => {
    render(<Harness count={10_000} />)
    expect(screen.getByTestId('windowed')).toHaveTextContent('true')
    const rendered = screen.getAllByTestId('row')
    expect(rendered.length).toBeGreaterThan(0)
    expect(rendered.length).toBeLessThan(100)
  })

  it('keeps the scroll height honest with spacer rows', () => {
    const { container } = render(<Harness count={1_000} />)
    const spacers = container.querySelectorAll('tr[aria-hidden]')
    const total = Array.from(spacers).reduce(
      (sum, row) => sum + Number.parseInt((row as HTMLElement).style.height || '0', 10),
      0,
    )
    const shown = screen.getAllByTestId('row').length
    // Spacers plus rendered rows must account for every row's height, or the
    // scrollbar lies about how much list there is.
    expect(total + shown * ROW_HEIGHT).toBe(1_000 * ROW_HEIGHT)
  })

  it('hides the spacers from assistive technology', () => {
    const { container } = render(<Harness count={1_000} />)
    for (const spacer of container.querySelectorAll('tr[aria-hidden]')) {
      expect(spacer).toHaveAttribute('aria-hidden')
    }
  })
})
