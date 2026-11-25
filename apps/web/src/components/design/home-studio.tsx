'use client'
// Design Studio → Home design: the whole home in one place — design concept (style for every room + per-room edits), the home plan
// (rooms placed on one house plan, whole-house DXF) and the whole home in 3D. All design decisions come from the server.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import { Download, FileText, Lightbulb, Loader2, Move, Palette, Sparkles, Sun, Wand2 } from 'lucide-react'
import { api, downloadFile, Project } from '@/lib/api'
import { Alert, btn, Card, Drawer, Empty, Field, hasRole, input, Ok, PageHeader, Pill, Switch, useAction, useLoad, useRole } from '@/components/ui/kit'
import { FurnitureModel } from '@/components/design/three/models'
import { Lighting, RealisticRoom, eyePoint, facing, isNight } from '@/components/design/three/scene'
import { Finishes } from '@/components/design/three/finishes'

interface Obj { id: string; name: string; category: string; x: number; y: number; length: number; width: number; height: number; z?: number; rotation?: number; colour?: string | null }
interface Op { id: string; kind: string; wall: string; offset: number; width: number; height: number; sill: number }
interface PlanRoom { id: string; name: string; room_type: string; x: number | null; y: number | null; level: number; L: number | null; W: number | null; H: number | null
  placed: boolean; openings: Op[]; objects: Obj[]; finishes: (Finishes & { style_label?: string; idea?: string; ceiling?: { type: string; label?: string }; floor?: { kind: string; tone: string; label?: string }; accent?: Finishes['accent'] }) | null; design_version: number | null }
interface Plan { rooms: PlanRoom[]; warnings: string[]; bounds: { x0: number; y0: number; x1: number; y1: number } | null; unmeasured: string[]; wall_mm: number }
interface Styles { styles: Record<string, { label: string; idea: string; palette: Record<string, string>; floor: string }>; accent_types: Record<string, string>; ceilings: Record<string, string>; floors: Record<string, string> }
const WET = ['BATHROOM', 'UTILITY', 'KITCHEN', 'WASH_AREA']
const EDIT = ['ADMIN', 'PROJECT_MANAGER', 'INTERIOR_DESIGNER']

export function HomeStudio() {
  const role = useRole(); const can = hasRole(role, EDIT)
  const { data: projects } = useLoad<Project[]>('/projects')
  const [pid, setPid] = useState('')
  useEffect(() => { if (!pid && projects?.length) setPid(projects[0].id) }, [projects, pid])
  const [tab, setTab] = useState<'concept' | 'plan' | '3d'>('concept')
  const { data: plan, setData: setPlan, reload, error } = useLoad<Plan>(pid ? `/projects/${pid}/home-plan` : null, [pid])
  const { data: st } = useLoad<Styles>('/concept/styles')
  const { data: unitSetting } = useLoad<{ units: 'ftin' | 'mm' }>('/settings/drawing-units')
  const [units, setUnits] = useState<'ftin' | 'mm'>('ftin')
  useEffect(() => { if (unitSetting) setUnits(unitSetting.units) }, [unitSetting])
  const changeUnits = (u: 'ftin' | 'mm') => { setUnits(u); if (hasRole(role, ['ADMIN', 'PROJECT_MANAGER'])) api.put('/settings/drawing-units', { units: u }).catch(() => {}) }
  const T = (k: typeof tab, label: string, Icon: typeof Palette) => <button role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
    className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded ${tab === k ? 'bg-white shadow-sm font-medium' : 'text-stone-500'}`}><Icon className="w-3.5 h-3.5" />{label}</button>
  return (
    <div className="space-y-4">
      <PageHeader title="Home design" subtitle="Design the whole home: one style for every room (feature walls, ceilings, colours, curtains, decor), all rooms on one plan, and the complete home in 3D.">
        <select aria-label="Project" value={pid} onChange={e => setPid(e.target.value)} className={input + ' w-64'}>
          {(projects ?? []).map(p => <option key={p.id} value={p.id}>{p.project_number} · {p.name}</option>)}</select>
        {pid && <button onClick={() => downloadFile(`/projects/${pid}/presentation.pdf`, 'design-presentation.pdf').catch(() => {})} className={btn.primary}><Download className="w-3.5 h-3.5" />Design presentation (PDF)</button>}
        {pid && <select aria-label="Drawing units" value={units} onChange={e => changeUnits(e.target.value as 'ftin' | 'mm')} className={input + ' w-32'} title="How working drawings print dimensions">
          <option value="ftin">Feet-inches</option><option value="mm">Millimetres</option></select>}
        {pid && <button onClick={() => downloadFile(`/projects/${pid}/drawing-set.pdf?units=${units}`, 'working-drawings.pdf').catch(() => {})} className={btn.ghost}
          title="A3 sheets for the site team: light detail, room plans + elevations, bed, wardrobe and kitchen details, 3D views"><FileText className="w-3.5 h-3.5" />Working drawings (PDF)</button>}
      </PageHeader>
      <div className="flex gap-1 bg-stone-100 rounded p-1 w-fit" role="tablist">{T('concept', 'Design concept', Palette)}{T('plan', 'Home plan', Move)}{T('3d', 'Whole home 3D', Sparkles)}</div>
      {error && <Alert>{error}</Alert>}
      {!pid ? <Empty>Create a project first.</Empty> : !plan || !st ? <Empty>Loading…</Empty> : <>
        {plan.unmeasured.length > 0 && <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">Needs length and width (Site Survey → Rooms): {plan.unmeasured.join(', ')}.</p>}
        {tab === 'concept' && <ConceptTab pid={pid} plan={plan} st={st} can={can} units={units} onChanged={reload} />}
        {tab === 'plan' && <PlanTab pid={pid} plan={plan} setPlan={setPlan} can={can} />}
        {tab === '3d' && <Home3D plan={plan} />}
      </>}
    </div>
  )
}

// ── Design concept ───────────────────────────────────────────────────────────
function ConceptTab({ pid, plan, st, can, units, onChanged }: { pid: string; plan: Plan; st: Styles; can: boolean; units: 'ftin' | 'mm'; onChanged: () => void }) {
  const current = plan.rooms.find(r => r.finishes)?.finishes?.style ?? ''
  const [style, setStyle] = useState(current || 'modern'); const [fill, setFill] = useState(true)
  const [res, setRes] = useState<{ label: string; rooms: { room: string; version: number; feature_wall: string | null; ceiling: string }[]; skipped: { room: string; reason: string }[] } | null>(null)
  const [editing, setEditing] = useState<PlanRoom | null>(null); const a = useAction()
  const run = () => a.run('home', async () => { setRes(await api.postLong(`/projects/${pid}/concept`, { style, generate_missing: fill })); onChanged() })
  return <div className="space-y-4">
    <Card title="1 · Pick a style">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3" role="radiogroup" aria-label="Style">{Object.entries(st.styles).map(([k, s]) =>
        <button key={k} role="radio" aria-checked={style === k} onClick={() => setStyle(k)} data-style={k}
          className={`text-left rounded-lg border p-3 transition ${style === k ? 'border-amber-600 ring-2 ring-amber-200 bg-amber-50/40' : 'border-stone-200 hover:border-stone-300'}`}>
          <div className="flex gap-1 mb-2">{Object.values(s.palette).map((c, i) => <span key={i} className="w-6 h-6 rounded-full border border-stone-200" style={{ background: c }} />)}</div>
          <p className="font-semibold text-sm">{s.label}{current === k && <span className="ml-1.5 text-[10px] text-green-700">current</span>}</p>
          <p className="text-[11px] text-stone-500 mt-0.5 leading-snug">{s.idea}</p>
          <p className="text-[10px] text-stone-400 mt-1">Floor: {s.floor}</p></button>)}</div>
    </Card>
    <Card title="2 · Design the whole home">
      <label className="flex items-center gap-2 text-sm mb-3"><input type="checkbox" checked={fill} onChange={e => setFill(e.target.checked)} />Lay out furniture in rooms that don't have a design yet</label>
      {can ? <button onClick={run} disabled={!!a.busy} className={btn.primary}>{a.busy === 'home' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}Design my home — {st.styles[style]?.label}</button>
        : <p className="text-xs text-stone-400">Only designers, project managers and admins can apply a style.</p>}
      {a.error && <Alert>{a.error}</Alert>}
      {res && <div className="mt-3 text-sm" data-testid="design-result"><p className="text-green-800 font-medium">{res.label} applied to {res.rooms.length} room(s), each saved as a new design version.</p>
        {res.skipped.length > 0 && <ul className="text-xs text-amber-800 mt-1">{res.skipped.map(s => <li key={s.room}>{s.room}: {s.reason}</li>)}</ul>}</div>}
    </Card>
    <Card title="3 · Room by room">
      <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="room-concepts"><thead><tr className="text-[11px] uppercase text-stone-400 text-left">
        <th className="py-2 font-medium">Room</th><th className="font-medium">Feature wall</th><th className="font-medium">Ceiling</th><th className="font-medium">Floor</th><th className="font-medium">Colours</th><th /></tr></thead>
        <tbody className="divide-y divide-stone-50">{plan.rooms.map(r => { const f = r.finishes
          return <tr key={r.id} data-room={r.name}><td className="py-2"><p className="font-medium">{r.name}</p><p className="text-[11px] text-stone-400">{r.room_type.replace('_', ' ').toLowerCase()}{r.design_version ? ` · v${r.design_version}` : ''}</p></td>
            <td className="text-xs">{f?.accent ? st.accent_types[f.accent.type] : <span className="text-stone-300">—</span>}</td>
            <td className="text-xs">{f?.ceiling ? st.ceilings[f.ceiling.type] : <span className="text-stone-300">—</span>}</td>
            <td className="text-xs">{f?.floor ? st.floors[f.floor.kind] : <span className="text-stone-300">—</span>}</td>
            <td>{f && <div className="flex gap-1">{[f.walls?.colour, f.accent?.colour, f.floor?.tone].filter(Boolean).map((c, i) => <span key={i} className="w-4 h-4 rounded border border-stone-200" style={{ background: c as string }} />)}</div>}</td>
            <td className="text-right whitespace-nowrap space-x-1">{r.design_version && <button onClick={() => downloadFile(`/projects/${pid}/drawing-set.pdf?room_id=${r.id}&units=${units}`, `working-drawings-${r.name}.pdf`).catch(() => {})}
              className={btn.small} aria-label={`Working drawings of ${r.name}`} title="Working drawings of this room (PDF)"><FileText className="w-3 h-3" />Drawings</button>}
              {can && f && <button onClick={() => setEditing(r)} className={btn.small} aria-label={`Edit design of ${r.name}`}>Edit</button>}</td></tr> })}</tbody></table></div>
    </Card>
    {editing && <EditConcept room={editing} st={st} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged() }} />}
  </div>
}

function EditConcept({ room, st, onClose, onSaved }: { room: PlanRoom; st: Styles; onClose: () => void; onSaved: () => void }) {
  const f = room.finishes!
  const [o, setO] = useState({ accent_type: f.accent?.type ?? 'NONE', accent_wall: f.accent?.wall ?? 'N', accent_colour: f.accent?.colour ?? '#6b4a32', ceiling: f.ceiling?.type ?? 'PLAIN',
    floor: f.floor?.kind ?? 'WOOD', floor_tone: f.floor?.tone ?? '#b88a5a', wall_colour: f.walls?.colour ?? '#efebe5', curtain_colour: f.curtains?.[0]?.colour ?? '#cfc6b8',
    rug: !!f.rug, art: !!f.art?.length, plants: !!f.plants?.length })
  const a = useAction()
  const save = () => a.run('s', async () => {
    const ov: Record<string, unknown> = { ...o }
    if (o.accent_type === 'NONE') { delete ov.accent_wall; delete ov.accent_colour }
    if (!f.curtains?.length) delete ov.curtain_colour
    if (o.rug === !!f.rug) delete ov.rug
    if (o.art === !!f.art?.length) delete ov.art
    if (o.plants === !!f.plants?.length) delete ov.plants
    await api.put(`/rooms/${room.id}/concept`, { overrides: ov }); onSaved() })
  const sel = (label: string, k: keyof typeof o, opts: [string, string][]) => <Field label={label}><select aria-label={label} value={String(o[k])} onChange={e => setO({ ...o, [k]: e.target.value })} className={input}>
    {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
  const col = (label: string, k: keyof typeof o) => <label className="flex items-center gap-2 text-sm"><input type="color" aria-label={label} value={String(o[k])} onChange={e => setO({ ...o, [k]: e.target.value })} className="w-9 h-7 rounded border border-stone-200" />{label}</label>
  return <Drawer label="Edit room design" title={`${room.name} — design`} onClose={onClose}>
    <p className="text-xs text-stone-500">{f.style_label} style. Changes are saved as a new design version (earlier versions stay).</p>
    {sel('Feature wall', 'accent_type', [['NONE', 'No feature wall'], ...Object.entries(st.accent_types)])}
    {o.accent_type !== 'NONE' && <div className="grid grid-cols-2 gap-2">{sel('On wall', 'accent_wall', [['N', 'North'], ['E', 'East'], ['S', 'South'], ['W', 'West']])}<div className="pt-6">{col('Feature colour', 'accent_colour')}</div></div>}
    {sel('False ceiling', 'ceiling', Object.entries(st.ceilings))}
    <div className="grid grid-cols-2 gap-2">{sel('Flooring', 'floor', Object.entries(st.floors))}<div className="pt-6">{col('Floor tone', 'floor_tone')}</div></div>
    <div className="space-y-2">{col('Wall paint', 'wall_colour')}{!!f.curtains?.length && col('Curtains', 'curtain_colour')}</div>
    <div className="space-y-2 border-t border-stone-100 pt-3"><Switch label="Rug" checked={o.rug} onChange={v => setO({ ...o, rug: v })} disabled={!f.rug && !o.rug} />
      <Switch label="Wall art" checked={o.art} onChange={v => setO({ ...o, art: v })} disabled={!f.art?.length && !o.art} />
      <Switch label="Plants" checked={o.plants} onChange={v => setO({ ...o, plants: v })} disabled={!f.plants?.length && !o.plants} /></div>
    {a.error && <Alert>{a.error}</Alert>}
    <button onClick={save} disabled={!!a.busy} className={btn.primary + ' w-full'}>Save design</button>
  </Drawer>
}

// ── Home plan (drag rooms) ───────────────────────────────────────────────────
function PlanTab({ pid, plan, setPlan, can }: { pid: string; plan: Plan; setPlan: (p: Plan) => void; can: boolean }) {
  const rooms = plan.rooms.filter(r => r.L && r.W)
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>({}); const a = useAction()
  useEffect(() => { setPos(Object.fromEntries(rooms.filter(r => r.placed).map(r => [r.id, { x: r.x!, y: r.y! }]))) }, [plan]) // eslint-disable-line react-hooks/exhaustive-deps
  const placed = rooms.filter(r => pos[r.id])
  const svg = useRef<SVGSVGElement>(null); const drag = useRef<{ id: string; sx: number; sy: number; ox: number; oy: number } | null>(null)
  const pad = 1200
  const bx0 = Math.min(0, ...placed.map(r => pos[r.id].x)) - pad, by0 = Math.min(0, ...placed.map(r => pos[r.id].y)) - pad
  const bx1 = Math.max(8000, ...placed.map(r => pos[r.id].x + r.L!)) + pad, by1 = Math.max(6000, ...placed.map(r => pos[r.id].y + r.W!)) + pad
  const vw = bx1 - bx0, vh = by1 - by0
  const toMm = (e: React.PointerEvent) => { const b = svg.current!.getBoundingClientRect(); return { x: bx0 + (e.clientX - b.left) / b.width * vw, y: by1 - (e.clientY - b.top) / b.height * vh } }
  const dirty = rooms.some(r => pos[r.id] && (pos[r.id].x !== r.x || pos[r.id].y !== r.y))
  const save = () => a.run('save', async () => setPlan(await api.put<Plan>(`/projects/${pid}/home-plan`, { rooms: Object.entries(pos).map(([id, p]) => ({ id, x: p.x, y: p.y })) })), 'Home plan saved')
  const auto = (all: boolean) => a.run('auto', async () => setPlan(await api.post<Plan>(`/projects/${pid}/home-plan/auto`, { all_rooms: all })))
  return <div className="space-y-3">
    <div className="flex gap-2 flex-wrap items-center">
      {can && <button onClick={() => auto(false)} disabled={!!a.busy} className={btn.ghost}><Wand2 className="w-3.5 h-3.5" />Place new rooms</button>}
      {can && <button onClick={() => auto(true)} disabled={!!a.busy} className={btn.ghost}>Re-arrange all</button>}
      {can && <button onClick={save} disabled={!dirty || !!a.busy} className={btn.primary}>Save plan</button>}
      <button onClick={() => a.run('dxf', () => downloadFile(`/projects/${pid}/home-plan.dxf`, 'home-plan.dxf'))} disabled={!placed.length} className={btn.ghost}><Download className="w-3.5 h-3.5" />Whole-house DXF</button>
      <span className="text-[11px] text-stone-500">Drag rooms to place them (50 mm snap). Leave about {plan.wall_mm} mm between rooms for the wall.</span>
    </div>
    {a.error && <Alert>{a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
    {plan.warnings.length > 0 && <ul className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2" data-testid="plan-warnings">{plan.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
    {!placed.length ? <Empty>No rooms on the plan yet — click “Place new rooms”.</Empty> :
      <div className="bg-white border border-stone-200 rounded-lg p-2"><svg ref={svg} viewBox={`0 0 ${vw} ${vh}`} className="w-full h-[62vh] touch-none select-none" data-testid="home-plan"
        onPointerMove={e => { const d = drag.current; if (!d) return; const p = toMm(e); setPos(s => ({ ...s, [d.id]: { x: Math.round((d.ox + p.x - d.sx) / 50) * 50, y: Math.round((d.oy + p.y - d.sy) / 50) * 50 } })) }}
        onPointerUp={() => { drag.current = null }} onPointerLeave={() => { drag.current = null }}>
        <rect x={0} y={0} width={vw} height={vh} fill="#fafaf9" />
        {placed.map(r => { const p = pos[r.id], sx = p.x - bx0, sy = by1 - (p.y + r.W!)
          return <g key={r.id} data-plan-room={r.name} className={can ? 'cursor-move' : ''} onPointerDown={e => { if (!can) return; (e.target as Element).setPointerCapture?.(e.pointerId); const m = toMm(e); drag.current = { id: r.id, sx: m.x, sy: m.y, ox: p.x, oy: p.y } }}>
            <rect x={sx - 115} y={sy - 115} width={r.L! + 230} height={r.W! + 230} fill="#57534e" />
            <rect x={sx} y={sy} width={r.L!} height={r.W!} fill={r.finishes?.floor?.tone ?? '#f5f1ea'} fillOpacity={0.55} />
            {r.objects.map(o => <rect key={o.id} transform={o.rotation ? `rotate(${-o.rotation} ${sx + o.x + o.length / 2} ${sy + r.W! - o.y - o.width / 2})` : undefined}
              x={sx + o.x} y={sy + r.W! - o.y - o.width} width={o.length} height={o.width} fill="#fde68a" stroke="#92400e" strokeWidth={12} fillOpacity={(o.z ?? 0) >= 1200 ? 0.25 : 0.8} />)}
            {r.openings.map(o => { const wall = o.wall, a0 = o.offset, w = o.width
              const [x, y, ww, hh] = wall === 'S' ? [sx + a0, sy + r.W!, w, 115] : wall === 'N' ? [sx + a0, sy - 115, w, 115] : wall === 'W' ? [sx - 115, sy + r.W! - a0 - w, 115, w] : [sx + r.L!, sy + r.W! - a0 - w, 115, w]
              return <rect key={o.id} x={x} y={y} width={ww} height={hh} fill={o.kind === 'DOOR' ? '#fafaf9' : '#7dd3fc'} /> })}
            <text x={sx + r.L! / 2} y={sy + r.W! / 2} fontSize={Math.min(260, r.L! / 7)} textAnchor="middle" fill="#292524" fontWeight={600}>{r.name}</text>
            <text x={sx + r.L! / 2} y={sy + r.W! / 2 + Math.min(240, r.L! / 8)} fontSize={Math.min(180, r.L! / 10)} textAnchor="middle" fill="#57534e">{r.L} × {r.W}</text>
          </g> })}
        <text x={vw - 500} y={500} fontSize={260} fill="#a8a29e">N ↑</text>
      </svg></div>}
  </div>
}

// ── Whole home in 3D ─────────────────────────────────────────────────────────
function HomeFurniture({ o, room }: { o: Obj; room: { L: number; W: number } }) {
  const f = facing(o, room.L, room.W), h = Math.max(o.height, 20)
  return <group position={[(o.x + o.length / 2) / 1000, (o.z ?? 0) / 1000, -(o.y + o.width / 2) / 1000]} rotation={[0, ((o.rotation ?? 0) * Math.PI) / 180, 0]}>
    <group rotation={[0, f.yaw, 0]}><FurnitureModel category={o.category} name={o.name} l={f.l / 1000} d={f.d / 1000} h={h / 1000} colour={o.colour} /></group></group>
}

function Home3D({ plan }: { plan: Plan }) {
  const rooms = plan.rooms.filter(r => r.placed && r.L && r.W)
  const [hour, setHour] = useState(10.5); const [lights, setLights] = useState(false); const [look, setLook] = useState('')
  const b = plan.bounds
  const cam = useMemo(() => {
    if (!b) return null
    const r = rooms.find(x => x.id === look)
    if (r) { const e = eyePoint(r.L!, r.W!, r.openings, r.objects); const ox = (r.x! - b.x0) / 1000, oz = -(r.y! - b.y0) / 1000
      return { pos: [e.pos[0] + ox, e.pos[1], e.pos[2] + oz] as [number, number, number], target: [e.target[0] + ox, e.target[1], e.target[2] + oz] as [number, number, number], fov: 68 } }
    const L = (b.x1 - b.x0) / 1000, W = (b.y1 - b.y0) / 1000, span = Math.max(L, W)
    return { pos: [L / 2 + span * 0.5, span * 1.05, -W / 2 + span * 0.85] as [number, number, number], target: [L / 2, 0, -W / 2] as [number, number, number], fov: 45 }
  }, [b, look]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!b || !cam) return <Empty>Place the rooms on the Home plan first.</Empty>
  const L = (b.x1 - b.x0) / 1000, W = (b.y1 - b.y0) / 1000
  return <div className="space-y-2">
    <div className="flex gap-3 items-center flex-wrap text-xs text-stone-600">
      <label className="flex items-center gap-1.5"><Sun className="w-3.5 h-3.5 text-amber-600" /><input type="range" aria-label="Time of day" min={6} max={21} step={0.25} value={hour} onChange={e => setHour(Number(e.target.value))} className="w-28 accent-amber-700" />
        <span className="font-mono w-10">{`${Math.floor(hour)}:${String(Math.round((hour % 1) * 60)).padStart(2, '0')}`}</span></label>
      <button className={btn.small} onClick={() => setLights(v => !v)} aria-pressed={lights}><Lightbulb className="w-3 h-3" />Lights {lights || isNight(hour) ? 'on' : 'off'}</button>
      <select aria-label="Look inside" value={look} onChange={e => setLook(e.target.value)} className="w-56 text-xs border border-stone-200 rounded px-2 py-1 bg-white">
        <option value="">Whole home (bird's eye)</option>{rooms.map(r => <option key={r.id} value={r.id}>Stand in: {r.name}</option>)}</select>
      <span className="text-stone-400">Drag to orbit, scroll to zoom. Edit furniture in the 3D Editor, designs in Design concept.</span>
    </div>
    <div className="h-[68vh] rounded-lg overflow-hidden border border-stone-200 bg-stone-100" data-testid="home-3d">
      <Canvas key={look} shadows="soft" dpr={[1, 2]} gl={{ preserveDrawingBuffer: true, antialias: true }}>
        <PerspectiveCamera makeDefault position={cam.pos} fov={cam.fov} near={0.05} far={400} />
        <OrbitControls makeDefault target={cam.target} enableDamping maxPolarAngle={look ? Math.PI * 0.62 : Math.PI / 2 - 0.02} />
        <Lighting L={L} W={W} H={3} hour={hour} />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2, -0.012, -W / 2]} receiveShadow><planeGeometry args={[L + 30, W + 30]} /><meshStandardMaterial color="#d9d4cb" /></mesh>
        {rooms.map(r => <group key={r.id} position={[(r.x! - b.x0) / 1000, 0, -(r.y! - b.y0) / 1000]}>
          <RealisticRoom L={r.L! / 1000} W={r.W! / 1000} H={(r.H ?? 2750) / 1000} ops={r.openings} hour={hour} lightsOn={lights} wet={WET.includes(r.room_type)} finishes={r.finishes} ground={false} />
          {r.objects.map(o => <HomeFurniture key={o.id} o={o} room={{ L: r.L!, W: r.W! }} />)}
        </group>)}
      </Canvas>
    </div>
    {rooms.length > 0 && <p className="text-[11px] text-stone-400"><Pill tone="stone" label={`${rooms.length} room(s)`} /> real furniture sizes, each room's design concept, sun by time of day.</p>}
  </div>
}
