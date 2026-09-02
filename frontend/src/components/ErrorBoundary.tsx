import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from './primitives/Button'

type Props = { children: ReactNode }
type State = { error: Error | null }

/**
 * Catch a render error and keep the shell standing (spec §8A: never a crash).
 *
 * Without this, one bad render blanks the entire document — the worst thing
 * that can happen in front of an audience, because there is nothing left on
 * screen to explain it or navigate away from. The boundary keeps the sidebar
 * and command bar alive, says what broke, and offers the two ways out.
 *
 * A class component because that is still the only way to catch a render
 * error in React 18.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Not swallowed: the console is where a developer will look, and a demo
    // audience never sees it.
    console.error('SAMAN render error', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="space-y-6 border border-hairline p-8" role="alert">
        <div className="space-y-2">
          <p className="micro-label">Something on this screen failed</p>
          <h1 className="text-2xl">This page could not render</h1>
          <p className="max-w-prose text-sm text-muted">
            The rest of SAMAN is still running; the sidebar and every other screen work.
            Nothing has been written or lost.
          </p>
        </div>

        <pre className="overflow-x-auto border border-hairline p-4 font-mono text-xs text-muted">
          {error.message || String(error)}
        </pre>

        <div className="flex flex-wrap gap-3">
          <Button variant="primary" onClick={() => this.setState({ error: null })}>
            Try this screen again
          </Button>
          <Button variant="secondary" onClick={() => window.location.assign('/')}>
            Go to Home
          </Button>
        </div>
      </div>
    )
  }
}
