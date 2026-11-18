// Types + pure helpers for M10–M13 screens (operations, insights, settings, portal). Money arrives as server strings; never computed here.
export type QuoteStatus = 'DRAFT' | 'SENT' | 'APPROVED' | 'REJECTED' | 'SUPERSEDED'
export interface Quotation {
  id: string; quotation_no: string; project_id: string; project_number: string; project_name: string; client_name: string | null; room_id: string; room_name: string
  version: number; design_version: number; grand_total: string; status: QuoteStatus; status_note: string | null; status_at: string | null; paid: string; created_at: string
}
export interface PaymentRow { id: string; boq_id: string; amount: string; received_on: string; mode: string; reference: string | null; note: string | null; user_name: string | null }
export interface PaymentSummary { quoted: string; paid: string; balance: string; schedule: { stage: string; pct: number; amount: string; received: string; status: 'PAID' | 'PART' | 'DUE' }[]; payments: PaymentRow[] }
export interface FLine { line: number; sku: string | null; description: string; category: string; unit: string; qty: number; item_id: string | null; supplier: string | null
  kind: 'MANUFACTURED' | 'BOUGHT_OUT' | 'MANUAL'; ready: number; on_order: number; booked: number; delivered: number; deliverable: number; work_orders?: number }
export interface Fulfilment { boq: Quotation; lines: FLine[]; boards: { sheets: Record<string, number>; edge_band_m: number } }
export interface POLine { id: string; item_id: string; sku: string; description: string; unit: string; qty: number; received: number; outstanding: number; rate: string; amount: string }
export interface PO { id: string; po_number: string; status: 'DRAFT' | 'ISSUED' | 'PARTIAL' | 'RECEIVED' | 'CANCELLED'; project_id: string; project_number: string; project_name: string; boq_id: string
  supplier_id: string; supplier_name: string; supplier_phone: string | null; expected_on: string | null; notes: string | null; total: string; lines_count: number; received_pct: number
  created_at: string; issued_at: string | null; lines?: POLine[] }
export interface ProcureResult { created: PO[]; allocated_from_stock: { sku: string; qty: number }[]; unassigned: string[]; manual: string[]; nothing_to_do: boolean }
export interface Panel { name: string; length: number; width: number; qty: number; thickness: number; edge_m: number }
export interface CutList { size: { length: number; depth: number; height: number }; panels: Panel[]; sheets: Record<string, { board: string; sheets: number; utilisation_pct: number }>; edge_band_m: number; basis: string }
export interface WorkOrder { id: string; wo_number: string; project_id: string; project_number: string; project_name: string; boq_id: string; sku: string | null; description: string; unit_no: number; stage: string; cut_list: CutList; updated_at: string }
export interface DeliveryNote { id: string; dn_number: string; status: 'SCHEDULED' | 'DISPATCHED' | 'DELIVERED' | 'CANCELLED'; project_id: string; project_number: string; project_name: string; boq_id: string
  scheduled_on: string | null; vehicle: string | null; driver: string | null; received_by: string | null; delivered_at: string | null; created_at: string; lines: { sku: string | null; description: string; unit: string; qty: number }[] }
export interface InstallTask { id: string; project_id: string; sku: string | null; title: string; qty: number; status: 'PENDING' | 'IN_PROGRESS' | 'DONE'; assigned_to: string | null; assigned_name: string | null; note: string | null; updated_by: string | null; updated_at: string }
export interface QCState { checks: { id: string; title: string; source: string; status: 'PENDING' | 'PASS' | 'FAIL'; note: string | null; checked_by: string | null; checked_at: string | null }[]
  snags: { id: string; check_id: string | null; title: string; status: 'OPEN' | 'FIXED'; raised_by: string | null; fixed_by: string | null; fix_note: string | null; created_at: string; fixed_at: string | null }[]
  readiness: Readiness; installed: boolean }
export interface Readiness { ready: boolean; blockers: string[]; balance_due: string }
export interface HandoverState { handover: { received_by: string; handed_over_on: string; warranty_months: number; notes: string | null; user_name: string | null } | null; readiness: Readiness }
export interface Overview { id: string; project_number: string; name: string; status: string; progress: number; archived: boolean; client_name: string | null; site_address: string | null; target_date: string | null
  stages: string[]; stage_index: number; quotations: Quotation[]; payments: PaymentSummary; procurement: { pos: number; open: number; received: number }; manufacturing: { work_orders: number; ready: number }
  delivery: { notes: number; delivered: number }; installation: { tasks: number; done: number }; qc: { checks: number; passed: number; open_snags: number }
  handover: HandoverState['handover']; timeline?: { text: string; created_at: string }[]; deliveries?: Pick<DeliveryNote, 'dn_number' | 'status' | 'scheduled_on' | 'delivered_at' | 'lines'>[] }
export interface TimelineEvent { id: string; kind: string; text: string; user_name: string | null; created_at: string }
export interface Alert { severity: 'HIGH' | 'MEDIUM' | 'LOW'; rule: string; text: string; action: string; project_id: string | null; project_number: string | null; project_name: string | null }
export interface ProjectRow { id: string; project_number: string; name: string; client_name: string | null; status: string; progress: number; archived: boolean; target_date: string | null; days_left: number | null
  quoted: string | null; paid: string | null; balance: string | null; open_snags: number; alerts: number }
export interface Dashboard { cards: Record<string, number | string | null>; stages: { stage: string; count: number }[]; lead_stages: { stage: string; count: number }[]
  projects: ProjectRow[]; alerts: Alert[]; activity: { id: string; text: string; kind: string; user_name: string | null; created_at: string; project_number: string | null }[]; money_visible: boolean }
export interface UserRow { id: string; email: string; full_name: string; role: string; is_active: boolean; phone: string | null; client_id: string | null; client_name: string | null; created_at: string | null }
export interface ContactRow { id: string; client_id: string; client_name: string | null; name: string; relation: string | null; phone: string | null; email: string | null; notes: string | null }
export interface DocRow { id: string; name: string; kind: string; category: string; status: string; size_bytes: number; room_id: string | null; created_at: string | null }

export const STAGE_LABEL: Record<string, string> = { LEAD: 'Lead', SURVEY: 'Survey', DESIGN: 'Design', QUOTATION: 'Quotation', PROCUREMENT: 'Procurement', MANUFACTURING: 'Manufacturing',
  DELIVERY: 'Delivery', INSTALLATION: 'Installation', QC: 'QC', HANDOVER: 'Handover', COMPLETED: 'Completed' }
export const WO_STAGES = ['PENDING', 'CUTTING', 'EDGEBANDING', 'ASSEMBLY', 'FINISHING', 'READY'] as const
export const ROLE_LABEL = (r: string) => r.split('_').map(w => w[0] + w.slice(1).toLowerCase()).join(' ')

/** Next quotation actions allowed from a status (mirror of the API's ALLOWED map). */
export function quoteActions(s: QuoteStatus): ('SENT' | 'APPROVED' | 'REJECTED')[] {
  return ({ DRAFT: ['SENT', 'APPROVED', 'REJECTED'], SENT: ['APPROVED', 'REJECTED'], REJECTED: ['SENT'], APPROVED: [], SUPERSEDED: [] } as const)[s].slice() as ('SENT' | 'APPROVED' | 'REJECTED')[]
}

/** Neighbouring work-order stages for the ← / → buttons. */
export function woNeighbours(stage: string): { prev: string | null; next: string | null } {
  const i = WO_STAGES.indexOf(stage as typeof WO_STAGES[number])
  return { prev: i > 0 ? WO_STAGES[i - 1] : null, next: i >= 0 && i < WO_STAGES.length - 1 ? WO_STAGES[i + 1] : null }
}

/** Compare two money strings exactly (as integer paise) — no floats. */
export function paise(s: string | null | undefined): bigint {
  const m = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec((s ?? '0').trim()); if (!m) return BigInt(0)
  const v = BigInt(m[2]) * BigInt(100) + BigInt(((m[3] ?? '') + '00').slice(0, 2)); return m[1] ? -v : v
}

export const isoDay = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export function fmtDate(s: string | null | undefined) {
  if (!s) return '—'
  const d = new Date(s.length === 10 ? s + 'T12:00:00' : (s.endsWith('Z') || s.includes('+') ? s : s + 'Z'))
  return isNaN(d.getTime()) ? s : d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

/** SVG plan scale: fit L×W mm into a box of maxW×maxH px with padding. */
export function fitScale(L: number, W: number, maxW: number, maxH: number, pad = 40) {
  const s = Math.min((maxW - 2 * pad) / Math.max(L, 1), (maxH - 2 * pad) / Math.max(W, 1))
  return { s, pad, w: L * s + 2 * pad, h: W * s + 2 * pad }
}
