'use client'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AuthImg, ItemPhoto, photoPath } from '@/components/catalogue/photo'
import { SupplierPrices } from '@/components/catalogue/supplier-prices'
import { AlertCircle, Archive, ArchiveRestore, CheckCircle2, Download, FileUp, Loader2, Minus, Plus, Search, X } from 'lucide-react'
import { api, ApiError, CatItem, CatItemDetail, CatKind, CatMeta, ImportResult, session, Supplier, downloadFile } from '@/lib/api'
import { KINDS, canEditCatalogue, canMoveStock, cleanPrice, csvTemplate, dimsText, inr, parseDelta, stockText } from '@/lib/catalogue-logic'
import { timeAgo } from '@/lib/crm-logic'

const input = 'w-full text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400 disabled:bg-stone-50 disabled:text-stone-500'
const ctl = input.replace('w-full ', '')                                 // filter-bar controls size themselves
const btn = 'flex items-center justify-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded disabled:opacity-50'
const primary = btn + ' bg-amber-700 hover:bg-amber-800 text-white'
const ghost = btn + ' border border-stone-200 bg-white hover:bg-stone-50 text-stone-700'
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong')
const Alert = ({ children }: { children: React.ReactNode }) => <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{children}</p>

function StockBadge({ i }: { i: CatItem }) {
  const cls = i.stock_status === 'OUT' ? 'text-red-700 bg-red-50' : i.stock_status === 'LOW' ? 'text-amber-800 bg-amber-50' : 'text-green-700 bg-green-50'
  const Icon = i.stock_status === 'OK' ? CheckCircle2 : AlertCircle
  return <span data-status={i.stock_status} className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-full whitespace-nowrap ${cls}`}><Icon className="w-3 h-3" />{stockText(i)}</span>
}

function Drawer({ label, title, onClose, children, wide }: { label: string; title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-stone-900/30" onClick={onClose}>
      <div role="dialog" aria-label={label} className={`w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} h-full bg-white shadow-xl flex flex-col`} onClick={e => e.stopPropagation()}>
        <div className="h-14 px-5 flex items-center justify-between border-b border-stone-200 shrink-0">
          <h2 className="text-sm font-semibold text-stone-900 truncate">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-stone-100"><X className="w-4 h-4 text-stone-500" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-5">{children}</div>
      </div>
    </div>
  )
}

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="block"><span className="block text-[11px] font-medium text-stone-500 mb-1">{label}</span>{children}</label>)

export function CatalogueView({ kind }: { kind: CatKind }) {
  const info = KINDS[kind]
  const [role, setRole] = useState<string | null>(null)                  // read after mount so server and browser render the same first frame
  useEffect(() => { setRole(session.user()?.role ?? null) }, [])
  const canEdit = canEditCatalogue(role), canStock = canMoveStock(role)
  const [items, setItems] = useState<CatItem[] | null>(null)
  const [meta, setMeta] = useState<CatMeta | null>(null)
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [q, setQ] = useState(''); const [category, setCategory] = useState(''); const [stock, setStock] = useState(''); const [status, setStatus] = useState('active')
  const [error, setError] = useState('')
  const [open, setOpen] = useState<string | 'new' | 'import' | null>(null)

  const load = useCallback(() => {
    const p = new URLSearchParams({ kind, status }); if (q.trim()) p.set('q', q.trim()); if (category) p.set('category', category); if (stock) p.set('stock', stock)
    api.get<CatItem[]>('/catalogue/items?' + p).then(r => { setItems(r); setError('') }).catch(e => setError(errMsg(e)))
  }, [kind, q, category, stock, status])
  const loadMeta = useCallback(() => { api.get<CatMeta>('/catalogue/meta').then(setMeta).catch(() => {}) }, [])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])
  useEffect(() => { loadMeta(); api.get<Supplier[]>('/suppliers').then(setSuppliers).catch(() => {}) }, [loadMeta])
  const refresh = () => { load(); loadMeta() }
  const categories = useMemo(() => Array.from(new Set([...(meta?.categories[kind] ?? [])])).sort(), [meta, kind])
  const attention = items?.filter(i => i.stock_status !== 'OK').length ?? 0

  const exportCsv = async () => { try { await downloadFile(`/catalogue/export.csv?kind=${kind}&status=${status}`, `catalogue-${kind.toLowerCase()}.csv`) } catch (e) { setError(errMsg(e)) } }
  const exportXlsx = async () => { try { await downloadFile(`/catalogue/export.xlsx?kind=${kind}&status=${status}`, `catalogue-${kind.toLowerCase()}.xlsx`) } catch (e) { setError(errMsg(e)) } }

  return (
    <div className="space-y-5 max-w-[1400px]">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div><h1 className="text-xl font-semibold text-stone-900">{info.title}</h1>
          <p className="text-sm text-stone-500 mt-0.5 max-w-2xl">{info.subtitle}</p></div>
        <div className="flex gap-2">
          <button onClick={exportCsv} className={ghost}><Download className="w-3.5 h-3.5" />Export CSV</button>
          <button onClick={exportXlsx} className={ghost}><Download className="w-3.5 h-3.5" />Export Excel</button>
          {canEdit && <button onClick={() => setOpen('import')} className={ghost}><FileUp className="w-3.5 h-3.5" />Import CSV / Excel</button>}
          {canEdit && <button onClick={() => setOpen('new')} className={primary}><Plus className="w-3.5 h-3.5" />Add {info.singular}</button>}
        </div>
      </div>

      <div className="flex gap-2 flex-wrap items-center">
        <div className="relative"><Search className="w-3.5 h-3.5 text-stone-400 absolute left-2.5 top-2.5" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search SKU, name, material…" aria-label="Search catalogue" className={ctl + ' pl-8 w-64'} /></div>
        <select value={category} onChange={e => setCategory(e.target.value)} aria-label="Category filter" className={ctl + ' w-44'}>
          <option value="">All categories</option>{categories.map(c => <option key={c}>{c}</option>)}</select>
        <select value={stock} onChange={e => setStock(e.target.value)} aria-label="Stock filter" className={ctl + ' w-44'}>
          <option value="">Any stock</option><option value="ATTENTION">Low or out of stock</option><option value="OUT">Out of stock</option></select>
        <select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status filter" className={ctl + ' w-36'}>
          <option value="active">Active</option><option value="archived">Archived</option><option value="all">All</option></select>
        {items && <span className="text-xs text-stone-500 ml-1">{items.length} item{items.length === 1 ? '' : 's'}{attention > 0 && <> · <span className="text-amber-800">{attention} need stock</span></>}</span>}
      </div>
      {error && <Alert>{error}</Alert>}

      <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
        {items === null ? <p className="p-8 text-center text-sm text-stone-400">Loading…</p>
          : items.length === 0 ? <p className="p-8 text-center text-sm text-stone-400">
              {q || category || stock || status !== 'active' ? 'Nothing matches these filters.' : `No ${info.title.toLowerCase()} yet.${canEdit ? ' Add one, or import your price list (CSV or Excel).' : ''}`}</p>
          : <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead><tr className="border-b border-stone-100 bg-stone-50">
                {['SKU', 'Item', 'Category', ...(info.needsSize ? ['Size (L × W × H)'] : []), 'Unit price', ...(items.some(x => x.cost_visible) ? ['Cost · margin'] : []), 'Stock', 'Supplier'].map(h =>
                  <th key={h} className={`text-[11px] font-medium text-stone-400 uppercase tracking-wide px-4 py-3 ${h === 'Unit price' || h === 'Cost · margin' ? 'text-right' : 'text-left'}`}>{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-stone-50">{items.map(i => (
                <tr key={i.id} data-sku={i.sku} onClick={() => setOpen(i.id)} className={`hover:bg-stone-50 cursor-pointer ${i.is_active ? '' : 'opacity-60'}`}>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-stone-500 whitespace-nowrap">{i.sku}</td>
                  <td className="px-4 py-2.5"><div className="flex items-center gap-2.5">{i.has_photo && <AuthImg path={photoPath(i)} alt="" className="w-9 h-9 rounded object-cover border border-stone-200 flex-shrink-0" />}<div><p className="font-medium text-stone-900">{i.name}{!i.is_active && <span className="ml-2 text-[10px] uppercase font-semibold text-stone-500 bg-stone-100 px-1.5 py-0.5 rounded">Archived</span>}</p>
                    {(i.material || i.colour) && <p className="text-[11px] text-stone-400">{[i.material, i.colour].filter(Boolean).join(' · ')}</p>}</div></div></td>
                  <td className="px-4 py-2.5 text-xs text-stone-600">{i.category}</td>
                  {info.needsSize && <td className="px-4 py-2.5 text-xs text-stone-500 whitespace-nowrap">{dimsText(i) || '—'}</td>}
                  <td className="px-4 py-2.5 text-right whitespace-nowrap"><span className="font-semibold text-stone-900">{inr(i.price)}</span><span className="text-[11px] text-stone-400"> / {i.unit}</span></td>
                  {items.some(x => x.cost_visible) && <td className="px-4 py-2.5 text-right whitespace-nowrap text-xs" data-testid="cost-cell">{i.cost_price ? <>{inr(i.cost_price)} <span className={Number(i.margin_pct) < 15 ? 'text-red-700' : 'text-green-700'}>· {i.margin_pct}%</span></> : <span className="text-amber-700">no cost</span>}</td>}
                  <td className="px-4 py-2.5"><StockBadge i={i} /></td>
                  <td className="px-4 py-2.5 text-xs text-stone-500">{i.supplier_name ?? <span className="text-stone-300">—</span>}</td>
                </tr>))}</tbody></table></div>}
      </div>

      {open === 'new' && <NewItem kind={kind} categories={categories} units={meta?.units ?? []} suppliers={suppliers} onClose={() => setOpen(null)} onSaved={id => { refresh(); setOpen(id) }} />}
      {open === 'import' && <ImportCsv kind={kind} onClose={() => setOpen(null)} onApplied={refresh} />}
      {open && open !== 'new' && open !== 'import' && <ItemDrawer id={open} categories={categories} units={meta?.units ?? []} suppliers={suppliers} canEdit={canEdit} canStock={canStock}
        onClose={() => setOpen(null)} onChanged={refresh} />}
    </div>
  )
}

// ── New item ─────────────────────────────────────────────────────────────────
type Form = Record<'sku' | 'name' | 'category' | 'unit' | 'price' | 'cost_price' | 'stock' | 'min_stock' | 'length_mm' | 'width_mm' | 'height_mm' | 'material' | 'colour' | 'supplier_id' | 'description' | 'mount_mm' | 'style', string>

function itemBody(f: Form, creating: boolean): Record<string, unknown> | string {
  const out: Record<string, unknown> = {}
  for (const k of ['name', 'category', 'unit', 'material', 'colour', 'description', 'style'] as const) out[k] = f[k].trim() || null
  out.supplier_id = f.supplier_id || null
  for (const k of ['length_mm', 'width_mm', 'height_mm', 'mount_mm'] as const) {
    const v = f[k].trim(); if (v && !/^\d+(\.\d+)?$/.test(v)) return `${k.replace('_mm', '')} must be a number of mm`
    out[k] = v ? Number(v) : null
  }
  const ms = f.min_stock.trim(); if (ms && !/^\d+$/.test(ms)) return 'Reorder level must be a whole number'
  out.min_stock = ms ? parseInt(ms, 10) : null
  if (creating) {
    out.sku = f.sku.trim()
    const p = cleanPrice(f.price); if ('error' in p) return p.error
    out.price = p.price
    if (f.cost_price.trim()) { const c = cleanPrice(f.cost_price); if ('error' in c) return 'Cost: ' + c.error; out.cost_price = c.price }
    const st = f.stock.trim(); if (st && !/^\d+$/.test(st)) return 'Opening stock must be a whole number'
    out.stock = st ? parseInt(st, 10) : 0
    for (const k of Object.keys(out)) if (out[k] === null) delete out[k]
  }
  return out
}

function ItemFields({ f, set, kind, categories, units, suppliers, creating, disabled }: {
  f: Form; set: (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => void
  kind: CatKind; categories: string[]; units: string[]; suppliers: Supplier[]; creating: boolean; disabled?: boolean
}) {
  const info = KINDS[kind]; const req = info.needsSize ? ' *' : ''
  const cats = Array.from(new Set([...categories, ...info.categories])).sort()
  return (<div className="space-y-3">
    {creating && <div className="grid grid-cols-2 gap-3">
      <Field label="SKU *"><input value={f.sku} onChange={set('sku')} required placeholder="BED-QN-OAK-001" className={input + ' font-mono uppercase'} autoFocus /></Field>
      <Field label="Price (₹) *"><input value={f.price} onChange={set('price')} required inputMode="decimal" placeholder="68000" className={input} /></Field>
      <Field label="Cost price (₹, what you pay)"><input value={f.cost_price} onChange={set('cost_price')} inputMode="decimal" placeholder="optional" className={input} /></Field></div>}
    <Field label="Name *"><input value={f.name} onChange={set('name')} required disabled={disabled} className={input} /></Field>
    <div className="grid grid-cols-2 gap-3">
      <Field label="Category *"><input value={f.category} onChange={set('category')} required disabled={disabled} list={`cats-${kind}`} className={input} />
        <datalist id={`cats-${kind}`}>{cats.map(c => <option key={c} value={c} />)}</datalist></Field>
      <Field label="Unit"><select aria-label="Unit" value={f.unit} onChange={set('unit')} disabled={disabled} className={input}>{(units.length ? units : [f.unit]).map(u => <option key={u}>{u}</option>)}</select></Field></div>
    <div className="grid grid-cols-3 gap-3">
      <Field label={`Length (mm)${req}`}><input value={f.length_mm} onChange={set('length_mm')} required={info.needsSize} disabled={disabled} inputMode="numeric" className={input} /></Field>
      <Field label={`Width (mm)${req}`}><input value={f.width_mm} onChange={set('width_mm')} required={info.needsSize} disabled={disabled} inputMode="numeric" className={input} /></Field>
      <Field label={`Height (mm)${req}`}><input value={f.height_mm} onChange={set('height_mm')} required={info.needsSize} disabled={disabled} inputMode="numeric" className={input} /></Field></div>
    <div className="grid grid-cols-2 gap-3">
      <Field label="Material"><input value={f.material} onChange={set('material')} disabled={disabled} className={input} /></Field>
      <Field label="Colour"><input value={f.colour} onChange={set('colour')} disabled={disabled} className={input} /></Field></div>
    <div className="grid grid-cols-2 gap-3">
      <Field label="Style tags (the designer prefers matches)"><input aria-label="Style tags" value={f.style} onChange={set('style')} disabled={disabled} placeholder="modern, minimal" className={input} /></Field>
      <Field label="Fixed above floor (mm)"><input aria-label="Mounting height" value={f.mount_mm} onChange={set('mount_mm')} disabled={disabled} inputMode="numeric" placeholder="stands on the floor" className={input} /></Field></div>
    <div className={`grid gap-3 ${creating ? 'grid-cols-3' : 'grid-cols-2'}`}>
      {creating && <Field label="Opening stock"><input value={f.stock} onChange={set('stock')} inputMode="numeric" placeholder="0" className={input} /></Field>}
      <Field label="Reorder level"><input value={f.min_stock} onChange={set('min_stock')} disabled={disabled} inputMode="numeric" placeholder="none" className={input} /></Field>
      <Field label="Supplier"><select aria-label="Supplier" value={f.supplier_id} onChange={set('supplier_id')} disabled={disabled} className={input}>
        <option value="">— none —</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field></div>
    <Field label="Description"><textarea rows={2} value={f.description} onChange={set('description')} disabled={disabled} className={input} /></Field>
  </div>)
}

function useForm(init: Form) {
  const [f, setF] = useState<Form>(init)
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF(prev => ({ ...prev, [k]: e.target.value }))
  return [f, set, setF] as const
}

function NewItem({ kind, categories, units, suppliers, onClose, onSaved }: { kind: CatKind; categories: string[]; units: string[]; suppliers: Supplier[]; onClose: () => void; onSaved: (id: string) => void }) {
  const info = KINDS[kind]
  const [f, set] = useForm({ sku: '', name: '', category: '', unit: info.unit, price: '', cost_price: '', stock: '', min_stock: '', length_mm: '', width_mm: '', height_mm: '', material: '', colour: '', supplier_id: '', description: '', mount_mm: '', style: '' })
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError('')
    const body = itemBody(f, true); if (typeof body === 'string') { setError(body); return }
    setBusy(true)
    try { const it = await api.post<CatItem>('/catalogue/items', { ...body, kind }); onSaved(it.id) } catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  return (
    <Drawer label={`New ${info.singular}`} title={`New ${info.singular}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <ItemFields f={f} set={set} kind={kind} categories={categories} units={units} suppliers={suppliers} creating />
        {error && <Alert>{error}</Alert>}
        <button disabled={busy} className={primary + ' w-full py-2'}>{busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Create item</button>
      </form>
    </Drawer>
  )
}

// ── Item detail: edit, price, stock, archive ─────────────────────────────────
function ItemDrawer({ id, categories, units, suppliers, canEdit, canStock, onClose, onChanged }: {
  id: string; categories: string[]; units: string[]; suppliers: Supplier[]; canEdit: boolean; canStock: boolean; onClose: () => void; onChanged: () => void
}) {
  const [it, setIt] = useState<CatItemDetail | null>(null)
  const [error, setError] = useState(''); const [saved, setSaved] = useState('')
  const [f, set, setF] = useForm({} as Form)
  const [price, setPrice] = useState(''); const [priceReason, setPriceReason] = useState(''); const [cost, setCost] = useState(''); const [costReason, setCostReason] = useState('')
  const [qty, setQty] = useState(''); const [stockReason, setStockReason] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const fill = (d: CatItemDetail) => {
    setIt(d)
    const s = (v: unknown) => (v == null ? '' : String(v))
    setF({ sku: d.sku, name: d.name, category: d.category, unit: d.unit, price: d.price, cost_price: s(d.cost_price), stock: s(d.stock), min_stock: s(d.min_stock), length_mm: s(d.length_mm), width_mm: s(d.width_mm),
      height_mm: s(d.height_mm), material: s(d.material), colour: s(d.colour), supplier_id: s(d.supplier_id), description: s(d.description), mount_mm: s(d.mount_mm), style: s(d.style) })
  }
  const reload = useCallback(() => api.get<CatItemDetail>(`/catalogue/items/${id}`).then(fill).catch(e => setError(errMsg(e))), [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload() }, [reload])

  const act = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key); setError(''); setSaved('')
    try { await fn(); await reload(); onChanged(); setSaved(ok) } catch (err) { setError(errMsg(err)) } finally { setBusy(null) }
  }
  const saveDetails = (e: React.FormEvent) => {
    e.preventDefault(); const body = itemBody(f, false); if (typeof body === 'string') { setError(body); return }
    act('details', () => api.patch(`/catalogue/items/${id}`, body), 'Details saved')
  }
  const changePrice = (e: React.FormEvent) => {
    e.preventDefault(); const p = cleanPrice(price); if ('error' in p) { setError(p.error); return }
    act('price', async () => { await api.post(`/catalogue/items/${id}/price`, { price: p.price, reason: priceReason }); setPrice(''); setPriceReason('') }, 'Price changed')
  }
  const changeCost = (e: React.FormEvent) => {
    e.preventDefault(); const c = cleanPrice(cost); if ('error' in c) { setError(c.error); return }
    act('cost', async () => { await api.post(`/catalogue/items/${id}/cost`, { cost: c.price, reason: costReason }); setCost(''); setCostReason('') }, 'Cost changed')
  }
  const moveStock = (dir: 'in' | 'out') => {
    if (!it) return
    const d = parseDelta(qty, dir, it.stock); if ('error' in d) { setError(d.error); return }
    act(dir, async () => { await api.post(`/catalogue/items/${id}/stock`, { delta: d.delta, reason: stockReason }); setQty(''); setStockReason('') }, dir === 'in' ? 'Stock added' : 'Stock removed')
  }
  const toggleArchive = () => it && act('archive', () => api.patch(`/catalogue/items/${id}`, { is_active: !it.is_active }), it.is_active ? 'Archived' : 'Restored')

  const section = 'border border-stone-200 rounded-lg p-4 space-y-3'
  return (
    <Drawer label={it ? it.name : 'Item'} title={it ? `${it.sku} · ${it.name}` : 'Loading…'} onClose={onClose} wide>
      {!it ? (error ? <Alert>{error}</Alert> : <p className="text-sm text-stone-400">Loading…</p>) : <>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-lg font-semibold text-stone-900" data-testid="current-price">{inr(it.price)}<span className="text-xs text-stone-400 font-normal"> / {it.unit}</span></span>
          {it.cost_visible && <span className="text-xs text-stone-600" data-testid="current-cost">cost {it.cost_price ? <>{inr(it.cost_price)} · margin <b>{it.margin_pct}%</b></> : <span className="text-amber-700">not set</span>}</span>}
          <StockBadge i={it} />
          {!it.is_active && <span className="text-[11px] uppercase font-semibold text-stone-500 bg-stone-100 px-2 py-0.5 rounded">Archived — hidden from the designer</span>}
          {canEdit && <button onClick={toggleArchive} disabled={busy !== null} className={ghost + ' ml-auto text-xs'}>
            {it.is_active ? <><Archive className="w-3.5 h-3.5" />Archive</> : <><ArchiveRestore className="w-3.5 h-3.5" />Restore</>}</button>}
        </div>
        {error && <Alert>{error}</Alert>}
        {saved && <p role="status" className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">{saved}</p>}

        <div className="grid md:grid-cols-2 gap-4">
          <form onSubmit={changePrice} className={section}>
            <h3 className="text-xs font-semibold text-stone-700 uppercase tracking-wide">Price</h3>
            {canEdit && <div className="grid grid-cols-2 gap-2">
              <Field label="New price (₹)"><input value={price} onChange={e => setPrice(e.target.value)} required inputMode="decimal" className={input} /></Field>
              <Field label="Reason for price change"><input value={priceReason} onChange={e => setPriceReason(e.target.value)} required minLength={3} placeholder="Supplier rate Dec" className={input} /></Field>
              <button disabled={busy !== null} className={primary + ' col-span-2'}>{busy === 'price' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Change price</button>
              <p className="col-span-2 text-[11px] text-stone-400">Saved BOQs keep the price they were made with; new BOQs use this price.</p></div>}
            {canEdit && it.cost_visible && <div className="grid grid-cols-2 gap-2 border-t border-stone-100 pt-3" onSubmit={e => e.preventDefault()}>
              <Field label="New cost (₹)"><input value={cost} onChange={e => setCost(e.target.value)} inputMode="decimal" className={input} /></Field>
              <Field label="Reason for cost change"><input value={costReason} onChange={e => setCostReason(e.target.value)} placeholder="New supplier rate" className={input} /></Field>
              <button type="button" onClick={changeCost} disabled={busy !== null || !cost.trim() || costReason.trim().length < 3} className={ghost + ' col-span-2'}>Change cost</button>
              <p className="col-span-2 text-[11px] text-stone-400">New purchase orders use this cost; existing POs keep their own rates.</p></div>}
            <ul data-testid="price-history" className="text-xs divide-y divide-stone-100 max-h-56 overflow-y-auto">{it.price_history.map((p, n) => (
              <li key={n} className="py-1.5"><div className="flex justify-between gap-2"><span className="text-stone-800">{p.field === 'COST' && <span className="text-[10px] font-semibold text-violet-700 mr-1">COST</span>}{p.old_price ? <>{inr(p.old_price)} → <b>{inr(p.new_price)}</b></> : <b>{inr(p.new_price)}</b>}</span>
                <span className="text-stone-400 whitespace-nowrap">{timeAgo(p.created_at)}</span></div>
                <div className="text-[11px] text-stone-500">{p.reason} · {p.user_name ?? 'Unknown'}</div></li>))}
              {it.price_history.length === 0 && <li className="py-1.5 text-stone-400">No price changes recorded (item predates price history).</li>}</ul>
          </form>

          <div className={section}>
            <h3 className="text-xs font-semibold text-stone-700 uppercase tracking-wide">Stock</h3>
            {canStock && <div className="grid grid-cols-2 gap-2">
              <Field label="Quantity"><input value={qty} onChange={e => setQty(e.target.value)} inputMode="numeric" className={input} /></Field>
              <Field label="Reason for stock change"><input value={stockReason} onChange={e => setStockReason(e.target.value)} placeholder="PO received / issued to site" className={input} /></Field>
              <button type="button" onClick={() => moveStock('in')} disabled={busy !== null || stockReason.trim().length < 3} className={ghost}><Plus className="w-3.5 h-3.5" />Stock in</button>
              <button type="button" onClick={() => moveStock('out')} disabled={busy !== null || stockReason.trim().length < 3} className={ghost}><Minus className="w-3.5 h-3.5" />Stock out</button></div>}
            <ul data-testid="stock-history" className="text-xs divide-y divide-stone-100 max-h-56 overflow-y-auto">{it.stock_history.map((s, n) => (
              <li key={n} className="py-1.5"><div className="flex justify-between gap-2"><span className={s.delta > 0 ? 'text-green-700 font-semibold' : 'text-red-700 font-semibold'}>{s.delta > 0 ? '+' : ''}{s.delta}
                <span className="text-stone-500 font-normal"> → {s.balance} {it.unit}</span></span><span className="text-stone-400 whitespace-nowrap">{timeAgo(s.created_at)}</span></div>
                <div className="text-[11px] text-stone-500">{s.reason} · {s.user_name ?? 'Unknown'}</div></li>))}
              {it.stock_history.length === 0 && <li className="py-1.5 text-stone-400">No stock movements recorded.</li>}</ul>
          </div>
        </div>

        {it.cost_visible && <div className={section}><h3 className="text-xs font-semibold text-stone-700 uppercase tracking-wide">Supplier prices</h3>
          <SupplierPrices itemId={it.id} unit={it.unit} suppliers={suppliers} canEdit={canEdit} /></div>}

        <div className={section}><h3 className="text-xs font-semibold text-stone-700 uppercase tracking-wide">Photo</h3>
          <ItemPhoto item={it} canEdit={canEdit} onChanged={() => { reload(); onChanged() }} /></div>

        <form onSubmit={saveDetails} className={section}>
          <h3 className="text-xs font-semibold text-stone-700 uppercase tracking-wide">Details</h3>
          <p className="text-[11px] text-stone-400">The SKU can't change: saved designs refer to it.</p>
          <ItemFields f={f} set={set} kind={it.kind} categories={categories} units={units} suppliers={suppliers} creating={false} disabled={!canEdit} />
          {canEdit && <button disabled={busy !== null} className={primary}>{busy === 'details' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save details</button>}
        </form>
      </>}
    </Drawer>
  )
}

// ── CSV import with preview ──────────────────────────────────────────────────
function ImportCsv({ kind, onClose, onApplied }: { kind: CatKind; onClose: () => void; onApplied: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [res, setRes] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const send = async (apply: boolean) => {
    if (!file) return
    setBusy(true); setError('')
    const form = new FormData(); form.append('file', file)
    try { const r = await api.upload<ImportResult>(`/catalogue/import?kind=${kind}&apply=${apply}`, form); setRes(r); if (r.applied) onApplied() }
    catch (e) { setError(errMsg(e)); setRes(null) } finally { setBusy(false) }
  }
  const template = () => {
    const url = URL.createObjectURL(new Blob(['﻿' + csvTemplate(kind)], { type: 'text/csv' }))
    const a = document.createElement('a'); a.href = url; a.download = `catalogue-template-${kind.toLowerCase()}.csv`; a.click(); URL.revokeObjectURL(url)
  }
  const show = (v: unknown) => (v == null || v === '' ? '—' : String(v))
  const changed = res ? res.summary.create + res.summary.update : 0
  return (
    <Drawer label="Import CSV / Excel" title={`Import ${KINDS[kind].title.toLowerCase()} from CSV or Excel`} onClose={onClose} wide>
      <div className="text-xs text-stone-500 space-y-1">
        <p>Columns: <code className="text-stone-700">sku, name, category, price</code> are required; also <code className="text-stone-700">unit, stock, min_stock, length_mm, width_mm, height_mm, material, colour, supplier, description, kind, mount_mm, style</code>.</p>
        <p>Excel: the first sheet of an .xlsx workbook is read, with the same columns. Old .xls files: save them as .xlsx first.</p>
        <p>Existing SKUs are updated (price changes and stock differences are recorded in the history); new SKUs are created. If any row has an error, <b>nothing</b> is imported.</p>
        <button onClick={template} className="text-amber-700 hover:underline font-medium">Download a template</button>
      </div>
      <div className="flex gap-2 items-center flex-wrap">
        <input type="file" accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" aria-label="CSV or Excel file" onChange={e => { setFile(e.target.files?.[0] ?? null); setRes(null); setError('') }} className="text-sm" />
        <button onClick={() => send(false)} disabled={!file || busy} className={ghost}>{busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Preview</button>
      </div>
      {error && <Alert>{error}</Alert>}
      {res && <div className="space-y-3" data-testid="import-result">
        {res.applied
          ? <p role="status" className="text-sm text-green-800 bg-green-50 border border-green-200 rounded px-3 py-2">Imported: {res.summary.create} created, {res.summary.update} updated.</p>
          : <p className="text-sm text-stone-700"><b>{res.summary.create}</b> new · <b>{res.summary.update}</b> to update · {res.summary.unchanged} unchanged · <b className={res.summary.errors ? 'text-red-700' : ''}>{res.summary.errors} with errors</b></p>}
        {res.ignored_columns.length > 0 && <p className="text-xs text-amber-800">Ignored unknown column(s): {res.ignored_columns.join(', ')}</p>}
        {res.errors.length > 0 && <div className="border border-red-200 rounded overflow-hidden"><table className="w-full text-xs"><thead className="bg-red-50 text-red-800"><tr><th className="text-left px-3 py-1.5">Row</th><th className="text-left px-3 py-1.5">SKU</th><th className="text-left px-3 py-1.5">Problem</th></tr></thead>
          <tbody className="divide-y divide-red-100">{res.errors.map(e => <tr key={e.row}><td className="px-3 py-1.5 font-mono">{e.row}</td><td className="px-3 py-1.5 font-mono">{e.sku ?? '—'}</td><td className="px-3 py-1.5 text-red-700">{e.error}</td></tr>)}</tbody></table></div>}
        {res.rows.some(r => r.action !== 'UNCHANGED') && <div className="border border-stone-200 rounded overflow-hidden"><table className="w-full text-xs"><thead className="bg-stone-50 text-stone-500"><tr><th className="text-left px-3 py-1.5">Row</th><th className="text-left px-3 py-1.5">SKU</th><th className="text-left px-3 py-1.5">Action</th><th className="text-left px-3 py-1.5">Changes</th></tr></thead>
          <tbody className="divide-y divide-stone-100">{res.rows.filter(r => r.action !== 'UNCHANGED').map(r => <tr key={r.row}><td className="px-3 py-1.5 font-mono">{r.row}</td><td className="px-3 py-1.5 font-mono">{r.sku}</td>
            <td className="px-3 py-1.5"><span className={r.action === 'CREATE' ? 'text-green-700 font-semibold' : 'text-amber-800 font-semibold'}>{r.action === 'CREATE' ? 'New' : 'Update'}</span></td>
            <td className="px-3 py-1.5 text-stone-600">{r.action === 'CREATE' ? r.name : r.changes.map(c => `${c.field}: ${show(c.from)} → ${show(c.to)}`).join('; ')}</td></tr>)}</tbody></table></div>}
        {!res.applied && <button onClick={() => send(true)} disabled={busy || res.summary.errors > 0 || changed === 0} className={primary + ' w-full py-2'}>
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{res.summary.errors > 0 ? 'Fix the errors above, then preview again' : changed === 0 ? 'Nothing to import' : `Apply ${changed} change${changed === 1 ? '' : 's'}`}</button>}
      </div>}
    </Drawer>
  )
}
