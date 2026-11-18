'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Plus, Loader2 } from 'lucide-react'
import { api, ApiError, Client, ProjectWithClient } from '@/lib/api'
import { formatBudget } from '@/lib/crm-logic'
import { STAGE_LABEL } from '@/lib/ops'

const TITLES = { all: ['Projects', 'Each project belongs to a client; the client is printed on its quotations. Click a number to open the project.'],
  active: ['Active projects', 'Not archived and not yet handed over.'], completed: ['Completed projects', 'Handed over to the client.'], archived: ['Archived projects', 'Hidden from the active lists; restore one from its page.'] } as const

export function ProjectsView({ view = 'all' }: { view?: keyof typeof TITLES }) {
  const [items, setItems] = useState<ProjectWithClient[] | null>(null)
  const [clients, setClients] = useState<Client[]>([])
  const [error, setError] = useState('')
  const [num, setNum] = useState(''); const [name, setName] = useState(''); const [clientId, setClientId] = useState(''); const [busy, setBusy] = useState(false); const [target, setTarget] = useState('')
  const [saving, setSaving] = useState<string | null>(null)

  const load = () => api.get<ProjectWithClient[]>(`/projects?view=${view}`).then(setItems).catch(e => setError(e.message))
  useEffect(() => {
    load()
    api.get<Client[]>('/clients').then(setClients).catch(() => { /* roles without CRM access still see projects; the client picker just stays read-only */ })
  }, [])

  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try { await api.post('/projects', { project_number: num, name, client_id: clientId || null, target_date: target || null }); setNum(''); setName(''); setClientId(''); setTarget(''); await load() }
    catch (err) { setError(err instanceof ApiError ? err.message : 'Failed') } finally { setBusy(false) }
  }
  const changeClient = async (p: ProjectWithClient, cid: string) => {
    setSaving(p.id); setError('')
    try { const saved = await api.patch<ProjectWithClient>(`/projects/${p.id}`, { client_id: cid || null }); setItems(it => it?.map(x => (x.id === p.id ? saved : x)) ?? null) }
    catch (err) { setError(`Couldn't change the client of ${p.project_number}: ${err instanceof ApiError ? err.message : 'failed'}`) } finally { setSaving(null) }
  }
  const input = 'text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400'
  return (
    <div className="space-y-5 max-w-[1100px]">
      <div><h1 className="text-xl font-semibold text-stone-900">{TITLES[view][0]}</h1>
        <p className="text-sm text-stone-500 mt-0.5">{TITLES[view][1]}</p></div>
      {view === 'all' && <form onSubmit={create} className="flex gap-2 flex-wrap items-center bg-white border border-stone-200 rounded-lg p-3 shadow-sm">
        <input value={num} onChange={e => setNum(e.target.value)} placeholder="IQ-2026-001" required aria-label="Project number" className={input + ' w-36'} />
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Project name" required aria-label="Project name" className={input + ' flex-1 min-w-48'} />
        <select value={clientId} onChange={e => setClientId(e.target.value)} aria-label="Client for new project" className={input + ' w-48'}>
          <option value="">No client yet</option>{clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        <input type="date" value={target} onChange={e => setTarget(e.target.value)} aria-label="Target handover date" title="Target handover date" className={input + ' w-40'} />
        <button disabled={busy} className="flex items-center gap-1.5 bg-amber-700 hover:bg-amber-800 disabled:opacity-60 text-white text-sm font-medium px-3 py-1.5 rounded">
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}New project</button>
      </form>}
      {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
        {items === null ? <p className="p-8 text-center text-sm text-stone-400">Loading…</p>
          : items.length === 0 ? <p className="p-8 text-center text-sm text-stone-400">{view === 'all' ? 'No projects yet. Create one above, or convert a lead in' : 'Nothing here yet. See'} {view === 'all' ? <Link href="/crm/leads" className="underline">CRM → Leads</Link> : <Link href="/projects" className="underline">All projects</Link>}.</p>
          : <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="bg-stone-50 border-b border-stone-100">
              {['Number', 'Name', 'Client', 'Budget', 'Stage'].map(h => <th key={h} className="text-left text-[11px] text-stone-400 uppercase tracking-wide px-5 py-3">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-stone-50">{items.map(p => (
                <tr key={p.id} className="hover:bg-stone-50"><td className="px-5 py-3 font-mono text-xs"><Link href={`/projects/${p.id}`} className="text-amber-800 hover:underline">{p.project_number}</Link></td>
                  <td className="px-5 py-3 font-medium text-stone-900">{p.name}</td>
                  <td className="px-5 py-3">
                    {clients.length > 0 || p.client_id
                      ? <div className="flex items-center gap-1.5">
                          <select value={p.client_id ?? ''} disabled={saving === p.id || clients.length === 0} onChange={e => changeClient(p, e.target.value)}
                            aria-label={`Client of ${p.project_number}`} className="text-xs border border-stone-200 rounded px-2 py-1 bg-white max-w-[180px]">
                            <option value="">— none —</option>
                            {p.client_id && !clients.some(c => c.id === p.client_id) && <option value={p.client_id}>{p.client_name}</option>}
                            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                          </select>
                          {saving === p.id && <Loader2 className="w-3 h-3 animate-spin text-stone-400" />}
                        </div>
                      : <span className="text-xs text-stone-400">—</span>}
                  </td>
                  <td className="px-5 py-3 text-xs text-stone-600">{formatBudget(p.budget) || '—'}</td>
                  <td className="px-5 py-3"><span className="text-[11px] font-semibold bg-stone-100 text-stone-600 px-2 py-0.5 rounded-full">{STAGE_LABEL[p.status] ?? p.status}</span>
                    <div className="mt-1 h-1 w-24 bg-stone-100 rounded"><div className="h-1 bg-amber-600 rounded" style={{ width: `${(p as ProjectWithClient & { progress?: number }).progress ?? 0}%` }} /></div></td></tr>))}</tbody></table></div>}
      </div>
    </div>
  )
}
