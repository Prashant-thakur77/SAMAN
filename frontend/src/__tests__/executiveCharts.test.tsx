/**
 * The eight analytic sections of the executive dashboard. Each renders from a
 * typed payload; the interesting properties are the ones the design contract
 * insists on: headline figures formatted, a legend whenever two shades appear,
 * an honest empty state, a table twin so no value is reachable only by hover,
 * and the by-family chart sorted by coded share with the share labelled.
 */

import { render as renderBare, screen, within } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

// Chart rows open the rows behind them, so the charts live inside a router.
const render = (ui: ReactElement) => renderBare(<MemoryRouter>{ui}</MemoryRouter>)

import { EvaluationTable } from '../components/charts/EvaluationTable'
import { HarmonisationByClass } from '../components/charts/HarmonisationByClass'
import { HeldForReview } from '../components/charts/HeldForReview'
import { MaterialsByCpseCount } from '../components/charts/MaterialsByCpseCount'
import { PipelineLadder } from '../components/charts/PipelineLadder'
import { SavingsLadder } from '../components/charts/SavingsLadder'
import { StockAge } from '../components/charts/StockAge'
import { VetoAttributes } from '../components/charts/VetoAttributes'
import { formatRupees } from '../components/charts/CountUp'
import { niceTicks } from '../components/charts/ChartParts'
import type {
  ByClass,
  ByCpseCount,
  Evaluation,
  HeldForReview as HeldForReviewData,
  PipelineLadder as PipelineLadderData,
  SavingsLadder as SavingsLadderData,
  StockAge as StockAgeData,
  VetoAttributes as VetoAttributesData,
} from '../lib/api'

// ---- fixtures ---------------------------------------------------------------

const byClass: ByClass = {
  parts: [
    { key: 'coded', label: 'Carrying a CNMC' },
    { key: 'duplicate_pending', label: 'Duplicate found, awaiting a code' },
    { key: 'unique_pending', label: 'No duplicate found' },
  ],
  // Deliberately out of order: the component must sort by coded share.
  rows: [
    { class_code: 'bearing.ball.deep_groove', family: 'BRNG', rows: 1519, coded: 10, duplicate_pending: 948, unique_pending: 561, coded_share: 0.0066 },
    { class_code: 'ppe.helmet', family: 'PPEQ', rows: 648, coded: 215, duplicate_pending: 184, unique_pending: 249, coded_share: 0.3318 },
    { class_code: 'valve.gate', family: 'VALV', rows: 3127, coded: 821, duplicate_pending: 1106, unique_pending: 1200, coded_share: 0.2626 },
    { class_code: 'unclassified', family: null, rows: 0, coded: 0, duplicate_pending: 0, unique_pending: 0, coded_share: 0 },
  ],
  note: 'per-class rule',
}

const byCpseCount: ByCpseCount = {
  rows: [
    { cpses: 1, materials: 4592, rows: 4593 },
    { cpses: 2, materials: 1136, rows: 2273 },
    { cpses: 3, materials: 756, rows: 2271 },
    { cpses: 4, materials: 658, rows: 2641 },
  ],
  multi_materials: 2550,
  multi_rows: 7185,
  internal_duplicate_rows: 14,
  cpses_with_rows: 4,
  cpses_empty: ['BPCL'],
  note: '',
}

const pipeline: NonNullable<PipelineLadderData> = {
  run_id: 1,
  increments: null,
  run_at: '2026-09-02T16:49:34',
  rungs: [
    { key: 'possible', label: 'Possible pairs', value: 69354753, unit: 'pairs', factor_from_previous: null, aside: null, note: '11,778 rows, every pair' },
    { key: 'candidates', label: 'Candidates after blocking', value: 647429, unit: 'pairs', factor_from_previous: 107.1, aside: { label: 'true pairs no pass produced', value: 39 }, note: null },
    { key: 'close', label: 'Close enough to matter', value: 11164, unit: 'pairs', factor_from_previous: 58, aside: { label: 'refused as distinct by the machine', value: 636265 }, note: null },
    { key: 'merged', label: 'Merged automatically', value: 7386, unit: 'pairs', factor_from_previous: 1.5, aside: { label: 'held for a human', value: 3778 }, note: null },
    { key: 'materials', label: 'Materials with more than one name', value: 2551, unit: 'materials', factor_from_previous: null, aside: null, note: null },
    { key: 'codes', label: 'CNMCs issued', value: 754, unit: 'codes', factor_from_previous: null, aside: null, note: null },
  ],
  blocking: {
    recall: 0.9949,
    true_pairs: 7675,
    missed: 39,
    passes: [
      { pass: 'mpn', added: 6188, note: 'the same part number' },
      { pass: 'text', added: 87, note: 'byte-identical normalized text' },
      { pass: 'ann', added: 284185, note: 'nearest neighbours' },
    ],
  },
  source: 'run',
}

const veto: VetoAttributesData = {
  source: 'stored_pairs',
  pairs_with_veto: 7933,
  coverage: { conflict: 3310, refused: 4623, refused_total: 636265 },
  by_attribute: [
    { attr: 'load_rating_kg', label: 'Load rating (kg)', role: 'performance', pairs: 4616, example: { a: '300 kg', b: '1000 kg', reason: '300 kg vs 1000 kg — 70% apart, outside the 5% band' } },
    { attr: 'bore_mm', label: 'Bore (mm)', role: 'identity_critical', pairs: 1828, example: { a: '15 mm', b: '50 mm', reason: '15 mm vs 50 mm' } },
    { attr: 'seal_type', label: 'Seal type', role: 'identity_critical', pairs: 944, example: null },
  ],
  other: { attributes: 16, pairs: 1209 },
  attrs_per_pair: [
    { n: 1, pairs: 2513 },
    { n: 2, pairs: 2489 },
  ],
  cosmetic_never_vetoes: ['brand', 'colour'],
  note: '',
}

const held: HeldForReviewData = {
  total: 3778,
  thresholds: { t_low: 0.45, t_high: 0.86 },
  reasons: [
    {
      key: 'conflict',
      label: 'Same part number, but a specification disagrees',
      pairs: 3310,
      confidence: { min: 1, max: 1 },
      owner_roles: ['approver', 'registrar', 'admin'],
      parts: [
        { key: 'identity_critical', label: 'An identity-critical attribute differs', pairs: 116, equivalence_flagged: null },
        { key: 'performance_only', label: 'Only a performance rating is out of band', pairs: 3194, equivalence_flagged: 2430 },
      ],
    },
    {
      key: 'review',
      label: 'Scored inside the grey zone',
      pairs: 468,
      confidence: { min: 0.7045, max: 0.8586 },
      owner_roles: ['steward', 'approver'],
      parts: null,
    },
  ],
  also_queued: [
    { band: 'high', reason: 'confirm an automatic merge', pending: 7381, done: 5, disposition: 'policy', evidence: { duplicate_precision: 0.9973, split: 'holdout' } },
    { band: 'low', reason: 'confirm an automatic refusal', pending: 500, done: 0, disposition: 'audit_sample', sample_of: 636265 },
  ],
  decisions: { by_action: { approve: 5 }, total: 5, last_at: '2026-09-05T06:43:41' },
  labels: { reviewer: 5, simulated: 400 },
  note: '',
}

const evaluation: NonNullable<Evaluation> = {
  run_id: 1,
  computed_at: '2026-09-18T17:10:38',
  split: 'holdout',
  items_holdout: 4664,
  decisions_since: 0,
  rows: [
    { key: 'precision', label: 'Pairwise precision', value: 0.9973, target: 0.92, pass: true, baseline: 1, detail: '8 false positives' },
    { key: 'recall', label: 'Pairwise recall', value: 0.9595, target: 0.8, pass: true, baseline: 0.0287, detail: null },
    { key: 'f1', label: 'Pairwise F1', value: 0.978, target: null, pass: null, baseline: 0.0557, detail: null },
    { key: 'blocking_recall', label: 'Blocking recall', value: 0.9, target: 0.97, pass: false, baseline: null, detail: null },
  ],
  baseline_note: 'Naive: byte-identical text.',
  per_class: [
    { class_code: 'ppe.helmet', items: 261, precision: 1, recall: 1, f1: 1, false_negatives: 0 },
    { class_code: 'bearing.ball.deep_groove', items: 611, precision: 0.9944, recall: 0.9036, f1: 0.9468, false_negatives: 38 },
  ],
  worst_class: 'bearing.ball.deep_groove',
  note: 'Thresholds are tuned on the 60% tuning split; every number below is measured on the 40% held-out split.',
}

const savings: SavingsLadderData = {
  window_months: 12,
  capture: 0.6,
  assumption_note: 'Assumes 60% of the observed price spread is capturable at combined volume.',
  rungs: [
    { key: 'spend', label: 'Purchases in the last 12 months', value_inr: 33192375336.57, share_of_previous: null, materials: 5773, orders: 14016, assumption: null },
    { key: 'shared', label: 'On materials two or more CPSEs buy', value_inr: 17167589369.16, share_of_previous: 0.5172, materials: 1781, orders: 7392, assumption: null },
    { key: 'ceiling', label: 'If every order had been at the best price paid', value_inr: 3551643597.26, share_of_previous: 0.2069, materials: 1781, orders: null, assumption: 'Upper bound. Not a forecast.' },
    {
      key: 'estimate',
      label: 'Savings identified at 60% capture',
      value_inr: 2130986158.26,
      share_of_previous: 0.6,
      materials: null,
      orders: null,
      assumption: 'Assumes 60% of the observed price spread is capturable at combined volume.',
      sensitivity: { capture_low: 0.4, value_low_inr: 1420657438.9, capture_high: 0.8, value_high_inr: 2841314877.81 },
    },
  ],
  synthetic_note: 'Purchase history is seeded.',
}

const stockAge: StockAgeData = {
  rule_months: 12,
  quality_stale_months: 24,
  demand_window_months: 12,
  bins: [
    { from_months: 0, to_months: 6, label: '0–6', positions: 4398, materials: 3502, value_inr: 31610877009.72, demand_elsewhere_value_inr: 16956596462.33, no_demand_value_inr: 14654280547.39, idle: false },
    { from_months: 6, to_months: 12, label: '6–12', positions: 4973, materials: 3926, value_inr: 36798419635.6, demand_elsewhere_value_inr: 18517081027.05, no_demand_value_inr: 18281338608.55, idle: false },
    { from_months: 12, to_months: 18, label: '12–18', positions: 767, materials: 732, value_inr: 5723349218.21, demand_elsewhere_value_inr: 3208561207.75, no_demand_value_inr: 2514788010.46, idle: true },
    { from_months: 18, to_months: null, label: '18+', positions: 0, materials: 0, value_inr: 0, demand_elsewhere_value_inr: 0, no_demand_value_inr: 0, idle: true },
  ],
  idle: { value_inr: 16353254849.74, positions: 2390, materials: 2106, demand_elsewhere_value_inr: 8903537394.03, demand_elsewhere_materials: 1053 },
  top_class: { class_code: 'valve.gate', share_of_idle_value: 0.9345 },
  excluded_positions: 17,
  note: '',
}

// ---- helpers ------------------------------------------------------------------

const legendItems = (section: HTMLElement) => section.querySelectorAll('dl dt')
// testing-library's `within` is typed for HTMLElement; an SVG root queries the same way.
const chart = (section: HTMLElement) => section.querySelector('svg[role="img"]') as unknown as HTMLElement
const twin = (section: HTMLElement) => within(section.querySelector('details') as HTMLElement)

// ---- tests ------------------------------------------------------------------------

describe('Harmonisation by family', () => {
  it('sorts the rows by coded share, highest first, and labels every row with its share', () => {
    render(<HarmonisationByClass byClass={byClass} codesIssued={754} />)
    const svg = chart(screen.getByTestId('by_class'))
    // The class code is the first text node of each row's label; the family prefix is a tspan after it.
    const labels = Array.from(svg.querySelectorAll('g.chart-row')).map((row) =>
      (row.querySelector('text')?.firstChild?.textContent ?? '').trim(),
    )
    expect(labels).toEqual([
      'ppe.helmet',
      'valve.gate',
      'bearing.ball.deep_groove',
      'unclassified',
    ])
    // The coded share at the row's right end: whole percent, one decimal under 10%.
    for (const share of ['33%', '26%', '0.7%']) expect(within(svg).getByText(share)).toBeInTheDocument()
  })

  it('draws three ramp segments per row with a legend of the donut’s three parts', () => {
    render(<HarmonisationByClass byClass={byClass} />)
    const section = screen.getByTestId('by_class')
    expect(legendItems(section)).toHaveLength(3)
    expect(within(section).getAllByText('Carrying a CNMC').length).toBeGreaterThan(0)
    // Three classes with rows, three segments each; the 0-row class gets none and no label.
    expect(chart(section).querySelectorAll('path.chart-bar')).toHaveLength(9)
  })

  it('carries a tooltip per row and a table twin with every row', () => {
    render(<HarmonisationByClass byClass={byClass} />)
    const section = screen.getByTestId('by_class')
    expect(chart(section).querySelectorAll('title')).toHaveLength(4)
    expect(chart(section).getAttribute('aria-label')).toMatch(/bearing\.ball\.deep_groove trails at 0\.7%/)
    const table = twin(section)
    for (const code of ['ppe.helmet', 'valve.gate', 'bearing.ball.deep_groove', 'unclassified']) {
      expect(table.getByText(code)).toBeInTheDocument()
    }
    expect(table.getByText('1,519')).toBeInTheDocument()
  })

  it('quotes the live code count in its caption rather than a constant', () => {
    render(<HarmonisationByClass byClass={byClass} codesIssued={754} />)
    expect(screen.getByText(/all 754 codes were issued in one seeded batch/)).toBeInTheDocument()
  })
})

describe('How many companies describe the same material', () => {
  it('states the headline, legends its two shades and labels every bar tip', () => {
    render(<MaterialsByCpseCount data={byCpseCount} />)
    const section = screen.getByTestId('by_cpse_count')
    expect(within(section).getByText('2,550')).toBeInTheDocument()
    expect(within(section).getByText('7,142')).toBeInTheDocument()
    expect(legendItems(section)).toHaveLength(2)
    const svg = chart(section)
    expect(within(svg).getByText('658 materials')).toBeInTheDocument()
    expect(within(svg).getByText('· 2,641 rows')).toBeInTheDocument()
    expect(svg.querySelectorAll('path.chart-bar')).toHaveLength(4)
  })

  it('lists CPSEs, materials and rows in its table twin and names the empty CPSE', () => {
    render(<MaterialsByCpseCount data={byCpseCount} />)
    const section = screen.getByTestId('by_cpse_count')
    const table = twin(section)
    for (const n of ['4,592', '1,136', '756', '658', '4,593', '2,273', '2,271', '2,641']) {
      expect(table.getByText(n)).toBeInTheDocument()
    }
    expect(within(section).getByText(/BPCL has no rows yet, so the maximum is four/)).toBeInTheDocument()
    expect(within(section).getByText(/14 rows are duplicated inside a single CPSE/)).toBeInTheDocument()
  })
})

describe('The pipeline ladder', () => {
  it('is numbers, not bars: every rung’s count with its unit, the factors, the asides', () => {
    render(<PipelineLadder pipeline={pipeline} baselineRecall={0.0287} />)
    const section = screen.getByTestId('pipeline')
    expect(section.querySelector('svg')).toBeNull()
    expect(within(section).getByText('6,93,54,753')).toBeInTheDocument()
    expect(within(section).getByText('754')).toBeInTheDocument()
    expect(within(section).getByText('÷107')).toBeInTheDocument()
    expect(within(section).getByText('÷1.5')).toBeInTheDocument()
    expect(within(section).getByText(/3,778 held for a human/)).toBeInTheDocument()
    // Six 2×12 px ticks, one per rung.
    expect(section.querySelectorAll('ol > li span.h-3.w-0\\.5')).toHaveLength(6)
  })

  it('lists the blocking passes in execution order and flags the text pass as the baseline', () => {
    render(<PipelineLadder pipeline={pipeline} baselineRecall={0.0287} />)
    const section = screen.getByTestId('pipeline')
    const cells = Array.from(section.querySelectorAll('tbody td:first-child')).map((td) => td.textContent)
    expect(cells).toEqual(['mpn', 'text', 'ann'])
    expect(within(section).getByText(/the naive baseline; recall 0\.029/)).toBeInTheDocument()
  })

  it('renders the no-run empty state rather than zeros', () => {
    render(<PipelineLadder pipeline={null} />)
    const section = screen.getByTestId('pipeline')
    expect(within(section).getByText('No matching run yet')).toBeInTheDocument()
    expect(within(section).queryByText('0')).toBeNull()
  })
})

describe('What kept look-alikes apart', () => {
  it('draws a bar per attribute plus the folded tail, with a legend for the shades', () => {
    render(<VetoAttributes data={veto} />)
    const section = screen.getByTestId('veto_attributes')
    expect(legendItems(section)).toHaveLength(3)
    const svg = chart(section)
    expect(svg.querySelectorAll('path.chart-bar')).toHaveLength(4)
    for (const n of ['4,616', '1,828', '944', '1,209']) expect(within(svg).getByText(n)).toBeInTheDocument()
    expect(within(section).getByText('7,933')).toBeInTheDocument()
  })

  it('puts the real example in the tooltip and the table twin, and says bars are attributes not pairs', () => {
    render(<VetoAttributes data={veto} />)
    const section = screen.getByTestId('veto_attributes')
    const titles = Array.from(chart(section).querySelectorAll('title')).map((t) => t.textContent)
    expect(titles.some((t) => t?.includes('15 mm vs 50 mm'))).toBe(true)
    expect(twin(section).getByText('15 mm vs 50 mm')).toBeInTheDocument()
    expect(within(section).getByText(/1: 2,513 · 2: 2,489/)).toBeInTheDocument()
    expect(within(section).getByText(/Brand and colour differences never block a merge/)).toBeInTheDocument()
  })

  it('states its coverage from the payload: stored pairs, or the whole run', () => {
    const { rerender } = render(<VetoAttributes data={veto} />)
    expect(screen.getByText(/Counted over the 3,310 conflicts and the 4,623 most plausible refusals/)).toBeInTheDocument()
    rerender(<MemoryRouter><VetoAttributes data={{ ...veto, source: 'run' }} /></MemoryRouter>)
    expect(screen.getByText(/Counted over every pair the veto refused in the last run/)).toBeInTheDocument()
  })
})

describe('Why pairs wait for a human', () => {
  it('is a ladder of numbers with roles as neutral chips and thresholds from the payload', () => {
    render(<HeldForReview data={held} />)
    const section = screen.getByTestId('held_for_review')
    expect(section.querySelector('svg')).toBeNull()
    expect(within(section).getByRole('heading')).toHaveTextContent('Why 3,778 pairs wait for a human')
    for (const n of ['3,310', '116', '3,194', '2,430', '468', '7,381', '500', '400']) {
      expect(within(section).getByText(n)).toBeInTheDocument()
    }
    expect(within(section).getByText(/grey zone 0\.45–0\.86/)).toBeInTheDocument()
    expect(within(section).getByText('confidence 1.00 ·')).toBeInTheDocument()
    expect(within(section).getAllByText('approver')).toHaveLength(2)
    expect(within(section).getByText(/5 approvals/)).toBeInTheDocument()
    expect(within(section).getByText(/audit sample of 6,36,265/)).toBeInTheDocument()
  })
})

describe('The held-out scorecard', () => {
  it('shows values, targets, baselines and a status chip per measure, weakest class first', () => {
    render(<EvaluationTable evaluation={evaluation} />)
    const section = screen.getByTestId('evaluation')
    expect(within(section).getByText(/is the weakest family/)).toBeInTheDocument()
    expect(within(section).getAllByText('meets target')).toHaveLength(2)
    expect(within(section).getByText('below target')).toBeInTheDocument()
    expect(within(section).getAllByText('no target')).toHaveLength(1)
    expect(within(section).getByText('≥ 0.92')).toBeInTheDocument()
    // The baseline's recall in the hero sentence and in its own column.
    expect(within(section).getAllByText('0.029')).toHaveLength(2)
    const perClass = section.querySelectorAll('table')[1]
    const classes = Array.from(perClass.querySelectorAll('tbody td:first-child')).map((td) => td.textContent)
    expect(classes).toEqual(['bearing.ball.deep_groove', 'ppe.helmet'])
    expect(within(section).getByText(/Snapshot from run 1 at .*; 0 decisions since/)).toBeInTheDocument()
  })

  it('renders an empty state that points at /api/metrics when no snapshot exists', () => {
    render(<EvaluationTable evaluation={null} />)
    const section = screen.getByTestId('evaluation')
    expect(within(section).getByText('No held-out scorecard recorded')).toBeInTheDocument()
    expect(within(section).getByText(/\/api\/metrics/)).toBeInTheDocument()
  })
})

describe('The savings ladder', () => {
  it('labels every rung tip in ₹ Cr with its share of the rung above, and has no legend', () => {
    render(<SavingsLadder data={savings} />)
    const section = screen.getByTestId('savings_ladder')
    expect(legendItems(section)).toHaveLength(0)
    const svg = chart(section)
    for (const v of ['₹3,319.24 Cr', '₹1,716.76 Cr', '₹355.16 Cr', '₹213.10 Cr']) {
      expect(within(svg).getByText(v)).toBeInTheDocument()
    }
    expect(within(svg).getByText('· 52%')).toBeInTheDocument()
    expect(svg.querySelectorAll('path.chart-bar')).toHaveLength(4)
  })

  it('draws the sensitivity as one whisker and explains it in the rung’s label', () => {
    render(<SavingsLadder data={savings} />)
    const section = screen.getByTestId('savings_ladder')
    const svg = chart(section)
    expect(within(svg).getByText(/at 40%–80% capture: ₹142\.07 Cr–₹284\.13 Cr/)).toBeInTheDocument()
    // The ink whisker: a line and two end ticks.
    expect(svg.querySelectorAll('line[stroke="rgb(var(--ink))"]')).toHaveLength(3)
    const table = twin(section)
    expect(table.getByText('₹3,319.24 Cr')).toBeInTheDocument()
    expect(table.getByText('52%')).toBeInTheDocument()
    expect(table.getByText(/Upper bound/)).toBeInTheDocument()
  })
})

describe('Stock age', () => {
  it('reconciles its headline with the dead-stock tile and legends its two shades', () => {
    render(<StockAge data={stockAge} />)
    const section = screen.getByTestId('stock_age')
    expect(within(section).getByText('₹1,635.33 Cr')).toBeInTheDocument()
    expect(within(section).getByText('2,106')).toBeInTheDocument()
    expect(within(section).getByText('₹890.35 Cr')).toBeInTheDocument()
    expect(within(section).getByText('1,053')).toBeInTheDocument()
    expect(legendItems(section)).toHaveLength(2)
  })

  it('draws two segments per non-empty bin, a value at every tip and the rule at the constant', () => {
    render(<StockAge data={stockAge} />)
    const section = screen.getByTestId('stock_age')
    const svg = chart(section)
    expect(svg.querySelectorAll('path.chart-bar')).toHaveLength(6)
    for (const v of ['₹3,161.09 Cr', '₹3,679.84 Cr', '₹572.33 Cr']) {
      expect(within(svg).getByText(v)).toBeInTheDocument()
    }
    expect(within(svg).getByText(/counted as dead stock: 12 months without movement/)).toBeInTheDocument()
    const table = twin(section)
    for (const n of ['4,398', '4,973', '767']) expect(table.getByText(n)).toBeInTheDocument()
    expect(within(section).getByText(/24-month rule, a different definition/)).toBeInTheDocument()
  })
})

describe('the shared formats', () => {
  it('groups crore figures the Indian way', () => {
    expect(formatRupees(16353254849.74)).toBe('₹1,635.33 Cr')
    expect(formatRupees(2130986158.26)).toBe('₹213.10 Cr')
    expect(formatRupees(250000)).toBe('₹2.50 L')
  })

  it('ends an axis on a clean number at or above the maximum', () => {
    expect(niceTicks(4616)).toEqual([0, 1000, 2000, 3000, 4000, 5000])
    expect(niceTicks(3319)).toEqual([0, 1000, 2000, 3000, 4000])
    expect(niceTicks(0)).toEqual([0])
  })
})
