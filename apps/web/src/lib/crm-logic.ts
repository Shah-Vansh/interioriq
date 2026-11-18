/** Pure CRM helpers (no React, no fetch) so they can be unit-tested. Money is only FORMATTED here, never computed. */
import type { Lead } from './api'

export const STAGES = [
  { key: 'NEW', label: 'New', dot: 'bg-stone-400' },
  { key: 'CONTACTED', label: 'Contacted', dot: 'bg-blue-500' },
  { key: 'QUALIFIED', label: 'Qualified', dot: 'bg-purple-500' },
  { key: 'SITE_VISIT', label: 'Site visit', dot: 'bg-amber-500' },
  { key: 'DESIGN', label: 'Design', dot: 'bg-orange-500' },
  { key: 'QUOTATION', label: 'Quotation', dot: 'bg-cyan-500' },
  { key: 'NEGOTIATION', label: 'Negotiation', dot: 'bg-indigo-500' },
  { key: 'WON', label: 'Won', dot: 'bg-green-600' },
  { key: 'LOST', label: 'Lost', dot: 'bg-red-500' },
] as const

export type StageKey = (typeof STAGES)[number]['key']
export const stageLabel = (k: string | null | undefined) => STAGES.find(s => s.key === k)?.label ?? (k ?? '')

export function groupByStage(leads: Lead[]): Record<string, Lead[]> {
  const out: Record<string, Lead[]> = Object.fromEntries(STAGES.map(s => [s.key, [] as Lead[]]))
  for (const l of leads) (out[l.stage] ??= []).push(l)
  return out
}

/** Optimistic move: returns a NEW array with the lead's stage changed (the original is untouched so it can be restored on failure). */
export function moveLead(leads: Lead[], id: string, stage: string): Lead[] {
  return leads.map(l => (l.id === id ? { ...l, stage } : l))
}

/** Can this lead be dragged to `stage`? Mirrors the server rule (a converted lead stays Won). The server still decides. */
export function canMove(lead: Lead, stage: string): boolean {
  if (lead.stage === stage) return false
  return !(lead.project_id && stage !== 'WON')
}

/** "2200000.00" -> "₹22 L", "35000.00" -> "₹35,000". Display only. */
export function formatBudget(v: string | null | undefined): string {
  if (v == null || v === '') return ''
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  if (n >= 1e7) return `₹${trim(n / 1e7)} Cr`
  if (n >= 1e5) return `₹${trim(n / 1e5)} L`
  return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}
const trim = (x: number) => x.toFixed(2).replace(/\.?0+$/, '')

export function timeAgo(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
  if (!Number.isFinite(t)) return ''
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 60) return 'just now'
  const m = Math.round(s / 60); if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60); if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24); if (d < 30) return `${d}d ago`
  return new Date(t).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Strip empty strings so optional fields are sent as "not given" rather than "". */
export function compact<T extends Record<string, unknown>>(o: T): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => !(typeof v === 'string' && v.trim() === ''))) as Partial<T>
}
