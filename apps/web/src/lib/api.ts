/** The API lives on port 8000 of whatever host the site was opened from (localhost, 127.0.0.1…), unless NEXT_PUBLIC_API_URL says otherwise. */
export const apiBase = () =>
  process.env.NEXT_PUBLIC_API_URL || (typeof window !== 'undefined' ? `${window.location.protocol}//${window.location.hostname}:8000` : 'http://localhost:8000')

const TOKEN_KEY = 'iq_token'
const USER_KEY = 'iq_user'

export interface SessionUser { id: string; name: string; role: string }

// Some browsers/webviews (IDE preview panes, strict privacy modes) THROW when touching localStorage. Never let that freeze the app:
// fall back to memory (works until a full page reload) and tell the caller that nothing was persisted.
const mem: Record<string, string> = {}
const store = {
  get: (k: string): string | null => { try { return localStorage.getItem(k) } catch { return mem[k] ?? null } },
  set: (k: string, v: string): boolean => { try { localStorage.setItem(k, v); return true } catch { mem[k] = v; return false } },
  del: (k: string) => { try { localStorage.removeItem(k) } catch { /* ignore */ } delete mem[k] },
}

export const session = {
  token: () => (typeof window === 'undefined' ? null : store.get(TOKEN_KEY)),
  user: (): SessionUser | null => {
    if (typeof window === 'undefined') return null
    try { return JSON.parse(store.get(USER_KEY) || 'null') } catch { return null }
  },
  /** Returns false when the browser refused to persist (the session then lasts only until the page is reloaded). */
  save: (token: string, user: SessionUser): boolean => { const a = store.set(TOKEN_KEY, token); const b = store.set(USER_KEY, JSON.stringify(user)); return a && b },
  clear: () => { store.del(TOKEN_KEY); store.del(USER_KEY) },
  /** Can this browser actually persist data? (false in some webviews / privacy modes) */
  persistent: (): boolean => { try { localStorage.setItem('iq_probe', '1'); localStorage.removeItem('iq_probe'); return true } catch { return false } },
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

const unreachable = (base: string) =>
  `Cannot reach the API at ${base}. Start the backend (cd apps/api && uvicorn app.main:app --reload). If it is running, open this site at http://localhost:3000 — other addresses can be blocked by the browser.`

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = session.token(); const base = apiBase()
  const isUpload = init.body instanceof FormData
  const ctrl = new AbortController(); const timer = setTimeout(() => ctrl.abort(), isUpload ? 120_000 : 20_000)   // a hung request must end, not spin forever
  let res: Response
  try {
    res = await fetch(`${base}/api${path}`, {
      ...init, signal: ctrl.signal,
      headers: { ...(isUpload ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
    })
  } catch (e) {
    throw new ApiError(0, (e as Error)?.name === 'AbortError' ? `The server at ${base} did not answer in time. Check the backend terminal for errors.` : unreachable(base))
  } finally { clearTimeout(timer) }
  if (res.status === 401 && path !== '/auth/login') {
    session.clear()
    if (typeof window !== 'undefined') window.location.href = '/login'
    throw new ApiError(401, 'Session expired')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail
        : Array.isArray(j.detail) ? j.detail.map((d: { loc?: unknown[]; msg?: string }) => `${String(d.loc?.slice(-1)[0] ?? '')}: ${String(d.msg ?? '').replace(/^Value error, /, '')}`).join('; ')
        : JSON.stringify(j.detail)
    } catch {}
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: unknown) => request<T>(p, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  put: <T,>(p: string, body?: unknown) => request<T>(p, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  patch: <T,>(p: string, body?: unknown) => request<T>(p, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  delete: <T,>(p: string) => request<T>(p, { method: 'DELETE' }),
  upload: <T,>(p: string, form: FormData) => request<T>(p, { method: 'POST', body: form }),
  /** Is the backend reachable from this browser tab? (4s limit) */
  health: async (): Promise<boolean> => {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), 4000)
    try { return (await fetch(`${apiBase()}/api/health`, { signal: c.signal })).ok } catch { return false } finally { clearTimeout(t) }
  },
}

// ── Types mirroring the backend ──────────────────────────────────────────────
export interface Project { id: string; project_number: string; name: string; status: string }
export interface Room { id: string; name: string; room_type: string }
export interface Measurement { label: string; value: number; unit: string; source: string; confidence: number; verified: boolean }
export interface PlacedObject { id: string; name: string; category: string; sku?: string; x: number; y: number; length: number; width: number; height: number; price: number; z?: number }
export interface Validation { valid: boolean; errors: string[]; warnings: string[]; occupancy: number; flagged?: string[] }
export interface GenerateResult {
  requirements: { style: string; budget: number | null; priority: string[]; source?: string }
  objects: PlacedObject[]
  validation: Validation
  cost: Record<string, string>
  over_budget: boolean; budget_gap?: string | null
  kind?: string; notes?: string[]; missing?: { slot: string; label: string; required: boolean; out_of_stock: boolean; categories: string[] }[]
}
export interface DesignVersion { id: string; version: number; tier: string; is_valid: boolean; status: string }

export async function downloadFile(path: string, filename: string) {
  const res = await fetch(`${apiBase()}/api${path}`, { headers: { Authorization: `Bearer ${session.token()}` } })
  if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail } catch {} ; throw new ApiError(res.status, String(d)) }
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url)
}

export interface DesignDetail extends DesignVersion { objects: PlacedObject[]; validation: Validation | null }
export interface CatalogueItem { sku: string; name: string; category: string; length_mm: number; width_mm: number; height_mm: number; price: number; stock: number; mount_mm?: number | null; style?: string | null }

export async function fetchBlob(path: string): Promise<Blob> {
  const res = await fetch(`${apiBase()}/api${path}`, { headers: { Authorization: `Bearer ${session.token()}` } })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.blob()
}

export interface DocSummary { id: string; project_id: string; room_id: string | null; name: string; kind: string; size_bytes: number; status: string; error: string | null; provider: string | null; candidate_count: number; duplicate?: boolean }
export interface OcrCandidate { label: string | null; value_mm: number; raw: string; confidence: number; note: string | null; page: number }
export interface DocDetail extends DocSummary { pages: number | null; candidates: OcrCandidate[] }
export interface ApplyResult { results: { label: string; applied: boolean; reason: string | null }[]; applied: number; rejected: number }

export interface BoqParams { overhead_pct: string; margin_pct: string; discount_pct: string; gst_pct: string; labour_pct: string; transport: string; installation: string; gst_enabled?: boolean | string; include_takeoff?: boolean | string }
export interface BoqItem { line: number; sku: string | null; category: string; description: string; material: string | null; qty: string; unit: string; rate: string; labour: string; total: string; supplier: string | null; flags: string[] }
export interface BoqTotals { subtotal: string; overhead: string; margin: string; pre_tax: string; discount: string; after_discount: string; gst: string; grand_total: string }
export interface Boq { id: string; room_id: string; version: number; gst_enabled: boolean; include_takeoff?: boolean; design_version: number; quotation_no: string; created_at: string; params: BoqParams; totals: BoqTotals; warnings: string[]; items: BoqItem[] }
export interface BoqSummary { id: string; version: number; quotation_no: string; design_version: number; grand_total: string; warnings: number; created_at: string }

// ── CRM ──────────────────────────────────────────────────────────────────────
export interface Lead {
  id: string; name: string; phone: string | null; email: string | null; city: string | null; source: string | null; requirement: string | null
  budget: string | null; stage: string; client_id: string | null; project_id: string | null; project_number: string | null; created_at: string; updated_at: string
  assigned_to?: string | null; assigned_name?: string | null; archived?: boolean; lost_reason?: string | null; next_follow_up?: string | null; next_follow_up_kind?: string | null
  open_follow_ups?: number; follow_up_status?: 'OVERDUE' | 'TODAY' | 'UPCOMING' | 'NONE' | 'CLOSED'
}
export interface LeadActivity { id: string; kind: string; from_stage: string | null; to_stage: string | null; text: string | null; user_name: string | null; created_at: string }
export interface LeadDetail extends Lead { activity: LeadActivity[]; existing_client: { id: string; name: string } | null; follow_ups?: import('@/components/crm/followups').FollowUp[] }
export interface Client { id: string; name: string; phone: string | null; email: string | null; city: string | null; company: string | null; address: string | null; notes: string | null; gstin?: string | null; projects: number; created_at: string }
export interface ConvertResult { client_id: string; client_reused: boolean; project_id: string; project_number: string }
export interface ProjectWithClient extends Project { budget: string | null; client_id: string | null; client_name: string | null }

// ── Catalogue (M9) ─────────────────────────────────────────────────────────────
export type CatKind = 'FURNITURE' | 'MATERIAL' | 'LIGHTING' | 'HARDWARE'
export type StockStatus = 'OK' | 'LOW' | 'OUT'
export interface CatItem {
  id: string; sku: string; name: string; kind: CatKind; category: string; unit: string; price: string; stock: number; min_stock: number | null; stock_status: StockStatus
  length_mm: number | null; width_mm: number | null; height_mm: number | null; material: string | null; colour: string | null; description: string | null
  mount_mm?: number | null; style?: string | null
  supplier_id: string | null; supplier_name: string | null; is_active: boolean; updated_at: string | null
  cost_price?: string | null; margin_pct?: string | null; cost_visible?: boolean
}
export interface PriceChange { field?: 'PRICE' | 'COST'; old_price: string | null; new_price: string; reason: string; user_name: string | null; created_at: string }
export interface StockMove { delta: number; balance: number; reason: string; user_name: string | null; created_at: string }
export interface CatItemDetail extends CatItem { price_history: PriceChange[]; stock_history: StockMove[] }
export interface CatMeta { kinds: CatKind[]; units: string[]; categories: Record<CatKind, string[]>; csv_columns: string[] }
export interface Supplier {
  id: string; name: string; contact_person: string | null; phone: string | null; email: string | null; city: string | null; address: string | null
  gstin: string | null; lead_time_days: number | null; payment_terms_days?: number | null; notes: string | null; is_active: boolean; items: number; created_at: string | null
}
export interface SupplierDetail extends Supplier { item_list: CatItem[] }
export interface ImportRow { row: number; sku: string; name: string; action: 'CREATE' | 'UPDATE' | 'UNCHANGED'; changes: { field: string; from: unknown; to: unknown }[] }
export interface ImportResult { rows: ImportRow[]; errors: { row: number; sku: string | null; error: string }[]; summary: { create: number; update: number; unchanged: number; errors: number }; applied: boolean; ignored_columns: string[] }
