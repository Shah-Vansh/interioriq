'use client'
import { useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { api, Client } from '@/lib/api'
import { ContactRow } from '@/lib/ops'
import { Alert, btn, ctl, Drawer, Empty, Field, hasRole, input, PageHeader, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

const EMPTY = { client_id: '', name: '', relation: '', phone: '', email: '', notes: '' }

export function ContactsView() {
  const role = useRole(); const can = hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'SALES'])
  const [q, setQ] = useState(''); const [cid, setCid] = useState('')
  const params = new URLSearchParams(); if (q.trim()) params.set('q', q.trim()); if (cid) params.set('client_id', cid)
  const { data: rows, error, reload } = useLoad<ContactRow[]>(`/contacts?${params}`)
  const { data: clients } = useLoad<Client[]>('/clients')
  const [edit, setEdit] = useState<ContactRow | 'new' | null>(null)
  return (
    <div className="space-y-5 max-w-[1200px]">
      <PageHeader title="Contacts" subtitle="People around each client — spouse, architect, site supervisor, accounts. Search finds a phone however it's typed.">
        {can && <button onClick={() => setEdit('new')} disabled={!clients?.length} className={btn.primary}><Plus className="w-3.5 h-3.5" />Add contact</button>}</PageHeader>
      <div className="flex gap-2 flex-wrap"><input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, relation, phone…" aria-label="Search contacts" className={ctl + ' w-64'} />
        <select value={cid} onChange={e => setCid(e.target.value)} aria-label="Client filter" className={ctl}><option value="">All clients</option>{clients?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
      {error && <Alert>{error}</Alert>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!rows ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>{clients?.length ? 'No contacts yet.' : 'Add a client first (CRM → Clients).'}</Empty> :
        <Table head={['Name', 'Relation', 'Client', 'Phone', 'Email']}>{rows.map(c => <tr key={c.id} onClick={() => can && setEdit(c)} className={can ? 'cursor-pointer hover:bg-stone-50' : ''}>
          <td className="px-4 py-2.5 font-medium">{c.name}</td><td className="px-4 py-2.5 text-xs">{c.relation ?? '—'}</td><td className="px-4 py-2.5 text-xs">{c.client_name}</td>
          <td className="px-4 py-2.5 text-xs">{c.phone ?? '—'}</td><td className="px-4 py-2.5 text-xs">{c.email ?? '—'}</td></tr>)}</Table>}</div>
      {edit && clients && <ContactForm c={edit === 'new' ? null : edit} clients={clients} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </div>
  )
}

function ContactForm({ c, clients, onClose, onSaved }: { c: ContactRow | null; clients: Client[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState(c ? { client_id: c.client_id, name: c.name, relation: c.relation ?? '', phone: c.phone ?? '', email: c.email ?? '', notes: c.notes ?? '' } : { ...EMPTY, client_id: clients[0]?.id ?? '' })
  const a = useAction()
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(p => ({ ...p, [k]: e.target.value }))
  const body = () => Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === '' && k !== 'name' && k !== 'client_id' ? null : v.trim()]))
  const save = (e: React.FormEvent) => { e.preventDefault(); a.run('s', async () => { if (c) await api.patch(`/contacts/${c.id}`, body()); else await api.post('/contacts', body()); onSaved() }) }
  return (
    <Drawer label={c ? 'Edit contact' : 'New contact'} title={c ? `Edit ${c.name}` : 'New contact'} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        <Field label="Client *"><select aria-label="Client *" value={f.client_id} onChange={set('client_id')} className={input}>{clients.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <Field label="Name *"><input value={f.name} onChange={set('name')} required className={input} /></Field>
        <div className="grid grid-cols-2 gap-3"><Field label="Relation"><input value={f.relation} onChange={set('relation')} placeholder="Architect, spouse…" className={input} /></Field>
          <Field label="Phone"><input value={f.phone} onChange={set('phone')} className={input} /></Field></div>
        <Field label="Email"><input value={f.email} onChange={set('email')} className={input} /></Field>
        <Field label="Notes"><input value={f.notes} onChange={set('notes')} className={input} /></Field>
        {a.error && <Alert>{a.error}</Alert>}
        <button disabled={!!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy === 's' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{c ? 'Save changes' : 'Create contact'}</button>
        {c && <button type="button" onClick={() => a.run('d', async () => { await api.delete(`/contacts/${c.id}`); onSaved() })} className={btn.danger + ' w-full'}><Trash2 className="w-3.5 h-3.5" />Delete contact</button>}
      </form>
    </Drawer>
  )
}
