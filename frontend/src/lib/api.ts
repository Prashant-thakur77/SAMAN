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
}

export type LearnedOpinion = {
  probability: number
  leans: 'duplicate' | 'distinct'
  agrees_with_pipeline: boolean
  uncertainty: number
}

export type QueueResponse = {
  band: string | null
  counts: { high: number; grey: number; low: number }
  total: number
  offset: number
  order?: 'id' | 'uncertainty'
  model_available?: boolean
  tasks: TaskCard[]
}

export type QueueOrder = 'id' | 'uncertainty'

export const getQueue = (band?: string, offset = 0, limit = 25, order: QueueOrder = 'id') =>
  api.get<QueueResponse>(
    `/queues?limit=${limit}&offset=${offset}&order=${order}${band ? `&band=${band}` : ''}`,
  )

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
    } | null
    path: string
  } | null
  labels: Record<string, number>
  labels_since_training: number
  min_labels: number
  decides: false
  note: string
}

export const getLearnStatus = () => api.get<LearnStatus>('/learn/status')
export const trainModel = () => api.post<LearnStatus>('/learn/train')
export const simulateLabels = (n: number) =>
  api.post<LearnStatus & { simulated: { added: number } }>('/learn/simulate', { n })
export const CORPUS_URL = '/api/learn/corpus'

export const postDecision = (body: {
  task_id: number
  action: 'approve' | 'reject' | 'merge' | 'split'
  note?: string
  cluster_id?: number
  item_id?: number
}) => api.post<Record<string, unknown>>('/decisions', body)

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
  history: { po_date: string; unit_price: number; qty: number; vendor: string; cpse: string }[]
  last: { po_date: string; unit_price: number; vendor: string; cpse: string } | null
  trend: { from: number; to: number; change_pct: number; direction: string } | null
  price_band: { label: string } | null
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

export const getAudit = (params: { entity?: string; user?: string; action?: string; limit?: number } = {}) => {
  const query = new URLSearchParams()
  if (params.entity) query.set('entity', params.entity)
  if (params.user) query.set('user', params.user)
  if (params.action) query.set('action', params.action)
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

export type ExecutiveDashboard = {
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
  trend: { date: string; cnmcs_issued: number; cnmcs_total: number; decisions: number }[]
  inventory: {
    positions: number
    total_value: number
    dead_stock_value: number
    dead_stock_materials: number
  }
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
    items_with_variance: number
    rows: {
      cluster_id: number
      description?: string
      variance_pct: number
      lowest: { cpse: string; unit_price: number | null }
      highest: { cpse: string; unit_price: number | null }
      market_band?: { label: string } | null
    }[]
  }
  vendor_overlap: {
    items_found: number
    rows: { cluster_id: number; description?: string; vendor_count: number; cpse_count: number }[]
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
export const getOpportunity = (capture: number) =>
  api.get<OpportunityDashboard>(`/dashboard/opportunity?capture=${capture}`)

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

export type SearchResponse = {
  total: number
  offset: number
  limit: number
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
  limit?: number
  offset?: number
}) => {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
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
  rejected: { row_number: number; reason: string }[]
  samples: {
    legacy_code: string
    original: string
    normalized: string
    class_code: string
    class_confidence: number
    attrs: Record<string, unknown>
  }[]
}

export async function ingestCsv(
  file: File,
  cpseCode: string,
  dryRun: boolean,
  mapping?: Record<string, string>,
): Promise<IngestReport> {
  const form = new FormData()
  form.append('file', file)
  form.append('cpse_code', cpseCode)
  form.append('dry_run', String(dryRun))
  if (mapping) form.append('mapping', JSON.stringify(mapping))
  const res = await fetch('/api/ingest', { method: 'POST', body: form, credentials: 'include' })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as IngestReport
}

export type PipelineStatus = {
  state: string
  stage: string | null
  stages_done: string[]
  rows_done: number
  rows_total: number
  percent: number
  eta_seconds: number | null
  elapsed_seconds: number | null
  error: string | null
}

export const runPipeline = () => api.post<PipelineStatus>('/pipeline/run')
export const getPipelineStatus = () => api.get<PipelineStatus>('/pipeline/status')

export type AdminUser = {
  id: number
  email: string
  name: string
  role: Role
  cpse_code: string | null
  active: boolean
}

export const getUsers = () => api.get<{ roles: Role[]; count: number; users: AdminUser[] }>('/users')
export const createUser = (body: {
  email: string
  name: string
  role: string
  cpse_code?: string | null
}) => api.post<AdminUser>('/users', body)
export async function patchUser(id: number, body: { role?: string; active?: boolean }) {
  const res = await fetch(`/api/users/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const parsed = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(parsed?.detail ?? res.statusText), parsed)
  return parsed as AdminUser
}

export const getCpses = () => api.get<{ cpses: { code: string; name: string; items: number }[] }>('/cpses')
export const createCpse = (code: string, name: string) =>
  api.post<{ code: string; name: string }>('/cpses', { code, name })

export type HealthPanel = {
  capabilities: Health['capabilities']
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
  uom?: string
}) => api.post<SmartCreateResult>('/smart-create/check', body)

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
  const res = await fetch('/api/smart-create/scan', {
    method: 'POST',
    body: form,
    credentials: 'include',
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as SmartCreateResult
}

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
export type AssistantAction = { type: 'navigate'; to: string; label: string }
export type AssistantCitation = {
  item_id?: number
  cluster_id?: number
  cnmc?: string | null
  legacy_code?: string
  label?: string
}
export type AssistantReply = {
  kind: 'navigate' | 'answer' | 'copilot' | 'refusal' | 'unknown'
  answer: string
  action: AssistantAction | null
  citations: AssistantCitation[]
  sql?: string | null
  suggestions: string[]
  mode: string
  matched?: Record<string, unknown> | null
}
export const askAssistant = (question: string, path?: string) =>
  api.post<AssistantReply>('/assistant/query', { question, path })

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
  const res = await fetch('/api/assistant/speak', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text }),
    credentials: 'include',
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
  const res = await fetch('/api/assistant/transcribe', {
    method: 'POST',
    body: form,
    credentials: 'include',
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, String(body?.detail ?? res.statusText), body)
  return body as Transcript
}
