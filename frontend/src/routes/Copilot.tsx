import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { Input } from '../components/primitives/Field'
import {
  ApiError,
  askCopilot,
  getCopilotSuggestions,
  type CopilotAnswer,
  type CopilotSuggestions,
} from '../lib/api'
import { cn } from '../lib/cn'
import { listItemVariants } from '../lib/motion'

type Turn = { question: string; answer: CopilotAnswer | null; error?: string }

/**
 * /copilot — spec §6.9.
 *
 * Answers arrive whole from the API and are typed out here, so the "streaming"
 * is presentational and never leaves a half-formed number on screen. Every
 * answer carries its citations and the exact query behind it.
 */
export default function Copilot() {
  const [suggestions, setSuggestions] = useState<CopilotSuggestions | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getCopilotSuggestions()
      .then(setSuggestions)
      .catch(() => setSuggestions(null))
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  async function ask(text: string) {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setQuestion('')
    setTurns((prev) => [...prev, { question: trimmed, answer: null }])
    try {
      const answer = await askCopilot(trimmed)
      setTurns((prev) =>
        prev.map((turn, i) => (i === prev.length - 1 ? { ...turn, answer } : turn)),
      )
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'The copilot could not answer.'
      setTurns((prev) =>
        prev.map((turn, i) => (i === prev.length - 1 ? { ...turn, error: message } : turn)),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="Copilot"
        description="Ask about the material master in plain language. Answers cite their sources and show the query behind them; free-form SQL is never generated or run."
        actions={
          suggestions && (
            <StatusChip tone={suggestions.mode === 'ollama' ? 'ok' : 'neutral'}>
              {suggestions.sovereign_mode
                ? 'LOCAL MODE'
                : suggestions.mode === 'ollama'
                  ? 'local model active'
                  : 'template mode'}
            </StatusChip>
          )
        }
      />

      {suggestions && turns.length === 0 && (
        <section className="space-y-3">
          <p className="micro-label">Try one of these</p>
          <div className="flex flex-wrap gap-2">
            {suggestions.prompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => void ask(prompt)}
                className="card px-3 py-1.5 text-xs text-muted hover:text-ink"
              >
                {prompt}
              </button>
            ))}
          </div>
          <p className="max-w-prose pt-2 text-xs text-muted">{suggestions.note}</p>
        </section>
      )}

      <div className="space-y-6">
        <AnimatePresence initial={false}>
          {turns.map((turn, index) => (
            <motion.div
              key={`${index}-${turn.question}`}
              variants={listItemVariants(false)}
              initial="initial"
              animate="animate"
              className="space-y-3"
            >
              <p className="border-l-2 border-inverse pl-4 text-sm text-ink">{turn.question}</p>
              {turn.error ? (
                <p className="pl-4 text-sm text-danger">{turn.error}</p>
              ) : turn.answer ? (
                <AnswerBlock answer={turn.answer} />
              ) : (
                <p className="pl-4 text-sm text-muted">Thinking…</p>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          void ask(question)
        }}
        className="sticky bottom-0 flex gap-3 border-t border-hairline bg-bg py-4"
      >
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Which CPSE overpays for gaskets?"
          aria-label="Ask the copilot"
          className="font-mono"
        />
        <Button type="submit" variant="primary" disabled={busy || !question.trim()}>
          {busy ? 'Asking…' : 'Ask'}
        </Button>
      </form>
    </div>
  )
}

function AnswerBlock({ answer }: { answer: CopilotAnswer }) {
  const [showQuery, setShowQuery] = useState(false)
  const text = useTypewriter(answer.answer)

  return (
    <div className="space-y-3 pl-4">
      <p className={cn('text-sm', answer.refused ? 'text-danger' : 'text-ink')}>
        {text}
        {text.length < answer.answer.length && (
          <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-ink align-middle" />
        )}
      </p>

      {answer.citations.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {answer.citations.map((citation, i) => (
            <Link
              key={`${citation.cluster_id}-${i}`}
              to={citation.cluster_id ? `/clusters/${citation.cluster_id}` : '#'}
              className="max-w-full truncate card px-2 py-1 font-mono text-[11px] text-muted hover:text-ink"
              title={citation.label}
            >
              {citation.cnmc ? `${citation.cnmc} · ` : ''}
              {citation.label}
            </Link>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {answer.sql && (
          <button
            type="button"
            onClick={() => setShowQuery((v) => !v)}
            className="micro-label underline underline-offset-2 hover:text-ink"
          >
            {showQuery ? 'hide query' : 'show query and evidence'}
          </button>
        )}
        <span className="micro-label">
          {answer.template ? `${answer.template} · ` : ''}
          {answer.mode}
        </span>
        {answer.llm_rejected && (
          <span className="micro-label text-danger" title={answer.llm_rejected}>
            model output rejected; showing the computed answer
          </span>
        )}
      </div>

      {showQuery && answer.sql && (
        <div className="space-y-3 card p-4">
          <p className="micro-label">Reviewed query</p>
          <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-muted">
            {answer.sql}
          </pre>
          {Object.keys(answer.params).length > 0 && (
            <>
              <p className="micro-label">Bound parameters</p>
              <pre className="font-mono text-[11px] text-muted">
                {JSON.stringify(answer.params, null, 2)}
              </pre>
            </>
          )}
          {answer.rows.length > 0 && (
            <>
              <p className="micro-label">Rows returned</p>
              <pre className="max-h-64 overflow-auto font-mono text-[11px] text-muted">
                {JSON.stringify(answer.rows.slice(0, 8), null, 2)}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/** Presentational typewriter (§6.9). The answer is already complete. */
function useTypewriter(full: string, speed = 12) {
  const reduce = useReducedMotion() ?? false
  const [shown, setShown] = useState(reduce ? full : '')

  useEffect(() => {
    if (reduce) {
      setShown(full)
      return
    }
    setShown('')
    let index = 0
    const timer = setInterval(() => {
      index += 3
      setShown(full.slice(0, index))
      if (index >= full.length) clearInterval(timer)
    }, speed)
    return () => clearInterval(timer)
  }, [full, speed, reduce])

  return shown
}
