'use client'
// M34: per-supplier prices in the catalogue item drawer. The server decides which quote is best (Decimal) — the browser only shows it.
import { useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { api, Supplier } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { Alert, btn, Field, input, useAction, useLoad } from '@/components/ui/kit'

interface Quote { id: string; supplier_id: string; supplier_name: string | null; price: string; min_qty: number; valid_from: string; valid_to: string | null
  lead_days: number | null; note: string | null; ended_reason: string | null; valid_today: boolean; user_name: string | null }
interface Resp { quotes: Quote[]; best: { supplier_id: string | null; supplier_name: string | null; rate: string; source: 'QUOTE' | 'COST' | 'SELLING_PRICE'; qty: number } }

export function SupplierPrices({ itemId, unit, suppliers, canEdit }: { itemId: string; unit: string; suppliers: Supplier[]; canEdit: boolean }) {
  const { data, reload, error } = useLoad<Resp>(`/catalogue/items/${itemId}/supplier-prices`, [itemId])
  const [f, setF] = useState({ supplier_id: '', price: '', min_qty: '1', valid_from: '', valid_to: '', lead_days: '' })
  const [adding, setAdding] = useState(false); const a = useAction()
  const add = () => a.run('add', async () => {
    await api.post(`/catalogue/items/${itemId}/supplier-prices`, { supplier_id: f.supplier_id, price: f.price.replace(/[,\s₹]/g, ''), min_qty: Number(f.min_qty || 1),
      valid_from: f.valid_from || undefined, valid_to: f.valid_to || undefined, lead_days: f.lead_days ? Number(f.lead_days) : undefined })
    setF({ supplier_id: '', price: '', min_qty: '1', valid_from: '', valid_to: '', lead_days: '' }); setAdding(false); reload() })
  const end = (q: Quote) => { const reason = prompt(`End ${q.supplier_name}'s price of ${inr(q.price)}? Reason:`); if (reason && reason.trim().length >= 3) a.run(q.id, async () => { await api.post(`/supplier-prices/${q.id}/end`, { reason }); reload() }) }
  if (error) return <Alert>{error}</Alert>
  if (!data) return <p className="text-xs text-stone-400">Loading…</p>
  const b = data.best
  return <div className="space-y-2" data-testid="supplier-prices">
    <p className="text-xs text-stone-600" data-testid="best-price">Buying today: {b.supplier_name ? <b>{b.supplier_name}</b> : <span className="text-amber-700">no supplier</span>} at <b>{inr(b.rate)}</b> / {unit}
      <span className="text-stone-400"> ({b.source === 'QUOTE' ? 'cheapest valid quote' : b.source === 'COST' ? 'default supplier, item cost' : 'no cost set — selling price'})</span></p>
    {data.quotes.length > 0 && <table className="w-full text-[11px]"><thead><tr className="text-stone-400 text-left"><th className="font-medium">Supplier</th><th className="font-medium text-right">Price</th><th className="font-medium">Min qty</th><th className="font-medium">Valid</th><th /></tr></thead>
      <tbody className="divide-y divide-stone-50">{data.quotes.map(q => <tr key={q.id} data-quote={q.supplier_name ?? ''} className={q.valid_today ? '' : 'text-stone-400'}>
        <td className="py-1">{q.supplier_name}{q.lead_days != null && <span className="text-stone-400"> · {q.lead_days} d</span>}</td><td className="py-1 text-right font-mono">{inr(q.price)}</td><td className="py-1">{q.min_qty}+</td>
        <td className="py-1">{q.valid_from} → {q.valid_to ?? 'open'}{q.valid_today ? <span className="ml-1 text-green-700 font-semibold">today</span> : q.ended_reason ? <span className="ml-1">ended: {q.ended_reason}</span> : null}</td>
        <td className="py-1 text-right">{canEdit && (q.valid_today || !q.valid_to || q.valid_to >= new Date().toISOString().slice(0, 10)) && !q.ended_reason && <button onClick={() => end(q)} className="text-red-700 hover:underline" aria-label={`End price from ${q.supplier_name}`}>End</button>}</td></tr>)}</tbody></table>}
    {a.error && <Alert>{a.error}</Alert>}
    {canEdit && (adding ? <div className="grid grid-cols-2 gap-2 border border-stone-200 rounded p-2">
      <Field label="Supplier"><select aria-label="Quote supplier" value={f.supplier_id} onChange={e => setF({ ...f, supplier_id: e.target.value })} className={input + ' py-1 text-xs'}>
        <option value="">Choose…</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
      <Field label={`Price (₹ / ${unit})`}><input aria-label="Quote price" inputMode="decimal" value={f.price} onChange={e => setF({ ...f, price: e.target.value })} className={input + ' py-1 text-xs'} /></Field>
      <Field label="Min qty"><input aria-label="Quote minimum quantity" inputMode="numeric" value={f.min_qty} onChange={e => setF({ ...f, min_qty: e.target.value })} className={input + ' py-1 text-xs'} /></Field>
      <Field label="Lead time (days)"><input aria-label="Quote lead days" inputMode="numeric" value={f.lead_days} onChange={e => setF({ ...f, lead_days: e.target.value })} className={input + ' py-1 text-xs'} /></Field>
      <Field label="Valid from (blank = today)"><input type="date" aria-label="Quote valid from" value={f.valid_from} onChange={e => setF({ ...f, valid_from: e.target.value })} className={input + ' py-1 text-xs'} /></Field>
      <Field label="Valid to (blank = open)"><input type="date" aria-label="Quote valid to" value={f.valid_to} onChange={e => setF({ ...f, valid_to: e.target.value })} className={input + ' py-1 text-xs'} /></Field>
      <button type="button" onClick={add} disabled={!f.supplier_id || !f.price.trim() || !!a.busy} className={btn.primary + ' col-span-2 text-xs'}>{a.busy === 'add' && <Loader2 className="w-3 h-3 animate-spin" />}Save supplier price</button>
    </div> : <button type="button" onClick={() => setAdding(true)} className={btn.small}><Plus className="w-3 h-3" />Add supplier price</button>)}
    <p className="text-[11px] text-stone-400">Procurement orders from the cheapest valid quote for the quantity needed; with none, from the item's default supplier at its cost.</p>
  </div>
}
