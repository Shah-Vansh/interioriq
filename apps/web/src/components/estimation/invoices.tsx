'use client'
// Invoices. GST is optional: it follows each quotation's "Include GST" switch (GST on → Tax Invoice, off → plain Invoice, no GST anywhere).
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Download, Loader2, Plus } from 'lucide-react'
import { api, downloadFile } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { fmtDate, isoDay } from '@/lib/ops'
import { Alert, btn, ctl, Drawer, Empty, Field, hasRole, input, Ok, PageHeader, Pill, Table, useAction, useLoad, useRole } from '@/components/ui/kit'
import { SendButton } from '@/components/notify/send'

export interface Invoice { id: string; invoice_no: string; kind: 'TAX' | 'PLAIN'; status: 'ISSUED' | 'CANCELLED'; project_id: string; boq_id: string; issue_date: string; description: string
  amount: string; taxable: string; gst_rate: string; cgst: string; sgst: string; igst: string; place_of_supply: string | null; place_of_supply_name: string | null; buyer_name: string | null
  cancel_reason: string | null; user_name: string | null; project_number?: string; project_name?: string }
interface Milestone { stage: string; pct: number; amount: string; invoiced: string; remaining: string }
interface QuoteInv { boq_id: string; quotation_no: string; grand_total: string; gst_enabled: boolean; gst_pct: string; invoiced: string; remaining: string; milestones: Milestone[] }
interface ProjectInv { quotations: QuoteInv[]; invoices: Invoice[]; totals: { invoiced: string; paid: string; receivable: string }; states: Record<string, string> }
const WRITE = ['ADMIN', 'PROJECT_MANAGER', 'SALES']
const fileName = (no: string) => no.replace(/\//g, '-') + '.pdf'

export function GstBreakup({ i }: { i: Invoice }) {
  if (i.kind === 'PLAIN') return <span className="text-[11px] text-stone-400">No GST</span>
  return <span className="text-[11px] text-stone-500">taxable {inr(i.taxable)} · {i.igst !== '0.00' ? `IGST ${inr(i.igst)}` : `CGST ${inr(i.cgst)} + SGST ${inr(i.sgst)}`}</span>
}

/** Invoices card on the project page. */
export function ProjectInvoices({ projectId, onChanged }: { projectId: string; onChanged?: () => void }) {
  const role = useRole(); const can = hasRole(role, WRITE)
  const { data, reload, error } = useLoad<ProjectInv>(`/projects/${projectId}/invoices`)
  const [raising, setRaising] = useState(false); const [cancelling, setCancelling] = useState<Invoice | null>(null); const a = useAction()
  const refresh = () => { reload(); onChanged?.() }
  if (error) return <Alert>{error}</Alert>
  if (!data) return <Empty>Loading…</Empty>
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 text-center">{([['Invoiced', data.totals.invoiced], ['Paid', data.totals.paid], ['Receivable', data.totals.receivable]] as const).map(([l, v]) =>
        <div key={l} className="bg-stone-50 rounded p-2"><p className="text-[10px] uppercase text-stone-400">{l}</p><p data-testid={`inv-${l}`} className="text-sm font-semibold">{inr(v)}</p></div>)}</div>
      {a.error && <Alert>{a.error}</Alert>}
      {data.invoices.length > 0 && <ul className="divide-y divide-stone-50" data-testid="invoice-list">{data.invoices.map(i => <li key={i.id} data-invoice={i.invoice_no} className="py-2 text-xs space-y-0.5">
        <div className="flex items-center gap-2 flex-wrap"><b className="font-mono">{i.invoice_no}</b><Pill s={i.status === 'CANCELLED' ? 'CANCELLED' : i.kind === 'TAX' ? 'APPROVED' : 'PENDING'} label={i.status === 'CANCELLED' ? 'Cancelled' : i.kind === 'TAX' ? 'Tax invoice' : 'Invoice'} />
          <span className="ml-auto font-semibold">{inr(i.amount)}</span></div>
        <div className="flex items-center gap-2 flex-wrap"><span className="text-stone-600">{fmtDate(i.issue_date)} · {i.description}</span><GstBreakup i={i} />
          <button onClick={() => a.run(i.id, () => downloadFile(`/invoices/${i.id}/pdf`, fileName(i.invoice_no)))} className={btn.small + ' ml-auto'} aria-label={`PDF ${i.invoice_no}`}><Download className="w-3 h-3" />PDF</button>
          {i.status === 'ISSUED' && <SendButton kind="INVOICE" refId={i.id} onSent={refresh} />}
          {can && i.status === 'ISSUED' && <button onClick={() => setCancelling(i)} className={btn.small}>Cancel</button>}</div>
        {i.cancel_reason && <p className="text-red-700">Cancelled: {i.cancel_reason}</p>}</li>)}</ul>}
      {can && data.quotations.length > 0 && <button onClick={() => setRaising(true)} className={btn.ghost + ' w-full'}><Plus className="w-3.5 h-3.5" />Raise invoice</button>}
      {data.quotations.length === 0 && <p className="text-[11px] text-stone-400">Invoices can be raised once a quotation is approved.</p>}
      {raising && <RaiseInvoice projectId={projectId} data={data} onClose={() => setRaising(false)} onSaved={() => { setRaising(false); refresh() }} />}
      {cancelling && <CancelInvoice inv={cancelling} onClose={() => setCancelling(null)} onSaved={() => { setCancelling(null); refresh() }} />}
    </div>
  )
}

function RaiseInvoice({ projectId, data, onClose, onSaved }: { projectId: string; data: ProjectInv; onClose: () => void; onSaved: () => void }) {
  const [bid, setBid] = useState(data.quotations[0].boq_id)
  const q = data.quotations.find(x => x.boq_id === bid)!
  const open = q.milestones.filter(m => m.remaining !== '0.00')
  const [mode, setMode] = useState<'milestone' | 'amount'>(open.length ? 'milestone' : 'amount')
  const [milestone, setMilestone] = useState(open[0]?.stage ?? ''); const [amount, setAmount] = useState(''); const [desc, setDesc] = useState('')
  const [date, setDate] = useState(isoDay()); const [pos, setPos] = useState('')
  const a = useAction()
  useEffect(() => { setMilestone(q.milestones.find(m => m.remaining !== '0.00')?.stage ?? '') }, [bid]) // eslint-disable-line react-hooks/exhaustive-deps
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const body: Record<string, unknown> = { boq_id: bid, issue_date: date }
    if (mode === 'milestone') { if (!milestone) { a.setError('Every milestone is fully invoiced'); return } body.milestone = milestone }
    else {
      const amt = amount.replace(/[₹,\s]/g, '')
      if (!/^\d+(\.\d{1,2})?$/.test(amt) || /^0+(\.0+)?$/.test(amt)) { a.setError('Amount must be a positive number with at most 2 decimals'); return }
      body.amount = amt; body.description = desc.trim() || 'Interior works'
    }
    if (q.gst_enabled && pos) body.place_of_supply = pos
    a.run('s', async () => { await api.post(`/projects/${projectId}/invoices`, body); onSaved() })
  }
  return (
    <Drawer label="Raise invoice" title="Raise invoice" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Quotation"><select aria-label="Quotation" value={bid} onChange={e => setBid(e.target.value)} className={input}>{data.quotations.map(x => <option key={x.boq_id} value={x.boq_id}>{x.quotation_no} · {inr(x.grand_total)} · {inr(x.remaining)} left</option>)}</select></Field>
        <p className={`text-xs rounded px-3 py-2 ${q.gst_enabled ? 'bg-blue-50 text-blue-900' : 'bg-stone-100 text-stone-700'}`} data-testid="gst-mode">
          {q.gst_enabled ? `GST is ON for this quotation (${q.gst_pct}%): this will be a TAX INVOICE — the amount includes GST, split into CGST + SGST (same state) or IGST.` : 'GST is OFF for this quotation: this will be a plain INVOICE with no GST.'}</p>
        <div className="flex gap-4 text-sm"><label className="flex items-center gap-1.5"><input type="radio" checked={mode === 'milestone'} onChange={() => setMode('milestone')} disabled={!open.length} />Payment milestone</label>
          <label className="flex items-center gap-1.5"><input type="radio" checked={mode === 'amount'} onChange={() => setMode('amount')} />Other amount</label></div>
        {mode === 'milestone' ? <Field label="Milestone"><select aria-label="Milestone" value={milestone} onChange={e => setMilestone(e.target.value)} className={input}>
          {q.milestones.map(m => <option key={m.stage} value={m.stage} disabled={m.remaining === '0.00'}>{m.stage} ({m.pct}%) — {m.remaining === '0.00' ? 'invoiced' : `${inr(m.remaining)} to invoice`}</option>)}</select></Field>
          : <div className="grid grid-cols-2 gap-3"><Field label="Amount (₹, incl. GST if on)"><input aria-label="Amount" value={amount} onChange={e => setAmount(e.target.value)} inputMode="decimal" className={input} /></Field>
            <Field label="Description"><input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Advance / extra work…" className={input} /></Field></div>}
        <div className="grid grid-cols-2 gap-3"><Field label="Invoice date"><input type="date" value={date} max={isoDay()} onChange={e => setDate(e.target.value)} className={input} /></Field>
          {q.gst_enabled && <Field label="Place of supply"><select aria-label="Place of supply" value={pos} onChange={e => setPos(e.target.value)} className={input}>
            <option value="">Automatic (client GSTIN, else our state)</option>{Object.entries(data.states).map(([k, v]) => <option key={k} value={k}>{k} - {v}</option>)}</select></Field>}</div>
        {a.error && <Alert>{a.error}</Alert>}
        <button disabled={!!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Issue {q.gst_enabled ? 'tax invoice' : 'invoice'}</button>
        <p className="text-[11px] text-stone-400">An issued invoice can't be edited — only cancelled with a reason. Its number is never reused.</p>
      </form>
    </Drawer>
  )
}

function CancelInvoice({ inv, onClose, onSaved }: { inv: Invoice; onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState(''); const a = useAction()
  return <Drawer label="Cancel invoice" title={`Cancel ${inv.invoice_no}`} onClose={onClose}>
    <Field label="Reason"><input aria-label="Reason" value={reason} onChange={e => setReason(e.target.value)} className={input} /></Field>
    {a.error && <Alert>{a.error}</Alert>}
    <button onClick={() => a.run('c', async () => { await api.post(`/invoices/${inv.id}/cancel`, { reason }); onSaved() })} disabled={reason.trim().length < 3 || !!a.busy} className={btn.danger + ' w-full'}>Cancel invoice</button>
  </Drawer>
}

/** Estimation → Invoices: every invoice across projects. */
export function InvoicesView() {
  const [status, setStatus] = useState(''); const [kind, setKind] = useState(''); const [q, setQ] = useState('')
  const p = new URLSearchParams(); if (status) p.set('status', status); if (kind) p.set('kind', kind); if (q.trim()) p.set('q', q.trim())
  const { data: rows, error } = useLoad<Invoice[]>(`/invoices?${p}`); const a = useAction()
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Invoices" subtitle="Raised from a project page against an approved quotation. GST follows the quotation's “Include GST” switch: Tax Invoice (taxable value + CGST/SGST or IGST) when on, plain Invoice with no GST when off." />
      <div className="flex gap-2 flex-wrap">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search number, project, client…" aria-label="Search invoices" className={ctl + ' w-64'} />
        <select value={kind} onChange={e => setKind(e.target.value)} aria-label="Type filter" className={ctl}><option value="">Any type</option><option value="TAX">Tax invoices (GST)</option><option value="PLAIN">Invoices without GST</option></select>
        <select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status filter" className={ctl}><option value="">Any status</option><option value="ISSUED">Issued</option><option value="CANCELLED">Cancelled</option></select>
      </div>
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!rows ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>No invoices yet. Open a project with an approved quotation and press “Raise invoice”.</Empty> :
        <Table head={['Invoice', 'Date', 'Project / client', 'Description', 'Type', 'Amount', '']} right={[5]}>{rows.map(i => <tr key={i.id} data-invoice={i.invoice_no} className={i.status === 'CANCELLED' ? 'opacity-60' : ''}>
          <td className="px-4 py-2.5 font-mono text-xs font-semibold">{i.invoice_no}</td><td className="px-4 py-2.5 text-xs">{fmtDate(i.issue_date)}</td>
          <td className="px-4 py-2.5 text-xs"><Link href={`/projects/${i.project_id}`} className="hover:underline">{i.project_number} · {i.project_name}</Link><p className="text-stone-400">{i.buyer_name}</p></td>
          <td className="px-4 py-2.5 text-xs">{i.description}{i.status === 'CANCELLED' && <p className="text-red-700">Cancelled: {i.cancel_reason}</p>}</td>
          <td className="px-4 py-2.5"><Pill tone={i.kind === 'TAX' ? 'blue' : 'stone'} label={i.kind === 'TAX' ? `GST ${i.gst_rate}%` : 'No GST'} /><div><GstBreakup i={i} /></div></td>
          <td className="px-4 py-2.5 text-right font-semibold">{inr(i.amount)}</td>
          <td className="px-4 py-2.5"><button onClick={() => a.run(i.id, () => downloadFile(`/invoices/${i.id}/pdf`, fileName(i.invoice_no)))} className={btn.small} aria-label={`PDF ${i.invoice_no}`}><Download className="w-3 h-3" />PDF</button></td></tr>)}</Table>}</div>
    </div>
  )
}
