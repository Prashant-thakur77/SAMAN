import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError, askAssistant, type AssistantReply } from '../lib/api'
import { cn } from '../lib/cn'
import { EASE } from '../lib/motion'

/**
 * The floating assistant, docked bottom-right on every screen.
 *
 * It does three things and hands off the rest. Say where you want to go and it
 * takes you there; ask what something means and it tells you and offers the
 * screen; ask about the data and the answer comes from the Copilot, guards,
 * scope and citations intact. Voice in and voice out ride on the browser's own
 * speech engines when they exist and disappear when they do not.
 */

type Turn = {
  id: number
  role: 'user' | 'assistant'
  text: string
  reply?: AssistantReply
  error?: boolean
}

const OPENERS = [
  'Take me to the workbench',
  'What is a CNMC?',
  'Which CPSE overpays for gaskets?',
  'How does it decide two rows are the same?',
]

const SPEAK_KEY = 'saman.assistant.speak'
const STATE_KEY = 'saman.assistant.state'

type Persisted = { open: boolean; turns: Turn[] }

function loadState(): Persisted {
  try {
    const raw = sessionStorage.getItem(STATE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Persisted
      if (Array.isArray(parsed.turns)) return { open: Boolean(parsed.open), turns: parsed.turns }
    }
  } catch {
    /* a private window or a blocked store starts a fresh conversation */
  }
  return { open: false, turns: [] }
}

function saveState(state: Persisted) {
  try {
    sessionStorage.setItem(STATE_KEY, JSON.stringify(state))
  } catch {
    /* not persisting is survivable */
  }
}

type RecognitionCtor = new () => SpeechRecognitionLike
type SpeechRecognitionLike = {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
  start: () => void
  stop: () => void
}

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor
    webkitSpeechRecognition?: RecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

function canSpeak(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

/** The mark: a bearing race seen end-on, with a spark where the ball would be. */
export function AssistantMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden className={className} fill="none">
      <circle cx="20" cy="20" r="17" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="20" cy="20" r="10.5" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M20 12.5 L21.6 18.4 L27.5 20 L21.6 21.6 L20 27.5 L18.4 21.6 L12.5 20 L18.4 18.4 Z"
        fill="currentColor"
      />
    </svg>
  )
}

export function Assistant() {
  const [initial] = useState(loadState)
  const [open, setOpen] = useState(initial.open)
  const [turns, setTurns] = useState<Turn[]>(initial.turns)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [speak, setSpeak] = useState(() => {
    try {
      return localStorage.getItem(SPEAK_KEY) === '1'
    } catch {
      return false
    }
  })
  const [voiceIn] = useState(() => recognitionCtor() !== null)
  const [voiceOut] = useState(() => canSpeak())
  const recognition = useRef<SpeechRecognitionLike | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const launcherRef = useRef<HTMLButtonElement>(null)
  const counter = useRef(initial.turns.reduce((max, t) => Math.max(max, t.id), 0))
  const navigate = useNavigate()
  const location = useLocation()
  const reduce = useReducedMotion() ?? false

  useEffect(() => {
    if (!open) return
    const id = requestAnimationFrame(() => inputRef.current?.focus())
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        launcherRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(id)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    saveState({ open, turns })
  }, [open, turns])

  useEffect(() => {
    // jsdom has no scrollIntoView; a test environment is not a reason to throw.
    endRef.current?.scrollIntoView?.({ block: 'end', behavior: reduce ? 'auto' : 'smooth' })
  }, [turns, reduce])

  const say = useCallback(
    (text: string) => {
      if (!speak || !canSpeak()) return
      try {
        window.speechSynthesis.cancel()
        const utterance = new SpeechSynthesisUtterance(text)
        // Prefer an Indian English voice where the platform offers one.
        const voices = window.speechSynthesis.getVoices()
        const preferred =
          voices.find((v) => /en-IN/i.test(v.lang)) ?? voices.find((v) => /^en/i.test(v.lang))
        if (preferred) utterance.voice = preferred
        utterance.rate = 1
        window.speechSynthesis.speak(utterance)
      } catch {
        /* a platform without voices is a platform that reads */
      }
    },
    [speak],
  )

  const ask = useCallback(
    async (raw: string) => {
      const question = raw.trim()
      if (!question || busy) return
      setDraft('')
      setBusy(true)
      const userId = ++counter.current
      setTurns((prev) => [...prev, { id: userId, role: 'user', text: question }])
      try {
        const reply = await askAssistant(question, location.pathname)
        setTurns((prev) => [
          ...prev,
          { id: ++counter.current, role: 'assistant', text: reply.answer, reply },
        ])
        say(reply.answer)
        // A navigation answer is performed, not described. The card stays so
        // the person can see what happened and come back.
        if (reply.kind === 'navigate' && reply.action?.type === 'navigate') {
          navigate(reply.action.to)
        }
      } catch (err) {
        const text =
          err instanceof ApiError ? err.message : 'I could not reach the API. Is it running on :8000?'
        setTurns((prev) => [...prev, { id: ++counter.current, role: 'assistant', text, error: true }])
      } finally {
        setBusy(false)
      }
    },
    [busy, location.pathname, navigate, say],
  )

  function toggleListening() {
    const Ctor = recognitionCtor()
    if (!Ctor) return
    if (listening) {
      recognition.current?.stop()
      setListening(false)
      return
    }
    const rec = new Ctor()
    rec.lang = 'en-IN'
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? ''
      setListening(false)
      if (transcript) void ask(transcript)
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recognition.current = rec
    setListening(true)
    try {
      rec.start()
    } catch {
      setListening(false)
    }
  }

  function toggleSpeak() {
    setSpeak((current) => {
      const next = !current
      try {
        localStorage.setItem(SPEAK_KEY, next ? '1' : '0')
      } catch {
        /* not persisting is survivable */
      }
      if (!next && canSpeak()) window.speechSynthesis.cancel()
      return next
    })
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void ask(draft)
  }

  return (
    <>
      {/* Launcher */}
      <button
        ref={launcherRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="saman-assistant"
        aria-label={open ? 'Close the assistant' : 'Ask SAMAN'}
        className={cn(
          'fixed bottom-5 right-5 z-40 flex h-12 items-center gap-2 rounded-full border border-hairline',
          'bg-bg pl-2 pr-4 text-sm font-medium text-ink shadow-sm transition-opacity duration-150',
          'hover:bg-surface',
          open && 'opacity-0 pointer-events-none',
        )}
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-inverse text-bg">
          <AssistantMark className="h-5 w-5" />
        </span>
        Ask SAMAN
      </button>

      <AnimatePresence>
        {open && (
          <motion.section
            id="saman-assistant"
            role="dialog"
            aria-label="SAMAN assistant"
            initial={{ opacity: 0, y: reduce ? 0 : 16, scale: reduce ? 1 : 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1, transition: { duration: 0.22, ease: EASE } }}
            exit={{ opacity: 0, y: reduce ? 0 : 12, transition: { duration: 0.14 } }}
            className={cn(
              'fixed bottom-5 right-5 z-50 flex max-h-[min(40rem,calc(100vh-2.5rem))] w-[min(24rem,calc(100vw-2.5rem))] flex-col',
              'overflow-hidden rounded-2xl border border-hairline bg-bg text-ink shadow-sm',
            )}
          >
            <header className="flex items-center gap-3 border-b border-hairline px-4 py-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-inverse text-bg">
                <AssistantMark className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium leading-tight">Ask SAMAN</p>
                <p className="micro-label leading-tight">Navigate · explain · query</p>
              </div>
              {voiceOut && (
                <button
                  type="button"
                  onClick={toggleSpeak}
                  aria-pressed={speak}
                  aria-label={speak ? 'Stop reading replies aloud' : 'Read replies aloud'}
                  title={speak ? 'Reading replies aloud' : 'Read replies aloud'}
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-full border border-hairline',
                    speak ? 'bg-inverse text-bg' : 'text-muted hover:text-ink',
                  )}
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
                    <path d="M3 8v4h3l4 3V5L6 8H3z" />
                    <path d="M13 7.5a3.5 3.5 0 0 1 0 5" />
                    <path d="M15 5a6.5 6.5 0 0 1 0 10" />
                  </svg>
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  launcherRef.current?.focus()
                }}
                aria-label="Close"
                className="flex h-8 w-8 items-center justify-center rounded-full text-muted hover:text-ink"
              >
                <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
                  <path d="M5 5l10 10M15 5L5 15" />
                </svg>
              </button>
            </header>

            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
              {turns.length === 0 && (
                <div className="space-y-3">
                  <p className="text-sm text-muted">
                    Say where you want to go, ask what something means, or ask about the data.
                  </p>
                  <ul className="flex flex-wrap gap-2">
                    {OPENERS.map((prompt) => (
                      <li key={prompt}>
                        <button
                          type="button"
                          onClick={() => void ask(prompt)}
                          className="rounded-full border border-hairline px-3 py-1.5 text-xs text-ink hover:bg-surface"
                        >
                          {prompt}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {turns.map((turn) => (
                <div
                  key={turn.id}
                  className={cn('flex', turn.role === 'user' ? 'justify-end' : 'justify-start')}
                >
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm',
                      turn.role === 'user'
                        ? 'rounded-br-md bg-inverse text-bg'
                        : 'rounded-bl-md border border-hairline bg-surface text-ink',
                      turn.error && 'text-danger',
                    )}
                  >
                    <p>{turn.text}</p>
                    {turn.reply?.action && turn.reply.kind !== 'navigate' && (
                      <button
                        type="button"
                        onClick={() => {
                          navigate(turn.reply!.action!.to)
                          setOpen(false)
                        }}
                        className="mt-2 inline-flex items-center gap-1 border-b border-ink text-xs font-medium"
                      >
                        {turn.reply.action.label} →
                      </button>
                    )}
                    {turn.reply?.kind === 'navigate' && turn.reply.action && (
                      <p className="micro-label mt-2">Opened {turn.reply.action.to}</p>
                    )}
                    {turn.reply?.citations && turn.reply.citations.length > 0 && (
                      <ul className="mt-2 flex flex-wrap gap-1.5">
                        {turn.reply.citations.slice(0, 4).map((cite, index) => (
                          <li key={index}>
                            <button
                              type="button"
                              onClick={() => {
                                if (cite.item_id) navigate(`/items/${cite.item_id}`)
                                else if (cite.cluster_id) navigate(`/clusters/${cite.cluster_id}`)
                              }}
                              className="code-chip max-w-full truncate hover:bg-bg"
                            >
                              {cite.cnmc ?? cite.legacy_code ?? cite.label ?? `#${cite.item_id ?? cite.cluster_id ?? index + 1}`}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ))}
              {busy && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-md border border-hairline bg-surface px-3.5 py-2.5 text-sm text-muted">
                    …
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-hairline p-3">
              {voiceIn && (
                <button
                  type="button"
                  onClick={toggleListening}
                  aria-pressed={listening}
                  aria-label={listening ? 'Stop listening' : 'Speak your question'}
                  className={cn(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-hairline',
                    listening ? 'bg-danger text-bg' : 'text-muted hover:text-ink',
                  )}
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
                    <rect x="7" y="3" width="6" height="10" rx="3" />
                    <path d="M4.5 10a5.5 5.5 0 0 0 11 0M10 15.5V18" />
                  </svg>
                </button>
              )}
              <input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={listening ? 'Listening…' : 'Ask, or say where to go'}
                aria-label="Ask the assistant"
                className="h-9 min-w-0 flex-1 rounded-full border border-hairline bg-bg px-3.5 text-sm text-ink placeholder:text-muted"
              />
              <button
                type="submit"
                disabled={busy || !draft.trim()}
                aria-label="Send"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-inverse text-bg disabled:opacity-40"
              >
                <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
                  <path d="M4 10h11M11 5l5 5-5 5" />
                </svg>
              </button>
            </form>
          </motion.section>
        )}
      </AnimatePresence>
    </>
  )
}
