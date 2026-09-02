/**
 * The assistant's voice paths, exercised without a microphone or a speaker.
 *
 * jsdom has neither, which is the point: each engine is stubbed in turn so the
 * test says which control appears under which conditions, and that a reply is
 * handed to the synthesiser when the speaker is on.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const askAssistant = vi.fn()
const getVoice = vi.fn()
const transcribeAudio = vi.fn()
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    askAssistant: (...args: unknown[]) => askAssistant(...args),
    getVoice: (...args: unknown[]) => getVoice(...args),
    transcribeAudio: (...args: unknown[]) => transcribeAudio(...args),
  }
})

import { Assistant, downsample, encodeWav } from '../components/Assistant'

const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true }
const REPLY = {
  kind: 'answer',
  answer: 'The CNMC is the code SAMAN issues.',
  action: null,
  citations: [],
  suggestions: [],
  mode: 'deterministic',
}

function renderAssistant() {
  return render(
    <MemoryRouter future={ROUTER_FUTURE}>
      <Assistant />
    </MemoryRouter>,
  )
}

function open() {
  fireEvent.click(screen.getByRole('button', { name: /ask saman/i }))
}

// jsdom's window lacks every speech API; each test installs the one it needs
// and removes it again. Typed loosely so the removals are legal.
const w = window as unknown as Record<string, unknown>

describe('the WAV encoder', () => {
  it('writes a 16-bit mono PCM header the server accepts', async () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1])
    const blob = encodeWav(samples, 16_000)
    expect(blob.type).toBe('audio/wav')
    expect(blob.size).toBe(44 + samples.length * 2)
    const view = new DataView(await blob.arrayBuffer())
    const ascii = (o: number, n: number) =>
      String.fromCharCode(...new Uint8Array(view.buffer, o, n))
    expect(ascii(0, 4)).toBe('RIFF')
    expect(ascii(8, 4)).toBe('WAVE')
    expect(view.getUint16(22, true)).toBe(1) // channels
    expect(view.getUint32(24, true)).toBe(16_000) // rate
    expect(view.getUint16(34, true)).toBe(16) // bits
    expect(view.getInt16(46, true)).toBe(Math.round(0.5 * 0x7fff))
    expect(view.getInt16(50, true)).toBe(0x7fff)
    expect(view.getInt16(52, true)).toBe(-0x8000)
  })

  it('downsamples 48 kHz capture to 16 kHz', () => {
    const chunks = [new Float32Array(4800).fill(0.25), new Float32Array(4800).fill(0.25)]
    const out = downsample(chunks, 48_000, 16_000)
    expect(out.length).toBe(3200)
    expect(out[100]).toBeCloseTo(0.25)
  })
})

describe('voice in the assistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    askAssistant.mockResolvedValue(REPLY)
    getVoice.mockRejectedValue(new Error('no api'))
  })
  afterEach(() => {
    delete w['webkitSpeechRecognition']
    delete w['speechSynthesis']
    delete w['SpeechSynthesisUtterance']
    delete w['AudioContext']
  })

  it('offers no microphone and no speaker where the browser has neither', () => {
    renderAssistant()
    open()
    expect(screen.queryByRole('button', { name: /speak your question/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /read replies aloud/i })).not.toBeInTheDocument()
  })

  it('offers the browser recogniser when that is all there is', () => {
    const instances: Array<{ start: ReturnType<typeof vi.fn> }> = []
    w['webkitSpeechRecognition'] = class {
      lang = ''
      interimResults = false
      maxAlternatives = 1
      onresult: ((e: unknown) => void) | null = null
      onend: (() => void) | null = null
      onerror: ((e: unknown) => void) | null = null
      start = vi.fn()
      stop = vi.fn()
      constructor() {
        instances.push(this)
      }
    }
    renderAssistant()
    open()
    const mic = screen.getByRole('button', { name: /^speak your question$/i })
    fireEvent.click(mic)
    expect(instances).toHaveLength(1)
    expect(instances[0].start).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /stop listening/i })).toBeInTheDocument()
  })

  it('prefers the server recogniser when the server has one', async () => {
    getVoice.mockResolvedValue({ available: true, mode: 'whisper', engine: 'faster-whisper' })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn() },
    })
    w['AudioContext'] = class {}
    renderAssistant()
    open()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /transcribed on this server/i }),
      ).toBeInTheDocument(),
    )
    // Talk mode exists only where the server can listen; it is the loop of
    // listen, answer, speak, listen again.
    expect(screen.getByRole('button', { name: /talk mode/i })).toBeInTheDocument()
  })

  it('does not offer talk mode on the browser recogniser', () => {
    w['webkitSpeechRecognition'] = class {
      lang = ''
      interimResults = false
      maxAlternatives = 1
      onresult = null
      onend = null
      onerror = null
      start = vi.fn()
      stop = vi.fn()
    }
    renderAssistant()
    open()
    expect(screen.queryByRole('button', { name: /talk mode/i })).not.toBeInTheDocument()
  })

  it('reads a reply aloud when the speaker is on, and on request', async () => {
    const spoken: string[] = []
    w['SpeechSynthesisUtterance'] = class {
      text: string
      lang = ''
      rate = 1
      voice: unknown = null
      onstart: (() => void) | null = null
      onend: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor(text: string) {
        this.text = text
      }
    }
    w['speechSynthesis'] = {
      speak: vi.fn((u: { text: string }) => spoken.push(u.text)),
      cancel: vi.fn(),
      getVoices: () => [],
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as SpeechSynthesis
    renderAssistant()
    open()
    const toggle = screen.getByRole('button', { name: /read replies aloud/i })
    fireEvent.click(toggle)
    expect(spoken.at(-1)).toMatch(/speaker on/i)
    fireEvent.click(screen.getByRole('button', { name: /what is a cnmc/i }))
    await screen.findByText(/the cnmc is the code/i)
    expect(spoken.at(-1)).toBe(REPLY.answer)
    // Every reply can be read on demand, whatever the toggle says.
    fireEvent.click(toggle) // off
    fireEvent.click(screen.getByRole('button', { name: /read this reply aloud/i }))
    expect(spoken.filter((t) => t === REPLY.answer)).toHaveLength(2)
  })
})
