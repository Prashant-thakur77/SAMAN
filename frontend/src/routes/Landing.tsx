import { motion, useReducedMotion } from 'framer-motion'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import {
  getExecutive,
  getHealth,
  getMetrics,
  type ExecutiveDashboard,
  type Health,
  type MetricsReport,
} from '../lib/api'
import { cn } from '../lib/cn'
import { listItemVariants, listVariants } from '../lib/motion'

/**
 * / — the public front page (spec §1, §6.1).
 *
 * Everything the application asserts about itself is checkable from here
 * without signing in: the engine modes come from /api/health, the counts from
 * the executive dashboard, and the accuracy figures from /api/metrics, which
 * needs no session on purpose. A claim about precision that only its own
 * operators can verify is not evidence.
 *
 * Every one of those calls is allowed to fail. An empty database, a backend
 * that is not running and a first visit before `make demo` are all ordinary
 * states here: the page loses its numbers and keeps its sentences.
 */

const NAV = [
  { href: '#problem', label: 'The problem' },
  { href: '#what', label: 'What it does' },
  { href: '#how', label: 'How it works' },
  { href: '#evidence', label: 'Evidence' },
  { href: '#governance', label: 'Governance' },
] as const

/** The four counts worth showing a visitor, in the order they are produced. */
const HEADLINE_KPIS = ['items', 'clusters', 'duplicates', 'cnmcs'] as const

const PROBLEM = [
  {
    heading: 'One material, five descriptions',
    body: 'A deep-groove ball bearing, 25 mm bore, is "BRG BALL DG 6205 ZZ SKF" in one catalogue and "BEARING,BALL,DEEP GROOVE 25X52X15" in the next. Both are the same part. Neither system can tell.',
  },
  {
    heading: 'Stock nobody can see',
    body: 'One CPSE raises a purchase order for an item another holds in surplus two hundred kilometres away, because no query spans both catalogues. The stock exists; the name does not match.',
  },
  {
    heading: 'The same thing, bought twice',
    body: 'Without a shared code there is no shared tender, no negotiated rate across the sector, and no way to notice that four organisations are buying one item at four prices.',
  },
] as const

const CAPABILITIES = [
  {
    heading: 'Decides which rows are the same material',
    route: '/workbench',
    body: 'Exact anchors first, then probabilistic linkage, then meaning. Anything the engine is not sure about goes to a person with the evidence beside it.',
  },
  {
    heading: 'Issues one national code',
    route: '/clusters/:id',
    body: 'Each material gets a CNMC in the form CCCC-SSS-NNNNNN-K, closed by a Damm check digit so a transposed pair of digits is caught where it is typed.',
  },
  {
    heading: 'Moves the ERP without losing the past',
    route: '/migration',
    body: 'Plan, dry run, apply, verify, roll back. A superseded material is blocked, never deleted: the row and its history stay, which is how a real consolidation is done.',
  },
  {
    heading: 'Compares catalogues without exchanging them',
    route: '/pprl',
    body: 'Two CPSEs can measure their overlap from keyed encodings alone. Neither side learns a description it did not already hold, and the privacy cost is measured rather than asserted.',
  },
] as const

const PIPELINE = [
  {
    tier: 'Tier 0',
    heading: 'Exact anchors',
    body: 'A manufacturer part number, a GTIN or an identical normalised description settles the question outright. No score is needed for a fact.',
  },
  {
    tier: 'Tier 1',
    heading: 'Probabilistic linkage',
    body: 'Field-by-field agreement weighted by how often that agreement happens by chance, over candidate pairs from seven blocking passes.',
  },
  {
    tier: 'Tier 2',
    heading: 'Meaning, not spelling',
    body: 'Descriptions become vectors, so "SS316" and "STAINLESS STEEL 316" sit together even when no substring is shared.',
  },
  {
    tier: 'Veto',
    heading: 'A refusal outranks a score',
    body: 'Identity-critical attributes are compared with units understood. A 25 mm bore is not a 30 mm bore, however alike the two rows read, and no similarity is allowed to overrule that.',
  },
  {
    tier: 'Tier 3',
    heading: 'A person, with the evidence',
    body: 'What is left is a small grey band. The reviewer sees both rows, every attribute compared, and what the veto layer refused, and decides in one keystroke.',
  },
] as const

const GOVERNANCE = [
  {
    heading: 'Every change is on the record',
    body: 'Each mutation is one event in a hash chain, and each hash covers its own sequence number, so removing or reordering an entry breaks the chain as visibly as altering one. Anybody can re-walk it from the first event.',
  },
  {
    heading: 'Prices stay where they belong',
    body: 'A steward sees their own catalogue, their own prices and the shared golden layer. Another CPSE’s contract price is registrar and auditor scope, and the same function enforces that for the dashboards and the assistant alike.',
  },
  {
    heading: 'Offline by design',
    body: 'No runtime network call, anywhere. Optional components degrade to bundled ones rather than failing, and whichever is active is stated on this page and at /api/health.',
  },
] as const

const STEPS = [
  {
    heading: 'Bring a catalogue',
    body: 'Upload a CSV, confirm how its columns map, and read the dry run before a single row is written.',
  },
  {
    heading: 'Clear the grey band',
    body: 'The engine decides the confident cases. A reviewer sees only what genuinely needed a judgement.',
  },
  {
    heading: 'Adopt the code',
    body: 'Issue the CNMC, migrate the ERP against a plan that can be rolled back, and query stock across every CPSE at once.',
  },
] as const

function formatCount(value: number): string {
  return value.toLocaleString('en-IN')
}

function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

/** A section that rises into place once, the first time it is scrolled to. */
function Reveal({
  children,
  className,
  id,
  as = 'section',
}: {
  children: React.ReactNode
  className?: string
  id?: string
  as?: 'section' | 'div'
}) {
  const reduce = useReducedMotion() ?? false
  const Component = as === 'section' ? motion.section : motion.div
  return (
    <Component
      id={id}
      variants={listVariants(reduce)}
      initial="initial"
      whileInView="animate"
      viewport={{ once: true, margin: '-80px' }}
      className={className}
    >
      {children}
    </Component>
  )
}

function Item({ children, className }: { children: React.ReactNode; className?: string }) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.div variants={listItemVariants(reduce)} className={className}>
      {children}
    </motion.div>
  )
}

function SectionHeading({ label, title }: { label: string; title: string }) {
  return (
    <Item className="space-y-2">
      <p className="micro-label">{label}</p>
      <h2 className="text-xl font-medium">{title}</h2>
    </Item>
  )
}

export default function Landing() {
  const [health, setHealth] = useState<Health | null>(null)
  const [dashboard, setDashboard] = useState<ExecutiveDashboard | null>(null)
  const [metrics, setMetrics] = useState<MetricsReport | null>(null)
  const reduce = useReducedMotion() ?? false

  useEffect(() => {
    let alive = true
    // Settled rather than all: the page is worth reading with none of these.
    void Promise.allSettled([getHealth(), getExecutive(), getMetrics()]).then(
      ([h, d, m]) => {
        if (!alive) return
        if (h.status === 'fulfilled') setHealth(h.value)
        if (d.status === 'fulfilled') setDashboard(d.value)
        if (m.status === 'fulfilled') setMetrics(m.value)
      },
    )
    return () => {
      alive = false
    }
  }, [])

  const kpis = (dashboard?.kpis ?? []).filter((kpi) =>
    (HEADLINE_KPIS as readonly string[]).includes(kpi.key),
  )
  const loaded = kpis.some((kpi) => kpi.value > 0)
  const caps = health?.capabilities

  return (
    <div className="min-h-screen bg-bg text-ink">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-hairline focus:bg-bg focus:px-4 focus:py-2 focus:text-sm focus:text-ink"
      >
        Skip to content
      </a>

      {/* Utility strip: the context a reader needs before the wordmark means
          anything to them. */}
      <div className="border-b border-hairline bg-surface">
        <div className="mx-auto flex h-9 w-full max-w-content items-center justify-between gap-4 px-6">
          <p className="micro-label truncate">
            Smart India Hackathon 2026 · Problem statement SIH26099
          </p>
          <p className="micro-label hidden shrink-0 sm:block">
            Ministry of Petroleum &amp; Natural Gas
          </p>
        </div>
      </div>

      <header className="sticky top-0 z-40 border-b border-hairline bg-bg">
        <div className="mx-auto flex w-full max-w-content items-center gap-6 px-6 py-4">
          <Link to="/" className="min-w-0 shrink-0">
            <span className="block font-sans text-base font-medium uppercase tracking-wordmark">
              SAMAN
            </span>
            <span className="hidden text-xs text-muted md:block">
              Standardised Asset &amp; Material Analysis Network
            </span>
          </Link>

          <nav aria-label="Sections" className="ml-auto hidden items-center gap-6 lg:flex">
            {NAV.map((entry) => (
              <a
                key={entry.href}
                href={entry.href}
                className="text-sm text-muted transition-colors duration-150 hover:text-ink"
              >
                {entry.label}
              </a>
            ))}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-3 lg:ml-0">
            <ThemeToggle />
            <Link to="/login">
              <Button variant="primary">Sign in</Button>
            </Link>
          </div>
        </div>
      </header>

      <main id="main-content" tabIndex={-1} className="focus-visible:outline-none">
        {/* ---- hero ---- */}
        <div className="border-b border-hairline">
          <div className="mx-auto grid w-full max-w-content gap-12 px-6 py-16 lg:grid-cols-[1fr_20rem] lg:py-24">
            <motion.div
              variants={listVariants(reduce)}
              initial="initial"
              animate="animate"
              className="max-w-2xl space-y-6"
            >
              <Item>
                <p className="micro-label">A national material master for the CPSEs</p>
              </Item>
              <Item>
                <h1 className="text-2xl font-medium tracking-tight">
                  One Nation, One Material Code
                </h1>
              </Item>
              <Item>
                <p className="max-w-xl text-base text-muted">
                  Four public sector undertakings describe the same bearing four ways, in
                  four ERPs, under four codes. SAMAN reads those catalogues, works out
                  which rows are the same material, and issues one national code for each,
                  keeping the evidence for every decision it made and every one it refused
                  to make.
                </p>
              </Item>
              <Item className="flex flex-wrap items-center gap-3 pt-2">
                <Link to="/login">
                  <Button variant="primary">Sign in to the demo</Button>
                </Link>
                <a href="#how">
                  <Button variant="secondary">How it works</Button>
                </a>
              </Item>
              <Item>
                <p className="text-xs text-muted">
                  Every seeded account uses the password <span className="font-mono">demo</span>.
                  Nothing here calls the internet.
                </p>
              </Item>
            </motion.div>

            {/* The live status box. A government portal puts its service status
                on the front page; this one can, because the answer is computed
                rather than written down. */}
            <motion.aside
              variants={listItemVariants(reduce)}
              initial="initial"
              animate="animate"
              aria-label="System status"
              className="h-fit border border-hairline"
            >
              <p className="micro-label border-b border-hairline px-4 py-3">
                This instance, right now
              </p>
              <dl className="divide-y divide-hairline">
                <StatusRow
                  term="Network"
                  value={health ? 'Fully offline' : 'API unreachable'}
                  ok={Boolean(health)}
                />
                <StatusRow term="Linkage" value={caps?.linkage.mode ?? '—'} />
                <StatusRow term="Embeddings" value={caps?.embedding.mode ?? '—'} />
                <StatusRow term="Local model" value={caps?.llm.mode ?? '—'} />
                <StatusRow term="Version" value={health?.version ?? '—'} />
              </dl>
              <p className="border-t border-hairline px-4 py-3 text-xs text-muted">
                {health
                  ? 'Optional components degrade to bundled ones. Whichever is active is what this page reports.'
                  : 'The backend is not answering on :8000. The page below still describes the system; the numbers are what is missing.'}
              </p>
            </motion.aside>
          </div>
        </div>

        {/* ---- at a glance ---- */}
        <Reveal className="border-b border-hairline bg-surface">
          <div className="mx-auto w-full max-w-content px-6 py-12">
            <Item className="pb-6">
              <p className="micro-label">The estate loaded in this instance</p>
            </Item>
            {loaded ? (
              <>
                <div className="grid grid-cols-2 gap-px border border-hairline bg-hairline lg:grid-cols-4">
                  {kpis.map((kpi) => (
                    <Item key={kpi.key} className="space-y-2 bg-bg p-5">
                      <p className="micro-label">{kpi.label}</p>
                      <p className="font-mono text-xl">{formatCount(kpi.value)}</p>
                    </Item>
                  ))}
                </div>
                <Item>
                  <p className="pt-4 text-xs text-muted">
                    Read from the database on every load, not written into the page.
                    Sign in to see the same figures broken down by CPSE and by class.
                  </p>
                </Item>
              </>
            ) : (
              <Item className="border border-hairline bg-bg px-5 py-6">
                <p className="text-sm text-muted">
                  No catalogue is loaded in this instance yet. The sign-in screen offers
                  to build the demo estate, four CPSEs and about 12,000 rows, in roughly a
                  minute; <span className="font-mono text-xs">make demo</span> does the
                  same thing from the repository.
                </p>
              </Item>
            )}
          </div>
        </Reveal>

        {/* ---- the problem ---- */}
        <Reveal id="problem" className="border-b border-hairline">
          <div className="mx-auto w-full max-w-content space-y-8 px-6 py-16">
            <SectionHeading label="The problem" title="A code per organisation is a code too many" />
            <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-3">
              {PROBLEM.map((entry, index) => (
                <Item key={entry.heading} className="space-y-3 bg-bg p-6">
                  <p className="font-mono text-xs text-muted">{String(index + 1).padStart(2, '0')}</p>
                  <h3 className="text-base font-medium">{entry.heading}</h3>
                  <p className="text-sm text-muted">{entry.body}</p>
                </Item>
              ))}
            </div>
          </div>
        </Reveal>

        {/* ---- what it does ---- */}
        <Reveal id="what" className="border-b border-hairline">
          <div className="mx-auto w-full max-w-content space-y-8 px-6 py-16">
            <SectionHeading label="What it does" title="Four things, end to end" />
            <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-2">
              {CAPABILITIES.map((entry) => (
                <Item key={entry.route} className="space-y-3 bg-bg p-6">
                  <p className="font-mono text-xs text-muted">{entry.route}</p>
                  <h3 className="text-base font-medium">{entry.heading}</h3>
                  <p className="text-sm text-muted">{entry.body}</p>
                </Item>
              ))}
            </div>
          </div>
        </Reveal>

        {/* ---- how it works ---- */}
        <Reveal id="how" className="border-b border-hairline bg-surface">
          <div className="mx-auto w-full max-w-content space-y-8 px-6 py-16">
            <SectionHeading
              label="How it works"
              title="Cheap certainty first, judgement last"
            />
            <ol className="divide-y divide-hairline border border-hairline bg-bg">
              {PIPELINE.map((stage) => (
                <Item key={stage.tier}>
                  <li className="grid gap-4 p-6 md:grid-cols-[7rem_1fr]">
                    <p className="micro-label pt-1">{stage.tier}</p>
                    <div className="space-y-2">
                      <h3 className="text-base font-medium">{stage.heading}</h3>
                      <p className="max-w-prose text-sm text-muted">{stage.body}</p>
                    </div>
                  </li>
                </Item>
              ))}
            </ol>
            {metrics && (
              <Item>
                <p className="text-sm text-muted">
                  On the estate loaded here,{' '}
                  <span className="font-mono text-ink">
                    {formatPercent(metrics.automation.automation_rate, 1)}
                  </span>{' '}
                  of candidate pairs were settled without a person, leaving{' '}
                  <span className="font-mono text-ink">
                    {formatCount(metrics.automation.needs_review)}
                  </span>{' '}
                  for the review queue.
                </p>
              </Item>
            )}
          </div>
        </Reveal>

        {/* ---- evidence ---- */}
        <Reveal id="evidence" className="border-b border-hairline">
          <div className="mx-auto w-full max-w-content space-y-8 px-6 py-16">
            <SectionHeading label="Evidence" title="Measured on data it was not tuned on" />
            <Item>
              <p className="max-w-prose text-sm text-muted">
                Thresholds are tuned on 60% of the catalogue and every figure below is
                scored on the 40% held back. The report is served at{' '}
                <span className="font-mono text-xs">/api/metrics</span> without a session,
                so a reader can check it rather than take it.
              </p>
            </Item>

            {metrics ? (
              <>
                <Item className="overflow-x-auto border border-hairline">
                  <table className="w-full min-w-[36rem] border-collapse text-sm">
                    <caption className="sr-only">
                      Held-out evaluation results against their targets
                    </caption>
                    <thead>
                      <tr className="border-b border-hairline">
                        <th scope="col" className="micro-label px-4 py-3 text-left">
                          Measure
                        </th>
                        <th scope="col" className="micro-label px-4 py-3 text-right">
                          Result
                        </th>
                        <th scope="col" className="micro-label px-4 py-3 text-right">
                          Target
                        </th>
                        <th scope="col" className="micro-label px-4 py-3 text-right">
                          Gate
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hairline">
                      {Object.entries(metrics.gate).map(([key, row]) => (
                        <tr key={key}>
                          <td className="px-4 py-3">{key.replace(/_/g, ' ')}</td>
                          <td className="px-4 py-3 text-right font-mono">
                            {formatPercent(row.value, 1)}
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-muted">
                            {formatPercent(row.target, 0)}
                          </td>
                          <td
                            className={cn(
                              'px-4 py-3 text-right font-mono',
                              row.pass ? 'text-ok' : 'text-danger',
                            )}
                          >
                            {row.pass ? 'pass' : 'fail'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Item>

                <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-3">
                  <Item className="space-y-2 bg-bg p-5">
                    <p className="micro-label">Against a naive baseline</p>
                    <p className="font-mono text-xl">
                      {formatPercent(metrics.baseline_exact_text.pairwise.recall, 1)}
                    </p>
                    <p className="text-xs text-muted">
                      What matching byte-identical descriptions alone recovers of the same
                      duplicate pairs. SAMAN recovers{' '}
                      {formatPercent(metrics.duplicate.pairwise.recall, 1)}.
                    </p>
                  </Item>
                  <Item className="space-y-2 bg-bg p-5">
                    <p className="micro-label">Traps refused</p>
                    <p className="font-mono text-xl">
                      {formatCount(metrics.veto.traps_refused)} of{' '}
                      {formatCount(metrics.veto.traps_total)}
                    </p>
                    <p className="text-xs text-muted">
                      Pairs built to look alike and differ on something that matters, such
                      as a bore or a pressure class.
                    </p>
                  </Item>
                  <Item className="space-y-2 bg-bg p-5">
                    <p className="micro-label">Substitution, and its direction</p>
                    <p className="font-mono text-xl">
                      {metrics.equivalence.direction_accuracy !== undefined
                        ? formatPercent(metrics.equivalence.direction_accuracy, 1)
                        : '—'}
                    </p>
                    <p className="text-xs text-muted">
                      A 500 kg bearing can stand in for a 200 kg one and not the other way
                      round. Getting that direction right is scored separately.
                    </p>
                  </Item>
                </div>

                {metrics.worst_class && (
                  <Item>
                    <p className="text-xs text-muted">
                      Weakest class in this run:{' '}
                      <span className="font-mono">{metrics.worst_class}</span>. It is named
                      because an average that hides its worst case is not a measurement.
                    </p>
                  </Item>
                )}
              </>
            ) : (
              <Item className="border border-hairline px-5 py-6">
                <p className="text-sm text-muted">
                  The evaluation report needs a loaded catalogue and a completed pipeline
                  run. Once the demo estate is built, every figure appears here.
                </p>
              </Item>
            )}
          </div>
        </Reveal>

        {/* ---- governance ---- */}
        <Reveal id="governance" className="border-b border-hairline bg-surface">
          <div className="mx-auto w-full max-w-content space-y-8 px-6 py-16">
            <SectionHeading label="Governance" title="Auditable, scoped and self-contained" />
            <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-3">
              {GOVERNANCE.map((entry) => (
                <Item key={entry.heading} className="space-y-3 bg-bg p-6">
                  <h3 className="text-base font-medium">{entry.heading}</h3>
                  <p className="text-sm text-muted">{entry.body}</p>
                </Item>
              ))}
            </div>
          </div>
        </Reveal>

        {/* ---- getting started ---- */}
        <Reveal className="border-b border-hairline">
          <div className="mx-auto w-full max-w-content space-y-8 px-6 py-16">
            <SectionHeading label="For a CPSE" title="Three steps from a spreadsheet to a code" />
            <ol className="grid gap-px border border-hairline bg-hairline md:grid-cols-3">
              {STEPS.map((step, index) => (
                <Item key={step.heading} className="bg-bg p-6">
                  <li className="space-y-3">
                    <p className="font-mono text-xs text-muted">
                      Step {index + 1}
                    </p>
                    <h3 className="text-base font-medium">{step.heading}</h3>
                    <p className="text-sm text-muted">{step.body}</p>
                  </li>
                </Item>
              ))}
            </ol>
            <Item className="flex flex-wrap items-center gap-4 border border-hairline px-6 py-5">
              <p className="text-sm">
                The whole demo runs on this machine, with no account to create and nothing
                to configure.
              </p>
              <Link to="/login" className="ml-auto">
                <Button variant="primary">Sign in to the demo</Button>
              </Link>
            </Item>
          </div>
        </Reveal>
      </main>

      <footer className="bg-bg">
        <div className="mx-auto grid w-full max-w-content gap-8 px-6 py-12 md:grid-cols-4">
          <div className="space-y-3">
            <p className="font-sans text-sm font-medium uppercase tracking-wordmark">SAMAN</p>
            <p className="text-xs text-muted">
              Standardised Asset &amp; Material Analysis Network. One Nation, One Material
              Code.
            </p>
          </div>
          <FooterColumn
            heading="The system"
            rows={[
              'Tiered matching with a hard-constraint veto',
              'CNMC with a Damm check digit',
              'Two-way ERP migration with rollback',
            ]}
          />
          <FooterColumn
            heading="Governance"
            rows={[
              'Hash-chained audit of every change',
              'Row-level price visibility by role',
              'No runtime network call, anywhere',
            ]}
          />
          <FooterColumn
            heading="Open interfaces"
            rows={['/api/health', '/api/metrics', '/api/docs']}
            mono
          />
        </div>
        <div className="border-t border-hairline">
          <div className="mx-auto flex w-full max-w-content flex-wrap items-center justify-between gap-3 px-6 py-4">
            <p className="text-xs text-muted">
              A Smart India Hackathon 2026 prototype built for problem statement SIH26099.
              Not an official service of the Government of India.
            </p>
            <p className="text-xs text-muted">
              Built with permissively licensed components only.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}

function StatusRow({ term, value, ok }: { term: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <dt className="text-xs text-muted">{term}</dt>
      <dd
        className={cn(
          'font-mono text-xs',
          ok === undefined ? 'text-ink' : ok ? 'text-ok' : 'text-danger',
        )}
      >
        {value}
      </dd>
    </div>
  )
}

function FooterColumn({
  heading,
  rows,
  mono,
}: {
  heading: string
  rows: string[]
  mono?: boolean
}) {
  return (
    <div className="space-y-3">
      <p className="micro-label">{heading}</p>
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row} className={cn('text-xs text-muted', mono && 'font-mono')}>
            {row}
          </li>
        ))}
      </ul>
    </div>
  )
}
