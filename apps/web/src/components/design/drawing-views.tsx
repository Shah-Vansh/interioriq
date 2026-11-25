'use client'
// Design drawings rendered from the SERVER's layouts of a saved design version (the browser only draws what the API returns).
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Download, ImageOff, Upload } from 'lucide-react'
import { api, DesignVersion, downloadFile, fetchBlob, PlacedObject } from '@/lib/api'
import { DocRow, fitScale, fmtDate } from '@/lib/ops'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import { Opening, OpeningsSvg } from '@/components/survey/openings-card'
import { fitLabel } from '@/lib/plan-label'
import type { Pt, Structure } from '@/lib/room-shell'
import { OutlineSvg, StructuresSvg } from '@/components/survey/shell-svg'
import { Alert, btn, Card, ctl, Empty, Ok, PageHeader, Pill, Table, useAction, useLoad } from '@/components/ui/kit'

interface RoomDims { L: number; W: number; H: number; outline?: Pt[]; structures?: Structure[] }   // M41: L-shaped / angled rooms, beams + columns
interface Plan { version: number; is_valid: boolean; room: RoomDims; objects: PlacedObject[]; openings?: Opening[]; validation: { errors: string[]; warnings: string[] } | null }
interface Ceiling { version: number; room: RoomDims; false_ceiling_height: number; cove: number; gypsum_area_m2: number; cove_strip_m: number; lights: { type: string; x: number; y: number; label: string }[]; fan: { x: number; y: number } | null; rules: string[] }
interface Electrical { version: number; room: RoomDims; points: { id: string; type: string; label: string; x: number; y: number; height: number; note: string }[]; rules: string[]; assumptions: string[] }
interface Elevations { version: number; walls: { wall: string; length: number; height: number; items: { name: string; x: number; length: number; height: number; z?: number }[]; openings?: { label: string; kind: string; x: number; width: number; height: number; sill: number }[]
  ceiling_line?: [number, number][]; structures?: { label: string; kind: string; x: number; width: number; z: number }[] }[] }

function useRoom() {
  const [sel, setSel] = useState({ projectId: '', roomId: '' })
  const [versions, setVersions] = useState<DesignVersion[]>([]); const [picked, setPicked] = useState<{ room: string; v: number | null }>({ room: '', v: null })
  useEffect(() => {
    setVersions([]); setPicked({ room: sel.roomId, v: null }); if (!sel.roomId) return
    api.get<DesignVersion[]>(`/rooms/${sel.roomId}/designs`).then(v => { setVersions(v); setPicked({ room: sel.roomId, v: v.length ? v[v.length - 1].version : null }) }).catch(() => {})
  }, [sel.roomId])
  // a version only counts for the room it was picked in (switching rooms used to ask the new room for the old room's version → 404)
  const version = picked.room === sel.roomId ? picked.v : null
  const setVersion = (v: number) => setPicked({ room: sel.roomId, v })
  const picker = <div className="flex gap-2 flex-wrap items-center"><ProjectRoomPicker onChange={s => setSel({ projectId: s.projectId, roomId: s.roomId })} />
    {versions.length > 0 && <select aria-label="Design version" value={version ?? ''} onChange={e => setVersion(Number(e.target.value))} className={ctl}>
      {versions.map(v => <option key={v.id} value={v.version}>v{v.version}{v.is_valid ? '' : ' (has errors)'}</option>)}</select>}</div>
  return { ...sel, version, versions, picker }
}

/** Room shell + furniture in plan, north up, origin at the south-west corner. */
export function PlanSvg({ room, objects, children, openings = [], w = 760, h = 560 }: { room: RoomDims; objects: PlacedObject[]; openings?: Opening[]; children?: (sx: (x: number) => number, sy: (y: number) => number, s: number) => React.ReactNode; w?: number; h?: number }) {
  const f = fitScale(room.L, room.W, w, h)
  const sx = (x: number) => f.pad + x * f.s, sy = (y: number) => f.pad + (room.W - y) * f.s
  return (
    <svg viewBox={`0 0 ${f.w} ${f.h}`} className="w-full h-auto bg-white" role="img" aria-label="Floor plan">
      {room.outline && room.outline.length > 4 ? <><rect x={sx(0)} y={sy(room.W)} width={room.L * f.s} height={room.W * f.s} fill="none" stroke="#e7e5e4" strokeDasharray="4 4" />
        <OutlineSvg outline={room.outline} sx={sx} sy={sy} fill="#fafaf9" /></>
        : <rect x={sx(0)} y={sy(room.W)} width={room.L * f.s} height={room.W * f.s} fill="#fafaf9" stroke="#292524" strokeWidth={4} />}
      {room.structures && <StructuresSvg items={room.structures} sx={sx} sy={sy} />}
      {[...objects].sort((a, b) => (a.z ?? 0) - (b.z ?? 0)).map(o => { const up = (o.z ?? 0) >= 1200, label = up ? '' : fitLabel(o.name, o.length * f.s, o.width * f.s)
        return <g key={o.id} data-plan-object={o.category} data-wall-mounted={up || undefined}><title>{o.name}{up ? ` — fixed ${o.z} mm above the floor` : ''}</title>
        <rect transform={o.rotation ? `rotate(${-o.rotation} ${sx(o.x + o.length / 2)} ${sy(o.y + o.width / 2)})` : undefined} x={sx(o.x)} y={sy(o.y + o.width)} width={o.length * f.s} height={o.width * f.s} fill={up ? '#bae6fd' : '#fde68a'} fillOpacity={up ? 0.35 : 0.55} stroke={up ? '#0369a1' : '#92400e'} strokeWidth={1.2} strokeDasharray={up ? '4 3' : undefined} />
        {label && <text x={sx(o.x + o.length / 2)} y={sy(o.y + o.width / 2)} fontSize={11} textAnchor="middle" dominantBaseline="middle" fill="#44403c">{label}</text>}</g> })}
      <OpeningsSvg ops={openings} L={room.L} W={room.W} sx={sx} sy={sy} s={f.s} />
      {children?.(sx, sy, f.s)}
      <text x={sx(room.L / 2)} y={f.pad - 14} fontSize={11} textAnchor="middle" fill="#78716c">{room.L} mm</text>
      <text x={f.pad - 14} y={sy(room.W / 2)} fontSize={11} textAnchor="middle" fill="#78716c" transform={`rotate(-90 ${f.pad - 14} ${sy(room.W / 2)})`}>{room.W} mm</text>
      <text x={f.w - 18} y={22} fontSize={12} textAnchor="middle" fill="#b45309" fontWeight={700}>N ↑</text>
    </svg>)
}

const Shell = ({ title, subtitle, picker, children }: { title: string; subtitle: string; picker: React.ReactNode; children: React.ReactNode }) => (
  <div className="space-y-5 max-w-[1300px]"><PageHeader title={title} subtitle={subtitle} />{picker}{children}</div>)

function useDrawing<T>(roomId: string, version: number | null, kind: string) {
  return useLoad<T>(roomId && version ? `/rooms/${roomId}/drawings/${kind}?version=${version}` : null)
}
const dxf = (roomId: string, kind: string, version: number | null, name: string, extra = '', onErr?: (m: string) => void) =>
  downloadFile(`/rooms/${roomId}/drawings/${kind}/dxf?version=${version ?? ''}${extra}`, name).catch(e => onErr?.(e.message))

export function PlansView() {
  const r = useRoom(); const { data, error } = useDrawing<Plan>(r.roomId, r.version, 'plan'); const a = useAction()
  return <Shell title="Floor plans" subtitle="Plan of a saved design version, drawn from the server's Design Model (north up). Edit the layout in the 3D editor; download DXF for AutoCAD." picker={r.picker}>
    {(error || a.error) && <Alert>{error || a.error}</Alert>}
    {!r.version ? <Empty>No saved design for this room yet — create one in the AI Designer or 3D editor.</Empty> : data && <div className="grid grid-cols-12 gap-4">
      <Card title={`v${data.version}`} className="col-span-12 lg:col-span-8" right={<button onClick={() => dxf(r.roomId, 'plan', r.version, `plan-v${data.version}.dxf`, '', a.setError)} className={btn.small}><Download className="w-3 h-3" />DXF</button>}>
        <PlanSvg room={data.room} objects={data.objects} openings={data.openings} /></Card>
      <Card title="Schedule" className="col-span-12 lg:col-span-4"><Table head={['Item', 'Size (mm)']}>{data.objects.map(o => <tr key={o.id}><td className="px-4 py-1.5 text-xs">{o.name}</td><td className="px-4 py-1.5 text-xs">{o.length} × {o.width} × {o.height}</td></tr>)}</Table>
        {data.validation && data.validation.errors.length > 0 && <div className="mt-3"><Alert>{data.validation.errors.join('; ')}</Alert></div>}
        {data.validation?.warnings.map(w => <p key={w} className="text-xs text-amber-800 mt-1">{w}</p>)}</Card></div>}
  </Shell>
}

export function CeilingView() {
  const r = useRoom(); const { data: c, error } = useDrawing<Ceiling>(r.roomId, r.version, 'ceiling'); const { data: p } = useDrawing<Plan>(r.roomId, r.version, 'plan'); const a = useAction()
  return <Shell title="Ceiling plan" subtitle="False ceiling with a cove band, a downlight grid that avoids tall units, spots in front of wardrobes and a fan point — generated by rules from the saved design." picker={r.picker}>
    {(error || a.error) && <Alert>{error || a.error}</Alert>}
    {!r.version ? <Empty>No saved design for this room yet.</Empty> : c && p && <div className="grid grid-cols-12 gap-4">
      <Card title={`Reflected ceiling plan · v${c.version}`} className="col-span-12 lg:col-span-8" right={<button onClick={() => dxf(r.roomId, 'ceiling', r.version, `ceiling-v${c.version}.dxf`, '', a.setError)} className={btn.small}><Download className="w-3 h-3" />DXF</button>}>
        <PlanSvg room={c.room} objects={p.objects} openings={p.openings}>{(sx, sy, s) => <g>
          <rect x={sx(c.cove)} y={sy(c.room.W - c.cove)} width={(c.room.L - 2 * c.cove) * s} height={(c.room.W - 2 * c.cove) * s} fill="none" stroke="#2563eb" strokeDasharray="6 4" strokeWidth={1.5} />
          {c.lights.map((l, i) => <circle key={i} data-light={l.type} cx={sx(l.x)} cy={sy(l.y)} r={l.type === 'DOWNLIGHT' ? 6 : 8} fill={l.type === 'DOWNLIGHT' ? '#facc15' : '#f97316'} stroke="#78350f" />)}
          {c.fan && <g><circle cx={sx(c.fan.x)} cy={sy(c.fan.y)} r={14} fill="none" stroke="#0f766e" strokeWidth={2} /><text x={sx(c.fan.x)} y={sy(c.fan.y) + 4} fontSize={10} textAnchor="middle" fill="#0f766e">FAN</text></g>}</g>}</PlanSvg></Card>
      <Card title="Quantities & rules" className="col-span-12 lg:col-span-4"><dl className="text-sm space-y-1" data-testid="ceiling-qty">
        <div className="flex justify-between"><dt>Gypsum ceiling</dt><dd>{c.gypsum_area_m2} m²</dd></div><div className="flex justify-between"><dt>Cove LED strip</dt><dd>{c.cove_strip_m} m</dd></div>
        <div className="flex justify-between"><dt>Downlights</dt><dd>{c.lights.filter(l => l.type === 'DOWNLIGHT').length}</dd></div><div className="flex justify-between"><dt>Spotlights</dt><dd>{c.lights.filter(l => l.type === 'SPOTLIGHT').length}</dd></div>
        <div className="flex justify-between"><dt>False ceiling height</dt><dd>{c.false_ceiling_height} mm</dd></div></dl>
        <ul className="mt-3 text-[11px] text-stone-500 list-disc pl-4 space-y-1">{c.rules.map(x => <li key={x}>{x}</li>)}</ul></Card></div>}
  </Shell>
}

export function ElectricalView() {
  const r = useRoom(); const { data: e, error } = useDrawing<Electrical>(r.roomId, r.version, 'electrical'); const { data: p } = useDrawing<Plan>(r.roomId, r.version, 'plan'); const a = useAction()
  const colour: Record<string, string> = { SOCKET: '#2563eb', SWITCH: '#16a34a', SWITCHBOARD: '#b91c1c', AC: '#7c3aed', LIGHT: '#ca8a04' }
  return <Shell title="Electrical layout" subtitle="Socket, switch, AC and light points placed by rules from the furniture in the saved design. It's design intent for the electrician; assumptions are flagged." picker={r.picker}>
    {(error || a.error) && <Alert>{error || a.error}</Alert>}
    {!r.version ? <Empty>No saved design for this room yet.</Empty> : e && p && <div className="grid grid-cols-12 gap-4">
      <Card title={`Electrical points · v${e.version}`} className="col-span-12 lg:col-span-7" right={<button onClick={() => dxf(r.roomId, 'electrical', r.version, `electrical-v${e.version}.dxf`, '', a.setError)} className={btn.small}><Download className="w-3 h-3" />DXF</button>}>
        <PlanSvg room={e.room} objects={p.objects} openings={p.openings}>{(sx, sy) => <g>{e.points.map(pt => <g key={pt.id}><circle cx={sx(pt.x)} cy={sy(pt.y)} r={7} fill={colour[pt.type] ?? '#444'} />
          <text x={sx(pt.x) + 9} y={sy(pt.y) - 6} fontSize={10} fill="#1c1917">{pt.id}</text></g>)}</g>}</PlanSvg>
        {e.assumptions.map(x => <p key={x} className="text-xs text-amber-800 mt-2">⚠ {x}</p>)}</Card>
      <Card title="Point schedule" className="col-span-12 lg:col-span-5"><Table head={['#', 'Point', 'Height']} right={[2]}>{e.points.map(pt => <tr key={pt.id} data-point={pt.type}><td className="px-3 py-1.5 text-xs font-mono">{pt.id}</td>
        <td className="px-3 py-1.5 text-xs"><span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ background: colour[pt.type] }} />{pt.label}</td><td className="px-3 py-1.5 text-right text-xs">{pt.height} mm</td></tr>)}</Table>
        <ul className="mt-3 text-[11px] text-stone-500 list-disc pl-4 space-y-1">{e.rules.map(x => <li key={x}>{x}</li>)}</ul></Card></div>}
  </Shell>
}

export function ElevationsView() {
  const r = useRoom(); const { data, error } = useDrawing<Elevations>(r.roomId, r.version, 'elevations'); const a = useAction()
  return <Shell title="Elevations" subtitle="Each wall as seen from inside the room, with the units that stand against it (within 100 mm). Download any wall as DXF." picker={r.picker}>
    {(error || a.error) && <Alert>{error || a.error}</Alert>}
    {!r.version ? <Empty>No saved design for this room yet.</Empty> : data && <div className="grid md:grid-cols-2 gap-4">{data.walls.map(w => { const f = fitScale(w.length, w.height, 600, 300, 30)
      return <Card key={w.wall} title={`${w.wall} wall · ${w.length} × ${w.height} mm`} right={<button onClick={() => dxf(r.roomId, 'elevation', r.version, `elevation-${w.wall.toLowerCase()}.dxf`, `&wall=${w.wall}`, a.setError)} className={btn.small}><Download className="w-3 h-3" />DXF</button>}>
        <svg viewBox={`0 0 ${f.w} ${f.h}`} className="w-full h-auto bg-white" role="img" aria-label={`${w.wall} elevation`} data-wall={w.wall}>
          {w.ceiling_line && w.ceiling_line.some(([, h]) => h !== w.height)                // M41: sloped / uneven ceiling along this wall
            ? <polygon data-ceiling-line points={[[0, 0] as [number, number], [w.length, 0] as [number, number], ...[...w.ceiling_line].reverse()].map(([x, h]) => `${f.pad + x * f.s},${f.pad + (w.height - h) * f.s}`).join(' ')} fill="#fafaf9" stroke="#292524" strokeWidth={2.5} />
            : <rect x={f.pad} y={f.pad} width={w.length * f.s} height={w.height * f.s} fill="#fafaf9" stroke="#292524" strokeWidth={2.5} />}
          {(w.structures ?? []).map((st, i) => { const col = st.kind === 'COLUMN' || st.kind === 'PILLAR'; return <g key={'s' + i} data-elev-structure={st.kind}><title>{st.label}</title>
            <rect x={f.pad + st.x * f.s} y={f.pad} width={st.width * f.s} height={(w.height - st.z) * f.s} fill={col ? '#78716c' : '#e9d5ff'} stroke={col ? '#292524' : '#a21caf'} />
            <text x={f.pad + (st.x + st.width / 2) * f.s} y={f.pad + (w.height - st.z) * f.s + 11} fontSize={9} textAnchor="middle" fill={col ? '#44403c' : '#a21caf'}>{st.label}{col ? '' : ` u/s ${st.z}`}</text></g> })}
          {w.items.map((it, i) => { const z = it.z ?? 0, label = fitLabel(it.name, it.length * f.s, it.height * f.s); return <g key={i} data-elev-item={it.name}><title>{it.name}</title><rect x={f.pad + it.x * f.s} y={f.pad + (w.height - z - it.height) * f.s} width={it.length * f.s} height={it.height * f.s} fill="#fde68a" fillOpacity={0.6} stroke="#92400e" />
            {label && <text x={f.pad + (it.x + it.length / 2) * f.s} y={f.pad + (w.height - z - it.height / 2) * f.s} fontSize={10} textAnchor="middle" dominantBaseline="middle" fill="#44403c">{label}</text>}</g> })}
          {(w.openings ?? []).map((o, i) => <g key={'o' + i} data-elev-opening={o.kind}><rect x={f.pad + o.x * f.s} y={f.pad + (w.height - o.sill - o.height) * f.s} width={o.width * f.s} height={o.height * f.s}
            fill={o.kind === 'DOOR' ? '#fed7aa' : '#bae6fd'} fillOpacity={0.7} stroke={o.kind === 'DOOR' ? '#92400e' : '#0369a1'} />
            <text x={f.pad + (o.x + o.width / 2) * f.s} y={f.pad + (w.height - o.sill - o.height / 2) * f.s} fontSize={9} textAnchor="middle" fill="#1c1917">{o.label}</text></g>)}
        </svg>{w.items.length === 0 && !(w.openings ?? []).length && <p className="text-xs text-stone-400 mt-1">Nothing stands against this wall.</p>}</Card> })}</div>}
  </Shell>
}

export function CadView() {
  const r = useRoom(); const a = useAction()
  const files: [string, string, string][] = [['Room shell (floor plan)', `/rooms/${r.roomId}/cad/floor-plan`, 'floor-plan.dxf'], ['Furniture layout', `/rooms/${r.roomId}/drawings/plan/dxf?version=${r.version ?? ''}`, 'furniture-layout.dxf'],
    ['Ceiling plan', `/rooms/${r.roomId}/drawings/ceiling/dxf?version=${r.version ?? ''}`, 'ceiling.dxf'], ['Electrical layout', `/rooms/${r.roomId}/drawings/electrical/dxf?version=${r.version ?? ''}`, 'electrical.dxf'],
    ...(['NORTH', 'EAST', 'SOUTH', 'WEST'].map(w => [`${w[0] + w.slice(1).toLowerCase()} elevation`, `/rooms/${r.roomId}/drawings/elevation/dxf?version=${r.version ?? ''}&wall=${w}`, `elevation-${w.toLowerCase()}.dxf`]) as [string, string, string][])]
  return <Shell title="CAD export" subtitle="DXF drawings (mm, layered: WALLS, FURNITURE, CEILING, LIGHTS, ELECTRICAL, TEXT, DIMENSIONS) generated from the saved design version — open in AutoCAD, LibreCAD or DraftSight." picker={r.picker}>
    {a.error && <Alert>{a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
    {!r.version ? <Empty>No saved design for this room yet.</Empty> : <Card title={`Design v${r.version}`}><ul className="divide-y divide-stone-50">{files.map(([label, path, name]) => <li key={name} className="py-2 flex justify-between items-center">
      <span className="text-sm">{label}</span><button onClick={() => a.run(name, () => downloadFile(path, name), `${name} downloaded`)} className={btn.small} aria-label={`Download ${label}`}><Download className="w-3 h-3" />DXF</button></li>)}</ul></Card>}
  </Shell>
}

export function VersionsView() {
  const r = useRoom()
  const { data: detail } = useLoad<{ objects: PlacedObject[]; validation: { errors: string[]; warnings: string[] } | null }>(r.roomId && r.version ? `/rooms/${r.roomId}/designs/${r.version}` : null)
  return <Shell title="Design versions" subtitle="Every save is a new, permanent version — history is never overwritten. BOQs and drawings always say which version they came from." picker={r.picker}>
    {r.versions.length === 0 ? <Empty>No versions yet for this room.</Empty> : <div className="grid grid-cols-12 gap-4">
      <Card title={`${r.versions.length} version(s)`} className="col-span-12 md:col-span-4"><ul className="space-y-1" data-testid="versions">{[...r.versions].reverse().map(v => <li key={v.id} className="flex items-center justify-between text-sm">
        <span>v{v.version} · {v.tier}</span><Pill s={v.is_valid ? 'PASS' : 'FAIL'} label={v.is_valid ? 'valid' : 'has errors'} /></li>)}</ul>
        <Link href="/design/3d" className="text-xs text-amber-700 hover:underline block mt-3">Open the 3D editor to change the layout →</Link></Card>
      <Card title={`v${r.version} contents`} className="col-span-12 md:col-span-8">{!detail ? <Empty>Loading…</Empty> : <>
        <Table head={['Item', 'SKU', 'Position (x, y)', 'Size (L × W × H)']}>{detail.objects.map(o => <tr key={o.id}><td className="px-4 py-1.5 text-xs">{o.name}</td><td className="px-4 py-1.5 text-[11px] font-mono">{o.sku || '—'}</td>
          <td className="px-4 py-1.5 text-xs">{o.x}, {o.y}</td><td className="px-4 py-1.5 text-xs">{o.length} × {o.width} × {o.height}</td></tr>)}</Table>
        {detail.validation?.errors.map(x => <p key={x} className="text-xs text-red-700 mt-1">{x}</p>)}</>}</Card></div>}
  </Shell>
}

/** Image from an authenticated endpoint. */
export function AuthImage({ docId, alt }: { docId: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null); const [bad, setBad] = useState(false)
  useEffect(() => { let u = ''; fetchBlob(`/documents/${docId}/file`).then(b => { u = URL.createObjectURL(b); setUrl(u) }).catch(() => setBad(true)); return () => { if (u) URL.revokeObjectURL(u) } }, [docId])
  if (bad) return <div className="h-40 flex items-center justify-center bg-stone-100"><ImageOff className="w-6 h-6 text-stone-300" /></div>
  return url ? <img src={url} alt={alt} className="w-full h-40 object-cover bg-stone-100" /> : <div className="h-40 bg-stone-100 animate-pulse" />
}

/** Photo/render gallery for one project (category SITE_PHOTO or RENDER). */
export function MediaGallery({ category, title, subtitle }: { category: 'SITE_PHOTO' | 'RENDER'; title: string; subtitle: string }) {
  const [sel, setSel] = useState({ projectId: '', roomId: '' })
  const { data, reload, error } = useLoad<DocRow[]>(sel.projectId ? `/projects/${sel.projectId}/documents?category=${category}` : null)
  const a = useAction()
  const upload = (files: FileList | null) => { if (!files?.length) return
    a.run('u', async () => { for (const f of Array.from(files)) { const form = new FormData(); form.append('file', f); form.append('category', category); if (sel.roomId) form.append('room_id', sel.roomId); await api.upload(`/projects/${sel.projectId}/documents`, form) } await reload() }, `${files.length} file(s) uploaded`) }
  return <div className="space-y-5 max-w-[1300px]"><PageHeader title={title} subtitle={subtitle}>
    <label className={btn.primary + ' cursor-pointer'}><Upload className="w-3.5 h-3.5" />Upload images<input type="file" accept="image/png,image/jpeg" multiple className="hidden" aria-label="Upload images" onChange={e => { upload(e.target.files); e.target.value = '' }} disabled={!sel.projectId} /></label></PageHeader>
    <ProjectRoomPicker onChange={s => setSel({ projectId: s.projectId, roomId: s.roomId })} />
    {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
    {!data ? <Empty>Pick a project.</Empty> : data.length === 0 ? <Empty>No images yet.</Empty> :
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3" data-testid="gallery">{data.map(d => <figure key={d.id} className="bg-white border border-stone-200 rounded-lg overflow-hidden shadow-sm">
        <AuthImage docId={d.id} alt={d.name} /><figcaption className="p-2 text-[11px] text-stone-500 flex justify-between gap-2"><span className="truncate" title={d.name}>{d.name}</span><span>{fmtDate(d.created_at)}</span></figcaption></figure>)}</div>}
  </div>
}
