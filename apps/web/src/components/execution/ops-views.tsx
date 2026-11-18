'use client'
// Execution screens (M10–M11). Each screen is a thin view over the operations API; every rule (what can be ordered, delivered, passed, handed over)
// is enforced by the server and its message is shown as-is.
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Download, Loader2 } from 'lucide-react'
import { api, downloadFile } from '@/lib/api'
import { CatItem } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { timeAgo } from '@/lib/crm-logic'
import { CutList, DeliveryNote, Fulfilment, fmtDate, HandoverState, InstallTask, isoDay, PO, ProcureResult, QCState, Quotation, UserRow, WorkOrder, WO_STAGES, woNeighbours } from '@/lib/ops'
import { Alert, btn, Card, ctl, Drawer, Empty, Field, hasRole, input, Ok, PageHeader, Pill, ProjectPicker, Table, useAction, useLoad, useRole } from '@/components/ui/kit'
import { SendButton } from '@/components/notify/send'

const PROC = ['ADMIN', 'PROJECT_MANAGER', 'PROCUREMENT_MANAGER'], RECEIVE = [...PROC, 'INVENTORY_MANAGER'], MFG = ['ADMIN', 'PROJECT_MANAGER', 'MANUFACTURING_MANAGER']
const DELIV = ['ADMIN', 'PROJECT_MANAGER', 'INVENTORY_MANAGER', 'INSTALLATION_MANAGER'], INSTALL = ['ADMIN', 'PROJECT_MANAGER', 'INSTALLATION_MANAGER', 'SITE_ENGINEER']
const QC = ['ADMIN', 'PROJECT_MANAGER', 'QC_MANAGER'], SNAG = [...QC, 'INSTALLATION_MANAGER', 'SITE_ENGINEER'], HANDOVER = ['ADMIN', 'PROJECT_MANAGER']
const pdf = (path: string, name: string, onErr: (m: string) => void) => downloadFile(path, name).catch(e => onErr(e.message))

/** Approved quotations of the chosen project. */
function useApproved(pid: string) {
  const { data } = useLoad<Quotation[]>(pid ? `/quotations?project_id=${pid}&status=APPROVED` : null)
  return data
}

// ── Procurement ───────────────────────────────────────────────────────────────
export function ProcurementView() {
  const role = useRole(); const [pid, setPid] = useState(''); const approved = useApproved(pid); const [bid, setBid] = useState('')
  useEffect(() => { setBid(approved?.[0]?.id ?? '') }, [approved])
  const { data: f, reload, error } = useLoad<Fulfilment>(bid ? `/boqs/${bid}/fulfilment` : null)
  const [useStock, setUseStock] = useState(true); const [res, setRes] = useState<ProcureResult | null>(null); const a = useAction()
  const go = () => a.run('p', async () => { setRes(await api.post<ProcureResult>(`/boqs/${bid}/procure`, { use_stock: useStock })); reload() })
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Procurement" subtitle="From an APPROVED quotation: allocate what's already in stock, then raise draft purchase orders (one per supplier) for the rest — including boards and edge band from the cutting lists. Running it again only orders what's still missing." />
      <div className="flex gap-2 flex-wrap"><ProjectPicker value={pid} onChange={setPid} />
        <select value={bid} onChange={e => setBid(e.target.value)} aria-label="Approved quotation" className={ctl}>{!approved?.length && <option value="">No approved quotation</option>}
          {approved?.map(q => <option key={q.id} value={q.id}>{q.quotation_no} · {q.room_name}</option>)}</select></div>
      {error && <Alert>{error}</Alert>}
      {!bid ? <Empty>Approve a quotation for this project first (Estimation → Quotations).</Empty> : !f ? <Empty>Loading…</Empty> : <>
        <Card title={`What ${f.boq.quotation_no} needs`} right={hasRole(role, PROC) && <div className="flex items-center gap-3">
          <label className="text-xs text-stone-600 flex items-center gap-1.5"><input type="checkbox" checked={useStock} onChange={e => setUseStock(e.target.checked)} />Use stock first</label>
          <button onClick={go} disabled={!!a.busy} className={btn.primary}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Raise purchase orders</button></div>}>
          <Table head={['Item', 'Made / bought', 'Qty', 'Ready', 'On order', 'Delivered', 'Supplier']} right={[2, 3, 4, 5]}>
            {f.lines.map(l => <tr key={l.line} data-line={l.sku ?? l.description}><td className="px-4 py-2"><p className="font-medium">{l.description}</p><p className="text-[11px] text-stone-400">{l.sku ?? 'not in catalogue'} · {l.category}</p></td>
              <td className="px-4 py-2"><Pill tone={l.kind === 'MANUFACTURED' ? 'violet' : l.kind === 'MANUAL' ? 'amber' : 'blue'} label={l.kind === 'MANUFACTURED' ? 'Made in-house' : l.kind === 'MANUAL' ? 'Outside system' : 'Bought out'} /></td>
              <td className="px-4 py-2 text-right">{l.qty} {l.unit}</td><td className="px-4 py-2 text-right">{l.ready}</td><td className="px-4 py-2 text-right">{l.on_order || '—'}</td>
              <td className="px-4 py-2 text-right">{l.delivered}</td><td className="px-4 py-2 text-xs text-stone-500">{l.kind === 'MANUFACTURED' ? 'Workshop' : l.supplier ?? '—'}</td></tr>)}
          </Table>
          <p className="text-xs text-stone-500 mt-3">Boards from cutting lists: {Object.entries(f.boards.sheets).map(([t, n]) => `${n} × ${t}mm sheets`).join(', ') || 'none'} · edge band {f.boards.edge_band_m} m.
            {' '}Set the board/edge-band SKUs in <Link href="/settings/company" className="underline">Settings → Company</Link> to order them automatically.</p>
        </Card>
        {a.error && <Alert>{a.error}</Alert>}
        {res && <Card title="Result"><div className="text-sm space-y-1.5" data-testid="procure-result">
          {res.nothing_to_do && <p className="text-green-700">Nothing left to order — everything is allocated or on order.</p>}
          {res.allocated_from_stock.length > 0 && <p>Allocated from stock: {res.allocated_from_stock.map(x => `${x.sku} × ${x.qty}`).join(', ')}</p>}
          {res.created.map(p => <p key={p.id}>Drafted <Link href={`/execution/po?open=${p.id}`} className="font-semibold text-amber-800 underline">{p.po_number}</Link> for {p.supplier_name} · {inr(p.total)}</p>)}
          {res.unassigned.length > 0 && <p className="text-amber-800">No supplier set (assign one in the catalogue, then run again): {res.unassigned.join('; ')}</p>}
          {res.manual.length > 0 && <p className="text-stone-500">Not in the catalogue — procure outside the system: {res.manual.join(', ')}</p>}</div></Card>}
      </>}
    </div>
  )
}

// ── Purchase orders ───────────────────────────────────────────────────────────
export function POView() {
  const [status, setStatus] = useState(''); const [open, setOpen] = useState<string | null>(null)
  useEffect(() => { const id = new URLSearchParams(window.location.search).get('open'); if (id) setOpen(id) }, [])
  const { data: pos, error, reload } = useLoad<PO[]>(`/purchase-orders${status ? `?status=${status}` : ''}`)
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Purchase orders" subtitle="Drafts can be edited; issue to send; receive goods line by line (stock comes in and is allocated to the project in the ledger)." />
      <select value={status} onChange={e => setStatus(e.target.value)} aria-label="PO status filter" className={ctl}>{['', 'DRAFT', 'ISSUED', 'PARTIAL', 'RECEIVED', 'CANCELLED'].map(s => <option key={s} value={s}>{s || 'Any status'}</option>)}</select>
      {error && <Alert>{error}</Alert>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!pos ? <Empty>Loading…</Empty> : pos.length === 0 ? <Empty>No purchase orders. Raise them from Procurement.</Empty> :
        <Table head={['PO', 'Supplier', 'Project', 'Expected', 'Total', 'Received', 'Status']} right={[4, 5]}>
          {pos.map(p => <tr key={p.id} data-po={p.po_number} onClick={() => setOpen(p.id)} className="cursor-pointer hover:bg-stone-50">
            <td className="px-4 py-2.5 font-mono text-xs font-semibold">{p.po_number}</td><td className="px-4 py-2.5 text-xs">{p.supplier_name}</td>
            <td className="px-4 py-2.5 text-xs">{p.project_number}</td><td className="px-4 py-2.5 text-xs">{fmtDate(p.expected_on)}</td>
            <td className="px-4 py-2.5 text-right font-semibold">{inr(p.total)}</td><td className="px-4 py-2.5 text-right text-xs">{p.received_pct}%</td><td className="px-4 py-2.5"><Pill s={p.status} /></td></tr>)}
        </Table>}</div>
      {open && <PODrawer id={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </div>
  )
}

function PODrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const role = useRole(); const { data: po, reload, setData } = useLoad<PO>(`/purchase-orders/${id}`); const a = useAction()
  const [recv, setRecv] = useState<Record<string, string>>({}); const [qtys, setQtys] = useState<Record<string, string>>({}); const [rates, setRates] = useState<Record<string, string>>({}); const [expected, setExpected] = useState('')
  useEffect(() => { if (po) { setExpected(po.expected_on ?? ''); setQtys(Object.fromEntries((po.lines ?? []).map(l => [l.id, String(l.qty)]))); setRates(Object.fromEntries((po.lines ?? []).map(l => [l.id, l.rate]))) } }, [po])
  if (!po) return <Drawer label="Purchase order" title="Loading…" onClose={onClose}><Empty>Loading…</Empty></Drawer>
  const act = (k: string, fn: () => Promise<PO>, ok: string) => a.run(k, async () => { setData(await fn()); onChanged() }, ok)
  const canProc = hasRole(role, PROC), canRecv = hasRole(role, RECEIVE)
  const receive = () => {
    const lines = Object.entries(recv).filter(([, v]) => v.trim()).map(([line_id, v]) => ({ line_id, qty: Number(v) }))
    if (!lines.length || lines.some(l => !Number.isInteger(l.qty) || l.qty < 1)) { a.setError('Enter whole quantities to receive'); return }
    act('recv', () => api.post<PO>(`/purchase-orders/${id}/receive`, { lines }), 'Goods received').then(ok => ok && setRecv({}))
  }
  return (
    <Drawer label={po.po_number} title={`${po.po_number} · ${po.supplier_name}`} onClose={onClose} wide>
      <div className="flex items-center gap-2 flex-wrap"><Pill s={po.status} /><span className="text-sm font-semibold">{inr(po.total)}</span><span className="text-xs text-stone-500">{po.project_number} · {po.project_name}</span>
        <button onClick={() => pdf(`/purchase-orders/${id}/pdf`, `${po.po_number}.pdf`, a.setError)} className={btn.small + ' ml-auto'}><Download className="w-3 h-3" />PDF</button>
        {po.status !== 'CANCELLED' && <SendButton kind="PO" refId={id} label="Send to supplier" />}</div>
      {a.error && <Alert>{a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      <Table head={['SKU', 'Item', 'Qty', 'Received', 'Rate', 'Amount', ...(['ISSUED', 'PARTIAL'].includes(po.status) && canRecv ? ['Receive now'] : [])]} right={[2, 3, 4, 5]}>
        {(po.lines ?? []).map(l => <tr key={l.id}><td className="px-4 py-2 font-mono text-[11px]">{l.sku}</td><td className="px-4 py-2 text-xs">{l.description}</td>
          <td className="px-4 py-2 text-right">{po.status === 'DRAFT' && canProc ? <input aria-label={`Qty ${l.sku}`} value={qtys[l.id] ?? ''} onChange={e => setQtys({ ...qtys, [l.id]: e.target.value })} className={input + ' w-20 text-right py-1'} /> : `${l.qty} ${l.unit}`}</td>
          <td className="px-4 py-2 text-right">{l.received}</td><td className="px-4 py-2 text-right text-xs">{po.status === 'DRAFT' && canProc ? <input aria-label={`Rate ${l.sku}`} value={rates[l.id] ?? ''} onChange={e => setRates({ ...rates, [l.id]: e.target.value })} className={input + ' w-28 text-right py-1'} /> : inr(l.rate)}</td><td className="px-4 py-2 text-right text-xs">{inr(l.amount)}</td>
          {['ISSUED', 'PARTIAL'].includes(po.status) && canRecv && <td className="px-4 py-2">{l.outstanding > 0 ? <input aria-label={`Receive ${l.sku}`} placeholder={`max ${l.outstanding}`} value={recv[l.id] ?? ''} onChange={e => setRecv({ ...recv, [l.id]: e.target.value })} className={input + ' w-24 py-1'} /> : <span className="text-xs text-green-700">done</span>}</td>}</tr>)}
      </Table>
      {canProc && ['DRAFT', 'ISSUED', 'PARTIAL'].includes(po.status) && <div className="flex gap-2 items-end flex-wrap">
        <Field label="Expected delivery"><input type="date" value={expected} onChange={e => setExpected(e.target.value)} className={input} /></Field>
        <button className={btn.ghost} onClick={() => act('save', () => api.patch<PO>(`/purchase-orders/${id}`, { expected_on: expected || null, ...(po.status === 'DRAFT' ? { lines: Object.entries(qtys).map(([lid, q]) => ({ id: lid, qty: Number(q), rate: (rates[lid] ?? '').replace(/[₹,\s]/g, '') })) } : {}) }), 'Saved')}>Save</button>
        {po.status === 'DRAFT' && <button className={btn.primary} onClick={() => act('issue', () => api.post<PO>(`/purchase-orders/${id}/issue`), 'Issued')}>Issue PO</button>}
        {['DRAFT', 'ISSUED'].includes(po.status) && <button className={btn.danger} onClick={() => act('cancel', () => api.post<PO>(`/purchase-orders/${id}/cancel`), 'Cancelled')}>Cancel PO</button>}</div>}
      {['ISSUED', 'PARTIAL'].includes(po.status) && canRecv && <button onClick={receive} disabled={!!a.busy} className={btn.primary + ' w-full'}>{a.busy === 'recv' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Receive goods</button>}
    </Drawer>
  )
}

// ── Inventory ─────────────────────────────────────────────────────────────────
interface Move { id: string; sku: string; name: string; unit: string; delta: number; balance: number; reason: string; ref_type: string | null; user_name: string | null; created_at: string }
export function InventoryView() {
  const [attention, setAttention] = useState(false)
  const { data: items, error } = useLoad<CatItem[]>(`/catalogue/items?status=active${attention ? '&stock=ATTENTION' : ''}`)
  const { data: moves } = useLoad<Move[]>('/inventory/movements?limit=100')
  return (
    <div className="space-y-5 max-w-[1400px]">
      <PageHeader title="Inventory" subtitle="Stock of every catalogue item (all kinds) and the full stock ledger: purchases received, allocations to projects and manual adjustments. Adjust stock from the item in Catalogue." />
      <label className="text-sm text-stone-600 flex items-center gap-2"><input type="checkbox" checked={attention} onChange={e => setAttention(e.target.checked)} />Only items at or below their reorder level</label>
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-12 gap-4">
        <Card title={`Stock (${items?.length ?? 0})`} className="col-span-12 xl:col-span-6">{!items ? <Empty>Loading…</Empty> : items.length === 0 ? <Empty>Nothing here.</Empty> :
          <Table head={['SKU', 'Item', 'Kind', 'Stock', 'Reorder at']} right={[3, 4]}>{items.map(i => <tr key={i.id} data-sku={i.sku}><td className="px-4 py-2 font-mono text-[11px]">{i.sku}</td><td className="px-4 py-2 text-xs">{i.name}</td>
            <td className="px-4 py-2 text-[11px] text-stone-500">{i.kind}</td><td className="px-4 py-2 text-right"><Pill s={i.stock_status} label={`${i.stock} ${i.unit}`} /></td><td className="px-4 py-2 text-right text-xs">{i.min_stock ?? '—'}</td></tr>)}</Table>}</Card>
        <Card title="Stock ledger (latest 100)" className="col-span-12 xl:col-span-6">{!moves ? <Empty>Loading…</Empty> : moves.length === 0 ? <Empty>No movements yet.</Empty> :
          <ul className="divide-y divide-stone-50 text-xs" data-testid="ledger">{moves.map(m => <li key={m.id} className="py-1.5 flex justify-between gap-3">
            <span><b className={m.delta > 0 ? 'text-green-700' : 'text-red-700'}>{m.delta > 0 ? '+' : ''}{m.delta}</b> {m.sku} → {m.balance} {m.unit}<span className="block text-stone-500">{m.reason}</span></span>
            <span className="text-stone-400 whitespace-nowrap">{m.user_name ?? '—'} · {timeAgo(m.created_at)}</span></li>)}</ul>}</Card>
      </div>
    </div>
  )
}

// ── Manufacturing ─────────────────────────────────────────────────────────────
export function ManufacturingView() {
  const role = useRole(); const [pid, setPid] = useState(''); const approved = useApproved(pid)
  const { data: wos, reload, error } = useLoad<WorkOrder[]>(pid ? `/work-orders?project_id=${pid}` : null)
  const a = useAction(); const can = hasRole(role, MFG)
  const create = () => a.run('c', async () => { let n = 0; for (const q of approved ?? []) n += (await api.post<{ created: WorkOrder[] }>(`/boqs/${q.id}/work-orders`)).created.length; await reload(); return n },
    'Work orders are up to date')
  const move = (w: WorkOrder, stage: string) => a.run(w.id, async () => { await api.post(`/work-orders/${w.id}/stage`, { stage }); await reload() })
  return (
    <div className="space-y-5 max-w-[1500px]">
      <PageHeader title="Manufacturing" subtitle="One work order per in-house unit (wardrobes, TV units, study units…), each with its cutting list. Move a unit through the workshop stages; only READY units can be delivered.">
        {can && <button onClick={create} disabled={!approved?.length || !!a.busy} className={btn.primary}>Create work orders from approved quotations</button>}</PageHeader>
      <ProjectPicker value={pid} onChange={setPid} />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {!wos ? <Empty>Pick a project.</Empty> : wos.length === 0 ? <Empty>No work orders yet{approved?.length ? ' — press the button above.' : '. Approve a quotation first.'}</Empty> :
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">{WO_STAGES.map(st => <div key={st} data-stage={st} className="bg-stone-100/70 rounded-lg p-2 min-h-40">
          <p className="text-[11px] font-semibold text-stone-500 uppercase px-1 mb-2">{st} ({wos.filter(w => w.stage === st).length})</p>
          <div className="space-y-2">{wos.filter(w => w.stage === st).map(w => { const n = woNeighbours(w.stage); return <div key={w.id} data-wo={w.wo_number} className="bg-white rounded border border-stone-200 p-2 shadow-sm">
            <p className="text-[11px] font-mono text-stone-400">{w.wo_number}</p><p className="text-xs font-medium text-stone-800">{w.description}</p><p className="text-[11px] text-stone-400">unit {w.unit_no} · {Object.values(w.cut_list.sheets).map(s => `${s.sheets} sh`).join(' + ')}</p>
            {can && <div className="flex justify-between mt-1.5">
              <button disabled={!n.prev || !!a.busy} onClick={() => n.prev && move(w, n.prev)} className={btn.small} aria-label={`Back ${w.wo_number}`}><ArrowLeft className="w-3 h-3" /></button>
              <button disabled={!n.next || !!a.busy} onClick={() => n.next && move(w, n.next)} className={btn.small} aria-label={`Advance ${w.wo_number}`}>{n.next ?? 'done'}<ArrowRight className="w-3 h-3" /></button></div>}
          </div> })}</div></div>)}</div>}
    </div>
  )
}

// ── Cutting lists ─────────────────────────────────────────────────────────────
interface CutBlock { boq: Quotation; items: { sku: string; description: string; qty: number; cut_list: CutList }[]; sheets: Record<string, number>; edge_band_m: number }
export function CuttingView() {
  const [pid, setPid] = useState(''); const { data, error } = useLoad<CutBlock[]>(pid ? `/projects/${pid}/cutting` : null)
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Cutting lists" subtitle="Panels for every in-house unit on the approved quotations, from the unit's outer size (18 mm carcass, 8 mm back, partitions ~900 mm, shelves ~450 mm, shutters ~450 mm). Sheets are nested on 8×4 ft boards with 4 mm kerf. The workshop confirms against the final drawing." />
      <ProjectPicker value={pid} onChange={setPid} />
      {error && <Alert>{error}</Alert>}
      {!data ? <Empty>Pick a project.</Empty> : data.length === 0 ? <Empty>No approved quotation for this project.</Empty> : data.map(b => <Card key={b.boq.id} title={`${b.boq.quotation_no} · ${b.boq.room_name}`}
        right={<span className="text-xs text-stone-600" data-testid="sheet-total">Total: {Object.entries(b.sheets).map(([t, n]) => `${n} × ${t}mm sheets`).join(', ') || 'no in-house units'} · edge band {b.edge_band_m} m</span>}>
        {b.items.length === 0 ? <Empty>Everything on this quotation is bought out.</Empty> : b.items.map(it => <div key={it.sku} className="mb-5">
          <p className="text-sm font-semibold text-stone-800">{it.description} × {it.qty} <span className="text-xs font-normal text-stone-500">({it.cut_list.size.length} × {it.cut_list.size.depth} × {it.cut_list.size.height} mm)</span></p>
          <Table head={['Panel', 'Length', 'Width', 'Thk', 'Qty / unit', 'Edge band (m)']} right={[1, 2, 3, 4, 5]}>{it.cut_list.panels.map((p, i) => <tr key={i}><td className="px-4 py-1.5 text-xs">{p.name}</td>
            <td className="px-4 py-1.5 text-right text-xs">{p.length}</td><td className="px-4 py-1.5 text-right text-xs">{p.width}</td><td className="px-4 py-1.5 text-right text-xs">{p.thickness}</td>
            <td className="px-4 py-1.5 text-right text-xs">{p.qty}</td><td className="px-4 py-1.5 text-right text-xs">{p.edge_m}</td></tr>)}</Table>
          <p className="text-[11px] text-stone-500 mt-1">Per unit: {Object.entries(it.cut_list.sheets).map(([t, s]) => `${s.sheets} × ${s.board} (${s.utilisation_pct}% used)`).join(', ')}</p></div>)}
      </Card>)}
    </div>
  )
}

// ── Delivery ──────────────────────────────────────────────────────────────────
export function DeliveryView() {
  const role = useRole(); const [pid, setPid] = useState(''); const can = hasRole(role, DELIV)
  const { data: blocks, reload: rb } = useLoad<Fulfilment[]>(pid ? `/projects/${pid}/deliverable` : null)
  const { data: notes, reload: rn } = useLoad<DeliveryNote[]>(pid ? `/deliveries?project_id=${pid}` : null)
  const [qty, setQty] = useState<Record<string, string>>({}); const [f, setF] = useState({ scheduled_on: isoDay(), vehicle: '', driver: '' }); const [recvBy, setRecvBy] = useState<Record<string, string>>({})
  const a = useAction(); const refresh = () => { rb(); rn() }
  const schedule = (boqId: string, lines: Fulfilment['lines']) => {
    const chosen = lines.filter(l => (qty[l.sku ?? l.description] ?? '').trim()).map(l => ({ sku: l.sku ?? undefined, description: l.sku ? undefined : l.description, qty: Number(qty[l.sku ?? l.description]) }))
    if (!chosen.length || chosen.some(c => !Number.isInteger(c.qty) || c.qty < 1)) { a.setError('Enter whole quantities for the items to deliver'); return }
    a.run('s', async () => { await api.post(`/projects/${pid}/deliveries`, { boq_id: boqId, ...f, vehicle: f.vehicle || undefined, driver: f.driver || undefined, lines: chosen }); setQty({}); refresh() }, 'Delivery scheduled')
  }
  const act = (d: DeliveryNote, what: 'dispatch' | 'deliver' | 'cancel') => a.run(d.id + what, async () => {
    await api.post(`/deliveries/${d.id}/${what}`, what === 'deliver' ? { received_by: recvBy[d.id] ?? '' } : undefined); refresh() }, `${d.dn_number}: ${what === 'deliver' ? 'delivered' : what === 'dispatch' ? 'dispatched' : 'cancelled'}`)
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Delivery" subtitle="Schedule delivery notes for what is actually ready (READY work orders, received or allocated stock). Delivered items become installation tasks." />
      <ProjectPicker value={pid} onChange={setPid} />
      {a.error && <Alert>{a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {blocks?.map(b => <Card key={b.boq.id} title={`Ready to deliver · ${b.boq.quotation_no}`}>
        <Table head={['Item', 'Qty', 'Ready', 'On notes', 'Deliverable now', ...(can ? ['Deliver'] : [])]} right={[1, 2, 3, 4]}>{b.lines.map(l => <tr key={l.line}><td className="px-4 py-2 text-xs">{l.description}</td>
          <td className="px-4 py-2 text-right">{l.qty}</td><td className="px-4 py-2 text-right">{l.ready}</td><td className="px-4 py-2 text-right">{l.booked}</td><td className="px-4 py-2 text-right font-semibold">{l.deliverable}</td>
          {can && <td className="px-4 py-2">{l.deliverable > 0 ? <input aria-label={`Deliver ${l.description}`} placeholder={`max ${l.deliverable}`} value={qty[l.sku ?? l.description] ?? ''} onChange={e => setQty({ ...qty, [l.sku ?? l.description]: e.target.value })} className={input + ' w-24 py-1'} /> : <span className="text-[11px] text-stone-400">—</span>}</td>}</tr>)}</Table>
        {can && <div className="flex gap-2 items-end flex-wrap mt-3">
          <Field label="Date"><input type="date" value={f.scheduled_on} onChange={e => setF({ ...f, scheduled_on: e.target.value })} className={input} /></Field>
          <Field label="Vehicle"><input value={f.vehicle} onChange={e => setF({ ...f, vehicle: e.target.value })} className={input} /></Field>
          <Field label="Driver"><input value={f.driver} onChange={e => setF({ ...f, driver: e.target.value })} className={input} /></Field>
          <button onClick={() => schedule(b.boq.id, b.lines)} disabled={!!a.busy} className={btn.primary}>Schedule delivery</button></div>}
      </Card>)}
      {pid && blocks?.length === 0 && <Empty>No approved quotation for this project.</Empty>}
      <Card title="Delivery notes">{!notes?.length ? <Empty>None yet.</Empty> : <div className="space-y-2">{notes.map(d => <div key={d.id} data-dn={d.dn_number} className="border border-stone-200 rounded p-3">
        <div className="flex items-center gap-2 flex-wrap"><b className="font-mono text-xs">{d.dn_number}</b><Pill s={d.status} /><span className="text-xs text-stone-500">{fmtDate(d.scheduled_on)}{d.vehicle ? ` · ${d.vehicle}` : ''}{d.received_by ? ` · received by ${d.received_by}` : ''}</span>
          <button onClick={() => pdf(`/deliveries/${d.id}/pdf`, `${d.dn_number}.pdf`, a.setError)} className={btn.small + ' ml-auto'}><Download className="w-3 h-3" />Challan</button>
          {d.status !== 'CANCELLED' && <SendButton kind="DELIVERY" refId={d.id} label="Notify client" />}</div>
        <p className="text-xs text-stone-600 mt-1">{d.lines.map(l => `${l.description} × ${l.qty}`).join(', ')}</p>
        {can && <div className="flex gap-2 mt-2 items-center flex-wrap">
          {d.status === 'SCHEDULED' && <button onClick={() => act(d, 'dispatch')} className={btn.small}>Dispatch</button>}
          {d.status === 'DISPATCHED' && <><input aria-label={`Received by ${d.dn_number}`} placeholder="Received by (name)" value={recvBy[d.id] ?? ''} onChange={e => setRecvBy({ ...recvBy, [d.id]: e.target.value })} className={input + ' w-56 py-1 text-xs'} />
            <button onClick={() => act(d, 'deliver')} className={btn.small}>Mark delivered</button></>}
          {['SCHEDULED', 'DISPATCHED'].includes(d.status) && <button onClick={() => act(d, 'cancel')} className={btn.small}>Cancel</button>}</div>}
      </div>)}</div>}</Card>
    </div>
  )
}

// ── Installation ──────────────────────────────────────────────────────────────
export function InstallationView() {
  const role = useRole(); const [pid, setPid] = useState(''); const can = hasRole(role, INSTALL)
  const { data: tasks, reload, error } = useLoad<InstallTask[]>(pid ? `/projects/${pid}/install-tasks` : null)
  const { data: users } = useLoad<UserRow[]>('/users')
  const crew = useMemo(() => (users ?? []).filter(u => u.is_active && ['SITE_ENGINEER', 'INSTALLATION_MANAGER', 'PROJECT_MANAGER'].includes(u.role)), [users])
  const a = useAction(); const done = tasks?.filter(t => t.status === 'DONE').length ?? 0
  const patch = (t: InstallTask, body: Partial<InstallTask>) => a.run(t.id, async () => { await api.patch(`/install-tasks/${t.id}`, body); await reload() })
  return (
    <div className="space-y-5 max-w-[1200px]">
      <PageHeader title="Installation" subtitle="Tasks appear when goods are delivered. When everything is delivered and every task is DONE, the project moves to QC." />
      <ProjectPicker value={pid} onChange={setPid} />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}
      {tasks && <p className="text-sm text-stone-600">{done} of {tasks.length} done</p>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!tasks ? <Empty>Pick a project.</Empty> : tasks.length === 0 ? <Empty>No installation tasks yet — they're created when a delivery is marked delivered.</Empty> :
        <Table head={['Task', 'Qty', 'Status', 'Assigned to', 'Note', 'Updated']}>{tasks.map(t => <tr key={t.id} data-task={t.title}>
          <td className="px-4 py-2 text-sm font-medium">{t.title}</td><td className="px-4 py-2 text-sm">{t.qty}</td>
          <td className="px-4 py-2"><select aria-label={`Status of ${t.title}`} disabled={!can} value={t.status} onChange={e => patch(t, { status: e.target.value as InstallTask['status'] })} className={ctl + ' text-xs py-1'}>
            {['PENDING', 'IN_PROGRESS', 'DONE'].map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</select></td>
          <td className="px-4 py-2"><select aria-label={`Assignee of ${t.title}`} disabled={!can} value={t.assigned_to ?? ''} onChange={e => patch(t, { assigned_to: e.target.value || null })} className={ctl + ' text-xs py-1'}>
            <option value="">—</option>{crew.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></td>
          <td className="px-4 py-2"><input aria-label={`Note for ${t.title}`} disabled={!can} defaultValue={t.note ?? ''} onBlur={e => e.target.value !== (t.note ?? '') && patch(t, { note: e.target.value })} className={input + ' text-xs py-1'} /></td>
          <td className="px-4 py-2 text-[11px] text-stone-400">{t.updated_by ?? '—'} · {timeAgo(t.updated_at)}</td></tr>)}</Table>}</div>
    </div>
  )
}

// ── QC + handover ─────────────────────────────────────────────────────────────
export function QCView() {
  const role = useRole(); const [pid, setPid] = useState('')
  const { data: qc, reload, setData, error } = useLoad<QCState>(pid ? `/projects/${pid}/qc` : null)
  const { data: ho, reload: rh } = useLoad<HandoverState>(pid ? `/projects/${pid}/handover` : null)
  const a = useAction(); const [notes, setNotes] = useState<Record<string, string>>({}); const [custom, setCustom] = useState('')
  const [hf, setHf] = useState({ received_by: '', notes: '' })
  const put = (fn: () => Promise<QCState>, ok?: string) => a.run('q', async () => { setData(await fn()); rh() }, ok)
  const canQC = hasRole(role, QC), canFix = hasRole(role, SNAG), canHand = hasRole(role, HANDOVER)
  return (
    <div className="space-y-5 max-w-[1200px]">
      <PageHeader title="Quality control & handover" subtitle="QC starts once everything is delivered and installed. A failed check raises a snag; a fixed snag sends the check back for re-inspection. Handover is allowed only when every check has passed and no snag is open." />
      <ProjectPicker value={pid} onChange={setPid} />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {qc && <>
        {qc.checks.length === 0 ? <Card title="QC inspection"><p className="text-sm text-stone-600 mb-3">{qc.installed ? 'Everything is installed. Start the inspection to generate the checklist.' : 'Not ready: finish delivery and installation first.'}</p>
          {canQC && <button onClick={() => put(() => api.post<QCState>(`/projects/${pid}/qc/start`))} disabled={!qc.installed} className={btn.primary}>Start QC inspection</button>}</Card> :
          <Card title={`Checklist (${qc.checks.filter(c => c.status === 'PASS').length}/${qc.checks.length} passed)`}>
            <ul className="divide-y divide-stone-50" data-testid="qc-checks">{qc.checks.map(c => <li key={c.id} data-check={c.title} className="py-2 flex gap-3 items-start flex-wrap">
              <Pill s={c.status} /><div className="flex-1 min-w-60"><p className="text-sm text-stone-800">{c.title}</p>{c.note && <p className="text-[11px] text-stone-500">{c.note}{c.checked_by ? ` — ${c.checked_by}` : ''}</p>}</div>
              {canQC && !ho?.handover && <div className="flex gap-1.5 items-center">
                <input aria-label={`QC note ${c.title}`} placeholder="Note (required to fail)" value={notes[c.id] ?? ''} onChange={e => setNotes({ ...notes, [c.id]: e.target.value })} className={input + ' w-56 text-xs py-1'} />
                <button onClick={() => put(() => api.post<QCState>(`/qc-checks/${c.id}`, { status: 'PASS', note: notes[c.id] || undefined }))} className={btn.small} aria-label={`Pass ${c.title}`}>Pass</button>
                <button onClick={() => put(() => api.post<QCState>(`/qc-checks/${c.id}`, { status: 'FAIL', note: notes[c.id] || undefined }))} className={btn.small} aria-label={`Fail ${c.title}`}>Fail</button></div>}</li>)}</ul>
            {canQC && !ho?.handover && <div className="flex gap-2 mt-3"><input value={custom} onChange={e => setCustom(e.target.value)} placeholder="Add a check (e.g. Kitchen chimney duct sealed)" aria-label="New QC check" className={input} />
              <button onClick={() => put(async () => { const r = await api.post<QCState>(`/projects/${pid}/qc/checks`, { title: custom }); setCustom(''); return r })} disabled={custom.trim().length < 3} className={btn.ghost}>Add</button></div>}
          </Card>}
        <Card title={`Snags (${qc.snags.filter(s => s.status === 'OPEN').length} open)`}>{qc.snags.length === 0 ? <Empty>No snags.</Empty> :
          <ul className="divide-y divide-stone-50" data-testid="snags">{qc.snags.map(s => <li key={s.id} className="py-2 flex gap-3 items-start flex-wrap"><Pill s={s.status} />
            <div className="flex-1 min-w-60"><p className="text-sm">{s.title}</p><p className="text-[11px] text-stone-500">raised by {s.raised_by ?? '—'} · {timeAgo(s.created_at)}{s.fix_note ? ` · fixed: ${s.fix_note} (${s.fixed_by})` : ''}</p></div>
            {s.status === 'OPEN' && canFix && <div className="flex gap-1.5"><input aria-label={`Fix note ${s.title}`} placeholder="What was done" value={notes['s' + s.id] ?? ''} onChange={e => setNotes({ ...notes, ['s' + s.id]: e.target.value })} className={input + ' w-56 text-xs py-1'} />
              <button onClick={() => put(() => api.post<QCState>(`/snags/${s.id}/fix`, { note: notes['s' + s.id] ?? '' }), 'Snag fixed — re-inspect the check')} className={btn.small}>Mark fixed</button></div>}</li>)}</ul>}</Card>
      </>}
      {ho && <Card title="Handover">{ho.handover ? <div className="text-sm space-y-2" data-testid="handover-done"><p className="text-green-800">Handed over to <b>{ho.handover.received_by}</b> on {fmtDate(ho.handover.handed_over_on)} · warranty {ho.handover.warranty_months} months · by {ho.handover.user_name}.</p>
        <div className="flex gap-2"><button onClick={() => pdf(`/projects/${pid}/handover.pdf`, 'handover-certificate.pdf', a.setError)} className={btn.ghost}><Download className="w-3.5 h-3.5" />Handover certificate</button>
          <SendButton kind="HANDOVER" refId={pid} label="Send certificate" small={false} /></div></div>
        : <div className="space-y-3">{ho.readiness.ready ? <p className="text-sm text-green-800">Ready for handover.{ho.readiness.balance_due !== '0.00' ? ` Note: ${inr(ho.readiness.balance_due)} is still due from the client.` : ''}</p>
          : <ul className="text-sm text-amber-900 list-disc pl-5" data-testid="blockers">{ho.readiness.blockers.map(b => <li key={b}>{b}</li>)}</ul>}
          {canHand && <div className="flex gap-2 items-end flex-wrap"><Field label="Received by (client name)"><input value={hf.received_by} onChange={e => setHf({ ...hf, received_by: e.target.value })} className={input + ' w-64'} /></Field>
            <Field label="Notes"><input value={hf.notes} onChange={e => setHf({ ...hf, notes: e.target.value })} className={input + ' w-72'} /></Field>
            <button disabled={!ho.readiness.ready || hf.received_by.trim().length < 2 || !!a.busy} onClick={() => a.run('h', async () => { await api.post(`/projects/${pid}/handover`, { received_by: hf.received_by, notes: hf.notes || undefined }); rh(); reload() }, 'Handed over — project completed')} className={btn.primary}>Record handover</button></div>}</div>}</Card>}
    </div>
  )
}
