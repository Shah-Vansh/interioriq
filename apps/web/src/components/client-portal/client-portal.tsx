'use client'
import { useEffect, useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { api, downloadFile } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { fmtDate, Overview } from '@/lib/ops'
import { StageStepper } from '@/components/projects/project-detail'
import { Alert, btn, Card, ctl, Empty, input, Ok, PageHeader, Pill, useAction, useLoad, useRole } from '@/components/ui/kit'

export function ClientPortal() {
  const role = useRole()
  if (role && role !== 'CLIENT') return (
    <div className="max-w-2xl space-y-4"><PageHeader title="Client portal" subtitle="This is what your clients see when they sign in." />
      <Card><p className="text-sm text-stone-700">Create a login for a client in <b>Settings → Users</b> (role “Client”, linked to the client). They will see only their own projects: progress, quotations sent to them (which they can approve or reject), payments, deliveries and the handover certificate. Internal notes, costs and workshop details stay hidden.</p></Card></div>)
  return <Portal />
}

function Portal() {
  const { data: projects, error } = useLoad<{ id: string; project_number: string; name: string; status: string; progress: number }[]>('/portal/projects')
  const [pid, setPid] = useState('')
  useEffect(() => { if (!pid && projects?.length) setPid(projects[0].id) }, [projects, pid])
  const { data: o, reload } = useLoad<Overview>(pid ? `/portal/projects/${pid}` : null)
  const a = useAction(); const [note, setNote] = useState('')
  const decide = (bid: string, decision: 'APPROVED' | 'REJECTED') => a.run(bid + decision, async () => { await api.post(`/portal/boqs/${bid}/decision`, { decision, note: note || undefined }); setNote(''); await reload() },
    decision === 'APPROVED' ? 'Thank you — quotation approved.' : 'Quotation rejected. Our team will be in touch.')
  return (
    <div className="space-y-5 max-w-[1100px]">
      <PageHeader title="Your projects" subtitle="Progress, quotations, payments and deliveries for your home." >
        {projects && projects.length > 1 && <select value={pid} onChange={e => setPid(e.target.value)} aria-label="Your project" className={ctl}>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}</PageHeader>
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {!projects ? <Empty>Loading…</Empty> : projects.length === 0 ? <Empty>No projects are linked to your account yet.</Empty> : !o ? <Empty>Loading…</Empty> : <>
        <Card title={`${o.name} · ${o.project_number}`}><StageStepper stages={o.stages} index={o.stage_index} /><p className="text-xs text-stone-500 mt-2">{o.progress}% complete{o.target_date ? ` · target handover ${fmtDate(o.target_date)}` : ''}</p></Card>
        <Card title="Quotations">{o.quotations.length === 0 ? <Empty>No quotation has been sent to you yet.</Empty> : <ul className="divide-y divide-stone-50" data-testid="portal-quotes">{o.quotations.map(q => <li key={q.id} className="py-3 space-y-2">
          <div className="flex items-center gap-3 flex-wrap"><b className="font-mono text-sm">{q.quotation_no}</b><span className="text-sm">{q.room_name}</span><span className="text-sm font-semibold">{inr(q.grand_total)}</span><Pill s={q.status} />
            <button onClick={() => downloadFile(`/portal/boqs/${q.id}/quotation.pdf`, `${q.quotation_no}.pdf`).catch(e => a.setError(e.message))} className={btn.small + ' ml-auto'}><Download className="w-3 h-3" />PDF</button></div>
          {q.status === 'SENT' && <div className="flex gap-2 items-center flex-wrap"><input value={note} onChange={e => setNote(e.target.value)} placeholder="Comments (optional)" aria-label="Comments" className={input + ' max-w-sm'} />
            <button onClick={() => decide(q.id, 'APPROVED')} disabled={!!a.busy} className={btn.primary}>{a.busy === q.id + 'APPROVED' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Approve quotation</button>
            <button onClick={() => decide(q.id, 'REJECTED')} disabled={!!a.busy} className={btn.ghost}>Reject</button></div>}</li>)}</ul>}</Card>
        <div className="grid md:grid-cols-2 gap-4">
          <Card title="Payments"><div className="grid grid-cols-3 gap-2 text-center mb-3">{[['Total', o.payments.quoted], ['Paid', o.payments.paid], ['Balance', o.payments.balance]].map(([l, v]) => <div key={l} className="bg-stone-50 rounded p-2"><p className="text-[10px] uppercase text-stone-400">{l}</p><p className="text-sm font-semibold">{inr(v)}</p></div>)}</div>
            {o.payments.schedule.map(s => <div key={s.stage} className="flex justify-between text-xs py-1"><span>{s.stage} ({s.pct}%)</span><span>{inr(s.amount)} <Pill s={s.status} /></span></div>)}</Card>
          <Card title="Invoices">{!(o as Overview & { invoices?: { id: string; invoice_no: string; kind: string; issue_date: string; description: string; amount: string }[] }).invoices?.length ? <Empty>No invoices yet.</Empty> :
            <ul className="text-xs divide-y divide-stone-50" data-testid="portal-invoices">{(o as Overview & { invoices: { id: string; invoice_no: string; kind: string; issue_date: string; description: string; amount: string }[] }).invoices.map(i => <li key={i.id} className="py-1.5 flex items-center gap-2">
              <b className="font-mono">{i.invoice_no}</b><span className="text-stone-500">{fmtDate(i.issue_date)} · {i.description}{i.kind === 'TAX' ? ' · incl. GST' : ''}</span><b className="ml-auto">{inr(i.amount)}</b>
              <button onClick={() => downloadFile(`/portal/invoices/${i.id}/pdf`, i.invoice_no.replace(/\//g, '-') + '.pdf').catch(e => a.setError(e.message))} className={btn.small} aria-label={`PDF ${i.invoice_no}`}><Download className="w-3 h-3" />PDF</button></li>)}</ul>}
            {((o as Overview & { credit_notes?: { id: string; note_no: string; invoice_no: string; issue_date: string; reason: string; amount: string }[] }).credit_notes ?? []).length > 0 &&
              <ul className="text-xs divide-y divide-stone-50 mt-2 border-t border-stone-100" data-testid="portal-credit-notes">{(o as Overview & { credit_notes: { id: string; note_no: string; invoice_no: string; issue_date: string; reason: string; amount: string }[] }).credit_notes.map(n =>
                <li key={n.id} className="py-2 flex items-center gap-2 flex-wrap"><b className="font-mono">{n.note_no}</b><span className="text-stone-500">{fmtDate(n.issue_date)} · credit against {n.invoice_no} · {n.reason}</span>
                  <b className="ml-auto text-violet-800">−{inr(n.amount)}</b>
                  <button onClick={() => downloadFile(`/portal/credit-notes/${n.id}/pdf`, n.note_no.replace(/\//g, '-') + '.pdf').catch(e => a.setError(e.message))} className={btn.small} aria-label={`PDF ${n.note_no}`}><Download className="w-3 h-3" />PDF</button></li>)}</ul>}</Card>
          <Card title="Deliveries">{!o.deliveries?.length ? <Empty>Nothing delivered yet.</Empty> : <ul className="text-xs space-y-2">{o.deliveries.map(d => <li key={d.dn_number}><b>{d.dn_number}</b> <Pill s={d.status} /> {fmtDate(d.delivered_at ?? d.scheduled_on)}
            <p className="text-stone-500">{d.lines.map(l => `${l.description} × ${l.qty}`).join(', ')}</p></li>)}</ul>}</Card>
        </div>
        {o.handover && <Card title="Handover"><p className="text-sm text-green-800">Handed over to {o.handover.received_by} on {fmtDate(o.handover.handed_over_on)} · warranty {o.handover.warranty_months} months.</p>
          <button onClick={() => downloadFile(`/portal/projects/${o.id}/handover.pdf`, 'handover-certificate.pdf').catch(e => a.setError(e.message))} className={btn.ghost + ' mt-2'}><Download className="w-3.5 h-3.5" />Handover certificate</button></Card>}
        <Card title="Updates">{!o.timeline?.length ? <Empty>No updates yet.</Empty> : <ul className="divide-y divide-stone-50 text-sm" data-testid="portal-timeline">{o.timeline.map((e, i) => <li key={i} className="py-1.5 flex justify-between gap-3"><span>{e.text}</span><span className="text-[11px] text-stone-400 whitespace-nowrap">{fmtDate(e.created_at)}</span></li>)}</ul>}</Card>
      </>}
    </div>
  )
}
