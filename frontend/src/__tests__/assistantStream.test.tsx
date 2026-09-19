/**
 * The streamed answer: sentences appear as they are released, and a refused
 * stream ends with the assistant's own words rather than the model's.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/** A stand-in EventSource the test drives by hand. */
class FakeEventSource {
  static last: FakeEventSource | null = null
  onmessage: ((m: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) {
    FakeEventSource.last = this
  }
  emit(event: unknown) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }
  close() {
    this.closed = true
  }
}
// Must exist before the widget module decides whether it can stream.
;(globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource

const askAssistant = vi.fn()
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return { ...actual, askAssistant: (...args: unknown[]) => askAssistant(...args) }
})

const { Assistant } = await import('../components/Assistant')

function ask(question: string) {
  fireEvent.click(screen.getByRole('button', { name: /ask saman/i }))
  const input = screen.getByLabelText(/ask the assistant/i)
  fireEvent.change(input, { target: { value: question } })
  fireEvent.submit(input.closest('form')!)
}

describe('a streamed answer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    FakeEventSource.last = null
    askAssistant.mockResolvedValue({
      kind: 'stream',
      answer: '',
      action: null,
      citations: [],
      suggestions: [],
      mode: 'llm',
    })
  })

  it('asks for a stream and fills the card sentence by sentence', async () => {
    render(
      <MemoryRouter>
        <Assistant />
      </MemoryRouter>,
    )
    ask('what is the damm check digit')
    await waitFor(() => expect(askAssistant).toHaveBeenCalledWith('what is the damm check digit', '/', true, []))
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull())
    const source = FakeEventSource.last!
    expect(source.url).toContain('/api/assistant/stream?q=what+is+the+damm+check+digit')
    source.emit({ type: 'sources', sources: [] })
    source.emit({ type: 'delta', text: 'The Damm digit catches transpositions.' })
    await screen.findByText(/The Damm digit catches transpositions\./)
    source.emit({ type: 'delta', text: ' It is one digit.' })
    source.emit({
      type: 'done',
      accepted: true,
      text: 'The Damm digit catches transpositions. It is one digit.',
    })
    await screen.findByText(/It is one digit\./)
    await waitFor(() => expect(source.closed).toBe(true))
  })

  it('replaces a refused stream with the fallback reply', async () => {
    render(
      <MemoryRouter>
        <Assistant />
      </MemoryRouter>,
    )
    ask('how fast is it')
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull())
    const source = FakeEventSource.last!
    source.emit({ type: 'delta', text: 'It is fast.' })
    await screen.findByText(/It is fast\./)
    source.emit({
      type: 'done',
      accepted: false,
      reason: 'invented_figure',
      text: '',
      fallback: {
        kind: 'answer',
        answer: 'That is outside what I know.',
        action: null,
        citations: [],
        suggestions: [],
        mode: 'deterministic',
      },
    })
    await screen.findByText(/That is outside what I know\./)
    expect(screen.queryByText(/It is fast\./)).toBeNull()
  })
})
