import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import {
  ApiError,
  askAssistant,
  getVoice,
  speakText,
  transcribeAudio,
  type AssistantReply,
} from '../lib/api'
import { cn } from '../lib/cn'
import { EASE } from '../lib/motion'

/**
 * The floating assistant, docked bottom-right on every screen.
 *
 * It does three things and hands off the rest. Say where you want to go and it
 * takes you there; ask what something means and it tells you and offers the
 * screen; ask about the data and the answer comes from the Copilot, guards,
 * scope and citations intact.
 *
 * Voice, in order of preference:
 *   1. the server's local recogniser (`/api/assistant/transcribe`), which
 *      keeps the audio on the machine: the page records raw PCM, encodes a
 *      WAV, and posts it;
 *   2. the browser's own `SpeechRecognition`, where the server has none;
 *   3. no microphone at all, rather than one that cannot work.
 * Replies are read aloud through `speechSynthesis` when the speaker is on, and
 * every reply carries its own "read" button.
 */

type Turn = {
  id: number
  role: 'user' | 'assistant'
  text: string
  reply?: AssistantReply
  error?: boolean
  heard?: string
}

const OPENERS = [
  'Take me to the workbench',
  'What is a CNMC?',
  'Which CPSE overpays for gaskets?',
  'How does it decide two rows are the same?',
]

const SPEAK_KEY = 'saman.assistant.speak'
const STATE_KEY = 'saman.assistant.state'

/** Recording stops on its own after this much quiet following speech… */
const QUIET_MS = 1_300
/** …or after this long regardless, so a forgotten microphone is not left open. */
const MAX_RECORD_MS = 15_000
/** Floor for the speech threshold; the real one adapts to the room. */
const SPEECH_RMS_FLOOR = 0.006
/** Speech must exceed the measured ambient level by this factor. */
const SPEECH_OVER_AMBIENT = 3
/** How long the room is measured before speech is expected. */
const CALIBRATE_MS = 350
/** A running transcript is refreshed this often while you speak. */
const INTERIM_MS = 900
const TARGET_RATE = 16_000

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
  onerror: ((event: { error?: string }) => void) | null
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

function audioContextCtor(): (typeof AudioContext) | null {
  const w = window as unknown as {
    AudioContext?: typeof AudioContext
    webkitAudioContext?: typeof AudioContext
  }
  return w.AudioContext ?? w.webkitAudioContext ?? null
}

function canCapture(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    audioContextCtor() !== null
  )
}

function canSpeak(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

type VoiceMode = 'server' | 'browser' | 'none'

/* ---------- audio capture: raw PCM -> 16 kHz mono WAV ---------- */

type Capture = {
  stream: MediaStream
  ctx: AudioContext
  source: MediaStreamAudioSourceNode
  processor: ScriptProcessorNode
  chunks: Float32Array[]
  rate: number
  heardSpeech: boolean
  lastLoud: number
  startedAt: number
  timer: number | null
  ambient: number
  ambientFrames: number
  interimTimer: number | null
  interimBusy: boolean
}

export function downsample(chunks: Float32Array[], from: number, to: number): Float32Array {
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const joined = new Float32Array(total)
  let offset = 0
  for (const c of chunks) {
    joined.set(c, offset)
    offset += c.length
  }
  if (from === to) return joined
  const ratio = from / to
  const out = new Float32Array(Math.floor(joined.length / ratio))
  for (let i = 0; i < out.length; i++) {
    const pos = i * ratio
    const lo = Math.floor(pos)
    const hi = Math.min(lo + 1, joined.length - 1)
    const frac = pos - lo
    out[i] = joined[lo] * (1 - frac) + joined[hi] * frac
  }
  return out
}

export function encodeWav(samples: Float32Array, rate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const write = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i))
  }
  write(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  write(8, 'WAVE')
  write(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  let offset = 44
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, Math.round(s < 0 ? s * 0x8000 : s * 0x7fff), true)
  }
  return new Blob([buffer], { type: 'audio/wav' })
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

function IconSpeaker({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden
    >
      <path d="M3 8v4h3l4 3V5L6 8H3z" />
      <path d="M13 7.5a3.5 3.5 0 0 1 0 5" />
      <path d="M15 5a6.5 6.5 0 0 1 0 10" />
    </svg>
  )
}

function IconMic({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden
    >
      <rect x="7" y="3" width="6" height="10" rx="3" />
      <path d="M4.5 10a5.5 5.5 0 0 0 11 0M10 15.5V18" />
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
  const [transcribing, setTranscribing] = useState(false)
  /** Microphone level 0..1, for the meter. */
  const [level, setLevel] = useState(0)
  /** What the recogniser has caught so far, shown while you are still talking. */
  const [interim, setInterim] = useState('')
  /** Talk mode: listen, answer, speak, listen again, until switched off. */
  const [handsFree, setHandsFree] = useState(false)
  const handsFreeRef = useRef(false)
  const startCaptureRef = useRef<() => Promise<void>>(async () => {})
  const [speaking, setSpeaking] = useState(false)
  const [speak, setSpeak] = useState(() => {
    try {
      return localStorage.getItem(SPEAK_KEY) === '1'
    } catch {
      return false
    }
  })
  const [voiceMode, setVoiceMode] = useState<VoiceMode>(() =>
    recognitionCtor() ? 'browser' : 'none',
  )
  /** Where spoken replies come from: the server's voice, the browser's, or
   *  nowhere (in which case the speaker button says so instead of pretending). */
  const [speechMode, setSpeechMode] = useState<'server' | 'browser' | 'none'>(() =>
    canSpeak() ? 'browser' : 'none',
  )
  const voiceOut = speechMode !== 'none'
  const player = useRef<HTMLAudioElement | null>(null)
  const recognition = useRef<SpeechRecognitionLike | null>(null)
  const capture = useRef<Capture | null>(null)
  const voicesRef = useRef<SpeechSynthesisVoice[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const launcherRef = useRef<HTMLButtonElement>(null)
  const counter = useRef(initial.turns.reduce((max, t) => Math.max(max, t.id), 0))
  const navigate = useNavigate()
  const location = useLocation()
  const reduce = useReducedMotion() ?? false

  // Which microphone, if any. The server's recogniser wins when it exists and
  // the page can capture audio; the browser's is second; otherwise none.
  useEffect(() => {
    let alive = true
    getVoice()
      .then((voice) => {
        if (!alive) return
        if (voice.available && canCapture()) setVoiceMode('server')
        if (voice.tts?.available) setSpeechMode('server')
      })
      .catch(() => {
        /* the API being down leaves the browser engines, or nothing */
      })
    return () => {
      alive = false
    }
  }, [])

  // The browser's synthesiser counts only if it has a voice to speak with.
  // Linux Chromium reports none and fails `speak()` silently, which is how a
  // widget ends up "talking" to a room that hears nothing.
  useEffect(() => {
    if (!canSpeak()) return
    let settled = false
    const check = () => {
      if (settled) return
      const voices = window.speechSynthesis.getVoices()
      if (voices.length > 0) {
        settled = true
        return
      }
    }
    check()
    const timer = window.setTimeout(() => {
      if (!settled && window.speechSynthesis.getVoices().length === 0) {
        setSpeechMode((current) => (current === 'server' ? current : 'none'))
      }
    }, 1500)
    window.speechSynthesis.addEventListener?.('voiceschanged', check)
    return () => {
      window.clearTimeout(timer)
      if (canSpeak()) window.speechSynthesis.removeEventListener?.('voiceschanged', check)
    }
  }, [])

  // Chrome populates voices asynchronously; ask once and listen for the rest.
  useEffect(() => {
    if (!canSpeak()) return
    const load = () => {
      voicesRef.current = window.speechSynthesis.getVoices()
    }
    load()
    window.speechSynthesis.addEventListener?.('voiceschanged', load)
    return () => {
      // Guarded: the API can be gone by unmount (tests remove it; so can a
      // browser extension), and a cleanup must never throw.
      if (canSpeak()) window.speechSynthesis.removeEventListener?.('voiceschanged', load)
    }
  }, [])

  useEffect(() => {
    saveState({ open, turns })
  }, [open, turns])

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
    // jsdom has no scrollIntoView; a test environment is not a reason to throw.
    endRef.current?.scrollIntoView?.({ block: 'end', behavior: reduce ? 'auto' : 'smooth' })
  }, [turns, reduce])

  const stopSpeaking = useCallback(() => {
    if (player.current) {
      try {
        player.current.pause()
        player.current.src = ''
      } catch {
        /* nothing was playing */
      }
      player.current = null
    }
    if (canSpeak()) {
      try {
        window.speechSynthesis.cancel()
      } catch {
        /* nothing was speaking */
      }
    }
    setSpeaking(false)
  }, [])

  const pushError = useCallback((text: string) => {
    setTurns((prev) => [...prev, { id: ++counter.current, role: 'assistant', text, error: true }])
  }, [])

  const speakViaServer = useCallback(
    async (text: string, onDone?: () => void) => {
      try {
        const blob = await speakText(text)
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        player.current = audio
        const finish = () => {
          URL.revokeObjectURL(url)
          if (player.current === audio) player.current = null
          setSpeaking(false)
          onDone?.()
        }
        audio.onended = finish
        audio.onerror = finish
        setSpeaking(true)
        await audio.play()
      } catch (err) {
        setSpeaking(false)
        pushError(
          err instanceof ApiError
            ? err.message
            : 'The reply could not be played. Check the browser allows audio on this site.',
        )
        onDone?.()
      }
    },
    [pushError],
  )

  const say = useCallback((text: string, onDone?: () => void) => {
    if (!text) {
      onDone?.()
      return
    }
    stopSpeaking()
    if (speechMode === 'server') {
      void speakViaServer(text, onDone)
      return
    }
    if (speechMode !== 'browser' || !canSpeak()) {
      onDone?.()
      return
    }
    try {
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      // Prefer an Indian English voice where the platform offers one; with no
      // voice list at all the platform default still speaks.
      const voices = voicesRef.current.length
        ? voicesRef.current
        : window.speechSynthesis.getVoices()
      const preferred =
        voices.find((v) => /en[-_]IN/i.test(v.lang)) ?? voices.find((v) => /^en/i.test(v.lang))
      if (preferred) utterance.voice = preferred
      utterance.lang = preferred?.lang ?? 'en-IN'
      utterance.rate = 1
      utterance.onstart = () => setSpeaking(true)
      utterance.onend = () => {
        setSpeaking(false)
        onDone?.()
      }
      utterance.onerror = () => {
        setSpeaking(false)
        onDone?.()
      }
      window.speechSynthesis.speak(utterance)
    } catch {
      setSpeaking(false)
      onDone?.()
    }
  }, [speechMode, speakViaServer, stopSpeaking])

  // Nothing keeps talking after the panel is closed or the page moves on.
  useEffect(() => {
    if (!open) stopSpeaking()
  }, [open, stopSpeaking])
  useEffect(() => () => stopSpeaking(), [stopSpeaking])

  const ask = useCallback(
    async (raw: string, heard?: string) => {
      const question = raw.trim()
      if (!question || busy) return
      setDraft('')
      setBusy(true)
      const userId = ++counter.current
      setTurns((prev) => [...prev, { id: userId, role: 'user', text: question, heard }])
      try {
        const reply = await askAssistant(question, location.pathname)
        setTurns((prev) => [
          ...prev,
          { id: ++counter.current, role: 'assistant', text: reply.answer, reply },
        ])
        // A spoken question is answered aloud whatever the toggle says: that
        // is what a conversation is. In talk mode the microphone reopens once
        // the reply has been read.
        const spoken = Boolean(heard)
        if (speak || spoken) {
          say(reply.answer, () => {
            if (handsFreeRef.current) void startCaptureRef.current()
          })
        }
        // A navigation answer is performed, not described. The card stays so
        // the person can see what happened and come back.
        if (reply.kind === 'navigate' && reply.action?.type === 'navigate') {
          navigate(reply.action.to)
        }
      } catch (err) {
        pushError(
          err instanceof ApiError ? err.message : 'I could not reach the API. Please try again.',
        )
      } finally {
        setBusy(false)
      }
    },
    [busy, location.pathname, navigate, pushError, say, speak],
  )

  /* ---------- server-side recognition: record, encode, post ---------- */

  const finishCapture = useCallback(async () => {
    const cap = capture.current
    if (!cap) return
    capture.current = null
    if (cap.timer) window.clearInterval(cap.timer)
    if (cap.interimTimer) window.clearInterval(cap.interimTimer)
    setLevel(0)
    try {
      cap.processor.disconnect()
      cap.source.disconnect()
      cap.stream.getTracks().forEach((t) => t.stop())
      await cap.ctx.close()
    } catch {
      /* already closed */
    }
    setListening(false)
    if (!cap.heardSpeech) {
      setInterim('')
      pushError('I did not hear anything. Try again, a little closer to the microphone.')
      if (handsFreeRef.current) setHandsFree(false)
      return
    }
    setTranscribing(true)
    try {
      const wav = encodeWav(downsample(cap.chunks, cap.rate, TARGET_RATE), TARGET_RATE)
      const result = await transcribeAudio(wav)
      const text = (result.text ?? '').trim()
      setInterim('')
      if (!text) {
        pushError('I could not make out any words. Try again.')
        if (handsFreeRef.current) void startCaptureRef.current()
        return
      }
      await ask(text, `heard · ${result.engine ?? 'local'}`)
    } catch (err) {
      // ":8000" was in this message, which is only true while developing:
      // served from anywhere else the API is on the same origin, so the
      // advice sent people to look at the wrong thing.
      pushError(
        err instanceof ApiError ? err.message : 'Transcription failed. Please try again.',
      )
    } finally {
      setTranscribing(false)
    }
  }, [ask, pushError])

  const startCapture = useCallback(async () => {
    const Ctx = audioContextCtor()
    if (!Ctx) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      const ctx = new Ctx()
      await ctx.resume?.()
      const source = ctx.createMediaStreamSource(stream)
      // ScriptProcessor is deprecated in favour of AudioWorklet, but it needs
      // no separate module file, works in every browser that has a
      // microphone, and 4096 frames of latency is nothing for an utterance.
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      const cap: Capture = {
        stream,
        ctx,
        source,
        processor,
        chunks: [],
        rate: ctx.sampleRate,
        heardSpeech: false,
        lastLoud: performance.now(),
        startedAt: performance.now(),
        timer: null,
        ambient: 0,
        ambientFrames: 0,
        interimTimer: null,
        interimBusy: false,
      }
      processor.onaudioprocess = (event) => {
        const data = event.inputBuffer.getChannelData(0)
        cap.chunks.push(new Float32Array(data))
        let sum = 0
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i]
        const rms = Math.sqrt(sum / data.length)
        const elapsed = performance.now() - cap.startedAt
        // The room's noise floor is the quietest the signal has been, drifting
        // up slowly so a floor measured in a silent moment does not stay there
        // forever. Tracking the minimum rather than the opening average means
        // somebody who starts talking the instant they press the button does
        // not teach the meter that speech is silence.
        cap.ambientFrames += 1
        if (cap.ambientFrames === 1 || rms < cap.ambient) cap.ambient = rms
        else cap.ambient += (rms - cap.ambient) * 0.01
        const threshold = Math.max(SPEECH_RMS_FLOOR, cap.ambient * SPEECH_OVER_AMBIENT)
        setLevel(Math.min(1, rms / Math.max(threshold * 4, 0.05)))
        if (elapsed >= CALIBRATE_MS / 3 && rms > threshold) {
          cap.heardSpeech = true
          cap.lastLoud = performance.now()
        }
      }
      source.connect(processor)
      processor.connect(ctx.destination)
      capture.current = cap
      setInterim('')
      setListening(true)
      // A running transcript: every INTERIM_MS, everything heard so far goes to
      // the server and the words come back into the box while you are still
      // talking, so you can see what is being caught.
      cap.interimTimer = window.setInterval(() => {
        // Only once there is speech to transcribe, and never two in flight.
        if (!cap.heardSpeech || cap.interimBusy || capture.current !== cap) return
        if (performance.now() - cap.lastLoud > QUIET_MS) return
        cap.interimBusy = true
        const wav = encodeWav(downsample(cap.chunks, cap.rate, TARGET_RATE), TARGET_RATE)
        transcribeAudio(wav)
          .then((r) => {
            if (capture.current === cap && r.text) setInterim(r.text.trim())
          })
          .catch(() => {
            /* an interim miss costs nothing; the final pass still runs */
          })
          .finally(() => {
            cap.interimBusy = false
          })
      }, INTERIM_MS)
      // End-pointing: stop after a pause that follows speech, or at the cap.
      cap.timer = window.setInterval(() => {
        const now = performance.now()
        if (
          (cap.heardSpeech && now - cap.lastLoud > QUIET_MS) ||
          now - cap.startedAt > MAX_RECORD_MS
        ) {
          void finishCapture()
        }
      }, 150)
    } catch {
      setListening(false)
      pushError('The microphone could not be opened. Check the browser permission.')
    }
  }, [finishCapture, pushError])

  useEffect(() => {
    startCaptureRef.current = startCapture
  }, [startCapture])
  useEffect(() => {
    handsFreeRef.current = handsFree
  }, [handsFree])

  function toggleHandsFree() {
    if (voiceMode !== 'server') return
    setHandsFree((current) => {
      const next = !current
      handsFreeRef.current = next
      if (next) {
        stopSpeaking()
        if (!listening && !transcribing) void startCapture()
      } else if (listening) {
        void finishCapture()
      }
      return next
    })
  }

  /* ---------- browser recognition ---------- */

  function startBrowserRecognition() {
    const Ctor = recognitionCtor()
    if (!Ctor) return
    const rec = new Ctor()
    rec.lang = 'en-IN'
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? ''
      setListening(false)
      if (transcript) void ask(transcript, 'heard · browser')
    }
    rec.onend = () => setListening(false)
    rec.onerror = (event) => {
      setListening(false)
      pushError(
        event?.error === 'not-allowed'
          ? 'The microphone is blocked for this site.'
          : event?.error === 'network'
            ? 'The browser recogniser needs the internet and this machine has none. Run `make deps-stt` for local recognition.'
            : 'The browser could not recognise speech.',
      )
    }
    recognition.current = rec
    setListening(true)
    try {
      rec.start()
    } catch {
      setListening(false)
    }
  }

  function toggleListening() {
    if (listening) {
      if (voiceMode === 'server') void finishCapture()
      else recognition.current?.stop()
      setListening(false)
      return
    }
    stopSpeaking()
    if (voiceMode === 'server') void startCapture()
    else if (voiceMode === 'browser') startBrowserRecognition()
  }

  function toggleSpeak() {
    if (speechMode === 'none') {
      pushError(
        'This browser has no voices and the server has no speech engine. Run `make deps-tts` for local speech.',
      )
      return
    }
    setSpeak((current) => {
      const next = !current
      try {
        localStorage.setItem(SPEAK_KEY, next ? '1' : '0')
      } catch {
        /* not persisting is survivable */
      }
      if (!next) stopSpeaking()
      else say('Speaker on. I will read replies aloud.')
      return next
    })
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void ask(draft)
  }

  const micLabel = listening
    ? 'Stop listening'
    : voiceMode === 'server'
      ? 'Speak your question (transcribed on this server)'
      : 'Speak your question'

  const status = speaking
    ? 'Speaking'
    : transcribing
      ? 'Transcribing'
      : listening
        ? handsFree
          ? 'Listening · talk mode'
          : 'Listening'
        : handsFree
          ? 'Talk mode · waiting'
          : 'Navigate · explain · query'

  return (
    <>
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
          open && 'pointer-events-none opacity-0',
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
              <span
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-inverse text-bg',
                  speaking && !reduce && 'animate-pulse',
                )}
              >
                <AssistantMark className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium leading-tight">Ask SAMAN</p>
                <p className="micro-label leading-tight" aria-live="polite">
                  {status}
                </p>
              </div>
              {voiceMode === 'server' && (
                <button
                  type="button"
                  onClick={toggleHandsFree}
                  aria-pressed={handsFree}
                  aria-label={handsFree ? 'Stop talk mode' : 'Talk mode: listen, answer, listen again'}
                  title={handsFree ? 'Talk mode on' : 'Talk mode'}
                  className={cn(
                    'flex h-8 items-center gap-1.5 rounded-full border border-hairline px-2.5 text-xs',
                    handsFree ? 'bg-inverse text-bg' : 'text-muted hover:text-ink',
                  )}
                >
                  <IconMic className="h-3.5 w-3.5" /> Talk
                </button>
              )}
              {(
                <button
                  type="button"
                  onClick={toggleSpeak}
                  aria-pressed={speak && voiceOut}
                  aria-label={speak && voiceOut ? 'Stop reading replies aloud' : 'Read replies aloud'}
                  title={
                    speechMode === 'server'
                      ? 'Read replies aloud (voice synthesised on this server)'
                      : speechMode === 'browser'
                        ? 'Read replies aloud (browser voice)'
                        : 'No speech engine available'
                  }
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-full border border-hairline',
                    speak ? 'bg-inverse text-bg' : 'text-muted hover:text-ink',
                  )}
                >
                  <IconSpeaker className="h-4 w-4" />
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
                <svg
                  viewBox="0 0 20 20"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  aria-hidden
                >
                  <path d="M5 5l10 10M15 5L5 15" />
                </svg>
              </button>
            </header>

            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
              {turns.length === 0 && (
                <div className="space-y-3">
                  <p className="text-sm text-muted">
                    Say where you want to go, ask what something means, or ask about the data.
                    {voiceMode !== 'none' && ' Or press the microphone and speak.'}
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
                      'min-w-0 max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm',
                      turn.role === 'user'
                        ? 'rounded-br-md bg-inverse text-bg'
                        : 'rounded-bl-md border border-hairline bg-surface text-ink',
                      turn.error && 'text-danger',
                    )}
                  >
                    <p>{turn.text}</p>
                    {turn.heard && <p className="micro-label mt-1 opacity-70">{turn.heard}</p>}
                    {turn.role === 'assistant' && !turn.error && voiceOut && (
                      <button
                        type="button"
                        onClick={() => say(turn.text)}
                        aria-label="Read this reply aloud"
                        title="Read this reply aloud"
                        className="mr-3 mt-2 inline-flex items-center gap-1 text-xs text-muted hover:text-ink"
                      >
                        <IconSpeaker className="h-3.5 w-3.5" /> read
                      </button>
                    )}
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
                      <ul className="mt-2 flex max-w-full flex-wrap gap-1.5">
                        {turn.reply.citations.slice(0, 4).map((cite, index) => (
                          <li key={index} className="min-w-0 max-w-full">
                            <button
                              type="button"
                              onClick={() => {
                                if (cite.item_id) navigate(`/items/${cite.item_id}`)
                                else if (cite.cluster_id) navigate(`/clusters/${cite.cluster_id}`)
                              }}
                              className="code-chip block max-w-full truncate hover:bg-bg"
                            >
                              {cite.cnmc ??
                                cite.legacy_code ??
                                cite.label ??
                                `#${cite.item_id ?? cite.cluster_id ?? index + 1}`}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ))}
              {(busy || transcribing) && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-md border border-hairline bg-surface px-3.5 py-2.5 text-sm text-muted">
                    {transcribing ? 'Transcribing…' : '…'}
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            <form
              onSubmit={onSubmit}
              className="flex items-center gap-2 border-t border-hairline p-3"
            >
              {voiceMode !== 'none' && (
                <button
                  type="button"
                  onClick={toggleListening}
                  disabled={transcribing}
                  aria-pressed={listening}
                  aria-label={micLabel}
                  title={micLabel}
                  className={cn(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-hairline',
                    listening ? 'bg-danger text-bg' : 'text-muted hover:text-ink',
                    !reduce && listening && 'animate-pulse',
                  )}
                >
                  <IconMic className="h-4 w-4" />
                </button>
              )}
              <div className="relative min-w-0 flex-1">
                <input
                  ref={inputRef}
                  value={listening && interim ? interim : draft}
                  readOnly={listening}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={
                    listening
                      ? 'Listening… pause when you are done'
                      : 'Ask, or say where to go'
                  }
                  aria-label="Ask the assistant"
                  className={cn(
                    'h-9 w-full rounded-full border border-hairline bg-bg px-3.5 text-sm text-ink placeholder:text-muted',
                    listening && interim && 'italic text-muted',
                  )}
                />
                {listening && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute inset-x-3 bottom-0.5 h-0.5 overflow-hidden rounded-full bg-hairline"
                  >
                    <span
                      className="block h-full bg-ink transition-[width] duration-100"
                      style={{ width: `${Math.round(level * 100)}%` }}
                    />
                  </span>
                )}
              </div>
              <button
                type="submit"
                disabled={busy || !draft.trim()}
                aria-label="Send"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-inverse text-bg disabled:opacity-40"
              >
                <svg
                  viewBox="0 0 20 20"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  aria-hidden
                >
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
