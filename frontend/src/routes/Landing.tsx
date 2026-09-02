import { motion, useReducedMotion } from 'framer-motion'
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'


import { Assistant, AssistantMark } from '../components/Assistant'
import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/primitives/Button'
import { cn } from '../lib/cn'
import { EASE, listItemVariants, listVariants } from '../lib/motion'

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

/**
 * A filled city skyline, the way the SIH site sets its sections over one: pale
 * silhouette, full width, no outline. Indian civic architecture rather than a
 * generic downtown: a triumphal arch at the centre, domes on drums, a clock
 * tower, chhatris on the corners of the larger blocks, and office towers
 * towards the edges. Deterministic, so every load draws the same city.
 */
function CitySkyline() {
  const ground = 300
  const block = (x: number, w: number, h: number, windows = true) => (
    <g key={`b${x}`}>
      <rect x={x} y={ground - h} width={w} height={h} />
      {windows &&
        Array.from({ length: Math.max(0, Math.floor((h - 24) / 26)) }, (_, r) =>
          Array.from({ length: Math.max(0, Math.floor((w - 12) / 20)) }, (_, c) => (
            <rect
              key={`${r}-${c}`}
              x={x + 10 + c * 20}
              y={ground - h + 14 + r * 26}
              width="8"
              height="12"
              fill="rgb(var(--bg))"
              opacity="0.55"
            />
          )),
        )}
    </g>
  )
  const dome = (x: number, r: number, drum: number, base: number) => (
    <g key={`d${x}`}>
      <rect x={x - r * 0.72} y={ground - base} width={r * 1.44} height={base} />
      <rect x={x - r * 0.6} y={ground - base - drum} width={r * 1.2} height={drum} />
      <path d={`M${x - r} ${ground - base - drum} A${r} ${r * 0.95} 0 0 1 ${x + r} ${ground - base - drum} Z`} />
      <rect x={x - 2} y={ground - base - drum - r * 0.95 - 16} width="4" height="18" />
    </g>
  )
  const chhatri = (x: number, y: number) => (
    <g key={`c${x}-${y}`}>
      <path d={`M${x - 12} ${y} A12 10 0 0 1 ${x + 12} ${y} Z`} />
      <rect x={x - 14} y={y} width="28" height="3" />
      <rect x={x - 11} y={y + 3} width="3" height="16" />
      <rect x={x + 8} y={y + 3} width="3" height="16" />
    </g>
  )
  const archGate = (x: number) => (
    <g key="gate">
      <rect x={x - 70} y={ground - 190} width="140" height="190" />
      <rect x={x - 54} y={ground - 214} width="108" height="24" />
      <rect x={x - 24} y={ground - 230} width="48" height="16" />
      <path d={`M${x - 34} ${ground} v-96 A34 34 0 0 1 ${x + 34} ${ground - 96} v96 Z`} fill="rgb(var(--bg))" />
      {chhatri(x - 52, ground - 232)}
      {chhatri(x + 52, ground - 232)}
    </g>
  )
  const clockTower = (x: number) => (
    <g key="clock">
      <rect x={x - 16} y={ground - 236} width="32" height="236" />
      <rect x={x - 22} y={ground - 244} width="44" height="10" />
      <path d={`M${x - 16} ${ground - 244} L${x} ${ground - 284} L${x + 16} ${ground - 244} Z`} />
      <circle cx={x} cy={ground - 206} r="9" fill="rgb(var(--bg))" opacity="0.7" />
    </g>
  )
  return (
    <svg
      aria-hidden
      viewBox="0 0 1440 300"
      preserveAspectRatio="xMidYMax slice"
      fill="currentColor"
      className="h-full w-full"
    >
      {block(0, 70, 120)}
      {block(78, 54, 168)}
      {block(140, 90, 96)}
      {dome(292, 42, 14, 110)}
      {block(352, 68, 140)}
      {chhatri(386, ground - 156)}
      {block(430, 110, 88)}
      {clockTower(590)}
      {block(620, 80, 124)}
      {archGate(720)}
      {block(820, 80, 124)}
      {dome(940, 56, 18, 128)}
      {block(1010, 96, 92)}
      {block(1116, 60, 176)}
      {chhatri(1146, ground - 192)}
      {block(1184, 100, 104)}
      {block(1292, 64, 150)}
      {block(1364, 76, 112)}
      <rect x="0" y={ground - 6} width="1440" height="6" />
    </svg>
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

/** A scroll ornament: two mirrored volutes over a rule, the flourish a title
 *  sits under on a letterhead. Generated from one quarter, mirrored. */
function Ornament({ className }: { className?: string }) {
  const volute = 'M0 14 C 10 14, 18 8, 22 2 C 25 -2, 31 0, 30 5 C 29 9, 24 10, 22 7'
  return (
    <svg
      viewBox="-96 -8 192 26"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      className={className}
    >
      <line x1="-92" y1="14" x2="-34" y2="14" />
      <line x1="34" y1="14" x2="92" y2="14" />
      <g transform="translate(-30 0)">
        <path d={volute} />
      </g>
      <g transform="translate(30 0) scale(-1 1)">
        <path d={volute} />
      </g>
      <circle cx="0" cy="8" r="2.2" fill="currentColor" stroke="none" />
    </svg>
  )
}

/** A jali: the pierced lattice of a Mughal or Rajput stone screen, as one
 *  eight-point star tile that SVG repeats. */
function Jali({ className }: { className?: string }) {
  return (
    <svg aria-hidden className={className} width="100%" height="100%">
      <defs>
        <pattern id="jali" width="48" height="48" patternUnits="userSpaceOnUse">
          <g fill="none" stroke="currentColor" strokeWidth="1">
            <path d="M24 4 L28 16 L40 12 L32 24 L40 36 L28 32 L24 44 L20 32 L8 36 L16 24 L8 12 L20 16 Z" />
            <circle cx="24" cy="24" r="5" />
            <path d="M0 0 L8 8 M48 0 L40 8 M0 48 L8 40 M48 48 L40 40" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#jali)" />
    </svg>
  )
}

/** Textures for the giant wordmark, as data-URI SVG patterns in the page's
 *  own colours. One is picked per load, the way Sarvam's footer rotates the
 *  art behind its name; here the art is generated rather than photographed. */
const WORDMARK_TEXTURES = [
  // jali stars
  "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48" fill="#A66A34"/><g fill="none" stroke="#F4ECE0" stroke-width="1.2"><path d="M24 4L28 16L40 12L32 24L40 36L28 32L24 44L20 32L8 36L16 24L8 12L20 16Z"/><circle cx="24" cy="24" r="5"/></g></svg>'),
  // arcade
  "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60"><rect width="60" height="60" fill="#68401E"/><g fill="none" stroke="#CDB291" stroke-width="1.4"><path d="M8 58V26A22 22 0 0 1 52 26V58"/><path d="M0 58H60"/><path d="M18 58V32A12 12 0 0 1 42 32V58"/></g></svg>'),
  // bearing rings
  "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#CDB291"/><g fill="none" stroke="#68401E" stroke-width="1.2"><circle cx="32" cy="32" r="26"/><circle cx="32" cy="32" r="18"/><circle cx="32" cy="32" r="9"/><circle cx="32" cy="6" r="3"/><circle cx="58" cy="32" r="3"/><circle cx="32" cy="58" r="3"/><circle cx="6" cy="32" r="3"/></g></svg>'),
]

/** The word SAMAN at the foot of the page, cropped, filled with a texture. */
function GiantWordmark() {
  const texture = useMemo(
    () => WORDMARK_TEXTURES[Math.floor(Math.random() * WORDMARK_TEXTURES.length)],
    [],
  )
  const style: CSSProperties = {
    backgroundImage: `url("${texture}")`,
    backgroundSize: '64px 64px',
    WebkitBackgroundClip: 'text',
    backgroundClip: 'text',
    color: 'transparent',
    lineHeight: 0.78,
  }
  return (
    <div aria-hidden className="pointer-events-none select-none overflow-hidden">
      <p
        style={style}
        className="-mb-[0.2em] translate-y-[0.14em] whitespace-nowrap text-center font-semibold uppercase tracking-[0.06em]"
      >
        <span className="text-[26vw] leading-none md:text-[22vw]" style={{ fontSize: 'clamp(9rem, 22vw, 20rem)' }}>SAMAN</span>
      </p>
    </div>
  )
}

/** Grain over the closing card, generated in the page: feTurbulence at low
 *  opacity, blended soft-light, so the gradient reads as material rather than
 *  as a flat fill. */
function Grain() {
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 h-full w-full mix-blend-soft-light opacity-60">
      <filter id="grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#grain)" />
    </svg>
  )
}

/** Concentric rings across the closing card, the bearing race again. */
function Rings() {
  return (
    <svg aria-hidden viewBox="0 0 1200 400" preserveAspectRatio="xMidYMid slice" className="pointer-events-none absolute inset-0 h-full w-full text-bg/20" fill="none" stroke="currentColor" strokeWidth="1">
      {Array.from({ length: 9 }, (_, i) => (
        <circle key={i} cx="600" cy="420" r={80 + i * 90} />
      ))}
    </svg>
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

function FooterColumn({
  heading,
  links,
  mono,
}: {
  heading: string
  links: ReadonlyArray<readonly [string, string]>
  mono?: boolean
}) {
  return (
    <div className="space-y-3">
      <p className="micro-label text-earth">{heading}</p>
      <ul className="space-y-2">
        {links.map(([label, to]) => (
          <li key={to}>
            {to.startsWith('/api/') ? (
              <a href={to} className={cn('text-sm text-muted hover:text-ink', mono && 'font-mono text-xs')}>
                {label}
              </a>
            ) : (
              <Link to={to} className={cn('text-sm text-muted hover:text-ink', mono && 'font-mono text-xs')}>
                {label}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="micro-label text-earth">{children}</p>
}

export default function Landing() {
  const reduce = useReducedMotion() ?? false
  const [active, setActive] = useState<string>('')

  // The section nearest the top of the viewport owns the nav indicator, so it
  // slides along as you scroll and lands where a click sends it.
  useEffect(() => {
    const ids = NAV.map((entry) => entry.href.slice(1))
    const targets = ids.map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[]
    if (targets.length === 0 || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-20% 0px -60% 0px', threshold: 0 },
    )
    targets.forEach((target) => observer.observe(target))
    return () => observer.disconnect()
  }, [])

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
            {NAV.map((entry) => {
              const current = active === entry.href.slice(1)
              return (
                <a
                  key={entry.href}
                  href={entry.href}
                  aria-current={current ? 'location' : undefined}
                  onClick={(event) => {
                    // Slide to the section rather than jump. The hash still
                    // lands in the address bar for a link to be shared.
                    const target = document.getElementById(entry.href.slice(1))
                    if (!target) return
                    event.preventDefault()
                    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
                    history.replaceState(null, '', entry.href)
                  }}
                  className={cn(
                    'relative py-1 text-sm transition-colors duration-150 hover:text-ink',
                    current ? 'text-ink' : 'text-muted',
                  )}
                >
                  {entry.label}
                  {current && (
                    <motion.span
                      layoutId="landing-nav-indicator"
                      aria-hidden
                      className="absolute inset-x-0 -bottom-[1.4rem] h-0.5 bg-earth"
                      transition={{ duration: reduce ? 0 : 0.28, ease: EASE }}
                    />
                  )}
                </a>
              )
            })}
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
        {/* ---- hero: centred, one screen tall, the city along its foot ---- */}
        <motion.div
          variants={listVariants(reduce)}
          initial="initial"
          animate="animate"
          className="relative flex min-h-[calc(100vh-4rem)] flex-col overflow-hidden"
        >
          <Band className="relative flex flex-1 flex-col items-center justify-center py-16 text-center md:py-20">
            <Item>
              <Ornament className="mx-auto h-6 w-48 text-earth" />
            </Item>
            <Item className="pt-4">
              <Eyebrow>Standardised Asset &amp; Material Analysis Network</Eyebrow>
            </Item>
            <Item>
              <h1 className="mx-auto max-w-[16ch] pt-7 text-display font-medium">
                One Nation, One Material Code
              </h1>
            </Item>
            <Item>
              <div aria-hidden className="mx-auto mt-8 h-1 w-24 bg-earth" />
            </Item>
            <Item>
              <p className="mx-auto max-w-[44ch] pt-8 text-lead text-muted">
                Every public sector undertaking codes the same part differently. SAMAN works
                out which rows are one material, and gives it one code.
              </p>
            </Item>
            <Item className="flex flex-wrap items-center justify-center gap-4 pt-10">
              <a href="#how">
                <Button variant="primary">See how it decides</Button>
              </a>
              <Link to="/login">
                <Button variant="secondary">Open the demo</Button>
              </Link>
            </Item>
          </Band>

          {/* The city, pale and whole, inside the first screen. */}
          <Backdrop className="relative h-40 w-full shrink-0 text-earth-soft/50 md:h-52 lg:h-60">
            <CitySkyline />
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
          <Backdrop className="absolute inset-x-0 bottom-0 h-32 text-earth-soft/35 md:h-44">
            <CitySkyline />
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
        <Reveal className="relative overflow-hidden border-t border-hairline bg-surface">
          {/* The lattice owns the right third; nothing is set over it. */}
          <Backdrop className="absolute inset-y-0 right-0 hidden w-1/3 text-earth/[0.14] lg:block">
            <Jali />
          </Backdrop>
          <Band className="relative py-20 md:py-24">
            <div className="max-w-[60%] lg:max-w-[58ch]">
              <Item>
                <Eyebrow>Why it can be trusted</Eyebrow>
              </Item>
              <Item>
                <p className="whitespace-nowrap pt-8 font-mono text-headline text-earth-deep">
                  25 mm is not 30 mm.
                </p>
              </Item>
              <Item>
                <p className="max-w-[50ch] pt-8 text-lead text-muted">
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
          <Backdrop className="relative h-24 text-earth/20 md:h-32">
            <Colonnade />
          </Backdrop>
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

        {/* ---- close: the card Sarvam ends on, in this page's colours ---- */}
        <Reveal className="border-t border-hairline">
          <Band className="py-16 md:py-20">
            <Item className="relative overflow-hidden rounded-3xl border border-hairline bg-[linear-gradient(180deg,rgb(var(--ink))_0%,rgb(var(--earth-deep))_70%,rgb(var(--earth-soft))_140%)] px-6 py-16 text-center text-bg md:py-24">
              <Rings />
              <Grain />
              <div className="relative mx-auto max-w-[26ch]">
                <AssistantMark className="mx-auto h-8 w-8 text-bg/80" />
                <h2 className="pt-6 text-headline font-medium text-bg">
                  Build one material master for India.
                </h2>
                <p className="pt-5 text-lead text-bg/70">
                  Running on this machine. Any seeded account, password{' '}
                  <span className="font-mono">demo</span>.
                </p>
                <div className="pt-8">
                  <Link
                    to="/login"
                    className="inline-flex h-11 items-center rounded-full bg-bg px-6 text-sm font-medium text-ink hover:opacity-90"
                  >
                    Open the demo
                  </Link>
                </div>
              </div>
            </Item>
          </Band>
        </Reveal>
      </main>

      <footer className="relative border-t border-hairline bg-[linear-gradient(180deg,rgb(var(--bg))_0%,rgb(var(--surface))_100%)]">
        <Band className="grid gap-10 py-14 md:grid-cols-[1.3fr_1fr_1fr_1fr]">
          <div className="space-y-3">
            <p className="font-medium uppercase tracking-wordmark">SAMAN</p>
            <p className="max-w-[28ch] text-sm text-muted">
              Standardised Asset &amp; Material Analysis Network. One Nation, One Material Code.
            </p>
            <p className="pt-2 text-xs text-muted">
              Smart India Hackathon 2026 · SIH26099
              <br />
              Ministry of Petroleum &amp; Natural Gas
            </p>
          </div>
          <FooterColumn
            heading="Screens"
            links={[
              ['Search', '/search'],
              ['Workbench', '/workbench'],
              ['Executive', '/dashboard/executive'],
              ['Opportunity', '/dashboard/opportunity'],
              ['Smart-Create', '/smart-create'],
              ['Migration', '/migration'],
            ]}
          />
          <FooterColumn
            heading="Governance"
            links={[
              ['Audit trail', '/audit'],
              ['Restricted mode', '/pprl'],
              ['Admin', '/admin'],
              ['Sign in', '/login'],
            ]}
          />
          <FooterColumn
            heading="Open interfaces"
            links={[
              ['/api/docs', '/api/docs'],
              ['/api/health', '/api/health'],
              ['/api/metrics', '/api/metrics'],
            ]}
            mono
          />
        </Band>
        <Band className="flex flex-wrap items-center justify-between gap-3 border-t border-hairline py-5">
          <p className="text-xs text-muted">
            A prototype. Not an official service of the Government of India.
          </p>
          <p className="text-xs text-muted">Everything on this page is drawn in the page.</p>
        </Band>
        <GiantWordmark />
      </footer>

      {/* Inside `.landing`, so the widget takes the warm palette here and the
          monochrome one everywhere else. */}
      <Assistant />
    </div>
  )
}
