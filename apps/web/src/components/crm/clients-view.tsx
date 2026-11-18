'use client'
import { useCallback, useEffect, useState } from 'react'
import { Loader2, Mail, MapPin, Phone, Plus, Search, X } from 'lucide-react'
import { api, ApiError, Client } from '@/lib/api'
import { compact } from '@/lib/crm-logic'

const input = 'w-full text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400'
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong')
const EMPTY = { name: '', company: '', phone: '', email: '', city: '', address: '', gstin: '', notes: '' }
type Form = typeof EMPTY

export function ClientsView() {
  const [items, setItems] = useState<Client[] | null>(null)
  const [error, setError] = useState(''); const [q, setQ] = useState('')
  const [editing, setEditing] = useState<Client | 'new' | null>(null)

  const load = useCallback(() => {
    api.get<Client[]>('/clients' + (q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '')).then(c => { setItems(c); setError('') }).catch(e => setError(errMsg(e)))
  }, [q])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  return (
    <div className="space-y-5 max-w-[1300px]">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div><h1 className="text-xl font-semibold text-stone-900">Clients</h1>
          <p className="text-sm text-stone-500 mt-0.5">The same phone number can't be added twice, however it's typed.</p></div>
        <div className="flex gap-2 items-center">
          <div className="relative"><Search className="w-3.5 h-3.5 text-stone-400 absolute left-2.5 top-2.5" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, company, phone…" aria-label="Search clients" className={input + ' pl-8 w-64'} /></div>
          <button onClick={() => setEditing('new')} className="flex items-center gap-2 bg-amber-700 hover:bg-amber-800 text-white text-sm font-medium px-3 py-1.5 rounded">
            <Plus className="w-3.5 h-3.5" />Add client</button>
        </div>
      </div>
      {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
        {items === null ? <p className="p-8 text-center text-sm text-stone-400">Loading…</p>
          : items.length === 0 ? <p className="p-8 text-center text-sm text-stone-400">{q ? 'No clients match.' : 'No clients yet. Add one, or convert a lead.'}</p>
          : <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead><tr className="border-b border-stone-100 bg-stone-50">
                {['Client', 'Contact', 'City', 'Projects'].map(h => <th key={h} className="text-left text-[11px] font-medium text-stone-400 uppercase tracking-wide px-5 py-3">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-stone-50">{items.map(c => (
                <tr key={c.id} onClick={() => setEditing(c)} className="hover:bg-stone-50 cursor-pointer">
                  <td className="px-5 py-3"><div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-stone-200 flex items-center justify-center text-xs font-semibold text-stone-600">{c.name[0]?.toUpperCase()}</div>
                    <div><p className="font-medium text-stone-900">{c.name}</p>{c.company && <p className="text-[11px] text-stone-400">{c.company}</p>}</div></div></td>
                  <td className="px-5 py-3"><div className="text-[11px] text-stone-500 space-y-0.5">
                    {c.phone && <div className="flex items-center gap-1.5"><Phone className="w-3 h-3 text-stone-300" />{c.phone}</div>}
                    {c.email && <div className="flex items-center gap-1.5"><Mail className="w-3 h-3 text-stone-300" />{c.email}</div>}
                    {!c.phone && !c.email && '—'}</div></td>
                  <td className="px-5 py-3 text-xs text-stone-500">{c.city ? <span className="flex items-center gap-1"><MapPin className="w-3 h-3 text-stone-300" />{c.city}</span> : '—'}</td>
                  <td className="px-5 py-3 font-semibold text-stone-900">{c.projects}</td>
                </tr>))}</tbody></table></div>}
      </div>
      {editing && <ClientForm client={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
    </div>
  )
}

function ClientForm({ client, onClose, onSaved }: { client: Client | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<Form>(client ? Object.fromEntries(Object.keys(EMPTY).map(k => [k, (client as unknown as Record<string, string | null>)[k] ?? ''])) as Form : EMPTY)
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value })
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      // Editing: send every field so clearing a box really clears it. Creating: leave blanks out.
      if (client) await api.patch(`/clients/${client.id}`, Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === '' && k !== 'name' ? null : v])))
      else await api.post('/clients', compact(f))
      onSaved()
    } catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  const F = ({ k, label, ...p }: { k: keyof Form; label: string } & React.InputHTMLAttributes<HTMLInputElement>) => (
    <label className="block"><span className="block text-[11px] font-medium text-stone-500 mb-1">{label}</span><input value={f[k]} onChange={set(k)} className={input} {...p} /></label>)
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-stone-900/30" onClick={onClose}>
      <div role="dialog" aria-label={client ? 'Edit client' : 'New client'} className="w-full max-w-md h-full bg-white shadow-xl flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="h-14 px-5 flex items-center justify-between border-b border-stone-200">
          <h2 className="text-sm font-semibold text-stone-900">{client ? `Edit ${client.name}` : 'New client'}</h2>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-stone-100"><X className="w-4 h-4 text-stone-500" /></button>
        </div>
        <form onSubmit={submit} className="flex-1 overflow-y-auto p-5 space-y-3">
          {F({ k: 'name', label: 'Name *', required: true, autoFocus: true })}
          {F({ k: 'company', label: 'Company' })}
          <div className="grid grid-cols-2 gap-3">{F({ k: 'phone', label: 'Phone', placeholder: '+91 98765 43210' })}{F({ k: 'city', label: 'City' })}</div>
          {F({ k: 'email', label: 'Email', type: 'email' })}
          {F({ k: 'address', label: 'Address' })}
          {F({ k: 'gstin', label: 'GSTIN (only for GST-registered clients)', placeholder: '24AAACB1234C1Z5' })}
          <label className="block"><span className="block text-[11px] font-medium text-stone-500 mb-1">Notes</span>
            <textarea rows={3} value={f.notes} onChange={set('notes')} className={input} /></label>
          {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
          <button disabled={busy} className="w-full flex justify-center items-center gap-2 bg-amber-700 hover:bg-amber-800 disabled:opacity-60 text-white text-sm font-medium px-3 py-2 rounded">
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{client ? 'Save changes' : 'Create client'}</button>
        </form>
      </div>
    </div>
  )
}
