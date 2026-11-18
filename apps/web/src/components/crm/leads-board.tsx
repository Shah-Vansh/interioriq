'use client'
import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { ArrowRightLeft, Loader2, MapPin, Phone, Plus, Search, X } from 'lucide-react'
import { api, ApiError, ConvertResult, Lead, LeadDetail } from '@/lib/api'
import { STAGES, canMove, compact, formatBudget, groupByStage, moveLead, stageLabel, timeAgo } from '@/lib/crm-logic'
import { cn } from '@/lib/utils'
import { CrmMeta, FollowUpBadge, LeadFollowUps, LostDialog, initials } from '@/components/crm/followups'
import { useLoad } from '@/components/ui/kit'

const input = 'w-full text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400'
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong')

export function LeadsBoard() {
  const [leads, setLeads] = useState<Lead[] | null>(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overStage, setOverStage] = useState<string | null>(null)
  const [owner, setOwner] = useState(''); const [fu, setFu] = useState(''); const [showArchived, setShowArchived] = useState(false)
  const [losing, setLosing] = useState<Lead | null>(null)
  const { data: meta } = useLoad<CrmMeta>('/crm/meta')

  const load = useCallback(() => {
    const p = new URLSearchParams(); if (q.trim()) p.set('q', q.trim()); if (owner) p.set('assigned', owner); if (fu) p.set('follow_up', fu); if (showArchived) p.set('archived', 'true')
    api.get<Lead[]>('/leads?' + p).then(l => { setLeads(l); setError('') }).catch(e => setError(errMsg(e)))
  }, [q, owner, fu, showArchived])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  const grouped = useMemo(() => groupByStage(leads ?? []), [leads])

  const move = async (id: string, stage: string) => {
    if (!leads) return
    const lead = leads.find(l => l.id === id); if (!lead || !canMove(lead, stage)) return
    if (stage === 'LOST' && lead.stage !== 'LOST') { setLosing(lead); return }       // Lost needs a reason first
    const before = leads
    setLeads(moveLead(leads, id, stage)); setError('')
    try { const saved = await api.post<Lead>(`/leads/${id}/stage`, { stage }); setLeads(ls => ls?.map(l => (l.id === id ? { ...l, ...saved } : l)) ?? null) }
    catch (e) { setLeads(before); setError(`Couldn't move ${lead.name}: ${errMsg(e)}`) }
  }

  const markLost = async (reason: string) => {
    if (!losing) return
    const saved = await api.post<Lead>(`/leads/${losing.id}/stage`, { stage: 'LOST', reason })
    setLeads(ls => ls?.map(l => (l.id === losing.id ? { ...l, ...saved } : l)) ?? null); setLosing(null)
  }

  return (
    <div className="space-y-4 max-w-[1800px]">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div><h1 className="text-xl font-semibold text-stone-900">Leads</h1>
          <p className="text-sm text-stone-500 mt-0.5">Drag a card to change its stage. Every move and note is recorded.</p></div>
        <div className="flex gap-2 items-center">
          <div className="relative"><Search className="w-3.5 h-3.5 text-stone-400 absolute left-2.5 top-2.5" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, phone, city…" className={input + ' pl-8 w-64'} aria-label="Search leads" /></div>
          <button onClick={() => setAdding(true)} className="flex items-center gap-2 bg-amber-700 hover:bg-amber-800 text-white text-sm font-medium px-3 py-1.5 rounded">
            <Plus className="w-3.5 h-3.5" />Add lead</button>
        </div>
      </div>
      <div className="flex gap-2 flex-wrap items-center">
        <select aria-label="Owner filter" value={owner} onChange={e => setOwner(e.target.value)} className="text-sm border border-stone-200 rounded px-3 py-1.5 bg-white">
          <option value="">Everyone's leads</option><option value="me">My leads</option><option value="unassigned">Unassigned</option>{meta?.assignable.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
        <select aria-label="Follow-up filter" value={fu} onChange={e => setFu(e.target.value)} className="text-sm border border-stone-200 rounded px-3 py-1.5 bg-white">
          <option value="">Any follow-up</option><option value="OVERDUE">Overdue</option><option value="TODAY">Due today</option><option value="NONE">No next step</option></select>
        <label className="flex items-center gap-1.5 text-xs text-stone-600"><input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />Show archived</label>
        <Link href="/crm/followups" className="text-xs text-amber-700 hover:underline ml-auto">Follow-ups →</Link>
      </div>
      {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
      {leads === null && !error ? <p className="p-8 text-center text-sm text-stone-400">Loading leads…</p> : (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-3 min-w-max">
            {STAGES.map(s => {
              const items = grouped[s.key] ?? []
              const dragged = leads?.find(l => l.id === dragId)
              const allowed = dragged ? canMove(dragged, s.key) : false
              return (
                <div key={s.key} data-stage={s.key}
                  onDragOver={e => { if (allowed) { e.preventDefault(); setOverStage(s.key) } }}
                  onDragLeave={() => setOverStage(o => (o === s.key ? null : o))}
                  onDrop={e => { e.preventDefault(); const id = e.dataTransfer.getData('text/plain') || dragId; setOverStage(null); setDragId(null); if (id) move(id, s.key) }}
                  className={cn('w-60 flex-shrink-0 rounded-lg p-1.5 transition-colors min-h-[200px]', overStage === s.key ? 'bg-amber-50 ring-1 ring-amber-300' : 'bg-stone-100/60')}>
                  <div className="flex items-center gap-2 mb-2 px-1.5 pt-1">
                    <div className={cn('w-2 h-2 rounded-full', s.dot)} />
                    <span className="text-xs font-semibold text-stone-700">{s.label}</span>
                    <span className="ml-auto text-[11px] bg-white text-stone-500 rounded-full px-1.5 py-0.5" data-testid={`count-${s.key}`}>{items.length}</span>
                  </div>
                  <div className="space-y-2">
                    {items.map(l => (
                      <div key={l.id} draggable data-lead={l.name}
                        onDragStart={e => { e.dataTransfer.setData('text/plain', l.id); e.dataTransfer.effectAllowed = 'move'; setDragId(l.id) }}
                        onDragEnd={() => { setDragId(null); setOverStage(null) }}
                        onClick={() => setOpenId(l.id)}
                        className={cn('bg-white border border-stone-200 rounded-lg p-3 shadow-sm hover:border-stone-300 hover:shadow transition-all cursor-grab active:cursor-grabbing', dragId === l.id && 'opacity-50')}>
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <p className="text-sm font-medium text-stone-900 leading-snug">{l.name}</p>
                          {l.budget && <span className="text-[11px] font-semibold text-green-700 bg-green-50 px-1.5 py-0.5 rounded whitespace-nowrap">{formatBudget(l.budget)}</span>}
                        </div>
                        {l.requirement && <p className="text-xs text-stone-600 mb-1.5 line-clamp-2">{l.requirement}</p>}
                        <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
                          {l.assigned_name && <span title={`Owner: ${l.assigned_name}`} className="text-[10px] font-semibold text-stone-600 bg-stone-100 w-5 h-5 rounded-full inline-flex items-center justify-center">{initials(l.assigned_name)}</span>}
                          <FollowUpBadge status={l.follow_up_status ?? 'NONE'} next={l.next_follow_up ?? null} kind={l.next_follow_up_kind} />
                          {l.stage === 'LOST' && l.lost_reason && <span className="text-[10px] text-red-700">{l.lost_reason}</span>}
                        </div>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-stone-400">
                          {l.city && <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{l.city}</span>}
                          {l.phone && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{l.phone}</span>}
                        </div>
                        <div className="flex items-center justify-between pt-2 mt-2 border-t border-stone-100" onClick={e => e.stopPropagation()}>
                          {l.project_number
                            ? <span className="text-[10px] font-mono text-green-700">{l.project_number}</span>
                            : <select aria-label={`Stage for ${l.name}`} value={l.stage} onChange={e => move(l.id, e.target.value)}
                                className="text-[11px] text-stone-500 bg-transparent border border-stone-200 rounded px-1 py-0.5 outline-none">
                                {STAGES.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
                              </select>}
                          <span className="text-[10px] text-stone-400">{timeAgo(l.updated_at)}</span>
                        </div>
                      </div>
                    ))}
                    {items.length === 0 && <p className="text-[11px] text-stone-400 text-center py-4">{dragged && allowed ? 'Drop here' : 'No leads'}</p>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
      {adding && <AddLead onClose={() => setAdding(false)} onCreated={l => { setAdding(false); setLeads(ls => [l, ...(ls ?? [])]); setOpenId(l.id) }} />}
      {openId && <LeadDrawer id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
      {losing && <LostDialog name={losing.name} onCancel={() => setLosing(null)} onConfirm={markLost} />}
    </div>
  )
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-stone-900/30" onClick={onClose}>
      <div role="dialog" aria-label={title} className="w-full max-w-md h-full bg-white shadow-xl flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="h-14 px-5 flex items-center justify-between border-b border-stone-200 flex-shrink-0">
          <h2 className="text-sm font-semibold text-stone-900 truncate">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-stone-100"><X className="w-4 h-4 text-stone-500" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-5">{children}</div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="block text-[11px] font-medium text-stone-500 mb-1">{label}</span>{children}</label>
}

function AddLead({ onClose, onCreated }: { onClose: () => void; onCreated: (l: Lead) => void }) {
  const [f, setF] = useState({ name: '', phone: '', email: '', city: '', source: '', requirement: '', budget: '' })
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try { onCreated(await api.post<Lead>('/leads', compact(f))) } catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  return (
    <Modal title="New lead" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Name *"><input autoFocus required value={f.name} onChange={set('name')} className={input} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Phone"><input value={f.phone} onChange={set('phone')} placeholder="+91 98765 43210" className={input} /></Field>
          <Field label="City"><input value={f.city} onChange={set('city')} className={input} /></Field>
        </div>
        <Field label="Email"><input type="email" value={f.email} onChange={set('email')} className={input} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Source"><select value={f.source} onChange={set('source')} className={input}>
            <option value="">—</option>{['Walk-in', 'Referral', 'Website', 'Instagram', 'Phone', 'Architect', 'Other'].map(s => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Budget (₹)"><input inputMode="decimal" value={f.budget} onChange={set('budget')} placeholder="2200000" className={input} /></Field>
        </div>
        <Field label="Requirement"><textarea rows={3} value={f.requirement} onChange={set('requirement')} placeholder="3BHK full interior, modular kitchen…" className={input} /></Field>
        {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
        <button disabled={busy} className="w-full flex justify-center items-center gap-2 bg-amber-700 hover:bg-amber-800 disabled:opacity-60 text-white text-sm font-medium px-3 py-2 rounded">
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Create lead</button>
      </form>
    </Modal>
  )
}

function LeadDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<LeadDetail | null>(null); const [error, setError] = useState('')
  const [note, setNote] = useState(''); const [busy, setBusy] = useState(false)
  const [projNo, setProjNo] = useState(''); const [projName, setProjName] = useState(''); const [converted, setConverted] = useState<ConvertResult | null>(null)
  const load = useCallback(() => api.get<LeadDetail>(`/leads/${id}`).then(setD).catch(e => setError(errMsg(e))), [id])
  useEffect(() => { load() }, [load])

  const addNote = async (e: React.FormEvent) => {
    e.preventDefault(); if (!note.trim()) return; setBusy(true); setError('')
    try { await api.post(`/leads/${id}/notes`, { text: note }); setNote(''); await load(); onChanged() } catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  const convert = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try { setConverted(await api.post<ConvertResult>(`/leads/${id}/convert`, compact({ project_number: projNo, project_name: projName }))); await load(); onChanged() }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }

  return (
    <Modal title={d?.name ?? 'Lead'} onClose={onClose}>
      {!d ? <p className="text-sm text-stone-400">{error || 'Loading…'}</p> : <>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {([['Stage', stageLabel(d.stage)], ['Budget', formatBudget(d.budget) || '—'], ['Phone', d.phone || '—'], ['Email', d.email || '—'],
             ['City', d.city || '—'], ['Source', d.source || '—']] as const).map(([k, v]) => (
            <div key={k}><div className="text-[11px] text-stone-400">{k}</div><div className="text-stone-800 break-words">{v}</div></div>))}
          {d.requirement && <div className="col-span-2"><div className="text-[11px] text-stone-400">Requirement</div><div className="text-stone-800 whitespace-pre-wrap">{d.requirement}</div></div>}
        </div>

        <LeadFollowUps lead={d} followUps={d.follow_ups ?? []} onChanged={() => { load(); onChanged() }} />
        {d.lost_reason && d.stage === 'LOST' && <p className="text-xs text-red-800 bg-red-50 rounded px-2 py-1">Lost: {d.lost_reason}</p>}
        <button onClick={async () => { try { await api.post(`/leads/${id}/archive`, { archived: !d.archived }); await load(); onChanged() } catch (err) { setError(errMsg(err)) } }}
          className="text-xs text-stone-500 underline">{d.archived ? 'Restore from archive' : 'Archive this lead'}</button>
        {d.project_id ? (
          <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
            Converted to project <Link href="/projects" className="font-mono font-semibold underline">{d.project_number}</Link>
            {converted && <> · client {converted.client_reused ? 'reused (same phone)' : 'created'}</>}
          </div>
        ) : d.stage !== 'LOST' && (
          <form onSubmit={convert} className="rounded-lg border border-stone-200 p-3 space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium text-stone-800"><ArrowRightLeft className="w-4 h-4 text-amber-700" />Convert to client + project</div>
            {d.existing_client && <p className="text-xs text-amber-800 bg-amber-50 rounded px-2 py-1">A client with this phone already exists ({d.existing_client.name}); it will be reused.</p>}
            <div className="grid grid-cols-2 gap-2">
              <input required value={projNo} onChange={e => setProjNo(e.target.value)} placeholder="Project no. e.g. IQ-2026-014" aria-label="Project number" className={input} />
              <input value={projName} onChange={e => setProjName(e.target.value)} placeholder="Project name (optional)" aria-label="Project name" className={input} />
            </div>
            <button disabled={busy} className="flex items-center gap-2 bg-stone-900 hover:bg-stone-800 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded">
              {busy && <Loader2 className="w-3 h-3 animate-spin" />}Convert</button>
          </form>
        )}

        <form onSubmit={addNote} className="space-y-2">
          <textarea rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="Add a note (call summary, site visit outcome…)" aria-label="Note" className={input} />
          <button disabled={busy || !note.trim()} className="bg-amber-700 hover:bg-amber-800 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded">Add note</button>
        </form>
        {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}

        <div>
          <h3 className="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mb-2">History</h3>
          <ol className="space-y-3 border-l border-stone-200 pl-4" data-testid="lead-history">
            {d.activity.map(a => (
              <li key={a.id} className="relative">
                <span className="absolute -left-[21px] top-1.5 w-2 h-2 rounded-full bg-stone-300" />
                <div className="text-sm text-stone-800">
                  {a.kind === 'NOTE' ? <span className="whitespace-pre-wrap">{a.text}</span>
                    : a.kind === 'STAGE' ? <>Moved <b>{stageLabel(a.from_stage)}</b> → <b>{stageLabel(a.to_stage)}</b>{a.text ? <span className="text-red-700"> ({a.text})</span> : null}</>
                    : a.kind === 'CREATED' ? 'Lead created' : a.text}
                </div>
                <div className="text-[11px] text-stone-400">{a.user_name ?? 'Unknown'} · {new Date(a.created_at.endsWith('Z') || a.created_at.includes('+') ? a.created_at : a.created_at + 'Z').toLocaleString('en-IN')}</div>
              </li>))}
          </ol>
        </div>
      </>}
    </Modal>
  )
}
