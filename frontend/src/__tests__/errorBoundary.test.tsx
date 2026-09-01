/**
 * §8A: never a crash. One bad render must not blank the document, because
 * there would be nothing left on screen to explain it or navigate away from.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from '../components/ErrorBoundary'

function Explodes({ boom }: { boom: boolean }): JSX.Element {
  if (boom) throw new Error('attribute grid could not render')
  return <p>the screen</p>
}

describe('the error boundary', () => {
  beforeEach(() => {
    // React logs the caught error itself; the test output is not the place.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders its children when nothing is wrong', () => {
    render(
      <ErrorBoundary>
        <Explodes boom={false} />
      </ErrorBoundary>,
    )
    expect(screen.getByText('the screen')).toBeInTheDocument()
  })

  it('catches a render error instead of unmounting the app', () => {
    render(
      <ErrorBoundary>
        <Explodes boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('This page could not render')).toBeInTheDocument()
  })

  it('says what broke rather than only that something did', () => {
    render(
      <ErrorBoundary>
        <Explodes boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('attribute grid could not render')).toBeInTheDocument()
  })

  it('offers a way back', async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <ErrorBoundary>
        <Explodes boom />
      </ErrorBoundary>,
    )
    rerender(
      <ErrorBoundary>
        <Explodes boom={false} />
      </ErrorBoundary>,
    )
    await user.click(screen.getByRole('button', { name: /try this screen again/i }))
    expect(screen.getByText('the screen')).toBeInTheDocument()
  })

  it('reassures the reader that nothing was written', () => {
    render(
      <ErrorBoundary>
        <Explodes boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/Nothing has been written or lost/)).toBeInTheDocument()
  })
})
