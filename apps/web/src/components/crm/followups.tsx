'use client'
// Lead ownership + follow-ups: badge on cards, owner/follow-up section in the lead drawer, "why lost?" dialog, and CRM → Follow-ups.
import { useEffect, useRef, useState } from 'react'
import { CalendarClock, Check, Loader2, Plus, X } from 'lucide-react'
import { api } from '@/lib/api'
import { Alert, btn, ctl, Drawer, Empty, Field, hasRole, input, PageHeader, Pill, useAction, useLoad, useRole } from '@/components/ui/kit'

export interface FollowUp { id: string; lead_id: string; kind: string; due_at: string; note: string | null; assigned_to: string | null; assigned_name: string | null
  status: 'OPEN' | 'DONE' | 'CANCELLED'; outcome: string | null; closed_by: string | null; closed_at: string | null; bucket: string; lead_name?: string; lead_phone?: string | null; lead_stage?: string; lead_city?: string | null }
export interface CrmMeta { stages: string[]; lost_reasons: string[]; follow_up_kinds: string[]; assignable: { id: string; name: string; role: string }[] }
const WRITE = ['ADMIN', 'PROJECT_MANAGER', 'SALES']
const KIND_LABEL: Record<string, string> = { CALL: 'Call', VISIT: 'Site visit', MEETING: 'Meeting', WHATSAPP: 'WhatsApp', EMAIL: 'Email', OTHER: 'Other' }

const asDate = (s: string) => new Date(s.endsWith('Z') || /[+-]\d\d:\d\d$/.test(s) ? s : s + 'Z')
export const when = (s: string) => asDate(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
/** <input type=datetime-local> value for "now + h hours", in the browser's local time. */
export function localInput(hours = 24) { const d = new Date(Date.now() + hours * 3600_000); d.setSeconds(0, 0); const p = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}` }
/** datetime-local (browser local) → ISO with offset, so the server stores the exact instant. */
export const toIso = (local: string) => new Date(local).toISOString()

export function FollowUpBadge({ status, next, kind }: { status: string; next: string | null; kind?: string | null }) {
  if (status === 'CLOSED') return null
  if (status === 'NONE') return <span data-fu="NONE" className="text-[10px] font-semibold text-stone-500 bg-stone-100 px-1.5 py-0.5 rounded">No next step</span>
  const tone = status === 'OVERDUE' ? 'text-red-700 bg-red-50' : status === 'TODAY' ? 'text-amber-800 bg-amber-50' : 'text-blue-700 bg-blue-50'
  return <span data-fu={status} title={next ? `${KIND_LABEL[kind ?? ''] ?? ''} ${when(next)}` : ''} className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded ${tone}`}>
    <CalendarClock className="w-3 h-3" />{status === 'OVERDUE' ? 'Overdue' : status === 'TODAY' ? 'Today' : ''} {next ? when(next) : ''}</span>
}

export const initials = (n: string | null) => (n ?? '').split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase()

/** Owner + follow-ups section inside the lead drawer. */
export function LeadFollowUps({ lead, followUps, onChanged }: { lead: { id: string; stage: string; archived?: boolean; assigned_to?: string | null; project_id: string | null }; followUps: FollowUp[]; onChanged: () => void }) {
  const role = useRole(); const can = hasRole(role, WRITE)
  const { data: meta } = useLoad<CrmMeta>('/crm/meta')
  const [f, setF] = useState({ due: localInput(24), kind: 'CALL', note: '', assignee: '' })
  const [doing, setDoing] = useState<FollowUp | null>(null)
  const a = useAction()
  const closed = lead.archived || lead.stage === 'LOST' || lead.stage === 'WON'
  const assign = (uid: string) => a.run('assign', async () => { await api.post(`/leads/${lead.id}/assign`, { user_id: uid || null }); onChanged() })
  const add = (e: React.FormEvent) => { e.preventDefault(); a.run('add', async () => { await api.post(`/leads/${lead.id}/followups`, { due_at: toIso(f.due), kind: f.kind, note: f.note || undefined, assigned_to: f.assignee || undefined }); setF({ ...f, note: '', due: localInput(24) }); onChanged() }) }
  const open = followUps.filter(x => x.status === 'OPEN'); const past = followUps.filter(x => x.status !== 'OPEN')
  return (
    <div className="rounded-lg border border-stone-200 p-3 space-y-3" data-testid="lead-followups">
      <div className="flex items-center gap-2"><span className="text-[11px] text-stone-400 w-14">Owner</span>
        <select aria-label="Lead owner" disabled={!can} value={lead.assigned_to ?? ''} onChange={e => assign(e.target.value)} className={input + ' py-1 text-xs'}>
          <option value="">— unassigned —</option>{meta?.assignable.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></div>
      {a.error && <Alert>{a.error}</Alert>}
      <div><h3 className="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mb-1">Next steps</h3>
        {open.length === 0 ? <p className="text-xs text-stone-500">{closed ? 'This lead is closed.' : 'No follow-up scheduled — add the next call or visit below.'}</p> :
          <ul className="space-y-1.5" data-testid="open-followups">{open.map(x => <li key={x.id} data-followup={x.kind} className="flex items-start gap-2 text-xs">
            <Pill s={x.bucket === 'OVERDUE' ? 'FAIL' : x.bucket === 'TODAY' ? 'PART' : 'SENT'} label={x.bucket === 'OVERDUE' ? 'overdue' : x.bucket === 'TODAY' ? 'today' : 'upcoming'} />
            <span className="flex-1"><b>{KIND_LABEL[x.kind]}</b> · {when(x.due_at)}{x.assigned_name ? ` · ${x.assigned_name}` : ''}{x.note && <span className="block text-stone-500">{x.note}</span>}</span>
            {can && <button onClick={() => setDoing(x)} className={btn.small} aria-label={`Done ${KIND_LABEL[x.kind]}`}><Check className="w-3 h-3" />Done</button>}</li>)}</ul>}
      </div>
      {can && !closed && <form onSubmit={add} className="grid grid-cols-2 gap-2">
        <Field label="When"><input type="datetime-local" aria-label="Follow-up time" value={f.due} onChange={e => setF({ ...f, due: e.target.value })} required className={input + ' py-1 text-xs'} /></Field>
        <Field label="Type"><select aria-label="Follow-up type" value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })} className={input + ' py-1 text-xs'}>{(meta?.follow_up_kinds ?? ['CALL']).map(k => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></Field>
        <Field label="With (default: owner)"><select aria-label="Follow-up assignee" value={f.assignee} onChange={e => setF({ ...f, assignee: e.target.value })} className={input + ' py-1 text-xs'}>
          <option value="">Lead owner</option>{meta?.assignable.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
        <Field label="Note"><input aria-label="Follow-up note" value={f.note} onChange={e => setF({ ...f, note: e.target.value })} placeholder="What to discuss" className={input + ' py-1 text-xs'} /></Field>
        <button disabled={!!a.busy} className={btn.primary + ' col-span-2 text-xs'}>{a.busy === 'add' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}Schedule follow-up</button></form>}
      {past.length > 0 && <details className="text-xs"><summary className="cursor-pointer text-stone-500">{past.length} earlier follow-up(s)</summary>
        <ul className="mt-1 space-y-1">{past.map(x => <li key={x.id} className="text-stone-600"><b>{KIND_LABEL[x.kind]}</b> {when(x.due_at)} — {x.status === 'DONE' ? 'done' : 'cancelled'}: {x.outcome}</li>)}</ul></details>}
      {doing && <DoneDialog fu={doing} meta={meta} stage={lead.stage} converted={!!lead.project_id} onClose={() => setDoing(null)} onSaved={() => { setDoing(null); onChanged() }} />}
    </div>
  )
}

export function DoneDialog({ fu, meta, stage, converted, onClose, onSaved }: { fu: FollowUp; meta: CrmMeta | null | undefined; stage: string; converted: boolean; onClose: () => void; onSaved: () => void }) {
  const [outcome, setOutcome] = useState(''); const [next, setNext] = useState(true); const [due, setDue] = useState(localInput(72)); const [kind, setKind] = useState('CALL')
  const [nextStage, setNextStage] = useState(''); const a = useAction()
  const save = () => a.run('done', async () => {
    await api.post(`/followups/${fu.id}/done`, { outcome, stage: nextStage || undefined, next: next ? { due_at: toIso(due), kind } : undefined }); onSaved() })
  return <Drawer label="Follow-up done" title={`${KIND_LABEL[fu.kind]} with ${fu.lead_name ?? 'the lead'} — done`} onClose={onClose}>
    <Field label="Outcome (what happened?)"><textarea aria-label="Outcome" rows={3} value={outcome} onChange={e => setOutcome(e.target.value)} className={input} /></Field>
    {!converted && <Field label="Move the lead to (optional)"><select aria-label="Move lead to" value={nextStage} onChange={e => setNextStage(e.target.value)} className={input}>
      <option value="">Keep at {stage.replace('_', ' ').toLowerCase()}</option>{(meta?.stages ?? []).filter(s => !['WON', 'LOST', stage].includes(s)).map(s => <option key={s} value={s}>{s.replace('_', ' ').toLowerCase()}</option>)}</select></Field>}
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={next} onChange={e => setNext(e.target.checked)} />Book the next step now</label>
    {next && <div className="grid grid-cols-2 gap-2"><Field label="Next — when"><input type="datetime-local" aria-label="Next follow-up time" value={due} onChange={e => setDue(e.target.value)} className={input} /></Field>
      <Field label="Type"><select aria-label="Next follow-up type" value={kind} onChange={e => setKind(e.target.value)} className={input}>{(meta?.follow_up_kinds ?? ['CALL']).map(k => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></Field></div>}
    {a.error && <Alert>{a.error}</Alert>}
    <button onClick={save} disabled={outcome.trim().length < 3 || !!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save</button>
  </Drawer>
}

/** "Why was it lost?" — required before a lead moves to Lost (from the stage menu or by dragging). */
export function LostDialog({ name, onCancel, onConfirm }: { name: string; onCancel: () => void; onConfirm: (reason: string) => Promise<void> }) {
  const { data: meta } = useLoad<CrmMeta>('/crm/meta')
  const [pick, setPick] = useState(''); const [note, setNote] = useState(''); const a = useAction()
  const reason = [pick, note.trim()].filter(Boolean).join(' — ')
  return <Drawer label="Mark lost" title={`Why was ${name} lost?`} onClose={onCancel}>
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Lost reason">{meta?.lost_reasons.map(r => <button key={r} type="button" role="radio" aria-checked={pick === r} onClick={() => setPick(r)}
      className={`text-xs px-2.5 py-1 rounded-full border ${pick === r ? 'bg-red-700 border-red-700 text-white' : 'bg-white border-stone-200 text-stone-700'}`}>{r}</button>)}</div>
    <Field label="Details (optional)"><input aria-label="Lost details" value={note} onChange={e => setNote(e.target.value)} className={input} /></Field>
    <p className="text-[11px] text-stone-500">Open follow-ups on this lead are cancelled.</p>
    {a.error && <Alert>{a.error}</Alert>}
    <div className="flex gap-2"><button onClick={() => a.run('lost', () => onConfirm(reason))} disabled={reason.length < 3 || !!a.busy} className={btn.danger + ' flex-1'}>Mark lost</button>
      <button onClick={onCancel} className={btn.ghost}><X className="w-3.5 h-3.5" />Cancel</button></div>
  </Drawer>
}

/** CRM → Follow-ups: what to do today, what's overdue, what's coming. */
export function FollowUpsView() {
  const role = useRole(); const can = hasRole(role, WRITE)
  const [scope, setScope] = useState('mine'); const [tab, setTab] = useState<'overdue' | 'today' | 'upcoming' | 'done'>('today')
  const { data, reload, error } = useLoad<{ items: FollowUp[]; counts: Record<string, number> }>(`/followups?scope=${scope}&when=${tab}`)
  const { data: meta } = useLoad<CrmMeta>('/crm/meta')
  const [doing, setDoing] = useState<FollowUp | null>(null)
  const first = useRef(true)   // only on the first load: nothing today but something overdue → open Overdue
  useEffect(() => { if (!data || !first.current) return; first.current = false; if (data.counts.TODAY === 0 && data.counts.OVERDUE > 0) setTab('overdue') }, [data])
  const T = (k: typeof tab, l: string, n?: number) => <button role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`px-3 py-1.5 text-sm rounded ${tab === k ? 'bg-white shadow-sm font-medium' : 'text-stone-500'}`}>
    {l}{n !== undefined && <span className={`ml-1.5 text-[11px] px-1.5 rounded-full ${k === 'overdue' && n ? 'bg-red-600 text-white' : 'bg-stone-200 text-stone-600'}`}>{n}</span>}</button>
  return (
    <div className="space-y-5 max-w-[1100px]">
      <PageHeader title="Follow-ups" subtitle="Every open lead should have a next step. Do it, record the outcome, and book the next one in the same go.">
        <select aria-label="Whose follow-ups" value={scope} onChange={e => setScope(e.target.value)} className={ctl}><option value="mine">Mine</option><option value="team">Whole team</option>
          {meta?.assignable.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></PageHeader>
      <div className="flex gap-1 bg-stone-100 rounded p-1 w-fit" role="tablist">{T('overdue', 'Overdue', data?.counts.OVERDUE)}{T('today', 'Today', data?.counts.TODAY)}{T('upcoming', 'Upcoming', data?.counts.UPCOMING)}{T('done', 'Done')}</div>
      {error && <Alert>{error}</Alert>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!data ? <Empty>Loading…</Empty> : data.items.length === 0 ? <Empty>{tab === 'overdue' ? 'Nothing overdue. 👍' : 'Nothing here.'}</Empty> :
        <ul className="divide-y divide-stone-50" data-testid="followup-list">{data.items.map(x => <li key={x.id} data-followup-row={x.lead_name} className="px-4 py-3 flex items-start gap-3">
          <div className="w-28 shrink-0 text-xs"><p className={x.bucket === 'OVERDUE' ? 'text-red-700 font-semibold' : 'text-stone-700'}>{when(x.due_at)}</p><p className="text-stone-400">{KIND_LABEL[x.kind]}</p></div>
          <div className="flex-1 text-sm"><p className="font-medium text-stone-900">{x.lead_name}{x.lead_phone && <a href={`tel:${x.lead_phone}`} className="ml-2 text-xs text-amber-700 hover:underline">{x.lead_phone}</a>}</p>
            <p className="text-xs text-stone-500">{x.lead_stage?.replace('_', ' ').toLowerCase()}{x.lead_city ? ` · ${x.lead_city}` : ''}{x.assigned_name ? ` · ${x.assigned_name}` : ''}</p>
            {x.note && <p className="text-xs text-stone-600 mt-0.5">{x.note}</p>}{x.outcome && <p className="text-xs text-green-800 mt-0.5">Outcome: {x.outcome}</p>}</div>
          {can && x.status === 'OPEN' && <button onClick={() => setDoing(x)} className={btn.small} aria-label={`Done with ${x.lead_name}`}><Check className="w-3 h-3" />Done</button>}</li>)}</ul>}</div>
      {doing && <DoneDialog fu={doing} meta={meta} stage={doing.lead_stage ?? 'NEW'} converted={false} onClose={() => setDoing(null)} onSaved={() => { setDoing(null); reload() }} />}
    </div>
  )
}
