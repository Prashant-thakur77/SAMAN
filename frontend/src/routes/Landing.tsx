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
 * It explains how the system decides and carries no metrics: a visitor who has
 * not yet understood what the machine does cannot evaluate a precision figure.
 * The measured results live behind sign-in and at /api/metrics, where a reader
 * who wants them can check them rather than be shown them.
 *
 * It fetches nothing, so nothing here can be stale and the page renders
 * identically with the backend stopped.
 */

const NAV = [
  { href: '#problem', label: 'The problem' },
  { href: '#fixes', label: 'What it fixes' },
  { href: '#how', label: 'How it works' },
  { href: '#code', label: 'The code' },
] as const

/**
 * One real cluster, exactly as it stands in the demo database: three raw rows,
 * the record they were fused into, and the code issued for it. Nothing here is
 * written for the page (spec §10).
 */
const SAME_BEARING = [
  { cpse: 'CPCL', text: 'BRG,BALL,85MM BORE,150MM OD,28MM W,ZZ,2720 KG,150 C,FAG,6217-2ZR/H150' },
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

/** Each failure of a material master, paired with the mechanism that closes it. */
const FIXES = [
  ['One material, many codes', 'One national code, every legacy code mapped to it'],
  ['Look-alikes get merged', 'A mismatch on an identity attribute refuses the pair outright'],
  ['Substitutes stay invisible', 'Equivalence is directed, and keeps its own code'],
  ['Descriptions are free text', 'One canonical description per class, rendered deterministically'],
  ['Pack sizes hide the price', 'Unit and pack quantity split, so prices compare per base unit'],
  ['Stock nobody can see', 'Consolidated position, transfer suggestions, dead stock'],
  ['The same item bought twice', 'Joint-tender candidates from twelve-month demand'],
  ['New duplicates arrive daily', 'The same check runs before a code is raised'],
  ['Cleaning risks the live ERP', 'Dry run, apply, roll back; open orders held'],
  ['Nobody can audit the machine', 'Evidence per decision, in a hash chain'],
  ['Catalogues are sensitive', 'Overlap measured from encodings, not descriptions'],
  ['Data cannot leave the building', 'No network call at runtime, anywhere'],
] as const

const STAGES = [
  ['Exact anchors', 'A part number or a barcode settles it. No score is needed for a fact.'],
  ['Weighted agreement', 'Each field agreement counted by how surprising it is.'],
  ['Meaning, not spelling', 'SS316 lands beside STAINLESS STEEL 316.'],
  ['A refusal outranks a score', 'Identity attributes compared in real units. Any mismatch ends it.'],
  ['A person, with the evidence', 'What is left is small, and decided in one keystroke.'],
] as const

/** A code this system has issued, taken apart. Shade carries the structure. */
const SEGMENTS = [
  { part: 'BRNG', label: 'Family', tone: 'text-earth-deep', body: 'The class of thing.' },
  { part: '010', label: 'Segment', tone: 'text-earth', body: 'The group within it.' },
  { part: '000003', label: 'Serial', tone: 'text-ink', body: 'Issued once, never reissued.' },
  {
    part: '7',
    label: 'Check',
    tone: 'text-earth-deep',
    body: 'A Damm digit. Swap two figures and it fails.',
  },
] as const

const PROMISES = [
  ['Nothing is deleted', 'Superseded rows are blocked. History stays, and the migration reverses.'],
  ['Every change is recorded', 'One hash chain, which catches reordering as readily as editing.'],
  ['It runs on one machine', 'No network at runtime. Optional parts fall back rather than fail.'],
] as const

/* ------------------------------------------------------------------ *
 * Drawings. Line art rather than photographs: there is no network at
 * runtime and nothing to fetch, so every mark here is generated.
 * ------------------------------------------------------------------ */

function Drawing({ viewBox, children }: { viewBox: string; children: ReactNode }) {
  return (
    <svg
      aria-hidden
      viewBox={viewBox}
      preserveAspectRatio="xMidYMax meet"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-full w-full"
    >
      {children}
    </svg>
  )
}

/** A civic colonnade. Depicts no particular building. */
function Colonnade() {
  const arch = (x: number, key: string) => (
    <g key={key}>
      <path d={`M${x} 196 L${x} 150 A18 18 0 0 1 ${x + 36} 150 L${x + 36} 196`} />
      <line x1={x - 3} y1="150" x2={x + 39} y2="150" />
    </g>
  )
  const arcade = (start: number, count: number, prefix: string) =>
    Array.from({ length: count }, (_, i) => arch(start + i * 46, `${prefix}-${i}`))

  const chhatri = (x: number, key: string) => (
    <g key={key}>
      <path d={`M${x - 26} 138 A26 26 0 0 1 ${x + 26} 138 Z`} />
      <line x1={x} y1="112" x2={x} y2="104" />
      <line x1={x - 30} y1="138" x2={x + 30} y2="138" />
      <line x1={x - 22} y1="138" x2={x - 22} y2="196" />
      <line x1={x + 22} y1="138" x2={x + 22} y2="196" />
    </g>
  )

  return (
    <Drawing viewBox="0 0 1200 210">
      {arcade(60, 6, 'l')}
      {chhatri(392, 'c-l')}
      <g>
        <path d="M470 196 L470 128 L730 128 L730 196" />
        <line x1="452" y1="196" x2="748" y2="196" />
        <line x1="462" y1="186" x2="738" y2="186" />
        {[500, 540, 580, 620, 660, 700].map((x) => (
          <line key={x} x1={x} y1="186" x2={x} y2="132" />
        ))}
        <path d="M540 128 L540 104 L660 104 L660 128" />
        <path d="M534 104 A66 60 0 0 1 666 104" />
        <line x1="600" y1="44" x2="600" y2="28" />
        <circle cx="600" cy="24" r="4" />
      </g>
      {chhatri(808, 'c-r')}
      {arcade(866, 6, 'r')}
      <line x1="0" y1="196" x2="1200" y2="196" />
    </Drawing>
  )
}

/** The catalogue itself: a bearing, a gate valve, a flange, a bolt, a pipe. */
function MaterialFrieze() {
  return (
    <Drawing viewBox="0 0 1200 160">
      {/* deep-groove ball bearing */}
      <g>
        <circle cx="120" cy="80" r="56" />
        <circle cx="120" cy="80" r="42" />
        <circle cx="120" cy="80" r="26" />
        <circle cx="120" cy="80" r="14" />
        {Array.from({ length: 10 }, (_, i) => {
          const a = (i / 10) * Math.PI * 2
          return (
            <circle key={i} cx={120 + Math.cos(a) * 34} cy={80 + Math.sin(a) * 34} r="6" />
          )
        })}
      </g>

      {/* gate valve, elevation */}
      <g>
        <path d="M300 108 L300 60 L360 60 L360 108 Z" />
        <path d="M288 108 L372 108 L372 122 L288 122 Z" />
        <line x1="330" y1="60" x2="330" y2="30" />
        <line x1="308" y1="30" x2="352" y2="30" />
        <path d="M288 122 L288 132 L372 132 L372 122" />
        <line x1="300" y1="84" x2="360" y2="84" />
      </g>

      {/* flange, face on */}
      <g>
        <circle cx="520" cy="80" r="54" />
        <circle cx="520" cy="80" r="22" />
        {Array.from({ length: 8 }, (_, i) => {
          const a = (i / 8) * Math.PI * 2 + Math.PI / 8
          return <circle key={i} cx={520 + Math.cos(a) * 40} cy={80 + Math.sin(a) * 40} r="6" />
        })}
      </g>

      {/* hex bolt */}
      <g>
        <path d="M690 56 L712 44 L734 56 L734 80 L712 92 L690 80 Z" />
        <line x1="700" y1="92" x2="700" y2="130" />
        <line x1="724" y1="92" x2="724" y2="130" />
        {Array.from({ length: 7 }, (_, i) => (
          <line key={i} x1="700" y1={100 + i * 5} x2="724" y2={100 + i * 5} />
        ))}
      </g>

      {/* seamless pipe, sectioned */}
      <g>
        <line x1="880" y1="46" x2="1130" y2="46" />
        <line x1="880" y1="114" x2="1130" y2="114" />
        <ellipse cx="880" cy="80" rx="18" ry="34" />
        <ellipse cx="880" cy="80" rx="10" ry="22" />
        <path d="M1130 46 A18 34 0 0 1 1130 114" />
      </g>
    </Drawing>
  )
}

/** Warehouse racking: where all of this actually sits. */
function Racking() {
  const bay = (x: number, key: string) => (
    <g key={key}>
      <line x1={x} y1="20" x2={x} y2="150" />
      <line x1={x + 150} y1="20" x2={x + 150} y2="150" />
      {[52, 88, 124].map((y) => (
        <line key={y} x1={x} y1={y} x2={x + 150} y2={y} />
      ))}
      <rect x={x + 12} y="30" width="46" height="22" />
      <rect x={x + 70} y="34" width="34" height="18" />
      <rect x={x + 16} y="66" width="38" height="22" />
      <rect x={x + 66} y="62" width="62" height="26" />
      <rect x={x + 20} y="102" width="52" height="22" />
      <rect x={x + 84} y="106" width="30" height="18" />
    </g>
  )
  return (
    <Drawing viewBox="0 0 1200 160">
      {Array.from({ length: 7 }, (_, i) => bay(20 + i * 170, `bay-${i}`))}
      <line x1="0" y1="150" x2="1200" y2="150" />
    </Drawing>
  )
}

/** A drawing laid behind the page, never in front of the reading. Position
 *  and tone come from the caller: two position utilities on one element
 *  resolve by stylesheet order, not by intent. */
function Backdrop({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div aria-hidden className={cn('pointer-events-none', className)}>
      {children}
    </div>
  )
}

/** A filled skyline, the way the SIH site carries one behind its themes:
 *  silhouette rather than line, so it reads as distance. */
function Skyline() {
  // Deterministic heights so the silhouette is the same on every load.
  const blocks = [
    [0, 70, 60], [72, 44, 100], [118, 90, 80], [210, 50, 130], [262, 120, 70],
    [384, 64, 110], [450, 40, 150], [492, 96, 90], [590, 70, 60], [662, 130, 120],
    [794, 56, 140], [852, 88, 84], [942, 62, 104], [1006, 110, 66], [1118, 82, 96],
  ] as const
  return (
    <svg
      aria-hidden
      viewBox="0 0 1200 160"
      preserveAspectRatio="xMidYMax slice"
      fill="currentColor"
      className="h-full w-full"
    >
      {blocks.map(([x, w, h], i) => (
        <rect key={i} x={x} y={160 - h} width={w} height={h} />
      ))}
      {/* two domes and a tower, so it is not only offices */}
      <path d="M300 96 A38 34 0 0 1 376 96 L376 160 L300 160 Z" />
      <path d="M700 84 A26 24 0 0 1 752 84 L752 160 L700 160 Z" />
      <rect x="1060" y="36" width="14" height="124" />
      <rect x="1064" y="22" width="6" height="14" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */

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

/** The same reveal as a list item: a `div` between `<ul>` and `<li>` is invalid
 *  markup, and it costs the list its semantics for a screen reader. */
function ItemLi({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion() ?? false
  return (
    <motion.li variants={listItemVariants(reduce)} className={className}>
      {children}
    </motion.li>
  )
}

/** One container width and one gutter, used by every band on the page. */
function Band({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('mx-auto w-full max-w-content px-6 md:px-10', className)}>{children}</div>
  )
}

function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="micro-label text-earth">{children}</p>
}

export default function Landing() {
  const reduce = useReducedMotion() ?? false

  return (
    <div className="landing relative min-h-screen bg-bg text-ink">
      {/* The application is monochrome by design. This page is not, and the
          palette swap rides on the `landing` class rather than on new utility
          classes, so nothing here can leak into a screen people work in. */}
      <div aria-hidden className="landing-field pointer-events-none fixed inset-0" />
      <div aria-hidden className="landing-grid pointer-events-none fixed inset-0" />

      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-hairline focus:bg-bg focus:px-4 focus:py-2 focus:text-sm focus:text-ink"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b border-hairline bg-bg/90 backdrop-blur-sm">
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

      <main id="main-content" tabIndex={-1} className="relative focus-visible:outline-none">
        {/* ---- hero ---- */}
        <motion.div variants={listVariants(reduce)} initial="initial" animate="animate">
          <Band className="py-20 md:py-24">
            <Item>
              <Eyebrow>Standardised Asset &amp; Material Analysis Network</Eyebrow>
            </Item>
            <Item>
              <h1 className="max-w-[20ch] pt-8 text-display font-medium">
                One Nation, One Material Code
              </h1>
            </Item>
            <Item>
              <div aria-hidden className="mt-8 h-1 w-24 bg-earth" />
            </Item>
            <div className="grid gap-8 pt-10 lg:grid-cols-[1fr_auto] lg:items-end lg:gap-16">
              <Item>
                <p className="max-w-[44ch] text-lead text-muted">
                  Every public sector undertaking codes the same part differently. SAMAN
                  works out which rows are one material, and gives it one code.
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

          {/* A horizon under the headline rather than a picture behind it. */}
          <Backdrop className="relative -mt-4 h-32 text-earth/25 md:h-44 lg:h-52">
            <Colonnade />
          </Backdrop>
        </motion.div>

        {/* ---- the problem, shown rather than described ---- */}
        <Reveal id="problem" className="border-t border-hairline">
          <Band className="grid gap-10 py-20 md:py-24 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-20">
            <div>
              <Item>
                <Eyebrow>The problem</Eyebrow>
              </Item>
              <Item>
                <h2 className="pt-6 text-headline font-medium">Three catalogues. One bearing.</h2>
              </Item>
              <Item>
                <p className="max-w-[36ch] pt-6 text-base text-muted">
                  One 85 mm bearing. Three codes, three stock balances, and no query that
                  spans them.
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
                    <span className="micro-label text-earth">{row.cpse}</span>
                    <span className="break-words font-mono text-sm md:text-base">{row.text}</span>
                  </ItemLi>
                ))}
              </ul>

              <Item className="pt-8">
                <p className="micro-label">Resolved to one record</p>
              </Item>
              <Item className="mt-4 border border-earth/40 bg-bg/60 p-6">
                <p className="break-words font-mono text-sm md:text-base">{GOLDEN}</p>
                <p className="pt-5 font-mono text-lg text-earth-deep md:text-xl">{GOLDEN_CODE}</p>
              </Item>
            </div>
          </Band>
        </Reveal>

        {/* ---- problem by problem ---- */}
        <Reveal id="fixes" className="border-t border-hairline bg-surface">
          <Band className="py-20 md:py-24">
            <Item>
              <Eyebrow>What it fixes</Eyebrow>
            </Item>
            <Item>
              <h2 id="fixes-title" className="max-w-[24ch] pt-6 text-headline font-medium">
                Twelve problems, and what closes each.
              </h2>
            </Item>

            <ul aria-labelledby="fixes-title" className="pt-12">
              <li
                aria-hidden
                className="hidden gap-8 border-b border-hairline pb-3 md:grid md:grid-cols-[2.5rem_minmax(0,1fr)_minmax(0,1.15fr)]"
              >
                <span />
                <span className="micro-label">Today</span>
                <span className="micro-label text-earth">With SAMAN</span>
              </li>
              {FIXES.map(([problem, fix], index) => (
                <ItemLi
                  key={problem}
                  className="grid gap-1 border-b border-hairline py-4 md:grid-cols-[2.5rem_minmax(0,1fr)_minmax(0,1.15fr)] md:items-baseline md:gap-8"
                >
                  <span className="font-mono text-xs text-earth">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="text-base font-medium">{problem}</span>
                  <span className="text-sm text-muted">{fix}</span>
                </ItemLi>
              ))}
            </ul>
          </Band>

          <Backdrop className="relative h-28 text-earth/25 md:h-36">
            <MaterialFrieze />
          </Backdrop>
        </Reveal>

        {/* ---- how it works ---- */}
        <Reveal id="how" className="relative overflow-hidden border-t border-hairline">
          <Backdrop className="absolute inset-x-0 bottom-0 h-32 text-earth-soft/25 md:h-44">
            <Skyline />
          </Backdrop>
          {/* The list ends above the skyline, never on top of it. */}
          <Band className="relative pb-44 pt-20 md:pb-60 md:pt-24">
            <Item>
              <Eyebrow>How it works</Eyebrow>
            </Item>
            <Item>
              <h2 id="how-title" className="max-w-[24ch] pt-6 text-headline font-medium">
                Cheap certainty first. Judgement last.
              </h2>
            </Item>

            <ol aria-labelledby="how-title" className="pt-12">
              {STAGES.map(([heading, body], index) => (
                <ItemLi
                  key={heading}
                  className="grid gap-2 border-t border-hairline py-6 md:grid-cols-[4rem_minmax(0,18rem)_1fr] md:items-baseline md:gap-10"
                >
                  <p className="font-mono text-base text-earth">
                    {String(index + 1).padStart(2, '0')}
                  </p>
                  <h3 className="text-lg font-medium">{heading}</h3>
                  <p className="max-w-[52ch] text-base text-muted">{body}</p>
                </ItemLi>
              ))}
            </ol>
          </Band>
        </Reveal>

        {/* ---- the veto, given the room it deserves ---- */}
        <Reveal className="border-t border-hairline bg-surface">
          <Band className="grid gap-10 py-20 md:py-24 lg:grid-cols-[auto_1fr] lg:gap-20">
            <div>
              <Item>
                <Eyebrow>Why it can be trusted</Eyebrow>
              </Item>
              <Item>
                <p className="whitespace-nowrap pt-8 font-mono text-headline text-earth-deep">
                  25 mm is not 30 mm.
                </p>
              </Item>
            </div>
            <div className="lg:pt-14">
              <Item>
                <p className="max-w-[50ch] text-lead text-muted">
                  Two rows can read alike and still be different parts. Identity attributes
                  are compared in real units, and a disagreement refuses the match. No score
                  is permitted to overrule it.
                </p>
              </Item>
            </div>
          </Band>
        </Reveal>

        {/* ---- the code ---- */}
        <Reveal id="code" className="border-t border-hairline">
          <Band className="py-20 md:py-24">
            <Item>
              <Eyebrow>The code</Eyebrow>
            </Item>
            <Item>
              <h2 className="max-w-[24ch] pt-6 text-headline font-medium">
                One material, one number, everywhere.
              </h2>
            </Item>

            <Item className="pt-12">
              {/* Each segment takes the shade its annotation uses below, so the
                  code and its explanation read as one object. */}
              <p className="font-mono text-headline">
                {SEGMENTS.map((segment, index) => (
                  <span key={segment.label}>
                    {index > 0 && <span className="text-muted">-</span>}
                    <span className={segment.tone}>{segment.part}</span>
                  </span>
                ))}
              </p>
            </Item>

            <dl className="grid gap-8 pt-10 sm:grid-cols-2 lg:grid-cols-4">
              {SEGMENTS.map((segment) => (
                <Item key={segment.label} className="space-y-2 border-t border-hairline pt-4">
                  <dt className="micro-label">
                    {segment.label} ·{' '}
                    <span className={`font-mono ${segment.tone}`}>{segment.part}</span>
                  </dt>
                  <dd className="max-w-[28ch] text-sm text-muted">{segment.body}</dd>
                </Item>
              ))}
            </dl>
          </Band>
        </Reveal>

        {/* ---- guarantees, over the racking ---- */}
        <Reveal id="guarantees" className="relative overflow-hidden border-t border-hairline bg-surface">
          <Backdrop className="absolute inset-x-0 bottom-0 h-40 text-earth/[0.12] md:h-52">
            <Racking />
          </Backdrop>
          <Band className="relative pb-48 pt-20 md:pb-64 md:pt-24">
            <Item>
              <Eyebrow>What it guarantees</Eyebrow>
            </Item>
            <div className="grid gap-8 pt-10 md:grid-cols-3">
              {PROMISES.map(([heading, body]) => (
                <Item key={heading} className="space-y-3 border-t border-hairline pt-5">
                  <h3 className="text-lg font-medium">{heading}</h3>
                  <p className="text-sm text-muted">{body}</p>
                </Item>
              ))}
            </div>
          </Band>
        </Reveal>

        {/* ---- close ---- */}
        <Reveal className="border-t border-hairline">
          <Band className="grid gap-8 py-20 md:py-24 lg:grid-cols-[1fr_auto] lg:items-end lg:gap-20">
            <div>
              <Item>
                <h2 className="max-w-[20ch] text-headline font-medium">
                  It is running on this machine.
                </h2>
              </Item>
              <Item>
                <p className="max-w-[44ch] pt-6 text-lead text-muted">
                  Any seeded account, password <span className="font-mono">demo</span>.
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

      <footer className="relative border-t border-hairline">
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
