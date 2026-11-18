'use client'
// Payables: what we owe suppliers. Bills (matched against goods received on the PO), payments (oldest due first or by hand), ageing, statements.
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { api, Supplier } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { fmtDate, isoDay, PO } from '@/lib/ops'
import { Alert, btn, Card, ctl, Drawer, Empty, Field, hasRole, input, PageHeader, Pill, Stat, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

export interface Bill { id: string; supplier_id: string; supplier_name: string | null; bill_no: string; bill_date: string; due_date: string; po_id: string | null; po_number: string | null
  project_id: string | null; project_number: string | null; taxable: string; gst: string; total: string; paid: string; outstanding: string
  status: 'OPEN' | 'PARTIAL' | 'PAID' | 'VOID'; match: string | null; approve_reason: string | null; overdue_days: number; note: string | null; void_reason: string | null }
interface Summary { totals: Record<string, string>; buckets: { key: string; label: string; amount: string }[]
  suppliers: (Record<string, string> & { supplier_id: string; supplier_name: string; bills: number })[]; due_soon: { bill_id: string; bill_no: string; supplier_name: string; due_date: string; days: number; outstanding: string }[] }
interface PaymentRow { id: string; supplier_id: string; supplier_name: string | null; amount: string; paid_on: string; mode: string; reference: string | null; status: 'ACTIVE' | 'VOID'; void_reason: string | null
  allocations: { bill_id: string; bill_no: string | null; amount: string }[] }
interface Statement { supplier_name: string; payment_terms_days: number; balance: string; entries: { date: string; type: 'BILL' | 'PAYMENT'; ref: string; bill: string | null; paid: string | null; balance: string; void: boolean; note: string | null }[] }
export const PAYABLES = ['ADMIN', 'PROJECT_MANAGER', 'PROCUREMENT_MANAGER']; const PAY = ['ADMIN', 'PROJECT_MANAGER']
const MATCH: Record<string, [string, string]> = { MATCHED: ['green', 'matched to goods received'], OVER_BILLED: ['red', 'over-billed (approved)'], UNDER_BILLED: ['amber', 'part-billed'], NO_PO: ['stone', 'no PO'] }

export function PayablesView() {
  const role = useRole(); const canPay = hasRole(role, PAY)
  const [tab, setTab] = useState<'overview' | 'bills' | 'payments'>('overview'); const [key, setKey] = useState(0)
  const { data: s, error } = useLoad<Summary>('/payables/summary', [key])
  const [status, setStatus] = useState('UNPAID')
  const { data: bills } = useLoad<Bill[]>(`/bills${status ? `?status=${status}` : ''}`, [key])
  const { data: pays } = useLoad<PaymentRow[]>('/supplier-payments', [key])
  const [open, setOpen] = useState<'bill' | 'pay' | null>(null); const [stmt, setStmt] = useState<string | null>(null); const [voiding, setVoiding] = useState<{ kind: 'bill' | 'pay'; id: string; label: string } | null>(null)
  const refresh = () => setKey(k => k + 1)
  const T = (k: typeof tab, l: string) => <button role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`px-3 py-1.5 text-sm rounded ${tab === k ? 'bg-white shadow-sm font-medium' : 'text-stone-500'}`}>{l}</button>
  return (
    <div className="space-y-5 max-w-[1400px]">
      <PageHeader title="Payables" subtitle="What you owe suppliers. Record each supplier bill (against its purchase order where possible — bills for more than was received need an approval reason), then record payments; they settle the oldest due bills first unless you choose.">
        <button onClick={() => setOpen('bill')} className={btn.ghost}><Plus className="w-3.5 h-3.5" />Record bill</button>
        {canPay && <button onClick={() => setOpen('pay')} className={btn.primary}><Plus className="w-3.5 h-3.5" />Record payment</button>}</PageHeader>
      {error && <Alert>{error}</Alert>}
      {s && <div className="grid grid-cols-2 md:grid-cols-4 gap-3"><Stat label="Owed to suppliers" value={inr(s.totals.outstanding)} />
        <Stat label="Overdue" value={inr(s.totals.overdue)} tone={s.totals.overdue !== '0.00' ? 'red' : 'green'} /><Stat label="Due in 7 days" value={inr(s.totals.due_7_days)} tone={s.totals.due_7_days !== '0.00' ? 'amber' : undefined} />
        <Stat label="Suppliers with balance" value={s.suppliers.length} /></div>}
      <div className="flex gap-1 bg-stone-100 rounded p-1 w-fit" role="tablist">{T('overview', 'Overview')}{T('bills', 'Bills')}{T('payments', 'Payments')}</div>

      {tab === 'overview' && s && <div className="grid grid-cols-12 gap-4">
        <Card title="Ageing" className="col-span-12 lg:col-span-5"><div className="space-y-1.5" data-testid="ageing">{s.buckets.map(b => <div key={b.key} className="flex justify-between text-sm">
          <span className={b.key === 'not_due' ? 'text-stone-600' : 'text-red-700'}>{b.label}</span><b>{inr(b.amount)}</b></div>)}</div>
          {s.due_soon.length > 0 && <><h3 className="text-xs font-semibold text-stone-500 uppercase mt-4 mb-1">Due in the next 7 days</h3>
            <ul className="text-xs space-y-1">{s.due_soon.map(d => <li key={d.bill_id} className="flex justify-between"><span>{d.supplier_name} · {d.bill_no} · {d.days === 0 ? 'today' : `in ${d.days}d`}</span><b>{inr(d.outstanding)}</b></li>)}</ul></>}</Card>
        <Card title="By supplier" className="col-span-12 lg:col-span-7">{s.suppliers.length === 0 ? <Empty>Nothing owed.</Empty> :
          <Table head={['Supplier', 'Bills', 'Outstanding', 'Overdue', '']} right={[1, 2, 3]}>{s.suppliers.map(r => <tr key={r.supplier_id} data-supplier={r.supplier_name}>
            <td className="px-4 py-2 text-sm">{r.supplier_name}</td><td className="px-4 py-2 text-right text-xs">{r.bills}</td><td className="px-4 py-2 text-right font-semibold">{inr(r.outstanding)}</td>
            <td className={`px-4 py-2 text-right text-xs ${r.overdue !== '0.00' ? 'text-red-700 font-semibold' : ''}`}>{inr(r.overdue)}</td>
            <td className="px-4 py-2"><button onClick={() => setStmt(r.supplier_id)} className={btn.small}>Statement</button></td></tr>)}</Table>}</Card></div>}

      {tab === 'bills' && <>
        <select value={status} onChange={e => setStatus(e.target.value)} aria-label="Bill status filter" className={ctl}><option value="UNPAID">Unpaid</option><option value="PAID">Paid</option><option value="VOID">Void</option><option value="">All</option></select>
        <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!bills ? <Empty>Loading…</Empty> : bills.length === 0 ? <Empty>No bills.</Empty> :
          <Table head={['Bill', 'Supplier', 'PO / project', 'Due', 'Total', 'Outstanding', 'Status', '']} right={[4, 5]}>{bills.map(b => <tr key={b.id} data-bill={b.bill_no} className={b.status === 'VOID' ? 'opacity-60' : ''}>
            <td className="px-4 py-2"><p className="font-mono text-xs font-semibold">{b.bill_no}</p><p className="text-[11px] text-stone-400">{fmtDate(b.bill_date)}</p></td>
            <td className="px-4 py-2 text-xs">{b.supplier_name}</td>
            <td className="px-4 py-2 text-xs">{b.po_number ?? '—'}{b.project_number && <> · <Link href={`/projects/${b.project_id}`} className="hover:underline">{b.project_number}</Link></>}
              {b.match && <div><Pill tone={MATCH[b.match][0]} label={MATCH[b.match][1]} /></div>}{b.approve_reason && <p className="text-[11px] text-stone-500">“{b.approve_reason}”</p>}</td>
            <td className={`px-4 py-2 text-xs ${b.overdue_days ? 'text-red-700 font-semibold' : ''}`}>{fmtDate(b.due_date)}{b.overdue_days ? ` (${b.overdue_days}d late)` : ''}</td>
            <td className="px-4 py-2 text-right text-xs">{inr(b.total)}{b.gst !== '0.00' && <p className="text-[10px] text-stone-400">incl. GST {inr(b.gst)}</p>}</td>
            <td className="px-4 py-2 text-right font-semibold">{inr(b.outstanding)}</td><td className="px-4 py-2"><Pill s={b.status === 'OPEN' ? 'DUE' : b.status} label={b.status.toLowerCase()} />{b.void_reason && <p className="text-[11px] text-red-700">{b.void_reason}</p>}</td>
            <td className="px-4 py-2">{b.status !== 'VOID' && b.paid === '0.00' && <button onClick={() => setVoiding({ kind: 'bill', id: b.id, label: `bill ${b.bill_no}` })} className={btn.small}>Void</button>}</td></tr>)}</Table>}</div></>}

      {tab === 'payments' && <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!pays ? <Empty>Loading…</Empty> : pays.length === 0 ? <Empty>No supplier payments yet.</Empty> :
        <Table head={['Date', 'Supplier', 'Mode / ref', 'Settled bills', 'Amount', '']} right={[4]}>{pays.map(p => <tr key={p.id} data-payment={p.reference ?? p.id} className={p.status === 'VOID' ? 'opacity-60' : ''}>
          <td className="px-4 py-2 text-xs">{fmtDate(p.paid_on)}</td><td className="px-4 py-2 text-xs">{p.supplier_name}</td><td className="px-4 py-2 text-xs">{p.mode}{p.reference ? ` · ${p.reference}` : ''}</td>
          <td className="px-4 py-2 text-xs">{p.allocations.map(a => `${a.bill_no} ${inr(a.amount)}`).join(', ')}{p.void_reason && <p className="text-red-700">void: {p.void_reason}</p>}</td>
          <td className="px-4 py-2 text-right font-semibold">{inr(p.amount)}</td>
          <td className="px-4 py-2">{canPay && p.status === 'ACTIVE' && <button onClick={() => setVoiding({ kind: 'pay', id: p.id, label: `payment ${inr(p.amount)}` })} className={btn.small}>Void</button>}</td></tr>)}</Table>}</div>}

      {open === 'bill' && <BillForm onClose={() => setOpen(null)} onSaved={() => { setOpen(null); setTab('bills'); refresh() }} />}
      {open === 'pay' && <PaymentForm onClose={() => setOpen(null)} onSaved={() => { setOpen(null); setTab('payments'); refresh() }} />}
      {stmt && <StatementDrawer supplierId={stmt} onClose={() => setStmt(null)} />}
      {voiding && <VoidDrawer v={voiding} onClose={() => setVoiding(null)} onSaved={() => { setVoiding(null); refresh() }} />}
    </div>
  )
}

function BillForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { data: sups } = useLoad<Supplier[]>('/suppliers'); const { data: pos } = useLoad<PO[]>('/purchase-orders')
  const usable = (pos ?? []).filter(p => ['ISSUED', 'PARTIAL', 'RECEIVED'].includes(p.status))
  const [f, setF] = useState({ po_id: '', supplier_id: '', bill_no: '', bill_date: isoDay(), due_date: '', taxable: '', gst: '', note: '', approve_reason: '' })
  const [check, setCheck] = useState<{ received: string; billed_before: string; left_to_bill: string; status: string; payment_terms_days: number } | null>(null)
  const a = useAction(); const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(p => ({ ...p, [k]: e.target.value }))
  const money = (s: string) => s.replace(/[₹,\s]/g, '')
  useEffect(() => {
    if (!f.po_id) { setCheck(null); return }
    const t = setTimeout(() => api.get<typeof check>(`/bills/po-check?po_id=${f.po_id}&taxable=${/^\d+(\.\d{1,2})?$/.test(money(f.taxable)) ? money(f.taxable) : 0}`).then(setCheck).catch(() => setCheck(null)), 300)
    return () => clearTimeout(t)
  }, [f.po_id, f.taxable])
  const save = (e: React.FormEvent) => {
    e.preventDefault()
    for (const [k, v] of [['Taxable value', f.taxable], ['GST', f.gst || '0']] as const) if (!/^\d+(\.\d{1,2})?$/.test(money(v))) { a.setError(`${k} must be a number with at most 2 decimals`); return }
    a.run('s', async () => { await api.post('/bills', { po_id: f.po_id || undefined, supplier_id: f.po_id ? undefined : f.supplier_id || undefined, bill_no: f.bill_no, bill_date: f.bill_date,
      due_date: f.due_date || undefined, taxable: money(f.taxable), gst: money(f.gst || '0'), note: f.note || undefined, approve_reason: f.approve_reason || undefined }); onSaved() })
  }
  return <Drawer label="Record bill" title="Record supplier bill" onClose={onClose}><form onSubmit={save} className="space-y-3">
    <Field label="Purchase order (recommended)"><select aria-label="Purchase order" value={f.po_id} onChange={set('po_id')} className={input}><option value="">— no PO (overheads, small purchases) —</option>
      {usable.map(p => <option key={p.id} value={p.id}>{p.po_number} · {p.supplier_name} · {p.status.toLowerCase()} · {inr(p.total)}</option>)}</select></Field>
    {!f.po_id && <Field label="Supplier"><select aria-label="Supplier" value={f.supplier_id} onChange={set('supplier_id')} className={input}><option value="">— pick —</option>{sups?.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>}
    {check && <p className={`text-xs rounded px-3 py-2 ${check.status === 'OVER_BILLED' ? 'bg-red-50 text-red-800' : 'bg-stone-50 text-stone-700'}`} data-testid="po-check">
      Goods received on this PO: <b>{inr(check.received)}</b> · already billed {inr(check.billed_before)} · left to bill <b>{inr(check.left_to_bill)}</b>. {check.status === 'OVER_BILLED' ? 'This bill is MORE than was received — an approval reason is required.' : ''} Terms: {check.payment_terms_days} days.</p>}
    <div className="grid grid-cols-2 gap-3">
      <Field label="Supplier's bill number"><input aria-label="Bill number" value={f.bill_no} onChange={set('bill_no')} required className={input} /></Field>
      <Field label="Bill date"><input type="date" value={f.bill_date} max={isoDay()} onChange={set('bill_date')} className={input} /></Field>
      <Field label="Taxable value (₹)"><input aria-label="Taxable value" value={f.taxable} onChange={set('taxable')} required inputMode="decimal" className={input} /></Field>
      <Field label="GST on the bill (₹, 0 if none)"><input aria-label="GST on the bill" value={f.gst} onChange={set('gst')} inputMode="decimal" placeholder="0" className={input} /></Field>
      <Field label="Due date (default: from terms)"><input type="date" aria-label="Due date" value={f.due_date} onChange={set('due_date')} className={input} /></Field>
      <Field label="Note"><input value={f.note} onChange={set('note')} className={input} /></Field></div>
    {check?.status === 'OVER_BILLED' && <Field label="Approval reason (why accept more than received)"><input aria-label="Approval reason" value={f.approve_reason} onChange={set('approve_reason')} className={input} /></Field>}
    {a.error && <Alert>{a.error}</Alert>}
    <button disabled={!!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save bill</button></form></Drawer>
}

function PaymentForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { data: sum } = useLoad<Summary>('/payables/summary')
  const [sid, setSid] = useState(''); const { data: bills } = useLoad<Bill[]>(sid ? `/bills?supplier_id=${sid}&status=UNPAID` : null)
  const [f, setF] = useState({ amount: '', paid_on: isoDay(), mode: 'BANK', reference: '' }); const [manual, setManual] = useState(false); const [alloc, setAlloc] = useState<Record<string, string>>({})
  const a = useAction(); const money = (s: string) => s.replace(/[₹,\s]/g, '')
  useEffect(() => { if (!sid && sum?.suppliers.length) setSid(sum.suppliers[0].supplier_id) }, [sum, sid])
  const owed = sum?.suppliers.find(s => s.supplier_id === sid)?.outstanding
  const save = (e: React.FormEvent) => {
    e.preventDefault(); const amt = money(f.amount)
    if (!/^\d+(\.\d{1,2})?$/.test(amt) || /^0+(\.0+)?$/.test(amt)) { a.setError('Amount must be a positive number with at most 2 decimals'); return }
    const allocations = manual ? Object.entries(alloc).filter(([, v]) => money(v)).map(([bill_id, v]) => ({ bill_id, amount: money(v) })) : undefined
    a.run('s', async () => { await api.post('/supplier-payments', { supplier_id: sid, amount: amt, paid_on: f.paid_on, mode: f.mode, reference: f.reference || undefined, allocations }); onSaved() })
  }
  return <Drawer label="Record payment" title="Pay a supplier" onClose={onClose}><form onSubmit={save} className="space-y-3">
    {sum && sum.suppliers.length === 0 ? <Empty>Nothing is owed to any supplier.</Empty> : <>
      <Field label="Supplier"><select aria-label="Supplier" value={sid} onChange={e => { setSid(e.target.value); setAlloc({}) }} className={input}>{sum?.suppliers.map(s => <option key={s.supplier_id} value={s.supplier_id}>{s.supplier_name} · owed {inr(s.outstanding)}</option>)}</select></Field>
      <div className="grid grid-cols-2 gap-3"><Field label={`Amount (₹)${owed ? ` — owed ${inr(owed)}` : ''}`}><input aria-label="Amount" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} inputMode="decimal" className={input} /></Field>
        <Field label="Paid on"><input type="date" value={f.paid_on} max={isoDay()} onChange={e => setF({ ...f, paid_on: e.target.value })} className={input} /></Field>
        <Field label="Mode"><select aria-label="Mode" value={f.mode} onChange={e => setF({ ...f, mode: e.target.value })} className={input}>{['BANK', 'UPI', 'CHEQUE', 'CASH', 'CARD'].map(x => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Reference (UTR / cheque no.)"><input aria-label="Reference" value={f.reference} onChange={e => setF({ ...f, reference: e.target.value })} className={input} /></Field></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={manual} onChange={e => setManual(e.target.checked)} />Choose which bills it settles (otherwise: oldest due first)</label>
      {manual && <Table head={['Bill', 'Due', 'Outstanding', 'Pay']} right={[2]}>{bills?.map(b => <tr key={b.id}><td className="px-3 py-1.5 font-mono text-xs">{b.bill_no}</td><td className="px-3 py-1.5 text-xs">{fmtDate(b.due_date)}</td>
        <td className="px-3 py-1.5 text-right text-xs">{inr(b.outstanding)}</td><td className="px-3 py-1.5"><input aria-label={`Pay ${b.bill_no}`} value={alloc[b.id] ?? ''} onChange={e => setAlloc({ ...alloc, [b.id]: e.target.value })} className={input + ' w-28 py-1'} /></td></tr>)}</Table>}
      {a.error && <Alert>{a.error}</Alert>}
      <button disabled={!!a.busy || !sid} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save payment</button></>}
  </form></Drawer>
}

export function StatementDrawer({ supplierId, onClose }: { supplierId: string; onClose: () => void }) {
  const { data: s, error } = useLoad<Statement>(`/suppliers/${supplierId}/statement`)
  return <Drawer label="Supplier statement" title={s ? `Statement · ${s.supplier_name}` : 'Statement'} onClose={onClose} wide>
    {error ? <Alert>{error}</Alert> : !s ? <Empty>Loading…</Empty> : <>
      <p className="text-sm">Balance owed: <b data-testid="statement-balance">{inr(s.balance)}</b> · payment terms {s.payment_terms_days} days</p>
      {s.entries.length === 0 ? <Empty>No bills or payments yet.</Empty> : <Table head={['Date', 'Document', 'Bill', 'Paid', 'Balance']} right={[2, 3, 4]}>{s.entries.map((e, i) => <tr key={i} className={e.void ? 'opacity-50 line-through' : ''}>
        <td className="px-3 py-1.5 text-xs">{fmtDate(e.date)}</td><td className="px-3 py-1.5 text-xs">{e.type === 'BILL' ? 'Bill' : 'Payment'} {e.ref}{e.note ? ` · ${e.note}` : ''}</td>
        <td className="px-3 py-1.5 text-right text-xs">{e.bill ? inr(e.bill) : ''}</td><td className="px-3 py-1.5 text-right text-xs">{e.paid ? inr(e.paid) : ''}</td><td className="px-3 py-1.5 text-right text-xs font-semibold">{inr(e.balance)}</td></tr>)}</Table>}</>}
  </Drawer>
}

function VoidDrawer({ v, onClose, onSaved }: { v: { kind: 'bill' | 'pay'; id: string; label: string }; onClose: () => void; onSaved: () => void }) {
  const [reason, setReason] = useState(''); const a = useAction()
  return <Drawer label="Void" title={`Void ${v.label}`} onClose={onClose}>
    <Field label="Reason"><input aria-label="Reason" value={reason} onChange={e => setReason(e.target.value)} className={input} /></Field>
    {a.error && <Alert>{a.error}</Alert>}
    <button disabled={reason.trim().length < 3 || !!a.busy} onClick={() => a.run('v', async () => { await api.post(v.kind === 'bill' ? `/bills/${v.id}/void` : `/supplier-payments/${v.id}/void`, { reason }); onSaved() })} className={btn.danger + ' w-full'}>Void</button>
  </Drawer>
}
