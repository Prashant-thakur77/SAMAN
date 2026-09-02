import { motion, useReducedMotion } from 'framer-motion'
import { type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import { cn } from '../lib/cn'
import { listItemVariants, listVariants } from '../lib/motion'

/**
 * / — the public front page.
 *
 * This page explains how the system decides. It deliberately carries no
 * metrics: a visitor who has not yet understood what the machine does cannot
 * evaluate a precision figure, and a wall of them reads as a defence rather
 * than an explanation. The measured results live behind sign-in, on the
 * dashboards and at /api/metrics, where a reader who wants them can check
 * them rather than be shown them.
 *
 * It fetches nothing for the same reason. Nothing here can be stale, nothing
 * can fail to load, and the page renders identically with the backend stopped.
 */

const NAV = [
  { href: '#problem', label: 'The problem' },
  { href: '#fixes', label: 'What it fixes' },
  { href: '#how', label: 'How it works' },
  { href: '#code', label: 'The code' },
] as const

/**
 * One real cluster, exactly as it stands in the demo database: three raw rows,
 * the record they were fused into, and the code that was issued for it. Nothing
 * here is written for the page (spec §10).
 */
const SAME_BEARING = [
  {
    cpse: 'CPCL',
    text: 'BRG,BALL,85MM BORE,150MM OD,28MM W,ZZ,2720 KG,150 C,FAG,6217-2ZR/H150',
  },
  {
    cpse: 'GAIL',
    text: 'FAG - BEARING - BALL - 85MM BORE - 150MM OD - 28MM W - ZZ - 2720 KG - 150 C - 6217-2ZR/H150 - GTIN 8905095590714',
  },
  {
    cpse: 'IOCL',
    text: 'BEARING BALL 85MM BORE 150MM OD 28MM W ZZ 2720 KG 150 C FAG 6217-2ZR/H150 EAN 8905095590714',
  },
] as const

const GOLDEN = 'BEARING, BALL DEEP GROOVE, 85MM BORE, 150MM OD, 28MM W, ZZ, FAG 6217-2ZR'
const GOLDEN_CODE = 'BRNG-010-000003-7'

/**
 * What is broken in a material master today, and the mechanism in this build
 * that closes it. Paired deliberately: a problem without a named mechanism is a
 * complaint, and a mechanism without a named problem is a feature list.
 */
const FIXES = [
  {
    problem: 'One material, many codes',
    today: 'Each organisation raises its own code for the same part, so nothing can be counted, compared or tendered across them.',
    fix: 'A tiered matcher decides which rows are the same material and issues one national code, with every legacy code mapped to it.',
  },
  {
    problem: 'Look-alikes get merged',
    today: 'De-duplication by text similarity eventually merges two parts that read alike and differ where it matters, and a crew is issued something that does not fit.',
    fix: 'Identity-critical attributes are compared in real units, and a disagreement refuses the match outright. No score can overrule it.',
  },
  {
    problem: 'Substitutes are invisible',
    today: 'A higher-rated part that would have done the job sits in another store, unrecorded as an alternative, because nothing models substitution.',
    fix: 'Equivalence is a directed relation of its own. Substitutes keep separate codes and carry a link that records which way round it is safe.',
  },
  {
    problem: 'Descriptions are free text',
    today: 'Abbreviations, orderings and spellings differ between organisations and within them, so search fails and specification takes days.',
    fix: 'A per-class template renders one canonical description from normalised attributes, deterministically, with the source of every fused field recorded.',
  },
  {
    problem: 'Units and pack sizes hide the price',
    today: 'A box of a hundred is compared against a single piece, and the resulting price analysis is confidently wrong.',
    fix: 'Unit of measure is canonicalised and pack quantity extracted separately, so every price is compared per base unit.',
  },
  {
    problem: 'Stock nobody can see',
    today: 'One organisation raises a purchase order for an item another holds in surplus, because no query spans both catalogues.',
    fix: 'Once rows share a code, the position consolidates: stock per organisation and plant, transfer suggestions, and a dead-stock report.',
  },
  {
    problem: 'The same item, bought separately',
    today: 'Several organisations buy one material from different vendors at different prices, with no combined volume to negotiate on.',
    fix: 'Twelve-month demand windows surface joint-tender candidates and vendor overlap, with the capture assumption stated and adjustable.',
  },
  {
    problem: 'New duplicates arrive daily',
    today: 'A cleaned master starts drifting the moment it is cleaned, because nothing checks a request before a code is raised.',
    fix: 'The same matcher and veto layer run at the point of creation. Creating anyway needs a reason, and the reason is audited.',
  },
  {
    problem: 'Cleaning the master risks the ERP',
    today: 'Consolidation touches live masters with open purchase orders and valuations attached, which is why it is so often deferred.',
    fix: 'Plan, dry run, impact, apply, verify, roll back. Records with open transactions are held automatically and nothing is ever deleted.',
  },
  {
    problem: 'Nobody can audit the machine',
    today: 'An algorithm that merges records without saying why cannot be signed off by anyone accountable for the result.',
    fix: 'Every decision keeps its evidence and every change is one event in a hash chain that detects reordering as readily as editing.',
  },
  {
    problem: 'Catalogues are commercially sensitive',
    today: 'Finding the overlap between two organisations normally means one of them hands over its catalogue first.',
    fix: 'Restricted mode compares keyed encodings instead. Neither side learns a description it did not already hold.',
  },
  {
    problem: 'Procurement data cannot leave the building',
    today: 'A cloud service is not an option for national procurement data, and an offline one usually means a weaker one.',
    fix: 'Everything runs on one machine with no network call at runtime. Optional components fall back rather than fail, and the active mode is stated.',
  },
] as const

const STAGES = [
  {
    index: '01',
    heading: 'Start with what is certain',
    body: 'A manufacturer part number. A barcode. Two descriptions that normalise to the same string. Where one of these exists the answer is already known, and nothing is scored, because a fact does not need a probability attached to it.',
  },
  {
    index: '02',
    heading: 'Weigh the agreements',
    body: 'For everything else, compare field by field and weigh each agreement by how surprising it is. Two rows sharing a size agree about very little. Two rows sharing a size, a seal type and a manufacturer agree about a great deal.',
  },
  {
    index: '03',
    heading: 'Read the meaning, not the spelling',
    body: 'Descriptions become vectors, so SS316 lands beside STAINLESS STEEL 316 although the two share no substring. This is where the abbreviations, the transliterations and the house styles stop mattering.',
  },
  {
    index: '04',
    heading: 'Let a refusal outrank a score',
    body: 'Then every identity-critical attribute is compared with its units understood, and any disagreement ends the matter. This is the step that keeps the rest honest.',
  },
  {
    index: '05',
    heading: 'Hand the rest to a person',
    body: 'What survives all of that is a small band of genuinely ambiguous pairs. A reviewer sees both rows, every attribute compared, and what was refused, then decides in a single keystroke.',
  },
] as const

/** A code this system has actually issued, taken apart. */
const SEGMENTS = [
  {
    part: 'BRNG',
    label: 'Family',
    body: 'Four letters for the class of thing. Bearings, valves, gaskets, cable.',
  },
  { part: '010', label: 'Segment', body: 'The group within that family.' },
  { part: '000003', label: 'Serial', body: 'Issued once and never reissued, even after a merge.' },
  {
    part: '7',
    label: 'Check',
    body: 'A Damm digit. Mistype a figure or swap two, and the code fails where it is keyed.',
  },
] as const

const PROMISES = [
  {
    heading: 'Nothing is deleted',
    body: 'A superseded material is blocked, not removed. The row stays, its history stays, and the migration that consolidated it can be rolled back to the byte.',
  },
  {
    heading: 'Every change is on the record',
    body: 'Each one is an event in a hash chain, and each hash covers its own position, so reordering the ledger breaks it as visibly as editing it.',
  },
  {
    heading: 'It runs on one machine',
    body: 'No network call at runtime, anywhere. Optional components fall back to bundled ones instead of failing, and the active mode is always stated.',
  },
] as const

/** Sections rise into place once, the first time they are scrolled to. */
function Reveal({
  children,
  className,
  id,
}: {
  children: ReactNode
  className?: string
  id?: string
}) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.section
      id={id}
      variants={listVariants(reduce)}
      initial="initial"
      whileInView="animate"
      viewport={{ once: true, margin: '-80px' }}
      className={className}
    >
      {children}
    </motion.section>
  )
}

function Item({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.div variants={listItemVariants(reduce)} className={className}>
      {children}
    </motion.div>
  )
}

/** The same reveal, as a list item.
 *
 * A `div` between `<ul>` and `<li>` is invalid markup, and a screen reader
 * stops announcing the list as a list, which for the pipeline is the one thing
 * about it worth announcing: five steps, in order.
 */
function ItemLi({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.li variants={listItemVariants(reduce)} className={className}>
      {children}
    </motion.li>
  )
}

/** One container width and one gutter, used by every band on the page. */
function Band({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('mx-auto w-full max-w-content px-6 md:px-10', className)}>
      {children}
    </div>
  )
}

export default function Landing() {
  const reduce = useReducedMotion() ?? false

  return (
    <div className="min-h-screen bg-bg text-ink">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-hairline focus:bg-bg focus:px-4 focus:py-2 focus:text-sm focus:text-ink"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b border-hairline bg-bg">
        <Band className="flex h-16 items-center gap-8">
          <Link to="/" className="shrink-0 font-medium uppercase tracking-wordmark">
            SAMAN
          </Link>
          <nav aria-label="Sections" className="hidden items-center gap-8 md:flex">
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
          <div className="ml-auto flex shrink-0 items-center gap-3">
            <ThemeToggle />
            <Link to="/login">
              <Button variant="primary">Sign in</Button>
            </Link>
          </div>
        </Band>
      </header>

      <main id="main-content" tabIndex={-1} className="focus-visible:outline-none">
        {/* ---- hero ---- */}
        <motion.div
          variants={listVariants(reduce)}
          initial="initial"
          animate="animate"
        >
          <Band className="py-20 md:py-28">
            <Item>
              <p className="micro-label">Standardised Asset &amp; Material Analysis Network</p>
            </Item>
            <Item>
              <h1 className="max-w-[20ch] pt-8 text-display font-medium">
                One Nation, One Material Code
              </h1>
            </Item>
            <div className="grid gap-10 pt-12 lg:grid-cols-[1fr_auto] lg:items-end lg:gap-16">
              <Item>
                <p className="max-w-[52ch] text-lead text-muted">
                  Public sector undertakings describe the same part in different words, in
                  different systems, under different codes. SAMAN works out which rows are
                  the same material and gives each one a single national code.
                </p>
              </Item>
              <Item className="flex flex-wrap items-center gap-4">
                <a href="#how">
                  <Button variant="primary">See how it decides</Button>
                </a>
                <Link to="/login">
                  <Button variant="secondary">Open the demo</Button>
                </Link>
              </Item>
            </div>
          </Band>
        </motion.div>

        {/* ---- the problem, shown rather than described ---- */}
        <Reveal id="problem" className="border-t border-hairline">
          <Band className="grid gap-12 py-20 md:py-28 lg:grid-cols-[minmax(0,24rem)_1fr] lg:gap-20">
            <div>
              <Item>
                <p className="micro-label">The problem</p>
              </Item>
              <Item>
                <h2 className="pt-6 text-headline font-medium">
                  Three catalogues. One bearing.
                </h2>
              </Item>
              <Item>
                <p className="max-w-[44ch] pt-8 text-lead text-muted">
                  Every one of these is the same 85 mm deep-groove ball bearing. Three
                  codes, three stock balances, three purchase orders, and no query that
                  spans them. The surplus in one warehouse is invisible to the buyer in
                  the next.
                </p>
              </Item>
              <Item>
                <p className="max-w-[44ch] pt-6 text-base text-muted">
                  Taken from the demo database as it stands, not written for this page.
                </p>
              </Item>
            </div>

            <div>
              <ul className="border-b border-hairline">
                {SAME_BEARING.map((row) => (
                  <ItemLi
                    key={row.cpse}
                    className="grid grid-cols-[4rem_1fr] items-baseline gap-4 border-t border-hairline py-5 md:gap-8"
                  >
                    <span className="micro-label">{row.cpse}</span>
                    <span className="break-words font-mono text-sm md:text-base">
                      {row.text}
                    </span>
                  </ItemLi>
                ))}
              </ul>

              <Item className="pt-10">
                <p className="micro-label">Resolved to one record</p>
              </Item>
              <Item className="mt-4 border border-hairline p-6">
                <p className="break-words font-mono text-sm md:text-base">{GOLDEN}</p>
                <p className="pt-5 font-mono text-lg md:text-xl">{GOLDEN_CODE}</p>
              </Item>
            </div>
          </Band>
        </Reveal>

        {/* ---- problem by problem ---- */}
        <Reveal id="fixes" className="border-t border-hairline">
          <Band className="py-20 md:py-28">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,32rem)_1fr] lg:gap-20">
              <div>
                <Item>
                  <p className="micro-label">What it fixes</p>
                </Item>
                <Item>
                  <h2 id="fixes-title" className="pt-6 text-headline font-medium">
                    Twelve problems, and what closes each.
                  </h2>
                </Item>
              </div>
              <Item className="lg:self-end">
                <p className="max-w-[52ch] text-lead text-muted">
                  A material master fails in more than one way, and the failures have
                  different causes. Each one below is paired with the mechanism in this
                  build that answers it, rather than with a feature.
                </p>
              </Item>
            </div>

            <ul aria-labelledby="fixes-title" className="pt-16">
              <li
                aria-hidden
                className="hidden gap-12 border-b border-hairline pb-3 md:grid md:grid-cols-[3rem_minmax(0,1fr)_minmax(0,1fr)]"
              >
                <span />
                <span className="micro-label">The problem today</span>
                <span className="micro-label">What SAMAN does</span>
              </li>
              {FIXES.map((entry, index) => (
                <ItemLi
                  key={entry.problem}
                  className="grid gap-3 border-b border-hairline py-8 md:grid-cols-[3rem_minmax(0,1fr)_minmax(0,1fr)] md:gap-12"
                >
                  <p className="font-mono text-sm text-muted">
                    {String(index + 1).padStart(2, '0')}
                  </p>
                  <div className="space-y-2">
                    <h3 className="text-base font-medium">{entry.problem}</h3>
                    <p className="max-w-[52ch] text-sm text-muted">{entry.today}</p>
                  </div>
                  <p className="max-w-[52ch] text-sm md:pt-0.5">{entry.fix}</p>
                </ItemLi>
              ))}
            </ul>
          </Band>
        </Reveal>

        {/* ---- how it works ---- */}
        <Reveal id="how" className="border-t border-hairline bg-surface">
          <Band className="py-20 md:py-28">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,32rem)_1fr] lg:gap-20">
              <div>
                <Item>
                  <p className="micro-label">How it works</p>
                </Item>
                <Item>
                  <h2 id="how-title" className="pt-6 text-headline font-medium">
                    Cheap certainty first. Judgement last.
                  </h2>
                </Item>
              </div>
              <Item className="lg:self-end">
                <p className="max-w-[52ch] text-lead text-muted">
                  Deciding whether two rows are the same material is five questions asked
                  in order. Each one is more expensive than the last, and each only ever
                  sees what the one before it could not settle.
                </p>
              </Item>
            </div>

            <ol aria-labelledby="how-title" className="pt-16">
              {STAGES.map((stage) => (
                <ItemLi
                  key={stage.index}
                  className="grid gap-3 border-t border-hairline py-8 md:grid-cols-[4rem_minmax(0,20rem)_1fr] md:gap-12 md:py-10"
                >
                  <p className="font-mono text-lg text-muted">{stage.index}</p>
                  <h3 className="text-xl font-medium">{stage.heading}</h3>
                  <p className="max-w-[60ch] text-base text-muted md:text-lead">
                    {stage.body}
                  </p>
                </ItemLi>
              ))}
            </ol>
          </Band>
        </Reveal>

        {/* ---- the veto, given the room it deserves ---- */}
        <Reveal className="border-t border-hairline">
          <Band className="grid gap-12 py-20 md:py-28 lg:grid-cols-[auto_1fr] lg:gap-20">
            <div>
              <Item>
                <p className="micro-label">Why it can be trusted</p>
              </Item>
              <Item>
                <p className="whitespace-nowrap pt-8 font-mono text-headline">25 mm is not 30 mm.</p>
              </Item>
            </div>
            <div className="lg:pt-14">
              <Item>
                <p className="max-w-[58ch] text-lead text-muted">
                  Two rows can read almost identically and still be different parts. Every
                  matching system that scores similarity alone will eventually merge them,
                  and in a materials catalogue that means a maintenance crew is issued
                  something that does not fit.
                </p>
              </Item>
              <Item>
                <p className="max-w-[58ch] pt-6 text-lead text-muted">
                  So the attributes that define identity are compared separately, in real
                  units, and a disagreement on any of them refuses the match outright. No
                  score is permitted to overrule it. That refusal is recorded with the
                  reason, which is why the system can say not only what it merged, but
                  what it declined to.
                </p>
              </Item>
            </div>
          </Band>
        </Reveal>

        {/* ---- the code itself ---- */}
        <Reveal id="code" className="border-t border-hairline bg-surface">
          <Band className="py-20 md:py-28">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,32rem)_1fr] lg:gap-20">
              <div>
                <Item>
                  <p className="micro-label">The code</p>
                </Item>
                <Item>
                  <h2 className="pt-6 text-headline font-medium">
                    One material, one number, everywhere.
                  </h2>
                </Item>
              </div>
              <Item className="lg:self-end">
                <p className="max-w-[52ch] text-lead text-muted">
                  Issuing it is the easy half. The rest is moving several ERPs onto it
                  without losing what came before, which is why the code is the middle of
                  the story rather than the end of it.
                </p>
              </Item>
            </div>

            <Item className="pt-16">
              <p className="font-mono text-headline">
                {SEGMENTS.map((segment, index) => (
                  <span key={segment.label}>
                    {index > 0 && <span className="text-muted">-</span>}
                    {segment.part}
                  </span>
                ))}
              </p>
            </Item>

            <dl className="grid gap-10 pt-14 sm:grid-cols-2 lg:grid-cols-4 lg:gap-8">
              {SEGMENTS.map((segment) => (
                <Item key={segment.label} className="space-y-3 border-t border-hairline pt-5">
                  <dt className="micro-label">
                    {segment.label} · <span className="font-mono">{segment.part}</span>
                  </dt>
                  <dd className="max-w-[32ch] text-base text-muted">{segment.body}</dd>
                </Item>
              ))}
            </dl>
          </Band>
        </Reveal>

        {/* ---- the promises ---- */}
        <Reveal className="border-t border-hairline">
          <Band className="py-20 md:py-28">
            <Item>
              <p className="micro-label">What it guarantees</p>
            </Item>
            <div className="grid gap-10 pt-12 md:grid-cols-3">
              {PROMISES.map((promise) => (
                <Item
                  key={promise.heading}
                  className="space-y-4 border-t border-hairline pt-6"
                >
                  <h3 className="text-xl font-medium">{promise.heading}</h3>
                  <p className="text-base text-muted">{promise.body}</p>
                </Item>
              ))}
            </div>
          </Band>
        </Reveal>

        {/* ---- close ---- */}
        <Reveal className="border-t border-hairline">
          <Band className="grid gap-10 py-20 md:py-28 lg:grid-cols-[1fr_auto] lg:items-end lg:gap-20">
            <div>
              <Item>
                <h2 className="max-w-[20ch] text-headline font-medium">
                  It is running on this machine.
                </h2>
              </Item>
              <Item>
                <p className="max-w-[52ch] pt-8 text-lead text-muted">
                  Sign in with any seeded account, password{' '}
                  <span className="font-mono">demo</span>, and follow this bearing from
                  three catalogues to a single code.
                </p>
              </Item>
            </div>
            <Item>
              <Link to="/login">
                <Button variant="primary">Open the demo</Button>
              </Link>
            </Item>
          </Band>
        </Reveal>
      </main>

      <footer className="border-t border-hairline">
        <Band className="flex flex-wrap items-center justify-between gap-4 py-8">
          <p className="text-xs text-muted">
            Smart India Hackathon 2026 · Problem statement SIH26099
          </p>
          <p className="text-xs text-muted">
            A prototype. Not an official service of the Government of India.
          </p>
        </Band>
      </footer>
    </div>
  )
}
