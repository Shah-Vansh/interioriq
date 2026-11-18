'use client'
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, Plus, ShieldAlert } from 'lucide-react'
import { api, ApiError, Boq, BoqParams, BoqSummary, DesignVersion, downloadFile } from '@/lib/api'
import { Switch } from '@/components/ui/kit'
const gstOn = (r: BoqParams) => r.gst_enabled !== false && r.gst_enabled !== 'false'
const tkOn = (r: BoqParams) => r.include_takeoff === true || r.include_takeoff === 'true'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import { cn, inrStr } from '@/lib/utils'

const RATE_FIELDS: [keyof BoqParams, string, string][] = [['labour_pct', 'Labour %', '%'], ['overhead_pct', 'Overhead %', '%'], ['margin_pct', 'Margin %', '%'],
  ['discount_pct', 'Discount %', '%'], ['gst_pct', 'GST %', '%'], ['transport', 'Transport (lump)', 'Rs.'], ['installation', 'Installation (lump)', 'Rs.']]
const SUMMARY: [keyof Boq['totals'], string][] = [['subtotal', 'Subtotal (materials + labour)'], ['overhead', 'Overhead'], ['margin', 'Margin'], ['pre_tax', 'Total before tax'],
  ['discount', 'Discount'], ['after_discount', 'After discount'], ['gst', 'GST']]

export function BoqView() {
  const [roomId, setRoomId] = useState('')
  const [designs, setDesigns] = useState<DesignVersion[]>([])
  const [boqs, setBoqs] = useState<BoqSummary[]>([])
  const [open, setOpen] = useState<Boq | null>(null)
  const [rates, setRates] = useState<BoqParams | null>(null)
  const [showRates, setShowRates] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => { api.get<BoqParams>('/estimation/defaults').then(setRates).catch(() => {}) }, [])
  const load = useCallback(async () => {
    setOpen(null); setMsg(null)
    if (!roomId) { setDesigns([]); setBoqs([]); return }
    try { const [d, b] = await Promise.all([api.get<DesignVersion[]>(`/rooms/${roomId}/designs`), api.get<BoqSummary[]>(`/rooms/${roomId}/boqs`)]); setDesigns(d); setBoqs(b) }
    catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed to load' }) }
  }, [roomId])
  useEffect(() => { load() }, [load])

  const create = async (version: number) => {
    setBusy(version); setMsg(null)
    try {
      const b = await api.post<Boq>(`/rooms/${roomId}/designs/${version}/boq`, rates ?? {})
      setOpen(b); setBoqs(await api.get<BoqSummary[]>(`/rooms/${roomId}/boqs`)); setMsg({ ok: true, text: `Created ${b.quotation_no} from design v${version}.` })
    } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed to create the BOQ' }) } finally { setBusy(null) }
  }
  const show = async (id: string) => { try { setOpen(await api.get<Boq>(`/boqs/${id}`)) } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed to open' }) } }
  const pdf = (b: { id: string; quotation_no: string }) => downloadFile(`/boqs/${b.id}/quotation.pdf`, `${b.quotation_no}.pdf`).catch(e => setMsg({ ok: false, text: e.message }))
  const input = 'w-24 text-sm border border-stone-200 rounded px-2 py-1 bg-white font-mono outline-none focus:border-amber-400'

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div><h1 className="text-xl font-semibold text-stone-900">Bill of Quantities</h1>
        <p className="text-sm text-stone-500 mt-0.5">Priced from a saved design using today&apos;s catalogue prices. Each BOQ is a frozen version — a later price change never alters it.</p></div>
      <ProjectRoomPicker onChange={s => setRoomId(s.roomId)} />
      {msg && <p role="status" className={cn('text-xs rounded px-3 py-2 border', msg.ok ? 'text-green-700 bg-green-50 border-green-200' : 'text-red-600 bg-red-50 border-red-200')}>{msg.text}</p>}

      {!roomId ? <p className="text-sm text-stone-500 bg-white border border-stone-200 rounded-lg p-6">Pick a room. Designs are created in AI Designer and the 3D Editor.</p> : (
      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-12 lg:col-span-4 space-y-4">
          <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-stone-100 text-sm font-semibold">Saved designs</div>
            {designs.length === 0 ? <p className="p-4 text-xs text-stone-400">No saved design yet. Generate one in AI Designer and save it.</p> : designs.map(d => (
              <div key={d.id} className="flex items-center gap-2 px-4 py-2.5 border-b border-stone-50 last:border-0 text-xs">
                <span className="font-semibold">v{d.version}</span>
                {d.is_valid ? <span className="text-green-600 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" />valid</span> : <span className="text-red-600 flex items-center gap-1"><ShieldAlert className="w-3 h-3" />has errors</span>}
                <span className="flex-1" />
                <button onClick={() => create(d.version)} disabled={!d.is_valid || busy !== null} title={d.is_valid ? '' : 'Fix the layout and save a new version before pricing it'}
                  className="flex items-center gap-1 bg-amber-700 hover:bg-amber-800 disabled:opacity-40 disabled:cursor-not-allowed text-white px-2.5 py-1 rounded font-medium">
                  {busy === d.version ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}Create BOQ</button>
              </div>))}
            {designs.some(d => !d.is_valid) && <p className="px-4 py-2 text-[11px] text-red-600 bg-red-50 border-t border-red-100">Designs with errors can&apos;t be priced.</p>}
          </div>

          <div className="bg-white border border-stone-200 rounded-lg shadow-sm">
            {rates && <div className="px-4 pt-3"><Switch label="Include GST" checked={gstOn(rates)} onChange={v => setRates({ ...rates, gst_enabled: v })}
              hint={gstOn(rates) ? `GST at ${rates.gst_pct}% is added; invoices will be GST tax invoices.` : 'No GST on the quotation or its invoices.'} /></div>}
            {rates && <div className="px-4 pt-3"><Switch label="Include material take-off" checked={tkOn(rates)} onChange={v => setRates({ ...rates, include_takeoff: v })}
              hint={tkOn(rates) ? 'Adds ceiling, lighting, electrical points, paint, flooring… measured from the design (Estimation → Take-off).' : 'Furniture only.'} /></div>}
            <button onClick={() => setShowRates(v => !v)} className="w-full px-4 py-3 text-sm font-semibold text-left flex justify-between">Rates used for new BOQs <span className="text-xs text-stone-400 font-normal">{showRates ? 'hide' : 'edit'}</span></button>
            {showRates && rates && <div className="px-4 pb-4 grid grid-cols-2 gap-x-3 gap-y-2">
              {RATE_FIELDS.map(([k, label]) => (<label key={k} className="text-[11px] text-stone-500">{label}
                <input value={String(rates[k] ?? '')} onChange={e => setRates({ ...rates, [k]: e.target.value })} disabled={k === 'gst_pct' && !gstOn(rates)} inputMode="decimal" className={input + ' block mt-0.5 disabled:bg-stone-100 disabled:text-stone-400'} aria-label={label} /></label>))}
              <p className="col-span-2 text-[10px] text-stone-400">Defaults come from the server. The server validates every value (0–100% for rates).</p></div>}
          </div>

          <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-stone-100 text-sm font-semibold">BOQ versions ({boqs.length})</div>
            {boqs.length === 0 ? <p className="p-4 text-xs text-stone-400">None yet.</p> : boqs.map(b => (
              <button key={b.id} onClick={() => show(b.id)} className={cn('w-full text-left px-4 py-2.5 border-b border-stone-50 last:border-0 text-xs flex items-center gap-2', open?.id === b.id ? 'bg-amber-50' : 'hover:bg-stone-50')}>
                <div className="flex-1"><p className="font-semibold">{b.quotation_no}</p><p className="text-[11px] text-stone-400">from design v{b.design_version}{b.warnings ? ` · ${b.warnings} warning(s)` : ''}</p></div>
                <span className="font-mono">Rs. {inrStr(b.grand_total)}</span></button>))}
          </div>
        </div>

        <div className="col-span-12 lg:col-span-8">
          {!open ? <div className="bg-white border border-stone-200 rounded-lg p-14 text-center shadow-sm text-sm text-stone-400"><FileSpreadsheet className="w-8 h-8 mx-auto mb-2 text-stone-300" />Create a BOQ from a valid design, or open an existing version.</div> : (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex-1"><p className="text-sm font-semibold">{open.quotation_no}</p><p className="text-[11px] text-stone-400">Based on design v{open.design_version} · created {new Date(open.created_at).toLocaleString()}</p></div>
              <button onClick={() => pdf(open)} className="flex items-center gap-1.5 text-sm bg-stone-900 hover:bg-stone-800 text-white px-3 py-1.5 rounded font-medium"><Download className="w-4 h-4" />Quotation PDF</button>
            </div>
            {open.warnings.length > 0 && <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 space-y-1" role="alert">
              {open.warnings.map((w, i) => <p key={i} className="text-xs text-amber-900 flex gap-2"><AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />{w}</p>)}</div>}
            <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-x-auto">
              <table className="w-full text-xs"><thead><tr className="bg-stone-50 border-b border-stone-100">
                {['#', 'Item', 'Qty', 'Rate', 'Labour', 'Amount'].map((h, i) => <th key={h} className={cn('text-[11px] text-stone-400 uppercase tracking-wide px-4 py-2.5', i > 1 ? 'text-right' : 'text-left')}>{h}</th>)}</tr></thead>
                <tbody className="divide-y divide-stone-50">{open.items.map(i => (
                  <tr key={i.line}><td className="px-4 py-2.5 text-stone-400">{i.line}</td>
                    <td className="px-4 py-2.5"><p className="font-medium text-stone-800">{i.description}</p><p className="text-[11px] text-stone-400">{[i.category, i.sku, i.material].filter(Boolean).join(' · ')}{i.flags.includes('NOT_IN_CATALOGUE') && <span className="ml-2 text-amber-700 font-semibold">not in catalogue</span>}{i.flags.includes('TAKEOFF') && <span className="ml-2 text-blue-700 font-semibold" data-testid="takeoff-tag">take-off</span>}</p>{i.supplier && <p className="text-[11px] text-stone-500" data-testid="line-supplier">Supplier: {i.supplier}</p>}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{i.qty} {i.unit}</td><td className="px-4 py-2.5 text-right font-mono">{inrStr(i.rate)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-stone-500">{Number(i.labour) ? inrStr(i.labour) : '—'}</td><td className="px-4 py-2.5 text-right font-mono font-semibold">{inrStr(i.total)}</td></tr>))}</tbody></table>
            </div>
            <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-5 max-w-md ml-auto" data-testid="boq-summary">
              {SUMMARY.filter(([k]) => k !== 'gst' || open.gst_enabled).map(([k, label]) => <div key={k} className="flex justify-between py-1 text-xs"><span className="text-stone-500">{label}{k === 'discount' ? ` (${open.params.discount_pct}%)` : k === 'gst' ? ` (${open.params.gst_pct}%)` : k === 'overhead' ? ` (${open.params.overhead_pct}%)` : k === 'margin' ? ` (${open.params.margin_pct}%)` : ''}</span>
                <span className="font-mono">{k === 'discount' ? '−' : ''}{inrStr(open.totals[k])}</span></div>)}
              <div className="flex justify-between pt-3 mt-2 border-t-2 border-stone-200"><span className="font-bold">{open.gst_enabled ? 'Grand total (incl. GST)' : 'Grand total'}</span><span className="font-bold text-amber-700 font-mono" data-testid="grand-total">Rs. {inrStr(open.totals.grand_total)}</span></div>
            </div>
          </div>)}
        </div>
      </div>)}
    </div>
  )
}
