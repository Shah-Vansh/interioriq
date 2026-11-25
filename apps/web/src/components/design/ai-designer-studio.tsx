'use client'
import { useCallback, useEffect, useState } from 'react'
import { DesignChat } from '@/components/design/design-chat'
import Link from 'next/link'
import { Wand2, Loader2, ShieldCheck, ShieldAlert, Save, Download, History, Info, PackageX } from 'lucide-react'
import { api, ApiError, downloadFile, DesignVersion, GenerateResult, Measurement, Room } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import { PlanSvg } from '@/components/design/drawing-views'
import { Opening } from '@/components/survey/openings-card'
import { useLoad } from '@/components/ui/kit'
import { cn } from '@/lib/utils'

interface Slot { slot: string; label: string; categories: string[] }
interface LayoutMeta { kinds: string[]; room_kind: Record<string, string>; kitchen_shapes: string[]; tiers: string[]; styles: string[]; required: Record<string, Slot[]>; optional: Record<string, Slot[]> }
const KIND_LABEL: Record<string, string> = { BEDROOM: 'Bedroom', LIVING: 'Living room', DINING: 'Dining room', KITCHEN: 'Kitchen', STUDY: 'Study', BATHROOM: 'Bathroom', UTILITY: 'Utility / wash area', OUTDOOR: 'Verandah / balcony', FOYER: 'Foyer / passage', POOJA: 'Pooja room', STORE: 'Store room' }
const SHAPE_LABEL: Record<string, string> = { AUTO: 'Auto (most counter)', STRAIGHT: 'Straight', L: 'L-shaped', PARALLEL: 'Parallel', U: 'U-shaped' }
const EXAMPLES: Record<string, string[]> = {
  BEDROOM: ['Modern bedroom with walnut wardrobe, warm tones, under 20 lakh', 'Minimal luxury master bedroom, budget 12 lakh'],
  LIVING: ['Cosy living room with a big sofa facing the TV, under 6 lakh', 'Minimal Scandinavian living room, budget 4 lakh'],
  DINING: ['Six-seater walnut dining with a crockery unit, under 3 lakh'],
  KITCHEN: ['Modular kitchen with a tall fridge unit, budget 5 lakh'],
  STUDY: ['Quiet study by the window with a bookshelf, under 1.5 lakh'],
}
const COST_ROWS: [string, string][] = [['Subtotal', 'subtotal'], ['Overhead (8%)', 'overhead'], ['Margin (18%)', 'margin'], ['Discount (5%)', 'discount'], ['GST (18%)', 'gst']]
const TIER_LABEL: Record<string, string> = { BUDGET: 'Budget', BALANCED: 'Balanced', PREMIUM: 'Premium' }
const money = (v: string | number | null | undefined) => (v === null || v === undefined ? '—' : inr(String(v)))

export function AIDesignerStudio() {
  const [sel, setSel] = useState<{ projectId: string; roomId: string; room: Room | null }>({ projectId: '', roomId: '', room: null })
  const [dims, setDims] = useState<{ L: number; W: number } | null>(null)
  const [openings, setOpenings] = useState<Opening[]>([])
  const [prompt, setPrompt] = useState('')
  const [kind, setKind] = useState('')
  const [skip, setSkip] = useState<string[]>([])
  const [shape, setShape] = useState('AUTO')
  const [seats, setSeats] = useState('')
  const [inStock, setInStock] = useState(true)
  const [tier, setTier] = useState('BALANCED')
  const [style, setStyle] = useState('')
  const [chatBudget, setChatBudget] = useState<string | null>(null)       // set by the design chat; else read from the brief
  const [result, setResult] = useState<GenerateResult | null>(null)
  const [history, setHistory] = useState<DesignVersion[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const { data: meta } = useLoad<LayoutMeta>('/layouts/meta')

  const loadRoom = useCallback(async () => {
    setResult(null); setError(''); setSaved(''); setDims(null); setHistory([]); setOpenings([])
    if (!sel.roomId) return
    try {
      const [ms, h, op] = await Promise.all([api.get<Measurement[]>(`/rooms/${sel.roomId}/measurements`), api.get<DesignVersion[]>(`/rooms/${sel.roomId}/designs`),
        api.get<{ openings: Opening[] }>(`/rooms/${sel.roomId}/openings`)])
      const L = ms.find(m => m.label.toLowerCase().includes('length'))?.value
      const W = ms.find(m => m.label.toLowerCase().includes('width'))?.value
      if (L && W) setDims({ L, W })
      setHistory(h); setOpenings(op.openings)
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Failed to load room') }
  }, [sel.roomId])
  useEffect(() => { loadRoom() }, [loadRoom])
  // the room's own type decides the layout unless the user picks another (e.g. an 'Other' room laid out as a study)
  useEffect(() => { setKind(meta?.room_kind[sel.room?.room_type ?? ''] ?? ''); setSkip([]); setShape('AUTO'); setSeats(''); setChatBudget(null) }, [sel.room?.room_type, meta])

  const generate = async () => {
    setBusy(true); setError(''); setSaved('')
    try {
      setResult(await api.post<GenerateResult>(`/rooms/${sel.roomId}/designs/generate`, {
        prompt, catalogue_filter_in_stock: inStock, room_type: kind || undefined,
        budget: chatBudget ?? undefined,
        options: { skip, tier, ...(style ? { styles: [style] } : {}), ...(kind === 'KITCHEN' ? { kitchen_shape: shape } : {}), ...(kind === 'DINING' && seats ? { seats: Number(seats) } : {}) } }))
    } catch (e) { setResult(null); setError(e instanceof ApiError ? e.message : 'Generation failed') } finally { setBusy(false) }
  }
  const save = async () => {
    if (!result) return
    try {
      const r = await api.post<{ version: number; is_valid: boolean }>(`/rooms/${sel.roomId}/designs`, { tier: TIER_LABEL[tier] ?? 'Balanced', objects: result.objects })
      setSaved(`Saved as version ${r.version}${r.is_valid ? '' : ' (flagged invalid)'}.`)
      setHistory(await api.get<DesignVersion[]>(`/rooms/${sel.roomId}/designs`))
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Save failed') }
  }
  const dl = (k: string) => downloadFile(`/rooms/${sel.roomId}/cad/${k}`, `${k}.dxf`).catch(e => setError(e.message))

  const needsDims = !!sel.roomId && !dims
  const budget = result?.requirements.budget ?? null
  const unsupported = !!sel.room && !!meta && !meta.room_kind[sel.room.room_type]
  const optional = (kind && meta?.optional[kind]) || []

  return (
    <div className="max-w-[1300px] space-y-5">
      <div><h1 className="text-xl font-semibold text-stone-900">AI Designer</h1>
        <p className="text-sm text-stone-500 mt-0.5">Lays out bedrooms, living and dining rooms, kitchens and studies from your catalogue. The language model only reads your brief — placement, validation and cost are computed by rules on the server.</p></div>
      <ProjectRoomPicker onChange={setSel} />

      {!sel.roomId && <p className="text-sm text-stone-500 bg-white border border-stone-200 rounded-lg p-6">Pick a room first. Create projects and rooms under Projects and Survey → Rooms.</p>}
      {needsDims && <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        This room needs Length and Width measurements before it can be designed. <Link href="/survey/rooms" className="underline font-medium">Add them in Rooms →</Link></p>}

      {sel.roomId && dims && (
        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 lg:col-span-4 space-y-4">
            <div className="bg-white border border-stone-200 rounded-lg p-4 shadow-sm space-y-3">
              <h3 className="text-xs font-semibold text-stone-500 uppercase tracking-wide">Layout</h3>
              <label className="block text-xs text-stone-600">Lay out as
                <select aria-label="Layout type" value={kind} onChange={e => { setKind(e.target.value); setSkip([]); setResult(null) }}
                  className="mt-1 w-full text-sm border border-stone-200 rounded px-2 py-1.5 bg-white">
                  {unsupported && <option value="">— choose a layout type —</option>}
                  {meta?.kinds.map(k => <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>)}</select></label>
              {unsupported && <p className="text-[11px] text-amber-800">This room is a {sel.room?.room_type.replace('_', ' ').toLowerCase()} — automatic layouts don't cover it. Pick the closest type, or place items by hand in the 3D editor.</p>}
              {kind && meta && <p className="text-[11px] text-stone-500">Always places: {meta.required[kind].map(s => s.label).join(', ')}.</p>}
              {optional.length > 0 && <fieldset className="space-y-1"><legend className="text-xs text-stone-600 mb-1">Also place (if they fit)</legend>
                {optional.map(o => <label key={o.slot} className="flex items-center gap-2 text-sm"><input type="checkbox" aria-label={`Include ${o.label}`} checked={!skip.includes(o.slot)}
                  onChange={e => setSkip(s => e.target.checked ? s.filter(x => x !== o.slot) : [...s, o.slot])} />{o.label}</label>)}</fieldset>}
              {kind === 'KITCHEN' && <label className="block text-xs text-stone-600">Kitchen shape
                <select aria-label="Kitchen shape" value={shape} onChange={e => setShape(e.target.value)} className="mt-1 w-full text-sm border border-stone-200 rounded px-2 py-1.5 bg-white">
                  {meta?.kitchen_shapes.map(s => <option key={s} value={s}>{SHAPE_LABEL[s] ?? s}</option>)}</select></label>}
              {kind === 'DINING' && <label className="block text-xs text-stone-600">Seats
                <select aria-label="Seats" value={seats} onChange={e => setSeats(e.target.value)} className="mt-1 w-full text-sm border border-stone-200 rounded px-2 py-1.5 bg-white">
                  <option value="">As many as the table takes</option>{[2, 4, 6, 8].map(n => <option key={n} value={n}>{n}</option>)}</select></label>}
              <div className="grid grid-cols-2 gap-2">
                <label className="block text-xs text-stone-600">Tier
                  <select aria-label="Tier" value={tier} onChange={e => setTier(e.target.value)} className="mt-1 w-full text-sm border border-stone-200 rounded px-2 py-1.5 bg-white">
                    {(meta?.tiers ?? ['BALANCED']).map(t => <option key={t} value={t}>{TIER_LABEL[t] ?? t}{t === 'BUDGET' ? ' (cheapest first)' : t === 'PREMIUM' ? ' (finest first)' : ' (largest that fits)'}</option>)}</select></label>
                <label className="block text-xs text-stone-600">Style
                  <select aria-label="Style" value={style} onChange={e => setStyle(e.target.value)} className="mt-1 w-full text-sm border border-stone-200 rounded px-2 py-1.5 bg-white">
                    <option value="">From the brief</option>{meta?.styles.map(s => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select></label></div>
              <label className="flex items-center gap-2 text-xs text-stone-600"><input type="checkbox" checked={inStock} onChange={e => setInStock(e.target.checked)} />Use only items in stock</label>
            </div>
            <div className="bg-white border border-stone-200 rounded-lg p-4 shadow-sm">
              <h3 className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-3">Design brief</h3>
              <textarea aria-label="Design brief" value={prompt} onChange={e => setPrompt(e.target.value)} rows={4} placeholder="Describe the room (optional) — style and budget are read from it…"
                className="w-full text-sm border border-stone-200 rounded px-3 py-2.5 bg-stone-50 outline-none focus:border-amber-400 resize-none" />
              <div className="flex gap-1.5 my-2 flex-wrap">{(EXAMPLES[kind] ?? EXAMPLES.BEDROOM).map((e, i) => (
                <button key={i} onClick={() => setPrompt(e)} className="text-[11px] text-amber-700 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 rounded-full border border-amber-200">Example {i + 1}</button>))}</div>
              <button onClick={generate} disabled={busy || !kind} className="w-full flex items-center justify-center gap-2 py-2.5 rounded font-medium text-sm bg-amber-700 hover:bg-amber-800 disabled:opacity-60 text-white">
                {busy ? <><Loader2 className="w-4 h-4 animate-spin" />Generating…</> : <><Wand2 className="w-4 h-4" />Generate {KIND_LABEL[kind]?.toLowerCase() ?? ''} layout</>}</button>
            </div>
            {sel.roomId && kind && <DesignChat roomId={sel.roomId} roomType={kind} prompt={prompt} inStock={inStock} budget={chatBudget}
              options={{ skip, tier, styles: style ? [style] : [], kitchen_shape: shape, seats: seats ? Number(seats) : null }}
              onApply={r => { setSkip(r.options.skip); setTier(r.options.tier); setStyle(r.options.styles[0] ?? ''); setShape(r.options.kitchen_shape || 'AUTO')
                setSeats(r.options.seats ? String(r.options.seats) : ''); setChatBudget(r.budget); setResult(r.result); setSaved('') }} />}
            <div className="bg-white border border-stone-200 rounded-lg shadow-sm">
              <div className="px-4 py-3 border-b border-stone-100 flex items-center gap-2 text-sm font-semibold"><History className="w-4 h-4 text-amber-700" />Saved versions</div>
              {history.length === 0 ? <p className="p-4 text-xs text-stone-400">None yet. History is append-only — saving never overwrites.</p>
                : history.map(h => (<div key={h.id} className="flex items-center gap-3 px-4 py-2.5 border-b border-stone-50 last:border-0 text-xs">
                  <span className="font-semibold">v{h.version}</span><span className="text-stone-400 flex-1">{h.tier}</span>
                  <span className={cn('font-medium', h.is_valid ? 'text-green-600' : 'text-red-600')}>{h.is_valid ? 'valid' : 'invalid'}</span>
                  <span className="text-stone-400">{h.status}</span></div>))}
            </div>
          </div>

          <div className="col-span-12 lg:col-span-8 space-y-4">
            {error && <p role="alert" className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
            {!result ? <div className="bg-white border border-stone-200 rounded-lg p-6 shadow-sm">
                <p className="text-sm text-stone-400 text-center mb-3">Room is {dims.L} × {dims.W} mm{openings.length ? ` with ${openings.length} door(s)/window(s)` : ''}. Click Generate to place furniture.</p>
                <PlanSvg room={{ L: dims.L, W: dims.W, H: 0 }} objects={[]} openings={openings} h={380} /></div> : (<>
              <div data-testid="layout-validation" className={cn('rounded-lg border px-4 py-3 flex items-start gap-3', result.validation.valid ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200')}>
                {result.validation.valid ? <ShieldCheck className="w-5 h-5 text-green-600 mt-0.5" /> : <ShieldAlert className="w-5 h-5 text-red-600 mt-0.5" />}
                <div className="text-xs">
                  <p className={cn('font-semibold text-sm', result.validation.valid ? 'text-green-800' : 'text-red-800')}>{result.validation.valid ? 'Valid layout' : 'Invalid layout'} · occupancy {(result.validation.occupancy * 100).toFixed(0)}%</p>
                  {[...result.validation.errors, ...result.validation.warnings].map((m, i) => <p key={i} className="text-stone-600 mt-0.5">• {m}</p>)}
                  <p className="text-stone-400 mt-1">Brief read by: {result.requirements.source ?? 'none'} · style: {result.requirements.style}</p>
                </div>
              </div>
              {!!result.missing?.length && <div data-testid="layout-missing" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 flex gap-2">
                <PackageX className="w-4 h-4 mt-0.5 shrink-0" /><div>
                  <p className="font-semibold">Not in the catalogue{inStock ? ' (or out of stock)' : ''} — nothing was invented for these:</p>
                  {result.missing.map(m => <p key={m.slot}>• {m.label}{m.required ? ' (needed)' : ''} — {m.out_of_stock ? 'in the catalogue but out of stock; untick "Use only items in stock" or receive stock' : `add an item with category “${m.categories[0]}”`}</p>)}
                  <Link href="/catalogue/furniture" className="underline font-medium">Catalogue → Furniture</Link></div></div>}
              <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-2" data-testid="layout-preview">
                <PlanSvg room={{ L: dims.L, W: dims.W, H: 0 }} objects={result.objects} openings={openings} h={420} /></div>
              {!!result.notes?.length && <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4" data-testid="layout-notes">
                <p className="text-sm font-semibold mb-1.5 flex items-center gap-1.5"><Info className="w-4 h-4 text-amber-700" />Why it's laid out this way</p>
                <ul className="space-y-1 text-xs text-stone-700">{result.notes.map((n, i) => <li key={i}>• {n}</li>)}</ul></div>}
              <div className="grid md:grid-cols-2 gap-4">
                <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-stone-100 text-sm font-semibold">Placed objects ({result.objects.length})</div>
                  {result.objects.length === 0 && <p className="p-4 text-xs text-stone-400">Nothing could be placed — see the notes above.</p>}
                  {result.objects.map(o => (<div key={o.id} data-placed={o.category} className="flex items-center gap-3 px-4 py-2 border-b border-stone-50 last:border-0 text-xs">
                    <div className="flex-1"><p className="font-medium text-stone-800">{o.name}</p><p className="text-[11px] text-stone-400">{o.length}×{o.width}×{o.height} mm at ({Math.round(o.x)}, {Math.round(o.y)}){o.z ? `, fixed ${o.z} mm above the floor` : ''}</p></div>
                    <span className="font-mono">{money(o.price)}</span></div>))}
                </div>
                <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4">
                  <div className="text-sm font-semibold mb-2">Estimate</div>
                  {COST_ROWS.map(([l, k]) => (<div key={k} className="flex justify-between py-1 text-xs"><span className="text-stone-500">{l}</span><span className="font-mono">{k === 'discount' ? '−' : ''}{money(result.cost[k])}</span></div>))}
                  <div className="flex justify-between pt-2 mt-1 border-t border-stone-200"><span className="font-bold text-sm">Total</span><span className="font-bold text-amber-700" data-testid="layout-total">{money(result.cost.grand_total)}</span></div>
                  {budget && <p className={cn('text-[11px] mt-2', result.over_budget ? 'text-red-600' : 'text-green-600')}>{result.over_budget ? `Over your ${money(budget)} budget by ${money(result.budget_gap)}` : `Within your ${money(budget)} budget (${money(result.budget_gap)} to spare)`}</p>}
                </div>
              </div>
              <div className="flex gap-2 flex-wrap items-center">
                <button onClick={save} disabled={!result.objects.length} className="flex items-center gap-1.5 text-sm text-white bg-stone-900 hover:bg-stone-800 disabled:opacity-50 px-3 py-2 rounded font-medium"><Save className="w-4 h-4" />Save as new version</button>
                {saved && <span className="text-xs text-green-700">{saved} <Link href="/design/3d" className="underline">Open in 3D editor →</Link></span>}
                <div className="flex-1" />
                {history.length > 0 && ['floor-plan', 'furniture', 'elevation-north'].map(k => (
                  <button key={k} onClick={() => dl(k)} className="flex items-center gap-1.5 text-xs border border-stone-200 bg-white hover:bg-stone-50 px-3 py-2 rounded"><Download className="w-3.5 h-3.5" />{k}.dxf</button>))}
              </div>
              {history.length === 0 && <p className="text-[11px] text-stone-400">Save a version to enable DXF downloads (drawings come from the saved Design Model).</p>}
            </>)}
          </div>
        </div>)}
    </div>
  )
}
