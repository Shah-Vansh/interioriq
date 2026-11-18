'use client'
import { useCallback, useEffect, useState } from 'react'
import { Loader2, Mail, MapPin, Phone, Plus, Search, X } from 'lucide-react'
import { api, ApiError, session, Supplier, SupplierDetail } from '@/lib/api'
import { canEditCatalogue, inr } from '@/lib/catalogue-logic'
import { PAYABLES, StatementDrawer } from '@/components/finance/payables-view'
import { compact } from '@/lib/crm-logic'

const input = 'w-full text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400 disabled:bg-stone-50'
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong')
const EMPTY = { name: '', contact_person: '', phone: '', email: '', city: '', address: '', gstin: '', lead_time_days: '', payment_terms_days: '', notes: '' }
type Form = typeof EMPTY

export function SuppliersView() {
  const [items, setItems] = useState<Supplier[] | null>(null)
  const [error, setError] = useState(''); const [q, setQ] = useState(''); const [inactive, setInactive] = useState(false)
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [role, setRole] = useState<string | null>(null)
  useEffect(() => { setRole(session.user()?.role ?? null) }, [])
  const canEdit = canEditCatalogue(role)

  const load = useCallback(() => {
    const p = new URLSearchParams(); if (q.trim()) p.set('q', q.trim()); if (inactive) p.set('include_inactive', 'true')
    api.get<Supplier[]>('/suppliers?' + p).then(s => { setItems(s); setError('') }).catch(e => setError(errMsg(e)))
  }, [q, inactive])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  return (
    <div className="space-y-5 max-w-[1300px]">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div><h1 className="text-xl font-semibold text-stone-900">Suppliers</h1>
          <p className="text-sm text-stone-500 mt-0.5">Link catalogue items to a supplier and the BOQ shows who supplies each line. Duplicate phone, GSTIN or name is refused.</p></div>
        <div className="flex gap-2 items-center">
          <label className="flex items-center gap-1.5 text-xs text-stone-500"><input type="checkbox" checked={inactive} onChange={e => setInactive(e.target.checked)} />Show inactive</label>
          <div className="relative"><Search className="w-3.5 h-3.5 text-stone-400 absolute left-2.5 top-2.5" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, city, GSTIN, phone…" aria-label="Search suppliers" className={input.replace('w-full ', '') + ' pl-8 w-64'} /></div>
          {canEdit && <button onClick={() => setEditing('new')} className="flex items-center gap-2 bg-amber-700 hover:bg-amber-800 text-white text-sm font-medium px-3 py-1.5 rounded">
            <Plus className="w-3.5 h-3.5" />Add supplier</button>}
        </div>
      </div>
      {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
        {items === null ? <p className="p-8 text-center text-sm text-stone-400">Loading…</p>
          : items.length === 0 ? <p className="p-8 text-center text-sm text-stone-400">{q ? 'No suppliers match.' : 'No suppliers yet.'}</p>
          : <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead><tr className="border-b border-stone-100 bg-stone-50">
                {['Supplier', 'Contact', 'City', 'GSTIN', 'Lead time', 'Items'].map(h => <th key={h} className="text-left text-[11px] font-medium text-stone-400 uppercase tracking-wide px-5 py-3">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-stone-50">{items.map(s => (
                <tr key={s.id} onClick={() => setEditing(s.id)} className={`hover:bg-stone-50 cursor-pointer ${s.is_active ? '' : 'opacity-60'}`}>
                  <td className="px-5 py-3"><p className="font-medium text-stone-900">{s.name}{!s.is_active && <span className="ml-2 text-[10px] uppercase font-semibold text-stone-500 bg-stone-100 px-1.5 py-0.5 rounded">Inactive</span>}</p>
                    {s.contact_person && <p className="text-[11px] text-stone-400">{s.contact_person}</p>}</td>
                  <td className="px-5 py-3"><div className="text-[11px] text-stone-500 space-y-0.5">
                    {s.phone && <div className="flex items-center gap-1.5"><Phone className="w-3 h-3 text-stone-300" />{s.phone}</div>}
                    {s.email && <div className="flex items-center gap-1.5"><Mail className="w-3 h-3 text-stone-300" />{s.email}</div>}
                    {!s.phone && !s.email && '—'}</div></td>
                  <td className="px-5 py-3 text-xs text-stone-500">{s.city ? <span className="flex items-center gap-1"><MapPin className="w-3 h-3 text-stone-300" />{s.city}</span> : '—'}</td>
                  <td className="px-5 py-3 font-mono text-[11px] text-stone-500">{s.gstin ?? '—'}</td>
                  <td className="px-5 py-3 text-xs text-stone-600">{s.lead_time_days != null ? `${s.lead_time_days} days` : '—'}</td>
                  <td className="px-5 py-3 font-semibold text-stone-900">{s.items}</td>
                </tr>))}</tbody></table></div>}
      </div>
      {editing && <SupplierForm id={editing === 'new' ? null : editing} canEdit={canEdit} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
    </div>
  )
}

function SupplierForm({ id, canEdit, onClose, onSaved }: { id: string | null; canEdit: boolean; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<Form>(EMPTY)
  const [detail, setDetail] = useState<SupplierDetail | null>(null)
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [stmt, setStmt] = useState(false)
  const [role, setRole] = useState<string | null>(null); useEffect(() => { setRole(session.user()?.role ?? null) }, [])
  const PAYABLES_ROLE = !!role && (role === 'SUPER_ADMIN' || PAYABLES.includes(role))
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && !stmt && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  useEffect(() => {
    if (!id) return
    api.get<SupplierDetail>(`/suppliers/${id}`).then(d => {
      setDetail(d); setF(Object.fromEntries(Object.keys(EMPTY).map(k => [k, String((d as unknown as Record<string, unknown>)[k] ?? '')])) as Form)
    }).catch(e => setError(errMsg(e)))
  }, [id])
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF(prev => ({ ...prev, [k]: e.target.value }))
  const body = (): Record<string, unknown> | string => {
    const pt = f.payment_terms_days.trim()
    if (pt && !/^\d+$/.test(pt)) return 'Payment terms must be a whole number of days'
    const lt = f.lead_time_days.trim()
    if (lt && !/^\d+$/.test(lt)) return 'Lead time must be a whole number of days'
    const out: Record<string, unknown> = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === '' && k !== 'name' ? null : v.trim()]))
    out.lead_time_days = lt ? parseInt(lt, 10) : null
    out.payment_terms_days = pt ? parseInt(pt, 10) : null
    return out
  }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError('')
    const b = body(); if (typeof b === 'string') { setError(b); return }
    setBusy(true)
    try { if (id) await api.patch(`/suppliers/${id}`, b); else await api.post('/suppliers', compact(b as Record<string, string>)); onSaved() }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  const toggleActive = async () => {
    if (!detail) return
    setBusy(true); setError('')
    try { await api.patch(`/suppliers/${detail.id}`, { is_active: !detail.is_active }); onSaved() } catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  const F = (k: keyof Form, label: string, p: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="block"><span className="block text-[11px] font-medium text-stone-500 mb-1">{label}</span><input value={f[k]} onChange={set(k)} disabled={!canEdit} className={input} {...p} /></label>)
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-stone-900/30" onClick={onClose}>
      <div role="dialog" aria-label={id ? 'Edit supplier' : 'New supplier'} className="w-full max-w-md h-full bg-white shadow-xl flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="h-14 px-5 flex items-center justify-between border-b border-stone-200">
          <h2 className="text-sm font-semibold text-stone-900">{id ? detail?.name ?? 'Supplier' : 'New supplier'}</h2>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-stone-100"><X className="w-4 h-4 text-stone-500" /></button>
        </div>
        <form onSubmit={submit} className="flex-1 overflow-y-auto p-5 space-y-3">
          {F('name', 'Name *', { required: true, autoFocus: !id })}
          {F('contact_person', 'Contact person')}
          <div className="grid grid-cols-2 gap-3">{F('phone', 'Phone', { placeholder: '+91 98765 43210' })}{F('city', 'City')}</div>
          {F('email', 'Email', { type: 'email' })}
          <div className="grid grid-cols-2 gap-3">{F('gstin', 'GSTIN', { placeholder: '24AAACB1234C1Z5', className: input + ' font-mono uppercase' })}{F('lead_time_days', 'Lead time (days)', { inputMode: 'numeric' })}</div>
          {F('payment_terms_days', 'Payment terms (days after bill date; blank = 30)', { inputMode: 'numeric' })}
          {F('address', 'Address')}
          <label className="block"><span className="block text-[11px] font-medium text-stone-500 mb-1">Notes</span>
            <textarea rows={2} value={f.notes} onChange={set('notes')} disabled={!canEdit} className={input} /></label>
          {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
          {canEdit && <button disabled={busy} className="w-full flex justify-center items-center gap-2 bg-amber-700 hover:bg-amber-800 disabled:opacity-60 text-white text-sm font-medium px-3 py-2 rounded">
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{id ? 'Save changes' : 'Create supplier'}</button>}
          {detail && PAYABLES_ROLE && <button type="button" onClick={() => setStmt(true)} className="w-full text-xs text-stone-600 border border-stone-200 rounded py-1.5 hover:bg-stone-50">Statement (bills &amp; payments)</button>}
          {stmt && detail && <StatementDrawer supplierId={detail.id} onClose={() => setStmt(false)} />}
          {canEdit && detail && <button type="button" onClick={toggleActive} disabled={busy} className="w-full text-xs text-stone-600 border border-stone-200 rounded py-1.5 hover:bg-stone-50">
            {detail.is_active ? 'Mark inactive' : 'Mark active again'}</button>}
          {detail && <div className="pt-2"><h3 className="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mb-1.5">Items from this supplier ({detail.item_list.length})</h3>
            {detail.item_list.length === 0 ? <p className="text-xs text-stone-400">None yet. Pick this supplier on a catalogue item, or put its name in the CSV &quot;supplier&quot; column.</p>
              : <ul data-testid="supplier-items" className="text-xs divide-y divide-stone-100">{detail.item_list.map(i => (
                <li key={i.id} className="py-1.5 flex justify-between gap-2"><span><span className="font-mono text-stone-400">{i.sku}</span> {i.name}</span><span className="text-stone-700 whitespace-nowrap">{inr(i.price)} / {i.unit}</span></li>))}</ul>}</div>}
        </form>
      </div>
    </div>
  )
}
