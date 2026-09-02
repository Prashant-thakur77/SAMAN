/**
 * The floating assistant. What matters: a navigation answer is performed, an
 * explanatory answer offers its screen, the microphone appears only where the
 * browser can listen, and a dead API is a sentence rather than a spinner.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const askAssistant = vi.fn()
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return { ...actual, askAssistant: (...args: unknown[]) => askAssistant(...args) }
})

import { Assistant } from '../components/Assistant'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }

function WhereAmI() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}

function renderAssistant(start = '/') {
  return render(
    <MemoryRouter initialEntries={[start]} future={ROUTER_FUTURE}>
      <Routes>
        <Route path="*" element={<WhereAmI />} />
      </Routes>
      <Assistant />
    </MemoryRouter>,
  )
}

function open() {
  fireEvent.click(screen.getByRole('button', { name: /ask saman/i }))
}

describe('the assistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // The widget keeps its conversation in sessionStorage so it survives the
    // front page / application remount. One jsdom serves every test here, so
    // each one starts from an empty store or inherits the last one's chat.
    sessionStorage.clear()
  })

  it('starts closed, with a launcher', () => {
    renderAssistant()
    expect(screen.getByRole('button', { name: /ask saman/i })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens with suggestions and focuses the input', async () => {
    renderAssistant()
    open()
    expect(screen.getByRole('dialog', { name: /saman assistant/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /take me to the workbench/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/ask the assistant/i)).toHaveFocus())
  })

  it('performs a navigation answer rather than describing it', async () => {
    askAssistant.mockResolvedValue({
      kind: 'navigate',
      answer: 'Opening Workbench.',
      action: { type: 'navigate', to: '/workbench', label: 'Open Workbench' },
      citations: [],
      suggestions: [],
      mode: 'deterministic',
    })
    renderAssistant('/')
    open()
    fireEvent.click(screen.getByRole('button', { name: /take me to the workbench/i }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/workbench'))
    // The current path travels with the question, so "open the workbench"
    // from the workbench can be answered rather than performed.
    expect(askAssistant).toHaveBeenCalledWith('Take me to the workbench', '/')
  })

  it('offers the screen for an explanatory answer instead of jumping', async () => {
    askAssistant.mockResolvedValue({
      kind: 'answer',
      answer: 'The CNMC is the code SAMAN issues.',
      action: { type: 'navigate', to: '/welcome#code', label: 'See a code taken apart' },
      citations: [],
      suggestions: [],
      mode: 'deterministic',
    })
    renderAssistant('/')
    open()
    fireEvent.click(screen.getByRole('button', { name: /what is a cnmc/i }))
    expect(await screen.findByText(/the cnmc is the code/i)).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/')
    fireEvent.click(screen.getByRole('button', { name: /see a code taken apart/i }))
    expect(screen.getByTestId('where')).toHaveTextContent('/welcome')
  })

  it('shows citations from a Copilot answer as chips', async () => {
    askAssistant.mockResolvedValue({
      kind: 'copilot',
      answer: 'CPCL pays the most for gaskets.',
      action: { type: 'navigate', to: '/copilot', label: 'Continue in the Copilot' },
      citations: [{ item_id: 6, cnmc: 'GSKT-030-000001-9' }],
      suggestions: [],
      mode: 'template',
    })
    renderAssistant('/')
    open()
    fireEvent.change(screen.getByLabelText(/ask the assistant/i), {
      target: { value: 'which cpse overpays for gaskets' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }))
    const chip = await screen.findByRole('button', { name: 'GSKT-030-000001-9' })
    fireEvent.click(chip)
    expect(screen.getByTestId('where')).toHaveTextContent('/items/6')
  })

  it('hides the microphone where the browser cannot listen', () => {
    renderAssistant()
    open()
    // jsdom has no SpeechRecognition; the control must not promise what it
    // cannot do.
    expect(screen.queryByRole('button', { name: /speak your question/i })).not.toBeInTheDocument()
  })

  it('says so when the API is unreachable', async () => {
    askAssistant.mockRejectedValue(new TypeError('Failed to fetch'))
    renderAssistant()
    open()
    fireEvent.click(screen.getByRole('button', { name: /what is a cnmc/i }))
    expect(await screen.findByText(/could not reach the api/i)).toBeInTheDocument()
  })

  it('closes on Escape and returns focus to the launcher', async () => {
    renderAssistant()
    open()
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /ask saman/i })).toHaveFocus()
  })
})
