'use client'
// Profitability (admins + project managers) and project expenses. Every number is a server string; nothing is computed here.
import Link from 'next/link'
import { useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { api } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { fmtDate, isoDay } from '@/lib/ops'
import { Alert, btn, Card, Drawer, Empty, Field, hasRole, input, PageHeader, Pill, Stat, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

interface Profit { revenue: string; gst: string; contract_value: string
  estimate: { materials: string; labour: string; lump_sums: string; total: string; profit: string; margin_pct: string | null }
  actual: { purchase_orders: string; purchase_received: string; from_stock: string; expenses: Record<string, string>; expenses_total: string; total: string; profit: string; margin_pct: string | null }
  variance: string; by_supplier: { supplier: string; amount: string }[]; cash: { received: string; spent_committed: string; supplier_bills: string; paid_to_suppliers: string; expenses_paid: string; position: string }; missing_cost: string[]; flags: string[]; has_quote: boolean }
interface Expense { id: string; category: string; amount: string; spent_on: string; vendor: string | null; note: string | null; status: 'ACTIVE' | 'VOID'; void_reason: string | null; user_name: string | null }
export const MONEY = ['ADMIN', 'PROJECT_MANAGER']
export const EXP_WRITE = ['ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER', 'PROCUREMENT_MANAGER']
const neg = (s: string | null | undefined) => !!s && s.startsWith('-')
const signed = (s: string) => (neg(s) ? '−' + inr(s.slice(1)) : inr(s))

export function ProfitCard({ projectId, refreshKey = 0 }: { projectId: string; refreshKey?: number }) {
  const { data: p, error } = useLoad<Profit>(`/projects/${projectId}/profit`, [refreshKey])
  if (error) return <Alert>{error}</Alert>
  if (!p) return <Empty>Loading…</Empty>
  if (!p.has_quote) return <p className="text-xs text-stone-400">Profitability starts once a quotation is approved.</p>
  const row = (l: string, est: string, act: string, bold = false) => <tr className={bold ? 'font-semibold border-t border-stone-200' : ''}><td className="py-1">{l}</td>
    <td className="py-1 text-right text-stone-500">{est}</td><td className="py-1 text-right">{act}</td></tr>
  return (
    <div className="space-y-3" data-testid="profit-card">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-stone-50 rounded p-2"><p className="text-[10px] uppercase text-stone-400">Revenue (ex-GST)</p><p className="text-sm font-semibold">{inr(p.revenue)}</p></div>
        <div className="bg-stone-50 rounded p-2"><p className="text-[10px] uppercase text-stone-400">Cost so far</p><p className="text-sm font-semibold">{inr(p.actual.total)}</p></div>
        <div className={`rounded p-2 ${neg(p.actual.profit) ? 'bg-red-50' : 'bg-green-50'}`}><p className="text-[10px] uppercase text-stone-400">Profit · margin</p>
          <p data-testid="profit-actual" className={`text-sm font-semibold ${neg(p.actual.profit) ? 'text-red-700' : 'text-green-800'}`}>{signed(p.actual.profit)} · {p.actual.margin_pct ?? '—'}%</p></div>
      </div>
      <table className="w-full text-xs"><thead><tr className="text-[10px] uppercase text-stone-400"><th className="text-left font-medium">Cost</th><th className="text-right font-medium">Estimate</th><th className="text-right font-medium">Actual</th></tr></thead>
        <tbody>{row('Materials — purchase orders', inr(p.estimate.materials), inr(p.actual.purchase_orders))}
          {row('Materials — taken from stock', '', inr(p.actual.from_stock))}
          {row('Labour / expenses', inr(p.estimate.labour), inr(p.actual.expenses_total))}
          {p.estimate.lump_sums !== '0.00' && row('Lump sums (transport/installation)', inr(p.estimate.lump_sums), '')}
          {row('Total cost', inr(p.estimate.total), inr(p.actual.total), true)}
          {row('Profit', `${signed(p.estimate.profit)} (${p.estimate.margin_pct ?? '—'}%)`, `${signed(p.actual.profit)} (${p.actual.margin_pct ?? '—'}%)`, true)}</tbody></table>
      {Object.keys(p.actual.expenses).length > 0 && <p className="text-[11px] text-stone-500">Expenses: {Object.entries(p.actual.expenses).map(([k, v]) => `${k.toLowerCase()} ${inr(v)}`).join(' · ')}</p>}
      <p className="text-[11px] text-stone-500" data-testid="cash-line">Cash: received {inr(p.cash.received)} − paid to suppliers {inr(p.cash.paid_to_suppliers)} − expenses {inr(p.cash.expenses_paid)} → <b className={neg(p.cash.position) ? 'text-red-700' : 'text-green-800'}>{signed(p.cash.position)}</b>
        {' '}(supplier bills so far {inr(p.cash.supplier_bills)}). GST {inr(p.gst)} is excluded from revenue.</p>
      {p.flags.map(f => <p key={f} className="text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded px-2 py-1">{f}</p>)}
    </div>
  )
}

export function ExpensesCard({ projectId, onChanged }: { projectId: string; onChanged?: () => void }) {
  const role = useRole(); const can = hasRole(role, EXP_WRITE)
  const { data, reload, error } = useLoad<{ categories: string[]; expenses: Expense[] }>(`/projects/${projectId}/expenses`)
  const [open, setOpen] = useState(false); const [voiding, setVoiding] = useState<Expense | null>(null)
  const refresh = () => { reload(); onChanged?.() }
  if (error) return <Alert>{error}</Alert>
  if (!data) return <Empty>Loading…</Empty>
  return <div className="space-y-2">
    {data.expenses.length === 0 ? <p className="text-xs text-stone-400">No expenses yet — record labour, contractor, transport and site costs here.</p> :
      <ul className="divide-y divide-stone-50 text-xs" data-testid="expenses">{data.expenses.map(e => <li key={e.id} className={`py-1.5 flex items-center gap-2 ${e.status === 'VOID' ? 'opacity-60' : ''}`}>
        <Pill tone="stone" label={e.category.toLowerCase()} /><span className="text-stone-600">{fmtDate(e.spent_on)}{e.vendor ? ` · ${e.vendor}` : ''}{e.note ? ` · ${e.note}` : ''}</span>
        <b className={`ml-auto ${e.status === 'VOID' ? 'line-through' : ''}`}>{inr(e.amount)}</b>
        {can && e.status === 'ACTIVE' && <button onClick={() => setVoiding(e)} className={btn.small}>Void</button>}
        {e.void_reason && <span className="text-red-700">void: {e.void_reason}</span>}</li>)}</ul>}
    {can && <button onClick={() => setOpen(true)} className={btn.ghost + ' w-full'}><Plus className="w-3.5 h-3.5" />Add expense</button>}
    {open && <ExpenseForm projectId={projectId} categories={data.categories} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); refresh() }} />}
    {voiding && <VoidExpense e={voiding} onClose={() => setVoiding(null)} onSaved={() => { setVoiding(null); refresh() }} />}
  </div>
}

function ExpenseForm({ projectId, categories, onClose, onSaved }: { projectId: string; categories: string[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ category: 'LABOUR', amount: '', spent_on: isoDay(), vendor: '', note: '' }); const a = useAction()
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(p => ({ ...p, [k]: e.target.value }))
  const save = (e: React.FormEvent) => {
    e.preventDefault(); const amt = f.amount.replace(/[₹,\s]/g, '')
    if (!/^\d+(\.\d{1,2})?$/.test(amt) || /^0+(\.0+)?$/.test(amt)) { a.setError('Amount must be a positive number with at most 2 decimals'); return }
    a.run('s', async () => { await api.post(`/projects/${projectId}/expenses`, { ...f, amount: amt, vendor: f.vendor || undefined, note: f.note || undefined }); onSaved() })
  }
  return <Drawer label="Add expense" title="Add expense" onClose={onClose}><form onSubmit={save} className="space-y-3">
    <div className="grid grid-cols-2 gap-3"><Field label="Category"><select aria-label="Category" value={f.category} onChange={set('category')} className={input}>{categories.map(c => <option key={c} value={c}>{c[0] + c.slice(1).toLowerCase()}</option>)}</select></Field>
      <Field label="Amount (₹)"><input aria-label="Amount" value={f.amount} onChange={set('amount')} inputMode="decimal" className={input} /></Field>
      <Field label="Date"><input type="date" value={f.spent_on} max={isoDay()} onChange={set('spent_on')} className={input} /></Field>
      <Field label="Paid to"><input aria-label="Paid to" value={f.vendor} onChange={set('vendor')} placeholder="Carpenter, transporter…" className={input} /></Field></div>
    <Field label="Note"><input value={f.note} onChange={set('note')} className={input} /></Field>
    {a.error && <Alert>{a.error}</Alert>}
    <button disabled={!!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save expense</button></form></Drawer>
}

function VoidExpense({ e, onClose, onSaved }: { e: Expense; onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState(''); const a = useAction()
  return <Drawer label="Void expense" title={`Void ${inr(e.amount)} ${e.category.toLowerCase()}`} onClose={onClose}>
    <Field label="Reason"><input aria-label="Reason" value={reason} onChange={x => setReason(x.target.value)} className={input} /></Field>
    {a.error && <Alert>{a.error}</Alert>}
    <button disabled={reason.trim().length < 3 || !!a.busy} onClick={() => a.run('v', async () => { await api.post(`/expenses/${e.id}/void`, { reason }); onSaved() })} className={btn.danger + ' w-full'}>Void expense</button></Drawer>
}

interface Row { id: string; project_number: string; name: string; client_name: string | null; status: string; revenue: string; estimate_cost: string; estimate_margin_pct: string | null
  actual_cost: string; profit: string; margin_pct: string | null; variance: string; flags: string[]; missing_cost: number }
export function ProfitabilityReport() {
  const { data, error } = useLoad<{ projects: Row[]; totals: { revenue: string; estimate_cost: string; actual_cost: string; profit: string; margin_pct: string | null } }>('/reports/profitability')
  return (
    <div className="space-y-5 max-w-[1400px]">
      <PageHeader title="Profitability" subtitle="Revenue = approved quotations before GST. Estimate = catalogue cost of the items + BOQ labour + lump sums. Actual = purchase orders at their rates + stock used at its cost + recorded expenses. Admins and project managers only." />
      {error && <Alert>{error}</Alert>}
      {!data ? <Empty>Loading…</Empty> : <>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3"><Stat label="Revenue (ex-GST)" value={inr(data.totals.revenue)} /><Stat label="Estimated cost" value={inr(data.totals.estimate_cost)} />
          <Stat label="Actual cost" value={inr(data.totals.actual_cost)} /><Stat label="Profit · margin" value={`${signed(data.totals.profit)} · ${data.totals.margin_pct ?? '—'}%`} tone={neg(data.totals.profit) ? 'red' : 'green'} /></div>
        <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{data.projects.length === 0 ? <Empty>No approved quotations or costs yet.</Empty> :
          <Table head={['Project', 'Revenue', 'Est. cost', 'Est. margin', 'Actual cost', 'Profit', 'Margin', 'Notes']} right={[1, 2, 3, 4, 5, 6]}>{data.projects.map(r => <tr key={r.id} data-profit={r.project_number}>
            <td className="px-4 py-2"><Link href={`/projects/${r.id}`} className="font-medium hover:underline">{r.project_number}</Link><p className="text-[11px] text-stone-400">{r.name}{r.client_name ? ` · ${r.client_name}` : ''}</p></td>
            <td className="px-4 py-2 text-right text-xs">{inr(r.revenue)}</td><td className="px-4 py-2 text-right text-xs text-stone-500">{inr(r.estimate_cost)}</td><td className="px-4 py-2 text-right text-xs text-stone-500">{r.estimate_margin_pct ?? '—'}%</td>
            <td className="px-4 py-2 text-right text-xs">{inr(r.actual_cost)}</td><td className={`px-4 py-2 text-right text-xs font-semibold ${neg(r.profit) ? 'text-red-700' : 'text-green-800'}`}>{signed(r.profit)}</td>
            <td className={`px-4 py-2 text-right text-xs ${neg(r.profit) ? 'text-red-700' : ''}`}>{r.margin_pct ?? '—'}%</td>
            <td className="px-4 py-2 text-[11px] text-amber-900 max-w-72">{r.flags.join(' · ') || <span className="text-stone-300">—</span>}</td></tr>)}</Table>}</div>
      </>}
    </div>
  )
}
