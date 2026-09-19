/**
 * Thin fetch wrapper for the SAMAN API.
 *
 * Same-origin in dev via the Vite proxy (see vite.config.ts), so the session
 * cookie rides along with `credentials: 'include'`. No third-party client.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
    })
  } catch (cause) {
    // Backend down or unreachable — surface it as a normal API failure so the
    // UI can render an empty state instead of a blank screen.
    throw new ApiError(0, 'Cannot reach the SAMAN backend.', cause)
  }

  const body = res.headers.get('content-type')?.includes('application/json')
    ? await res.json().catch(() => null)
    : null

  if (!res.ok) {
    const message =
      (body && typeof body === 'object' && 'detail' in body && String(body.detail)) ||
      `${res.status} ${res.statusText}`
    throw new ApiError(res.status, message, body)
  }
  return body as T
}

/**
 * `fetch`, with a dead connection turned into the same ApiError the JSON
 * client raises. The endpoints below post FormData or read a blob back, so
 * they cannot go through `request` — but without this they threw a raw
 * TypeError on an unreachable backend, and every caller's fallback message
 * had to guess at what went wrong.
 */
async function sendRaw(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, { credentials: 'include', ...init })
  } catch (cause) {
    throw new ApiError(0, 'Cannot reach the SAMAN backend.', cause)
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
}

// ---- typed shapes for endpoints that exist today (M1) ----

export type TierHealth = { mode: string; engine: string; degraded: boolean }

export type Health = {
  status: string
  app: string
  long_name: string
  version: string
  offline: boolean
  capabilities: {
    linkage: TierHealth
    embedding: TierHealth
    llm: TierHealth
    /** Not a tier — an optional input to Smart-Create's camera. */
    ocr?: { mode: string; engine: string; available: boolean }
    /** Local speech-to-text for the assistant's microphone. */
    stt?: { mode: string; engine: string; available: boolean }
    sovereign_mode: boolean
    degraded: string[]
  }
}

export const getHealth = () => api.get<Health>('/health')

export type Role =
  | 'registrar'
  | 'admin'
  | 'approver'
  | 'steward'
  | 'engineer'
  | 'auditor'
  | 'viewer'

export type User = {
  id: number
  email: string
  name: string
  role: Role
  cpse_code: string | null
}

export type DemoUser = Omit<User, 'id'>

export const getDemoUsers = () => api.get<DemoUser[]>('/auth/demo-users')
export const getLoginMode = () =>
  api.get<{ demo_login: boolean; has_users: boolean }>('/auth/login-mode')
export const login = (email: string, password: string) =>
  api.post<User>('/auth/login', { email, password })
export const logout = () => api.post<{ ok: boolean }>('/auth/logout')
export const getSession = () => api.get<User | null>('/auth/session')

// ---- review workbench (§6.5) ----

export type TierScores = {
  tier0_anchor: number
  tier0_key: string | null
  tier1_fuzzy: number
  tier1_engine?: string
  tier2_semantic: number
  attribute_agreement?: number
  tier1_waterfall?: {
    engine: string
    match_probability: number
    match_weight: number
    comparison_levels: Record<string, number>
  }
}

export type AttrDiff = {
  attr: string
  role: 'identity_critical' | 'performance' | 'cosmetic'
  a: unknown
  b: unknown
  result: string
  detail: string
  agrees: boolean
}

export type ItemCard = {
  item_id: number
  normalized: string
  description: string
  legacy_code: string
  cpse: string
  plant: string | null
  class_code: string
  class_confidence: number
  class_uncertain: boolean
  mpn_norm: string | null
  gtin: string | null
  pack_qty: number
  uom_base: string | null
  cluster_id: number | null
  attrs: Record<string, unknown>
}

export type TaskCard = {
  task_id: number
  band: 'high' | 'grey' | 'low'
  state: string
  reason: string | null
  cluster_id: number | null
  pair_id?: number
  verdict?: string
  /** One deterministic sentence: why this card is here. */
  why?: string
  confidence?: number
  tier_scores?: TierScores
  veto?: { vetoed_by: { attr: string; a: unknown; b: unknown; reason: string }[] } | null
  refused_because?: string[]
  adjudication?: {
    recommendation: 'lean_merge' | 'lean_review' | 'lean_split' | 'flag_conflict'
    confidence: number
    reasons: string[]
    summary: string
    prose_by: string
    prose_note: string | null
    decides: boolean
    note: string
  } | null
  equivalence?: { basis: string; direction: string | null } | null
  route?: string
  conflict?: string
  attribute_diff?: AttrDiff[]
  agreement?: number
  items?: [ItemCard, ItemCard]
  /** The learned pairwise model's opinion. It never decides. */
  learned?: LearnedOpinion | null
  /** In the uncertainty order: why this card is on the page. */
  picked_for?: 'uncertain' | 'random' | null
}

export type LearnedOpinion = {
  probability: number
  leans: 'duplicate' | 'distinct'
  agrees_with_pipeline: boolean
  uncertainty: number
}

export type QueueFacets = {
  classes: { code: string; count: number }[]
  cpses: { id: number; code: string; count: number }[]
}

export type QueueFilters = {
  class?: string | null
  cpse?: number | null
  mine?: boolean
}

export type QueueResponse = {
  band: string | null
  counts: { high: number; grey: number; low: number }
  total: number
  offset: number
  order?: 'id' | 'uncertainty'
  filters?: QueueFilters
  facets?: QueueFacets
  model_available?: boolean
  /** How long a reviewer may take a decision back, in seconds. */
  undo_window_s?: number
  /** In the uncertainty order: how many cards are the model's doubts and how many a random sample. */
  mix?: { uncertain: number; random: number; share: number } | null
  tasks: TaskCard[]
}

export type QueueOrder = 'id' | 'uncertainty'

/** Pending tasks per band, one query; for the Home page. */
export const getQueueCounts = () =>
  api.get<{ counts: Record<string, number>; total: number }>('/queues/counts')

export const getQueue = (
  band?: string,
  offset = 0,
  limit = 25,
  order: QueueOrder = 'id',
  filters: QueueFilters = {},
) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), order })
  if (band) params.set('band', band)
  if (filters.class) params.set('class', filters.class)
  if (filters.cpse) params.set('cpse', String(filters.cpse))
  if (filters.mine) params.set('mine', 'true')
  return api.get<QueueResponse>(`/queues?${params.toString()}`)
}

// ---- learning from the Workbench ----

export type LearnStatus = {
  trained: boolean
  model: {
    trained_at: string
    n_labels: number
    labels: Record<string, number>
    features: string[]
    weights: Record<string, number>
    cv: { folds: number; auc: number | null; precision: number | null; recall: number | null }
    holdout: {
      pairs: number
      positives?: number
      model_auc: number | null
      pipeline_auc: number | null
      grey_pairs?: number
      grey_model_auc?: number | null
      grey_pipeline_auc?: number | null
      per_class?: LearnClassRow[]
    } | null
    /** "reviewer" once people's decisions alone taught it; "all" while simulated labels were needed. */
    trained_on?: 'reviewer' | 'all'
    path: string
  } | null
  labels: Record<string, number>
  /** Out-of-sample confusion matrix over reviewer labels only; null while too few. */
  reviewer_confusion?: {
    labels: number
    folds: number
    tp: number
    tn: number
    fp: number
    fn: number
    agreement: number
    note: string
  } | null
  /** Which label set the next training would use. */
  next_training_uses?: 'reviewer' | 'all'
  labels_since_training: number
  min_labels: number
  decides: false
  note: string
  load_error?: string | null
  /** The champion/challenger loop: due after N reviewer labels; simulated ones never count. */
  auto_retrain?: {
    enabled: boolean
    every: number
    labels_since: number
    due: boolean
    running?: boolean
  }
  /** Every training attempt, newest first, promoted or kept. */
  history?: RetrainAttempt[]
  /** Per-class T_HIGH suggestions: computed, shown, never applied. */
  suggestions?: ThresholdSuggestions
}

export type LearnClassRow = {
  class_code: string
  pairs: number
  positives: number
  model_auc: number | null
  pipeline_auc: number | null
  precision: number
  recall: number
}

export type RetrainAttempt = {
  ts: string
  trigger: 'auto' | 'manual' | string
  n_labels: number | null
  labels: Record<string, number>
  cv_auc: number | null
  holdout_auc: number | null
  grey_auc: number | null
  holdout_pairs: number | null
  champion_auc: number | null
  promoted: boolean
  reason: string
  last_label_id: number
  weights: Record<string, number> | null
}

export type ThresholdSuggestion = {
  class_code: string
  labelled_pairs: number
  positives: number
  suggested_t_high: number
  suggested_precision: number
  suggested_recall: number
  suggested_f1: number
  current_t_high: number
  current_precision: number
  current_recall: number
  applied: false
}

export type ThresholdSuggestions = {
  applied: false
  current_t_high: number
  min_labels: number
  classes: ThresholdSuggestion[]
  note: string
}

export const getLearnStatus = () => api.get<LearnStatus>('/learn/status')
export const trainModel = () => api.post<LearnStatus>('/learn/train')
export const simulateLabels = (n: number) =>
  api.post<LearnStatus & { simulated: { added: number } }>('/learn/simulate', { n })
export const CORPUS_URL = '/api/learn/corpus'

/** Any two rows, scored now by the pipeline's matcher; nothing stored. */
export type Comparison = {
  items: [ItemCard, ItemCard]
  verdict: string
  band: 'high' | 'grey' | 'low'
  confidence: number
  tier_scores: TierScores
  veto: TaskCard['veto']
  refused_because: string[]
  equivalence: TaskCard['equivalence']
  attribute_diff: AttrDiff[]
  agreement: number | null
  why: string
  adjudication: NonNullable<TaskCard['adjudication']>
  pipeline: { paired: boolean; verdict: string | null; pair_id: number | null; same_cluster: boolean }
  note: string
}

export const compareItems = (a: number, b: number) =>
  api.get<Comparison>(`/compare?a=${a}&b=${b}`)

export type DecisionOutcome = {
  action: string
  decision_id: number
  task_id: number
  /** ISO time until which the decision can be taken back. */
  undo_until?: string
  merged_into?: number | null
  split_into?: number
}

export const postDecision = (body: {
  task_id: number
  action: 'approve' | 'reject' | 'merge' | 'split'
  note?: string
  cluster_id?: number
  item_id?: number
  /** How long the card was on screen. */
  seconds?: number
}) => api.post<DecisionOutcome>('/decisions', body)

export type BulkOutcome = {
  action: string
  count: number
  done: DecisionOutcome[]
  skipped: { task_id: number; reason: string }[]
}

/** A page of the high or low band with one reason; one audit event per row. */
export const postBulkDecisions = (body: {
  task_ids: number[]
  action: 'approve' | 'reject'
  note?: string
}) => api.post<BulkOutcome>('/decisions/bulk', body)

export const undoDecision = (decisionId: number) =>
  api.post<{ task_id: number; restored: Record<string, unknown> }>(
    `/decisions/${decisionId}/undo`,
    {},
  )

// ---- clusters (§6.6) ----

export type Provenance = {
  field: string
  source_member_id: number | null
  rule: string
  candidates: { value: string; member_id: number; source: string }[]
}

/** A class-level public code and the level it was assigned at. */
export type StandardCode = { code: string; title: string; level: string }
export type Standards = { unspsc?: StandardCode; hsn?: StandardCode }

export type ClusterDetail = {
  cluster_id: number
  status: string
  member_count: number
  class_code: string
  standards: Standards
  golden: {
    id: number
    std_description: string
    attrs: Record<string, unknown>
    status: string
    template: string
    proposed_by: number | null
    approved_by: number | null
  } | null
  cnmc: { code: string; status: string } | null
  provenance: Provenance[]
  conflicts: { attr: string; values: string[]; blocking: boolean; note: string }[]
  members: (ItemCard & { normalized: string })[]
  standardization_delta: {
    member_id: number
    legacy: string
    golden: string
    unchanged: boolean
    tokens_added: string[]
    tokens_dropped: string[]
  }[]
}

export const getCluster = (id: number) => api.get<ClusterDetail>(`/clusters/${id}`)
export const editGolden = (id: number, std_description: string) =>
  api.post<{ std_description: string }>(`/clusters/${id}/golden`, { std_description })
export const splitMember = (id: number, item_id: number, note?: string) =>
  api.post<{ new_cluster_id: number }>(`/clusters/${id}/split`, { item_id, note })
export const mergeCluster = (id: number, source_cluster_id: number, note?: string) =>
  api.post<{ cluster_id: number }>(`/clusters/${id}/merge`, { source_cluster_id, note })
export const issueCnmc = (goldenId: number) =>
  api.post<{ code: string; already_issued: boolean }>(`/cnmc/issue/${goldenId}`)

// ---- items (§6.4) ----

export type ConsolidatedStock = {
  cluster_id: number
  cpse_count: number
  plant_count: number
  total_qty: number
  total_value: number
  positions: {
    cpse: string
    plant: string
    qty_on_hand: number
    reserved_qty: number
    available: number
    unit_value: number | null
    value: number | null
    value_withheld: boolean
    last_movement: string | null
  }[]
}

export type PurchaseTrend = {
  /** ABC class at this CPSE by 12-month consumption value; null without purchases. */
  abc?: 'A' | 'B' | 'C' | null
  orders: number
  history: {
    po_date: string
    unit_price: number
    qty: number
    vendor: string
    cpse: string
    /** Times the median of this item's other orders, when far above them. */
    anomaly?: number
  }[]
  last: { po_date: string; unit_price: number; vendor: string; cpse: string } | null
  trend: { from: number; to: number; change_pct: number; direction: string } | null
  price_band: { label: string } | null
  /** Lines flagged under the stated rule; the rule itself when any are. */
  anomalies?: number
  anomaly_rule?: string | null
}

export type ItemDetail = ItemCard & {
  golden: { id: number; std_description: string; status: string; attrs: Record<string, unknown> } | null
  cnmc: { code: string; status: string } | null
  standards: Standards
  cluster: { id: number; status: string } | null
  /** Where this material is fitted, and the VED class that follows. */
  installed_on: Installation[]
  ved: string | null
  duplicates: ItemCard[]
  equivalents: {
    counterpart: ItemCard
    relation_id: number
    rel_type: string
    direction: string
    basis: string
    confidence: number
    status: SubstituteStatus
    approval: SubstituteApproval | null
    substitutes_this: boolean
  }[]
  consolidated_stock: ConsolidatedStock | null
  purchase_history: PurchaseTrend
  visibility: { note: string; sees_attributed_prices: boolean }
}

export const getItem = (id: number) => api.get<ItemDetail>(`/items/${id}`)

// ---- equipment context and approved substitutes ----

export type Installation = {
  tag: string
  description: string
  criticality: 'A' | 'B' | 'C'
  ved: string | null
  cpse: string
  qty: number
}
export type SubstituteStatus = 'proposed' | 'approved' | 'rejected'
export type SubstituteApproval = {
  status: SubstituteStatus
  decided_by: string | null
  reason: string
  ts: string | null
}
export type SubstituteSide = {
  item_id: number
  normalized?: string
  class_code?: string
  legacy_code?: string
  description?: string
  cpse?: string
  cluster_id?: number | null
  cnmc?: string | null
  installed_on: Installation[]
  ved: string | null
}
export type SubstituteRow = {
  id: number
  rel_type: string
  direction: string
  basis: string
  confidence: number
  status: SubstituteStatus
  evidence: Record<string, unknown>
  a: SubstituteSide
  b: SubstituteSide
  approval: SubstituteApproval | null
  criticality: string
}
export type SubstitutesResponse = {
  status: string
  total: number
  offset: number
  counts: Record<SubstituteStatus, number>
  relations: SubstituteRow[]
  note: string
}

export const getSubstitutes = (status: SubstituteStatus | 'all' = 'proposed', limit = 50) =>
  api.get<SubstitutesResponse>(`/substitutes?status=${status}&limit=${limit}`)
export const decideSubstitute = (id: number, decision: 'approved' | 'rejected', reason: string) =>
  api.post<{ relation_id: number; status: SubstituteStatus; decided_by: string; reason: string }>(
    `/substitutes/${id}/decide`,
    { decision, reason },
  )

// ---- audit (§6.10) ----

export type AuditEventRow = {
  seq: number
  ts: string
  user: string
  action: string
  entity: string
  payload: Record<string, unknown>
  prev_hash: string
  hash: string
}

export type AuditResponse = {
  total: number
  offset: number
  actions: Record<string, number>
  events: AuditEventRow[]
}

export type VerifyResponse = {
  valid: boolean
  events: number
  head_seq?: number
  head_hash?: string
  voided_events?: number[]
  first_break: { seq: number; reason: string } | null
  note: string
}

export const getAudit = (
  params: { entity?: string; user?: string; action?: string; exclude?: string; limit?: number } = {},
) => {
  const query = new URLSearchParams()
  if (params.entity) query.set('entity', params.entity)
  if (params.user) query.set('user', params.user)
  if (params.action) query.set('action', params.action)
  if (params.exclude) query.set('exclude', params.exclude)
  query.set('limit', String(params.limit ?? 100))
  return api.get<AuditResponse>(`/audit?${query}`)
}
export const verifyChain = () => api.get<VerifyResponse>('/audit/verify')

// ---- dashboards (§6.7, §6.8) ----

export type Kpi = {
  key: string
  label: string
  value: number
  format?: 'percent' | 'currency'
  note?: string
}

export type QualityRate = 'classified' | 'attributes' | 'uom' | 'mpn' | 'unique' | 'active'
export type QualityRow = {
  cpse: string
  name: string
  items: number
  internal_duplicates: number
  stale_rows: number
  rates: Record<QualityRate, number>
  score: number
}
export type QualityScorecard = {
  weights: Record<QualityRate, number>
  stale_months: number
  cpses: QualityRow[]
  national: QualityRow | null
  note: string
}

export type HarmonisationPart = 'coded' | 'duplicate_pending' | 'unique_pending'

/** The donut's three parts applied per material family; sums to the donut. */
export type ByClass = {
  parts: { key: HarmonisationPart; label: string }[]
  rows: {
    class_code: string
    family: string | null
    rows: number
    coded: number
    duplicate_pending: number
    unique_pending: number
    coded_share: number
  }[]
  note: string
}

/** How many CPSEs describe each material. */
export type ByCpseCount = {
  rows: { cpses: number; materials: number; rows: number }[]
  multi_materials: number
  multi_rows: number
  internal_duplicate_rows: number
  cpses_with_rows: number
  cpses_empty: string[]
  note: string
}

export type PipelineRungKey = 'possible' | 'candidates' | 'close' | 'merged' | 'materials' | 'codes'

/** The ladder from every possible pair to issued codes; null without a run. */
export type PipelineLadder = {
  run_id: number
  run_at: string | null
  /** Incremental runs since this full run, summed; null when there are none. */
  increments: { runs: number; new_items: number; pairs_scored: number; latest: string } | null
  rungs: {
    key: PipelineRungKey
    label: string
    value: number
    unit: 'pairs' | 'materials' | 'codes'
    factor_from_previous: number | null
    aside: { label: string; value: number } | null
    note: string | null
  }[]
  blocking: {
    recall: number | null
    true_pairs: number | null
    missed: number | null
    passes: { pass: string; added: number; note: string | null }[]
  }
  source: 'run'
} | null

export type VetoRole = 'identity_critical' | 'performance'

/** Which attribute kept look-alikes apart, counted as distinct pairs. */
export type VetoAttributes = {
  source: 'run' | 'stored_pairs'
  pairs_with_veto: number
  coverage: { conflict: number; refused: number; refused_total: number }
  by_attribute: {
    attr: string
    label: string
    role: VetoRole
    pairs: number
    example: { a: string; b: string; reason: string } | null
  }[]
  other: { attributes: number; pairs: number }
  attrs_per_pair: { n: number; pairs: number }[]
  cosmetic_never_vetoes: string[]
  note: string
}

/** What is in the share of pairs the machine did not decide. */
export type HeldForReview = {
  total: number
  thresholds: { t_low: number; t_high: number }
  reasons: [
    {
      key: 'conflict'
      label: string
      pairs: number
      confidence: { min: number | null; max: number | null }
      owner_roles: string[]
      parts: [
        { key: 'identity_critical'; label: string; pairs: number; equivalence_flagged: null },
        { key: 'performance_only'; label: string; pairs: number; equivalence_flagged: number },
      ]
    },
    {
      key: 'review'
      label: string
      pairs: number
      confidence: { min: number | null; max: number | null }
      owner_roles: string[]
      parts: null
    },
  ]
  also_queued: [
    {
      band: 'high'
      reason: string
      pending: number
      done: number
      disposition: 'policy'
      evidence: { duplicate_precision: number | null; split: 'holdout' }
    },
    {
      band: 'low'
      reason: string
      pending: number
      done: number
      disposition: 'audit_sample'
      sample_of: number
    },
  ]
  decisions: {
    by_action: Record<string, number>
    total: number
    last_at: string | null
    /** Seconds a card was on screen before it was decided; null until any decision reported it. */
    seconds?: { n: number; median: number; p90: number } | null
    undone?: number
  }
  labels: { reviewer: number; simulated: number }
  note: string
}

export type EvaluationRowKey =
  | 'precision'
  | 'recall'
  | 'f1'
  | 'bcubed_f1'
  | 'blocking_recall'
  | 'veto_precision'

/** The held-out scorecard the pipeline snapshotted; null when not recorded. */
export type Evaluation = {
  run_id: number
  computed_at: string
  split: 'holdout'
  items_holdout: number
  decisions_since: number
  rows: {
    key: EvaluationRowKey
    label: string
    value: number
    target: number | null
    pass: boolean | null
    baseline: number | null
    detail: string | null
  }[]
  baseline_note: string
  per_class: {
    class_code: string
    items: number
    precision: number
    recall: number
    f1: number
    false_negatives: number
  }[]
  worst_class: string | null
  note: string
} | null

export type SavingsRungKey = 'spend' | 'shared' | 'ceiling' | 'estimate'

/** From last year's spend to the savings KPI, one rung at a time. */
export type SavingsLadder = {
  window_months: number
  capture: number
  assumption_note: string
  rungs: {
    key: SavingsRungKey
    label: string
    value_inr: number
    share_of_previous: number | null
    materials: number | null
    orders: number | null
    assumption: string | null
    sensitivity?: {
      capture_low: number
      value_low_inr: number
      capture_high: number
      value_high_inr: number
    }
  }[]
  synthetic_note: string
}

/** Stock by months since its last movement, with the dead-stock rule drawn. */
export type StockAge = {
  rule_months: number
  quality_stale_months: number
  demand_window_months: number
  bins: {
    from_months: number
    to_months: number | null
    label: string
    positions: number
    materials: number
    value_inr: number
    demand_elsewhere_value_inr: number
    no_demand_value_inr: number
    idle: boolean
  }[]
  idle: {
    value_inr: number
    positions: number
    materials: number
    demand_elsewhere_value_inr: number
    demand_elsewhere_materials: number
  }
  top_class: { class_code: string; share_of_idle_value: number } | null
  excluded_positions: number
  note: string
}

/** Where a dashboard's figures came from (cache.stamped). */
export type DashboardProvenance = {
  computed_at: string
  seconds: number
  audit_seq: number
  match_run: number
  rows: {
    items: number
    cnmcs: number
    decisions: number
    stock_rows: number
    purchases: number
    relations: number
    substitute_approvals: number
    labels: number
  }
  note: string
}

export type ExecutiveDashboard = {
  provenance?: DashboardProvenance
  kpis: Kpi[]
  per_cpse: { cpse: string; name: string; items: number; coded: number; progress: number }[]
  heatmap: {
    classes: string[]
    cpses: string[]
    peak: number
    cells: { class_code: string; cpse: string; count: number; intensity: number }[]
  }
  review: { pending: Record<string, number>; decisions_made: number }
  quality: QualityScorecard
  harmonisation: {
    total: number
    parts: { key: HarmonisationPart; label: string; value: number; note: string }[]
  }
  by_class: ByClass
  by_cpse_count: ByCpseCount
  pipeline: PipelineLadder
  veto_attributes: VetoAttributes
  held_for_review: HeldForReview
  evaluation: Evaluation
  trend: { date: string; cnmcs_issued: number; cnmcs_total: number; decisions: number }[]
  savings_ladder: SavingsLadder
  inventory: {
    positions: number
    total_value: number
    dead_stock_value: number
    dead_stock_materials: number
  }
  stock_age: StockAge
  visibility: { role: string; cpse: string | null; sees_attributed_prices: boolean; note: string }
}

export type JointTender = {
  cluster_id: number
  description?: string
  cnmc?: string | null
  cpses: string[]
  cpse_count: number
  combined_qty: number
  price_low: number
  price_high: number
  price_spread: number
  spread_pct: number
  estimated_saving: number
  per_cpse: { cpse: string; orders: number; qty: number; unit_price: number | null }[]
  market_band?: { label: string } | null
}

export type OpportunityDashboard = {
  provenance?: DashboardProvenance
  /** The purchase window the money sections were read over. */
  window?: { months: number; since: string; purchases: number }
  joint_tenders: {
    window_months: number
    capture_assumption: number
    assumption_note: string
    candidates_found: number
    total_estimated_saving: number
    candidates: JointTender[]
  }
  price_variance: {
    note: string
    /** The flagging rule in words, with its factor, so a flag is never read as a verdict. */
    anomaly_rule: string
    anomaly_factor: number
    items_with_variance: number
    items_with_anomaly: number
    rows: {
      cluster_id: number
      description?: string
      variance_pct: number
      lowest: { cpse: string; unit_price: number | null }
      highest: { cpse: string; unit_price: number | null }
      market_band?: { label: string } | null
      anomaly_count: number
      /** Only the reader's own CPSE outside registrar scope. */
      anomalies: { cpse: string; times_median: number }[]
    }[]
  }
  vendor_overlap: {
    note: string
    items_found: number
    /** Spellings folded into one company across the rows shown ("SKF INDIA LTD" + "SKF India Limited"). */
    spellings_folded: number
    rows: {
      cluster_id: number
      description?: string
      cnmc?: string | null
      vendor_count: number
      cpse_count: number
      vendors: { vendor: string; cpses: string[]; also_spelt: string[] }[]
    }[]
  }
  inventory: {
    transfers: {
      note: string
      suggestions_found: number
      total_avoided_purchase_value: number
      suggestions: {
        cluster_id: number
        description?: string
        qty: number
        avoided_purchase_value: number | null
        idle_since: string | null
        from: { cpse: string; plant: string; available: number }
        to: { cpse: string; plant: string; available: number }
      }[]
    }
    dead_stock: {
      months_without_movement: number
      materials_found: number
      total_value: number
      rows: { cluster_id: number; description?: string; qty: number; value: number }[]
    }
    totals: { positions: number; total_qty: number; total_value: number }
  }
  visibility: { note: string; sees_attributed_prices: boolean }
}

export const getExecutive = () => api.get<ExecutiveDashboard>('/dashboard/executive')
export const getOpportunity = (capture: number, months = 12) =>
  api.get<OpportunityDashboard>(`/dashboard/opportunity?capture=${capture}&months=${months}`)

// ---- copilot (§6.9) ----

export type CopilotAnswer = {
  answer: string
  citations: { cluster_id: number | null; label: string; cnmc: string | null }[]
  sql: string | null
  params: Record<string, unknown>
  rows: Record<string, unknown>[]
  template: string | null
  mode: string
  refused: boolean
  note: string | null
  llm_rejected?: string
  scope: { note: string }
  engine: string
  /** For answers grounded in the project's documents rather than a query. */
  sources?: { source: string; heading: string; score: number }[]
  /** A screen the answer points to. */
  link?: { type: 'navigate'; to: string; label: string } | null
  /** Offered when the question was outside scope, or a greeting. */
  suggestions?: string[]
}

export type CopilotSuggestions = {
  prompts: string[]
  templates: { key: string; description: string; example: string }[]
  mode: string
  sovereign_mode: boolean
  note: string
}

export const getCopilotSuggestions = () => api.get<CopilotSuggestions>('/copilot/suggestions')
export const askCopilot = (question: string) =>
  api.post<CopilotAnswer>('/copilot/query', { question })

// ---- search (§6.3) ----

export type SearchHit = {
  item_id: number
  normalized: string
  description: string
  legacy_code: string
  cpse: string
  class_code: string
  mpn_norm: string | null
  brand: string | null
  cluster_id: number | null
  cluster_size: number
  cnmc: string | null
}

export type SearchSort = 'relevance' | 'shortest' | 'newest'

export type SearchResponse = {
  total: number
  offset: number
  limit: number
  sort?: SearchSort
  /** The query as the catalogue spells it, when an abbreviation was expanded. */
  read_as?: string | null
  rewritten?: { from: string; to: string }[]
  /** A spelling the catalogue does use, when the typed one found nothing. */
  did_you_mean?: string | null
  items: SearchHit[]
}

export type Facets = {
  cpses: { code: string; name: string; items: number }[]
  classes: { class_code: string; label: string; items: number }[]
  totals: { items: number; clusters: number; cnmcs: number }
}

export const searchItems = (params: {
  search?: string
  cpse?: string
  class?: string
  has_cnmc?: boolean
  sort?: SearchSort
  limit?: number
  offset?: number
}) => {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (params.sort) query.set('sort', params.sort)
  if (params.cpse) query.set('cpse', params.cpse)
  if (params.class) query.set('class', params.class)
  if (params.has_cnmc !== undefined) query.set('has_cnmc', String(params.has_cnmc))
  query.set('limit', String(params.limit ?? 25))
  query.set('offset', String(params.offset ?? 0))
  return api.get<SearchResponse>(`/items?${query}`)
}
export const getFacets = () => api.get<Facets>('/facets')

// ---- ingest & admin (§6.11, §6.13) ----

export type IngestReport = {
  cpse_code: string
  dry_run: boolean
  rows_read: number
  rows_accepted: number
  rows_rejected: number
  duplicates_in_file: number
  already_present: number
  column_mapping: Record<string, string>
  unmapped_columns: string[]
  rejected: { row_number: number; reason: string; raw?: Record<string, string> }[]
  /** How the file was read: csv or xlsx, which sheet, and any long-text sheet joined. */
  source?: {
    format: 'csv' | 'xlsx'
    sheet?: string
    sheets?: string[]
    long_text?: { sheet: string; column: string; rows_joined: number }
  }
  samples: {
    legacy_code: string
    original: string
    normalized: string
    class_code: string
    class_confidence: number
    attrs: Record<string, unknown>
  }[]
}

export type IngestHeaders = {
  headers: string[]
  mapping: Record<string, string>
  unmapped: string[]
  rows: number
  source: NonNullable<IngestReport['source']>
}

/** The file's header row and the API's own guess at the mapping, for CSV or .xlsx. */
export async function ingestHeaders(file: File, sheet?: string): Promise<IngestHeaders> {
  const form = new FormData()
  form.append('file', file)
  if (sheet) form.append('sheet', sheet)
  const res = await sendRaw('/api/ingest/headers', { method: 'POST', body: form })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as IngestHeaders
}

export async function ingestCsv(
  file: File,
  cpseCode: string,
  dryRun: boolean,
  mapping?: Record<string, string>,
  sheet?: string,
): Promise<IngestReport> {
  const form = new FormData()
  form.append('file', file)
  form.append('cpse_code', cpseCode)
  form.append('dry_run', String(dryRun))
  if (mapping) form.append('mapping', JSON.stringify(mapping))
  if (sheet) form.append('sheet', sheet)
  const res = await sendRaw('/api/ingest', { method: 'POST', body: form })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as IngestReport
}

export type PipelineStatus = {
  state: string
  stage: string | null
  incremental?: boolean
  new_items?: number
  note?: string | null
  stages_done: string[]
  rows_done: number
  rows_total: number
  percent: number
  eta_seconds: number | null
  elapsed_seconds: number | null
  error: string | null
}

/** `incremental` scores only the rows that arrived since the last run: an onboarding upload. */
export const runPipeline = (incremental = false) =>
  api.post<PipelineStatus>(`/pipeline/run${incremental ? '?incremental=true' : ''}`)
export const getPipelineStatus = () => api.get<PipelineStatus>('/pipeline/status')

export type UserActivity = {
  sign_ins: number
  last_sign_in: string | null
  decisions: number
  last_decision: string | null
  reports_sent: number
  undos: number
}

export type AdminUser = {
  id: number
  email: string
  name: string
  role: Role
  cpse_code: string | null
  active: boolean
  /** From the audit chain and the decision table; null for an account that never signed in. */
  activity?: UserActivity | null
}

export const getUsers = () => api.get<{ roles: Role[]; count: number; users: AdminUser[] }>('/users')
export const createUser = (body: {
  email: string
  name: string
  role: string
  cpse_code?: string | null
}) => api.post<AdminUser>('/users', body)
export async function patchUser(id: number, body: { role?: string; active?: boolean }) {
  const res = await sendRaw(`/api/users/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const parsed = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(parsed?.detail ?? res.statusText), parsed)
  return parsed as AdminUser
}

export type CpseRow = { code: string; name: string; items: number; contact_email: string | null }

export const getCpses = () => api.get<{ cpses: CpseRow[] }>('/cpses')
export const createCpse = (code: string, name: string) =>
  api.post<{ code: string; name: string }>('/cpses', { code, name })
export async function patchCpse(code: string, body: { name?: string; contact_email?: string | null }) {
  const res = await sendRaw(`/api/cpses/${code}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const parsed = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(parsed?.detail ?? res.statusText), parsed)
  return parsed as { code: string; name: string; contact_email: string | null }
}

// ---- per-CPSE catalogue report ----

export type ReportListing = {
  delivery: 'smtp' | 'outbox'
  outbox_dir: string | null
  cpses: {
    code: string
    name: string
    contact_email: string | null
    items: number
    last_sent: { at: string | null; mode: string | null; to: string[] } | null
  }[]
}

export type ReportSendResult = {
  mode: 'smtp' | 'outbox'
  host: string | null
  path: string | null
  cpse: string
  to: string[]
  sha256: string
  sent_at: string
  note: string
}

export const getReports = () => api.get<ReportListing>('/reports')
/** The printable page, for a new tab. */
export const reportHtmlUrl = (code: string) => `/api/reports/cpse/${code}?format=html`
/** Every CPSE on one page for the reader above them; money as a quarter among peers. */
export const rollupHtmlUrl = '/api/reports/rollup?format=html'
export const sendReport = (code: string, to: string[] | null = null) =>
  api.post<ReportSendResult>(`/reports/cpse/${code}/send`, { to })

export type RunsWhereRow = {
  engine: string
  version: string | null
  /** 'local' (this process), 'browser' (the user's device) or 'remote · host'. */
  where: string
  used_for: string
  available: boolean
}

export type HealthPanel = {
  capabilities: Health['capabilities']
  /** Each engine, its version and where it runs. */
  runs_where?: RunsWhereRow[]
  sovereign_mode: boolean
  ollama_configured: boolean
  database: string
  counts: Record<string, number>
  smart_create: SmartCreateStats
  visibility_policy: {
    summary: string
    rules: { who: string; sees: string; withheld: string }[]
    enforced_in: string
  }
  audit: VerifyResponse
}

export const getHealthPanel = () => api.get<HealthPanel>('/settings/health')
export const setSovereign = (enabled: boolean) =>
  api.post<{ sovereign_mode: boolean; note: string }>('/settings/sovereign', { enabled })

// ---- demo snapshot (§8A) ----

export type SnapshotStatus = {
  exists: boolean
  files: string[]
  bytes: number
  taken_at: string | null
  directory: string
}

export type SnapshotResult = { files: string[]; bytes: number; seconds: number; note?: string }

export const getSnapshot = () => api.get<SnapshotStatus>('/settings/snapshot')
export const takeSnapshot = () => api.post<SnapshotResult>('/settings/snapshot', {})
export const restoreSnapshot = () => api.post<SnapshotResult>('/settings/snapshot/restore', {})

// ---- ERP migration (§2C, §6.12) ----

export type MigrationChange = {
  matnr: string
  cpse: string
  legacy_code: string
  cluster_id: number
  cnmc: string
  action: 'crossref' | 'block'
  surviving_matnr: string | null
  impact: 'safe' | 'open_transactions' | 'valuation_conflict'
  open_po_lines: number
  open_qty: number
  stock_qty: number
  total_value: number | null
  price_withheld?: boolean
  before: Record<string, string>
  after?: Record<string, string>
  diff?: Record<string, { before: string | null; after: string | null }>
  will_apply?: boolean
}

export type MigrationPlan = {
  clusters: number
  changes: MigrationChange[]
  summary: {
    total: number
    crossref: number
    block: number
    safe: number
    held_open_transactions: number
    valuation_conflict: number
  }
  thresholds?: { valuation_conflict_value: number; note: string }
  visibility?: { role: string; cpse: string | null; sees_attributed_prices: boolean }
  would_apply?: number
  would_hold?: number
  total_changes?: number
  offset?: number
  limit?: number
  truncated?: boolean
  erp_fingerprint?: string
  note: string
}

export type ErpAdapterStatus = {
  requested: string
  mode: 'mock' | 'rfc'
  engine: string
  degraded: boolean
  note: string
}

export const LOADFILES_URL = '/api/migration/loadfiles'

export type ErpState = {
  adapter: ErpAdapterStatus
  system: string
  database: string
  counts: Record<string, number>
  materials_blocked: number
  materials_cross_referenced: number
  fingerprint: string
  sample: { matnr: string; lvorm: string; zz_cnmc: string; zz_supersedes: string }[]
  note: string
}

export type MigrationBatch = { id: number; status: string; ts: string; changes: number }

export type BatchDetail = {
  id: number
  status: string
  ts: string
  changes: {
    erp_table: string
    erp_key: string
    state: string
    before: Record<string, string>
    after: Record<string, string> | null
  }[]
  verification: { checked: number; in_sync: boolean; drifted: unknown[] }
}

export const getErpState = () => api.get<ErpState>('/migration/erp')
export const migrationDryRun = (
  clusterIds?: number[],
  page: { limit?: number; offset?: number } = {},
) =>
  api.post<MigrationPlan>('/migration/dryrun', {
    cluster_ids: clusterIds ?? null,
    ...page,
  })
export const migrationApply = (clusterIds?: number[], includeHeld = false) =>
  api.post<{ batch_id: number; applied: number; held: number }>('/migration/apply', {
    cluster_ids: clusterIds ?? null,
    include_held: includeHeld,
  })
export const migrationRollback = (batchId: number) =>
  api.post<{ batch_id: number; restored: number }>(`/migration/rollback/${batchId}`)
export const getMigrationBatches = () =>
  api.get<{ batches: MigrationBatch[] }>('/migration/batches')
export const getBatchDetail = (id: number) => api.get<BatchDetail>(`/migration/batches/${id}`)

// ---- Smart-Create: duplicate prevention at source (§5) ----

export type SmartCreateMatch = {
  item_id: number
  confidence: number
  band: string
  verdict: string
  description: string
  cpse: string | null
  cnmc: string | null
  class_code: string
  tier_scores: Record<string, unknown>
  veto: Record<string, unknown> | null
  why: string
  /**
   * On an interchangeable part only: the engineer's decision on the
   * equivalence between it and the existing record the check found.
   */
  approval?: SmartCreateApproval
}

export type SmartCreateApproval = {
  status: 'approved' | 'proposed' | 'rejected' | 'none'
  relation_id?: number
  with_item_id?: number
  decided_by?: string | null
  reason?: string | null
  ts?: string | null
  note?: string
}

export type SmartCreateResult = {
  check_id: number
  probe: {
    norm_text: string
    class_code: string
    class_confidence: number
    mpn_norm: string | null
    gtin: string | null
    uom_base: string | null
    pack_qty: number | null
    attrs: Record<string, string | number>
  }
  suggestions: SmartCreateMatch[]
  equivalents: SmartCreateMatch[]
  ruled_out: SmartCreateMatch[]
  recommendation: {
    action: 'reuse' | 'review' | 'create'
    reason: string
    override_requires_reason: boolean
  }
  create_token: string
  token_expires_in: number
  /** Present only when the description came from a photographed marking. */
  ocr?: OcrReading
  scanned?: boolean
  retake?: boolean
}

export type OcrReading = {
  engine: string
  text: string
  lines: { text: string; confidence: number; uncertain: boolean }[]
  mean_confidence: number
  uncertain_lines: number
  seconds: number
}

export type SmartCreateStats = {
  checks: number
  prevented: number
  created_anyway: number
  open: number
  prevention_rate: number | null
  note: string
}

export const smartCreateCheck = (body: {
  description: string
  mpn?: string
  /** The barcode on the box; its check digit is verified server-side. */
  gtin?: string
  uom?: string
}) => api.post<SmartCreateResult>('/smart-create/check', body)

// ---- drafts: a request saved before it is decided ----

export type SmartCreateDraft = {
  id: number
  created_at: string
  updated_at: string
  description: string
  mpn: string | null
  gtin: string | null
  uom: string | null
  note: string | null
  status: 'draft' | 'submitted' | 'discarded'
  last_check_id: number | null
  top_confidence: number | null
  candidates: number | null
}

export const getDrafts = () => api.get<{ drafts: SmartCreateDraft[] }>('/smart-create/drafts')
export const saveDraft = (body: {
  description: string
  mpn?: string
  gtin?: string
  uom?: string
  note?: string
  check_id?: number
}) => api.post<SmartCreateDraft>('/smart-create/drafts', body)
export const setDraftStatus = (id: number, status: 'submitted' | 'discarded') =>
  request<SmartCreateDraft>(`/smart-create/drafts/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })

export const smartCreateReuse = (check_id: number, item_id: number) =>
  api.post<{ check_id: number; outcome: string; reused_item_id: number }>(
    '/smart-create/reuse',
    { check_id, item_id },
  )

export const smartCreateCreate = (body: {
  create_token: string
  legacy_code: string
  description: string
  uom?: string
  reason?: string
}) =>
  api.post<{ outcome: string; raw_item_id: number; legacy_code: string; note: string }>(
    '/smart-create/create',
    body,
  )

export const getSmartCreateStats = () => api.get<SmartCreateStats>('/smart-create/stats')

export async function smartCreateScan(file: File, uom?: string): Promise<SmartCreateResult> {
  const form = new FormData()
  form.append('file', file)
  if (uom) form.append('uom', uom)
  const res = await sendRaw('/api/smart-create/scan', {
    method: 'POST',
    body: form,
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as SmartCreateResult
}

// ---- Scan: what a barcode, a label or a nameplate names ----

export type ScanMember = {
  item_id: number
  cpse: string
  legacy_code: string
  description: string
  mpn: string | null
  gtin: string | null
  /** True for the catalogue row the scanned code hit directly. */
  scanned: boolean
}

export type ScanPosition = {
  cpse: string
  plant: string
  qty_on_hand: number
  reserved_qty: number
  available: number
  unit_value: number | null
  value: number | null
  value_withheld: boolean
  last_movement: string | null
}

export type ScanInstallation = {
  tag: string
  description: string
  criticality: 'A' | 'B' | 'C'
  ved: string | null
  cpse: string
  qty: number
}

export type ScanSubstitute = {
  relation_id: number
  rel_type: 'equivalent' | 'supersedes'
  direction: string | null
  status: 'proposed' | 'approved' | 'rejected'
  confidence: number
  other: {
    item_id: number
    normalized?: string
    class_code?: string
    legacy_code?: string
    description?: string
    cpse?: string
    cluster_id?: number
    cnmc?: string | null
  }
  approval: {
    status: string
    decided_by: string | null
    reason: string | null
    ts: string | null
  } | null
}

export type ScanMaterial = {
  cluster_id: number | null
  golden_id: number | null
  cnmc: string | null
  status: string | null
  std_description: string | null
  class_code: string
  family: string | null
  attrs: Record<string, unknown>
  members: ScanMember[]
  cpses: string[]
  stock: {
    cluster_id: number
    cpse_count: number
    plant_count: number
    total_qty: number
    total_value: number
    positions: ScanPosition[]
  } | null
  installed_on: ScanInstallation[]
  ved: string | null
  substitutes: ScanSubstitute[]
}

export type ScanSpare = {
  item_id: number
  cluster_id: number | null
  cnmc: string | null
  legacy_code: string
  description: string
  class_code: string
  qty_fitted: number
  stock_here: number
  stock_elsewhere: number
  cpses_elsewhere: number
}

/** A tag plate: the equipment at one CPSE that carries it, with its spares. */
export type ScanEquipment = {
  id: number
  tag: string
  description: string
  criticality: 'A' | 'B' | 'C'
  ved: string | null
  cpse: string
  spares: ScanSpare[]
}

export type ScanResult = {
  query: string
  /** How the code resolved, in the order the server tries them. */
  matched_by: 'cnmc' | 'legacy_code' | 'gtin' | 'mpn' | 'bin' | 'equipment_tag' | null
  /** What was tried when nothing matched; 'cnmc' means the check digit failed. */
  tried: string | null
  /** 0, 1, or several (a part number shared by variants). */
  materials: ScanMaterial[]
  /** The plant carrying the tag, own CPSE first; empty unless matched by a tag. */
  equipment: ScanEquipment[]
  /** Attribute keys on which several materials differ; empty for 0 or 1. */
  differs_on: string[]
  /** One sentence for the reader. Always shown. */
  note: string
  next: {
    action: 'open_cluster' | 'open_item' | 'choose' | 'choose_site' | 'smart_create' | 'none'
    to: string | null
  }
}

export const scanLookup = (code: string) =>
  api.get<ScanResult>('/scan/lookup?code=' + encodeURIComponent(code))

/** "Wrong item?": the scan resolved, but the part in hand is not the one on screen. */
// ---- stock take: scan, count, next; bins bound to materials ----

export type CountLine = {
  id: number
  counted_at: string
  plant: string
  bin_code: string | null
  code: string
  matched_by: string | null
  cluster_id: number | null
  item_id: number | null
  legacy_code: string | null
  description: string | null
  cpse: string | null
  counted_qty: number
  system_qty: number | null
  variance: number | null
  note: string | null
}

export type CountSession = {
  session_id: string
  lines: CountLine[]
  totals: {
    lines: number
    counted: number
    system: number
    over: number
    short: number
    exact: number
    unknown_to_system: number
  }
  note: string
}

export const getPlants = () => api.get<{ plants: string[]; note?: string }>('/scan/plants')
export const postCount = (body: {
  session_id: string
  code: string
  counted_qty: number
  plant: string
  bin_code?: string
  note?: string
}) => api.post<CountLine>('/scan/count', body)
export const getCountSession = (id: string) =>
  api.get<CountSession>(`/scan/count/${encodeURIComponent(id)}`)

export type BinRow = {
  bin_code: string
  plant: string
  cluster_id: number | null
  item_id: number
  legacy_code: string | null
  description: string | null
  replaced?: boolean
}
export const bindBin = (body: { plant: string; bin_code: string; code: string }) =>
  api.post<BinRow>('/scan/bins', body)

export const reportWrongItem = (body: {
  code: string
  matched_by?: string | null
  cluster_id?: number | null
  item_id?: number | null
  cnmc?: string | null
  note?: string
}) => api.post<{ recorded: boolean; seq: number; note: string }>('/scan/report', body)

// ---- PPRL restricted mode (§5, M10) ----

export type PprlEncoding = { ref: string; bloom: string }

export type PprlPayload = {
  cpse: string
  mode: string
  records: number
  filter_bits: number
  hashes_per_feature: number
  encodings: PprlEncoding[]
  note: string
}

export type PprlReport = {
  left_records: number
  right_records: number
  comparisons: number
  overlap_records_left: number
  overlap_records_right: number
  overlap_pct_left: number
  overlap_pct_right: number
  possible_matches: number
  mode: string
  threshold: number
  report_threshold: number
  matches: { left_ref: string; right_ref: string; dice: number; verdict: string }[]
  truncated: boolean
  note: string
}

export type PprlModes = {
  default: string
  modes: Record<
    string,
    { bits: number; hashes: number; threshold: number; report: number; description: string }
  >
}

export type PprlEvaluation = {
  mode: string
  pair: string
  truth_pairs: number
  predicted_pairs: number
  precision: number
  recall: number
  f1: number
  threshold: number
}

export const getPprlKey = () => api.get<{ key: string; note: string }>('/pprl/key')
export const getPprlModes = () => api.get<PprlModes>('/pprl/modes')
export const pprlEncode = (body: { cpse: string; key: string; mode: string; limit: number }) =>
  api.post<PprlPayload>('/pprl/encode', body)
export const pprlCompare = (body: {
  left: PprlEncoding[]
  right: PprlEncoding[]
  mode: string
}) => api.post<PprlReport>('/pprl/compare', body)
export const pprlEvaluate = (left: string, right: string, mode: string) =>
  api.get<PprlEvaluation>(
    `/pprl/evaluate?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}&mode=${mode}`,
  )

// ---- First-run bootstrap (§8A) ----

export type BootstrapStatus = {
  empty: boolean
  users: number
  cpses: number
  raw_items: number
  profile: string
  pipeline: PipelineStatus
}

export const getBootstrapStatus = () => api.get<BootstrapStatus>('/bootstrap/status')
export const loadDemoData = () =>
  api.post<{ started: boolean; profile: string; note: string }>('/bootstrap/demo-data', {})

// ---- the floating assistant ----
export type AssistantAction = {
  type: 'navigate'
  to: string
  label: string
  /** For a visitor: the screen to open once they have signed in. */
  then?: string
}
export type AssistantCitation = {
  item_id?: number
  cluster_id?: number
  cnmc?: string | null
  legacy_code?: string
  label?: string
}
export type AssistantReply = {
  /** `stream`: the answer is coming from the model; read it with `streamAssistant`. */
  kind: 'navigate' | 'answer' | 'copilot' | 'refusal' | 'unknown' | 'stream'
  answer: string
  action: AssistantAction | null
  citations: AssistantCitation[]
  sql?: string | null
  suggestions: string[]
  mode: string
  matched?: Record<string, unknown> | null
}
export type AssistantTurn = { role: 'user' | 'assistant'; text: string }

export const askAssistant = (
  question: string,
  path?: string,
  stream = false,
  history: AssistantTurn[] = [],
) => api.post<AssistantReply>('/assistant/query', { question, path, stream, history })

export type AssistantSource = { source: string; heading: string; score: number }

/** The passage behind a citation, verbatim. */
export const getPassage = (source: string, heading: string) =>
  api.get<{ source: string; heading: string; text: string }>(
    `/assistant/passage?source=${encodeURIComponent(source)}&heading=${encodeURIComponent(heading)}`,
  )

export type StreamEvent =
  | { type: 'sources'; sources: { source: string; heading: string; score: number }[] }
  | { type: 'delta'; text: string }
  | {
      type: 'done'
      accepted: boolean
      text: string
      reason?: string
      note?: string
      sources?: { source: string; heading: string; score: number }[]
      /** What the assistant says instead when the model's words were refused. */
      fallback?: AssistantReply
    }

/**
 * The model's answer a checked sentence at a time (server-sent events).
 * Resolves with the `done` event; `onEvent` sees every event as it arrives.
 * Returns a function that abandons the stream.
 */
export function streamAssistant(
  question: string,
  path: string | undefined,
  onEvent: (event: StreamEvent) => void,
  history: AssistantTurn[] = [],
): { done: Promise<StreamEvent & { type: 'done' }>; cancel: () => void } {
  const params = new URLSearchParams({ q: question })
  if (path) params.set('path', path)
  if (history.length) params.set('h', JSON.stringify(history))
  const source = new EventSource(`/api/assistant/stream?${params.toString()}`, {
    withCredentials: true,
  })
  let settle: (value: StreamEvent & { type: 'done' }) => void = () => {}
  let fail: (reason: unknown) => void = () => {}
  const done = new Promise<StreamEvent & { type: 'done' }>((resolve, reject) => {
    settle = resolve
    fail = reject
  })
  source.onmessage = (message) => {
    let event: StreamEvent
    try {
      event = JSON.parse(message.data) as StreamEvent
    } catch {
      return
    }
    onEvent(event)
    if (event.type === 'done') {
      source.close()
      settle(event)
    }
  }
  source.onerror = () => {
    source.close()
    fail(new ApiError(0, 'The answer stream was interrupted.'))
  }
  return { done, cancel: () => source.close() }
}

export type Transcript = {
  text: string
  language?: string | null
  duration?: number
  confidence?: number
  engine?: string
  note?: string
}
export type VoiceStatus = {
  available: boolean
  mode: string
  engine: string
  languages: string[]
  note: string
  tts?: { available: boolean; mode: string; engine: string; note: string }
}
export const getVoice = () => api.get<VoiceStatus>('/assistant/voice')
/** One reply as a WAV, synthesised on the server. */
export async function speakText(text: string): Promise<Blob> {
  const res = await sendRaw('/api/assistant/speak', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  }
  return res.blob()
}
/** One spoken utterance as a PCM WAV blob, transcribed on the server. */
export async function transcribeAudio(wav: Blob, language?: string): Promise<Transcript> {
  const form = new FormData()
  form.append('audio', wav, 'question.wav')
  if (language) form.append('language', language)
  const res = await sendRaw('/api/assistant/transcribe', {
    method: 'POST',
    body: form,
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as Transcript
}

// ---- automatic code issue under a registrar's policy ----

export type AutoIssueFamily = {
  family: string
  classes: string[]
  enabled: boolean
  min_precision: number
  set_by: number | null
  set_at: string | null
  /** The lowest held-out precision among the family's classes; null without a snapshot. */
  precision: number | null
  eligible: number
}

export type AutoIssueStatus = {
  families: AutoIssueFamily[]
  eligible: number
  not_eligible: Record<string, number>
  has_snapshot: boolean
  issued_under_policy: number
  default_min_precision: number
}

export type AutoIssueRun = {
  dry_run: boolean
  eligible: number
  issued: { cluster_id: number; family: string; code: string | null; std_description: string; members: number }[]
  skipped: { cluster_id: number; reason: string }[]
  not_eligible: Record<string, number>
  note: string
}

export const getAutoIssue = () => api.get<AutoIssueStatus>('/autoissue/status')
export const setAutoIssuePolicy = (family: string, enabled: boolean, min_precision: number) =>
  request<{ family: string; enabled: boolean; min_precision: number }>(
    `/autoissue/policy/${family}`,
    { method: 'PUT', body: JSON.stringify({ enabled, min_precision }) },
  )
export const runAutoIssue = (dry_run: boolean, family?: string) =>
  api.post<AutoIssueRun>('/autoissue/run', { dry_run, family })

// ---- attachments on a golden record ----

export type Attachment = {
  id: number
  filename: string
  content_type: string
  size: number
  sha256: string
  kind: string
  note: string | null
  uploaded_by: string
  uploaded_at: string
}

export type AttachmentListing = {
  golden_id: number
  attachments: Attachment[]
  kinds: string[]
  accepts: string[]
  max_bytes: number
}

export const getAttachments = (clusterId: number) =>
  api.get<AttachmentListing>(`/clusters/${clusterId}/attachments`)

export async function addAttachment(
  clusterId: number,
  file: File,
  kind: string,
  note?: string,
): Promise<{ attached: number; attachments: Attachment[] }> {
  const form = new FormData()
  form.append('file', file)
  form.append('kind', kind)
  if (note) form.append('note', note)
  const res = await sendRaw(`/api/clusters/${clusterId}/attachments`, { method: 'POST', body: form })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as { attached: number; attachments: Attachment[] }
}

export const attachmentUrl = (id: number) => `/api/clusters/attachments/${id}/file`

export const voidAttachment = (id: number, reason?: string) =>
  request<{ voided: number }>(
    `/clusters/attachments/${id}${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`,
    { method: 'DELETE' },
  )

// ---- the house abbreviation dictionary ----

export type HouseWord = {
  id: number
  token: string
  expansion: string
  cpse: string | null
  note: string | null
  added_by: string
  added_at: string
  overrides_built_in: string | null
}

export type HouseWords = { built_in: number; house: HouseWord[]; note: string }

export const getAbbreviations = (cpse?: string) =>
  api.get<HouseWords>(`/abbreviations${cpse ? `?cpse=${encodeURIComponent(cpse)}` : ''}`)
export const addAbbreviation = (body: { token: string; expansion: string; cpse_code?: string; note?: string }) =>
  api.post<HouseWords & { added: number }>('/abbreviations', body)
export const retireAbbreviation = (id: number) =>
  request<{ retired: number }>(`/abbreviations/${id}`, { method: 'DELETE' })
export const previewAbbreviations = (description: string, cpse_code?: string) =>
  api.post<{ description: string; built_in_only: string; with_house_words: string; changed: boolean }>(
    '/abbreviations/preview',
    { description, cpse_code },
  )
