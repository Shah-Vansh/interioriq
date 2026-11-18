'use client'
// Small shared UI kit so every real screen looks and behaves the same (errors in role=alert, success in role=status, Esc closes drawers).
import { useCallback, useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api, ApiError, Project, session } from '@/lib/api'
import { cn } from '@/lib/utils'

export const input = 'w-full text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400 disabled:bg-stone-50 disabled:text-stone-500'
export const ctl = input.replace('w-full ', '')
const base = 'inline-flex items-center justify-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap'
export const btn = { primary: base + ' bg-amber-700 hover:bg-amber-800 text-white', ghost: base + ' border border-stone-200 bg-white hover:bg-stone-50 text-stone-700',
  danger: base + ' border border-red-200 bg-white hover:bg-red-50 text-red-700', small: 'inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded border border-stone-200 bg-white hover:bg-stone-50 text-stone-700 disabled:opacity-40' }
export const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Something went wrong')

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: React.ReactNode; children?: React.ReactNode }) {
  return <div className="flex items-end justify-between gap-3 flex-wrap"><div><h1 className="text-xl font-semibold text-stone-900">{title}</h1>
    {subtitle && <p className="text-sm text-stone-500 mt-0.5 max-w-3xl">{subtitle}</p>}</div>{children && <div className="flex gap-2 items-center flex-wrap">{children}</div>}</div>
}
export const Alert = ({ children }: { children: React.ReactNode }) => <p role="alert" className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{children}</p>
export const Ok = ({ children }: { children: React.ReactNode }) => <p role="status" className="text-xs text-green-800 bg-green-50 border border-green-200 rounded px-3 py-2">{children}</p>
export const Card = ({ title, children, className, right }: { title?: React.ReactNode; children: React.ReactNode; className?: string; right?: React.ReactNode }) => (
  <section className={cn('bg-white border border-stone-200 rounded-lg shadow-sm', className)}>
    {title && <div className="px-4 py-3 border-b border-stone-100 flex items-center justify-between gap-2"><h2 className="text-sm font-semibold text-stone-800">{title}</h2>{right}</div>}
    <div className="p-4">{children}</div></section>)
export const Empty = ({ children }: { children: React.ReactNode }) => <p className="p-6 text-center text-sm text-stone-400">{children}</p>
export const Field = ({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) => (
  <label className={cn('block', className)}><span className="block text-[11px] font-medium text-stone-500 mb-1">{label}</span>{children}</label>)

const TONES: Record<string, string> = {
  green: 'bg-green-50 text-green-800', amber: 'bg-amber-50 text-amber-800', red: 'bg-red-50 text-red-700', blue: 'bg-blue-50 text-blue-800', stone: 'bg-stone-100 text-stone-600', violet: 'bg-violet-50 text-violet-800' }
const STATUS_TONE: Record<string, string> = { APPROVED: 'green', PAID: 'green', RECEIVED: 'green', DELIVERED: 'green', DONE: 'green', PASS: 'green', READY: 'green', FIXED: 'green', COMPLETED: 'green', OK: 'green',
  SENT: 'blue', ISSUED: 'blue', DISPATCHED: 'blue', IN_PROGRESS: 'blue', PART: 'amber', PARTIAL: 'amber', SCHEDULED: 'amber', PENDING: 'stone', DRAFT: 'stone', DUE: 'stone',
  REJECTED: 'red', CANCELLED: 'red', FAIL: 'red', OPEN: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'blue', SUPERSEDED: 'stone' }
export function Pill({ s, label, tone }: { s?: string; label?: string; tone?: string }) {
  const t = tone ?? STATUS_TONE[s ?? ''] ?? 'violet'
  return <span data-status={s} className={cn('inline-block text-[11px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap', TONES[t])}>{label ?? (s ?? '').replace(/_/g, ' ')}</span>
}

export function Drawer({ label, title, onClose, children, wide }: { label: string; title: React.ReactNode; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-stone-900/30" onClick={onClose}>
      <div role="dialog" aria-label={label} className={cn('w-full h-full bg-white shadow-xl flex flex-col', wide ? 'max-w-3xl' : 'max-w-lg')} onClick={e => e.stopPropagation()}>
        <div className="h-14 px-5 flex items-center justify-between border-b border-stone-200 shrink-0"><h2 className="text-sm font-semibold text-stone-900 truncate">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-stone-100"><X className="w-4 h-4 text-stone-500" /></button></div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">{children}</div>
      </div>
    </div>)
}

export function Table({ head, children, right = [] }: { head: string[]; children: React.ReactNode; right?: number[] }) {
  return <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-stone-100 bg-stone-50">
    {head.map((h, i) => <th key={h + i} className={cn('text-[11px] font-medium text-stone-400 uppercase tracking-wide px-4 py-2.5', right.includes(i) ? 'text-right' : 'text-left')}>{h}</th>)}</tr></thead>
    <tbody className="divide-y divide-stone-50">{children}</tbody></table></div>
}

/** Fetch helper: data, error, reload. */
export function useLoad<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState('')
  const latest = useRef(path); latest.current = path       // a slow answer for an old path (e.g. a tab clicked away from) must not overwrite the new one
  const reload = useCallback(() => {
    if (!path) { setData(null); return Promise.resolve() }
    return api.get<T>(path).then(d => { if (latest.current === path) { setData(d); setError('') } }).catch(e => { if (latest.current === path) setError(errMsg(e)) })
  }, [path]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload() }, [reload, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, reload, setData }
}

/** Run an action with busy/error/ok state. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null); const [error, setError] = useState(''); const [ok, setOk] = useState('')
  const run = async (key: string, fn: () => Promise<unknown>, success?: string) => {
    setBusy(key); setError(''); setOk('')
    try { await fn(); if (success) setOk(success); return true } catch (e) { setError(errMsg(e)); return false } finally { setBusy(null) }
  }
  return { busy, error, ok, run, setError, setOk }
}

export function useRole() {
  const [role, setRole] = useState<string | null>(null)
  useEffect(() => { setRole(session.user()?.role ?? null) }, [])
  return role
}
export const hasRole = (role: string | null, allowed: readonly string[]) => !!role && (role === 'SUPER_ADMIN' || allowed.includes(role))

/** Project picker that remembers the last choice per browser tab (sessionStorage, guarded). */
export function ProjectPicker({ value, onChange, filter }: { value: string; onChange: (id: string) => void; filter?: (p: Project & { archived?: boolean }) => boolean }) {
  const [projects, setProjects] = useState<(Project & { archived?: boolean })[]>([])
  useEffect(() => {
    api.get<(Project & { archived?: boolean })[]>('/projects').then(ps => {
      const list = filter ? ps.filter(filter) : ps; setProjects(list)
      if (!value && list.length) {
        let saved = ''; try { saved = sessionStorage.getItem('iq_project') ?? '' } catch { /* storage blocked */ }
        onChange(list.some(p => p.id === saved) ? saved : list[0].id)
      }
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return <select aria-label="Project" value={value} onChange={e => { try { sessionStorage.setItem('iq_project', e.target.value) } catch { /* ignore */ } onChange(e.target.value) }} className={ctl + ' min-w-64'}>
    {projects.length === 0 && <option value="">No projects yet</option>}
    {projects.map(p => <option key={p.id} value={p.id}>{p.project_number} · {p.name}</option>)}</select>
}

export function Stat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: 'red' | 'amber' | 'green' }) {
  return <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4"><p className="text-[11px] uppercase tracking-wide text-stone-400 font-medium">{label}</p>
    <p data-testid={`stat-${label}`} className={cn('text-2xl font-semibold mt-1', tone === 'red' ? 'text-red-700' : tone === 'amber' ? 'text-amber-800' : tone === 'green' ? 'text-green-700' : 'text-stone-900')}>{value}</p>
    {hint && <p className="text-[11px] text-stone-400 mt-0.5">{hint}</p>}</div>
}

/** Accessible on/off switch (role=switch). */
export function Switch({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return <label className={cn('flex items-center justify-between gap-3', disabled ? 'opacity-60' : 'cursor-pointer')}>
    <span><span className="block text-sm font-medium text-stone-800">{label}</span>{hint && <span className="block text-[11px] text-stone-500">{hint}</span>}</span>
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={cn('relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors', checked ? 'bg-amber-700' : 'bg-stone-300')}>
      <span className={cn('absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all', checked ? 'left-[18px]' : 'left-0.5')} /></button></label>
}
