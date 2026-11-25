'use client'
// Room shell (M41): shape (rectangle / L-shaped with corner cut-outs / any outline with angled walls), ceiling (flat / sloped / uneven spots),
// and fixed building parts (beams, columns, pillars, ceiling drops). The SERVER validates everything and re-checks the latest design.
import { useEffect, useState } from 'react'
import { Loader2, Plus, Save, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { fitScale } from '@/lib/ops'
import { area, Ceiling, CORNERS, cutsOutline, KIND_LABEL, parsePoints, Shell, Structure } from '@/lib/room-shell'
import { Alert, btn, Empty, Field, hasRole, input, Ok, Table, useAction, useLoad, useRole } from '@/components/ui/kit'
import { OutlineSvg, StructuresSvg } from '@/components/survey/shell-svg'
import { OpeningsSvg, type Opening } from '@/components/survey/openings-card'

interface Resp extends Shell { openings: Opening[]; problems: string[]; latest_design: { version: number; valid: boolean; errors: string[]; warnings: string[] } | null }
const CORNER_LABEL: Record<string, string> = { SW: 'South-west (bottom left)', SE: 'South-east (bottom right)', NE: 'North-east (top right)', NW: 'North-west (top left)' }

export function ShellCard({ roomId, L, W, onChanged }: { roomId: string; L: number | null; W: number | null; onChanged?: () => void }) {
  const role = useRole(); const can = hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER', 'INTERIOR_DESIGNER'])
  const { data, setData, error } = useLoad<Resp>(L && W ? `/rooms/${roomId}/shape` : null, [roomId, L, W])
  const a = useAction()
  // shape form
  const [kind, setKind] = useState<'RECT' | 'CUTS' | 'POLYGON'>('RECT')
  const [cuts, setCuts] = useState<Record<string, { on: boolean; l: string; w: string }>>(Object.fromEntries(CORNERS.map(c => [c, { on: false, l: '1200', w: '1200' }])))
  const [pts, setPts] = useState('')
  // ceiling form
  const [ct, setCt] = useState<'FLAT' | 'SLOPED' | 'UNEVEN'>('FLAT')
  const [slope, setSlope] = useState({ low: '2600', high: '3200', high_wall: 'N' })
  const [spots, setSpots] = useState('')
  // structure form
  const [sf, setSf] = useState({ kind: 'BEAM', x_mm: '', y_mm: '', length_mm: '', width_mm: '230', depth_mm: '450', label: '' })

  useEffect(() => {                                                       // load the saved values into the forms
    if (!data) return
    setKind(data.shape.type)
    if (data.shape.type === 'CUTS') { const c = data.shape.cuts; setCuts(Object.fromEntries(CORNERS.map(k => [k, c[k] ? { on: true, l: String(c[k]![0]), w: String(c[k]![1]) } : { on: false, l: '1200', w: '1200' }]))) }
    setPts(data.outline.map(p => p.join(', ')).join('\n'))
    setCt(data.ceiling.type)
    if (data.ceiling.type === 'SLOPED') setSlope({ low: String(data.ceiling.low), high: String(data.ceiling.high), high_wall: data.ceiling.high_wall })
    if (data.ceiling.type === 'UNEVEN') setSpots(data.ceiling.points.map(p => p.join(', ')).join('\n'))
    else if (!spots) setSpots(`0, 0, ${data.H}\n${data.L}, 0, ${data.H}\n${data.L}, ${data.W}, ${data.H}\n0, ${data.W}, ${data.H}`)
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!L || !W) return <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4" data-testid="shell-card"><h2 className="text-sm font-semibold">Room shape, ceiling, beams & columns</h2><Empty>Add Length and Width first.</Empty></div>
  const cutVals = Object.fromEntries(CORNERS.filter(k => cuts[k].on).map(k => [k, [Number(cuts[k].l), Number(cuts[k].w)] as [number, number]]))
  const preview = kind === 'CUTS' ? cutsOutline(L, W, cutVals) : kind === 'POLYGON' ? ((parsePoints(pts, 2) as [number, number][] | null) ?? data?.outline ?? []) : [[0, 0], [L, 0], [L, W], [0, W]] as [number, number][]
  const fit = fitScale(L, W, 380, 300, 30); const sx = (x: number) => fit.pad + x * fit.s, sy = (y: number) => fit.pad + (W - y) * fit.s
  const done = (r: Resp) => { setData(r); onChanged?.() }

  const saveShape = () => {
    if (kind === 'POLYGON' && !parsePoints(pts, 2)) { a.setError('Outline: one corner per line as "x, y" in mm'); return }
    const shape = kind === 'RECT' ? { type: 'RECT' } : kind === 'CUTS' ? { type: 'CUTS', cuts: cutVals } : { type: 'POLYGON', points: parsePoints(pts, 2) }
    a.run('shape', async () => done(await api.put<Resp>(`/rooms/${roomId}/shape`, { shape })), 'Room shape saved')
  }
  const saveCeiling = () => {
    let ceiling: Ceiling | { type: string; [k: string]: unknown } = { type: 'FLAT' }
    if (ct === 'SLOPED') ceiling = { type: 'SLOPED', low: Number(slope.low), high: Number(slope.high), high_wall: slope.high_wall }
    if (ct === 'UNEVEN') { const p = parsePoints(spots, 3); if (!p) { a.setError('Spots: one per line as "x, y, height" in mm'); return } ceiling = { type: 'UNEVEN', points: p } }
    a.run('ceiling', async () => done(await api.put<Resp>(`/rooms/${roomId}/ceiling`, { ceiling })), 'Ceiling saved')
  }
  const addStructure = (e: React.FormEvent) => {
    e.preventDefault()
    const need = ['x_mm', 'y_mm', 'length_mm', 'width_mm', ...(sf.kind === 'BEAM' || sf.kind === 'CEILING_DROP' ? ['depth_mm'] : [])] as (keyof typeof sf)[]
    for (const k of need) if (!/^\d+(\.\d+)?$/.test(sf[k])) { a.setError('Enter position and sizes in whole millimetres'); return }
    const deep = sf.kind === 'BEAM' || sf.kind === 'CEILING_DROP'
    a.run('struct', async () => done(await api.post<Resp>(`/rooms/${roomId}/structures`, { kind: sf.kind, x_mm: Number(sf.x_mm), y_mm: Number(sf.y_mm), length_mm: Number(sf.length_mm),
      width_mm: Number(sf.width_mm), depth_mm: deep ? Number(sf.depth_mm) : undefined, label: sf.label || undefined })), `${KIND_LABEL[sf.kind as Structure['kind']].split(' (')[0]} added`)
  }
  const setS = (k: keyof typeof sf) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setSf(p => ({ ...p, [k]: e.target.value,
    ...(k === 'kind' ? (e.target.value === 'BEAM' ? { width_mm: '230', depth_mm: '450' } : e.target.value === 'CEILING_DROP' ? { width_mm: '600', depth_mm: '300' } : { width_mm: '300', length_mm: '300' }) : {}) }))

  return (
    <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4 space-y-3" data-testid="shell-card">
      <div><h2 className="text-sm font-semibold text-stone-800">Room shape, ceiling, beams & columns</h2>
        <p className="text-xs text-stone-500">For L-shaped or odd rooms, sloped or uneven ceilings and the beams, columns and pillars on site. Positions are in mm from the room&apos;s
          bottom-left (south-west) corner of the Length × Width box. The designer, the validator, every drawing, the take-off and the 3D view use them.</p></div>
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {data?.problems.map(p => <Alert key={p}>{p}</Alert>)}
      {data?.latest_design && !data.latest_design.valid && <Alert>Latest design v{data.latest_design.version} now has problems: {data.latest_design.errors.join('; ')}. Re-generate it or fix it in the 3D editor.</Alert>}
      <div className="grid lg:grid-cols-2 gap-4 items-start">
        <div>
          <svg viewBox={`0 0 ${fit.w} ${fit.h}`} className="w-full h-auto bg-stone-50 rounded" role="img" aria-label="Room shape plan" data-testid="shell-plan">
            <rect x={sx(0)} y={sy(W)} width={L * fit.s} height={W * fit.s} fill="none" stroke="#d6d3d1" strokeDasharray="4 4" />
            {preview.length >= 3 && <OutlineSvg outline={preview} sx={sx} sy={sy} />}
            {data && <StructuresSvg items={data.structures} sx={sx} sy={sy} />}
            {data && <OpeningsSvg ops={data.openings} L={L} W={W} s={fit.s} sx={sx} sy={sy} />}
            <text x={fit.w - 14} y={18} fontSize={11} fill="#b45309" fontWeight={700} textAnchor="middle">N ↑</text>
          </svg>
          {data && <p className="text-xs text-stone-500 mt-1" data-testid="shell-summary">Floor {data.area_sqm} sq.m · {data.edges.length} walls · ceiling {data.ceiling_min === data.ceiling_max ? `${data.ceiling_min} mm` : `${data.ceiling_min}–${data.ceiling_max} mm`}
            {preview.length >= 3 && kind !== 'RECT' ? ` · preview ${(area(preview) / 1e6).toFixed(2)} sq.m` : ''}</p>}
        </div>
        <div className="space-y-4">
          <fieldset className="space-y-2" disabled={!can}><legend className="text-xs font-semibold text-stone-600 uppercase">Shape</legend>
            <select aria-label="Room shape" value={kind} onChange={e => setKind(e.target.value as typeof kind)} className={input}>
              <option value="RECT">Rectangle</option><option value="CUTS">L-shaped / U-shaped (corner cut out)</option><option value="POLYGON">Any outline (angled walls) — corner points</option></select>
            {kind === 'CUTS' && <div className="space-y-1">{CORNERS.map(k => <div key={k} className="grid grid-cols-[1fr_80px_80px] gap-2 items-center text-xs">
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={cuts[k].on} onChange={e => setCuts(c => ({ ...c, [k]: { ...c[k], on: e.target.checked } }))} aria-label={`Cut ${k} corner`} />{CORNER_LABEL[k]}</label>
              <input aria-label={`${k} cut length`} value={cuts[k].l} onChange={e => setCuts(c => ({ ...c, [k]: { ...c[k], l: e.target.value } }))} className={input} placeholder="along x" disabled={!cuts[k].on} />
              <input aria-label={`${k} cut width`} value={cuts[k].w} onChange={e => setCuts(c => ({ ...c, [k]: { ...c[k], w: e.target.value } }))} className={input} placeholder="along y" disabled={!cuts[k].on} /></div>)}
              <p className="text-[11px] text-stone-400">Cut size: how far it goes along the length (x) × along the width (y), in mm.</p></div>}
            {kind === 'POLYGON' && <Field label="Corners in order around the room: x, y (mm), one per line"><textarea aria-label="Outline points" value={pts} onChange={e => setPts(e.target.value)} rows={6} className={input + ' font-mono text-xs'} /></Field>}
            {can && <button onClick={saveShape} disabled={!!a.busy} className={btn.primary}>{a.busy === 'shape' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}Save shape</button>}
          </fieldset>
          <fieldset className="space-y-2" disabled={!can}><legend className="text-xs font-semibold text-stone-600 uppercase">Ceiling</legend>
            <select aria-label="Ceiling type" value={ct} onChange={e => setCt(e.target.value as typeof ct)} className={input}>
              <option value="FLAT">Flat (Ceiling Height measurement)</option><option value="SLOPED">Sloped — low on one side, high on the other</option><option value="UNEVEN">Uneven — heights measured at spots</option></select>
            {ct === 'SLOPED' && <div className="grid grid-cols-3 gap-2">
              <Field label="Lowest (mm)"><input aria-label="Lowest ceiling" value={slope.low} onChange={e => setSlope(s => ({ ...s, low: e.target.value }))} className={input} /></Field>
              <Field label="Highest (mm)"><input aria-label="Highest ceiling" value={slope.high} onChange={e => setSlope(s => ({ ...s, high: e.target.value }))} className={input} /></Field>
              <Field label="High side"><select aria-label="High side" value={slope.high_wall} onChange={e => setSlope(s => ({ ...s, high_wall: e.target.value }))} className={input}>
                {['N', 'E', 'S', 'W'].map(w => <option key={w} value={w}>{w}</option>)}</select></Field></div>}
            {ct === 'UNEVEN' && <Field label="Spots: x, y, height (mm), one per line — measure where it's lowest too"><textarea aria-label="Ceiling spots" value={spots} onChange={e => setSpots(e.target.value)} rows={5} className={input + ' font-mono text-xs'} /></Field>}
            {can && <button onClick={saveCeiling} disabled={!!a.busy} className={btn.primary}>{a.busy === 'ceiling' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}Save ceiling</button>}
          </fieldset>
        </div>
      </div>
      <div className="border-t border-stone-100 pt-3 space-y-2">
        <h3 className="text-xs font-semibold text-stone-600 uppercase">Beams, columns, pillars, ceiling drops</h3>
        {!data ? <Empty>Loading…</Empty> : data.structures.length === 0 ? <p className="text-xs text-stone-400">None recorded.</p> :
          <Table head={['', 'Position (x, y)', 'Size', 'Depth', '']}>{data.structures.map(s => <tr key={s.id} data-structure-row={s.label}>
            <td className="px-2 py-1.5 text-xs font-medium">{s.label}</td><td className="px-2 py-1.5 text-xs">{s.x}, {s.y}</td><td className="px-2 py-1.5 text-xs">{s.length} × {s.width}</td>
            <td className="px-2 py-1.5 text-xs">{s.kind === 'BEAM' || s.kind === 'CEILING_DROP' ? `${s.depth} below ceiling` : 'floor to ceiling'}</td>
            <td className="px-2 py-1.5">{can && <button onClick={() => a.run(s.id, async () => done(await api.delete<Resp>(`/structures/${s.id}`)))} aria-label={`Remove ${s.label}`} className={btn.small}><Trash2 className="w-3 h-3" /></button>}</td></tr>)}</Table>}
        {can && <form onSubmit={addStructure} className="grid grid-cols-2 md:grid-cols-4 gap-2 items-end">
          <Field label="Type"><select aria-label="Structure type" value={sf.kind} onChange={setS('kind')} className={input}>{Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="From west wall x (mm)"><input aria-label="Structure x" value={sf.x_mm} onChange={setS('x_mm')} inputMode="numeric" className={input} /></Field>
          <Field label="From south wall y (mm)"><input aria-label="Structure y" value={sf.y_mm} onChange={setS('y_mm')} inputMode="numeric" className={input} /></Field>
          <Field label="Length along x (mm)"><input aria-label="Structure length" value={sf.length_mm} onChange={setS('length_mm')} inputMode="numeric" className={input} /></Field>
          <Field label="Width along y (mm)"><input aria-label="Structure width" value={sf.width_mm} onChange={setS('width_mm')} inputMode="numeric" className={input} /></Field>
          {(sf.kind === 'BEAM' || sf.kind === 'CEILING_DROP') && <Field label="Depth below ceiling (mm)"><input aria-label="Structure depth" value={sf.depth_mm} onChange={setS('depth_mm')} inputMode="numeric" className={input} /></Field>}
          <Field label="Label (optional)"><input aria-label="Structure label" value={sf.label} onChange={setS('label')} className={input} /></Field>
          <button disabled={!!a.busy} className={btn.primary}>{a.busy === 'struct' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}Add {KIND_LABEL[sf.kind as Structure['kind']].split(' (')[0].toLowerCase()}</button>
        </form>}
      </div>
    </div>
  )
}
