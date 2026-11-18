'use client'
import { useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { api, downloadFile } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { isoDay, PaymentSummary, Quotation, quoteActions } from '@/lib/ops'
import { Alert, btn, Drawer, errMsg, Field, input, Ok, Pill } from '@/components/ui/kit'
import { SendButton } from '@/components/notify/send'

const LABEL = { SENT: 'Mark sent', APPROVED: 'Approve', REJECTED: 'Reject' } as const

/** Send / approve / reject buttons for one quotation (a rejection asks for the reason). */
export function QuoteActions({ q, canEdit, onChanged }: { q: Quotation; canEdit: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(''); const [error, setError] = useState(''); const [rejecting, setRejecting] = useState(false); const [note, setNote] = useState('')
  const go = async (status: string, n?: string) => {
    setBusy(status); setError('')
    try { await api.post(`/boqs/${q.id}/status`, { status, note: n || undefined }); setRejecting(false); setNote(''); onChanged() } catch (e) { setError(errMsg(e)) } finally { setBusy('') }
  }
  const pdf = () => downloadFile(`/boqs/${q.id}/quotation.pdf`, `${q.quotation_no}.pdf`).catch(e => setError(errMsg(e)))
  return (
    <div className="space-y-1.5">
      <div className="flex gap-1.5 flex-wrap items-center">
        <button onClick={pdf} className={btn.small} aria-label={`PDF ${q.quotation_no}`}><Download className="w-3 h-3" />PDF</button>
        {q.status !== 'SUPERSEDED' && <SendButton kind="QUOTATION" refId={q.id} canMarkSent={q.status === 'DRAFT' || q.status === 'REJECTED'} onSent={onChanged} />}
        {canEdit && quoteActions(q.status).map(a => a === 'REJECTED'
          ? <button key={a} onClick={() => setRejecting(r => !r)} className={btn.small}>{LABEL[a]}</button>
          : <button key={a} onClick={() => go(a)} disabled={!!busy} className={btn.small} aria-label={`${LABEL[a]} ${q.quotation_no}`}>{busy === a && <Loader2 className="w-3 h-3 animate-spin" />}{LABEL[a]}</button>)}
      </div>
      {rejecting && <div className="flex gap-1.5"><input value={note} onChange={e => setNote(e.target.value)} placeholder="Reason for rejection" aria-label="Reason for rejection" className={input + ' text-xs py-1'} />
        <button onClick={() => go('REJECTED', note)} disabled={!note.trim() || !!busy} className={btn.small}>Confirm</button></div>}
      {error && <Alert>{error}</Alert>}
    </div>
  )
}

/** Payment schedule + record-payment form for a project. */
export function Payments({ projectId, summary, approved, canPay, onChanged }: { projectId: string; summary: PaymentSummary; approved: Quotation[]; canPay: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 text-center">
        {[['Quoted', summary.quoted], ['Received', summary.paid], ['Balance', summary.balance]].map(([l, v]) => <div key={l} className="bg-stone-50 rounded p-2">
          <p className="text-[10px] uppercase text-stone-400">{l}</p><p data-testid={`pay-${l}`} className="text-sm font-semibold text-stone-900">{inr(v)}</p></div>)}
      </div>
      {summary.schedule.length > 0 && <table className="w-full text-xs"><tbody className="divide-y divide-stone-50">{summary.schedule.map(s => <tr key={s.stage}>
        <td className="py-1.5 text-stone-600">{s.stage} ({s.pct}%)</td><td className="py-1.5 text-right">{inr(s.amount)}</td><td className="py-1.5 text-right"><Pill s={s.status} /></td></tr>)}</tbody></table>}
      {summary.payments.length > 0 && <ul className="text-xs divide-y divide-stone-50" data-testid="payments">{summary.payments.map(p => <li key={p.id} className="py-1.5 flex justify-between">
        <span>{p.received_on} · {p.mode}{p.reference ? ` · ${p.reference}` : ''}</span><b>{inr(p.amount)}</b></li>)}</ul>}
      {canPay && approved.length > 0 && <button onClick={() => setOpen(true)} className={btn.ghost + ' w-full'}>Record payment</button>}
      {canPay && approved.length === 0 && <p className="text-[11px] text-stone-400">Payments can be recorded once a quotation is approved.</p>}
      {open && <PaymentForm projectId={projectId} approved={approved} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); onChanged() }} />}
    </div>
  )
}

function PaymentForm({ projectId, approved, onClose, onSaved }: { projectId: string; approved: Quotation[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ boq_id: approved[0].id, amount: '', received_on: isoDay(), mode: 'BANK', reference: '', note: '' })
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [ok, setOk] = useState('')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(p => ({ ...p, [k]: e.target.value }))
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError('')
    const amt = f.amount.replace(/[₹,\s]/g, '')
    if (!/^\d+(\.\d{1,2})?$/.test(amt) || /^0+(\.0+)?$/.test(amt)) { setError('Amount must be a positive number with at most 2 decimals'); return }
    setBusy(true)
    try { await api.post(`/projects/${projectId}/payments`, { ...f, amount: amt, reference: f.reference || undefined, note: f.note || undefined }); setOk('Saved'); onSaved() }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  return (
    <Drawer label="Record payment" title="Record payment" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Against quotation"><select aria-label="Against quotation" value={f.boq_id} onChange={set('boq_id')} className={input}>{approved.map(q => <option key={q.id} value={q.id}>{q.quotation_no} · {inr(q.grand_total)} (paid {inr(q.paid)})</option>)}</select></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount (₹)"><input value={f.amount} onChange={set('amount')} required inputMode="decimal" className={input} /></Field>
          <Field label="Received on"><input type="date" value={f.received_on} max={isoDay()} onChange={set('received_on')} required className={input} /></Field>
          <Field label="Mode"><select aria-label="Mode" value={f.mode} onChange={set('mode')} className={input}>{['BANK', 'UPI', 'CHEQUE', 'CASH', 'CARD'].map(m => <option key={m}>{m}</option>)}</select></Field>
          <Field label="Reference (UTR / cheque no.)"><input value={f.reference} onChange={set('reference')} className={input} /></Field>
        </div>
        <Field label="Note"><input value={f.note} onChange={set('note')} className={input} /></Field>
        {error && <Alert>{error}</Alert>}{ok && <Ok>{ok}</Ok>}
        <button disabled={busy} className={btn.primary + ' w-full py-2'}>{busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save payment</button>
      </form>
    </Drawer>
  )
}
