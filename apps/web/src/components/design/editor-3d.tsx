'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { Canvas, ThreeEvent, useThree } from '@react-three/fiber'
import { Edges, Grid, Html, OrbitControls, OrthographicCamera, PerspectiveCamera } from '@react-three/drei'
import * as THREE from 'three'
import {
  Box, Copy, Eye, Grid3x3, Loader2, Magnet, Plus, Redo2, RotateCw, Save, ShieldAlert, ShieldCheck, Trash2, Undo2,
} from 'lucide-react'
import { api, ApiError, CatalogueItem, DesignDetail, DesignVersion, Measurement, Validation } from '@/lib/api'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import {
  Obj, SNAP_MM, canRedo, canUndo, commitDrag, createHistory, displayHeight, duplicate, fromCatalogue, fromThreeCenter, gaps,
  History, push, redo, replacePresent, rotate90, rotateBy, snap, toThree, undo,
} from '@/lib/editor-logic'
import { cn, fmt } from '@/lib/utils'
import { Camera, Lightbulb, PersonStanding, Sparkles, Sun } from 'lucide-react'
import { FurnitureModel } from '@/components/design/three/models'
import { Lighting, PhotoRender, RealisticFx, RealisticRoom, eyePoint, facing, isNight } from '@/components/design/three/scene'
import type { Shell } from '@/lib/room-shell'
import { M } from '@/components/design/three/materials'

const COLOURS: Record<string, string> = { Bed: '#b45309', Wardrobe: '#78716c', Study: '#0e7490', Sofa: '#6d28d9', Chair: '#65a30d' }
const FLOOR = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
const hitFloor = (ray: THREE.Ray) => ray.intersectPlane(FLOOR, new THREE.Vector3())
const newId = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID().slice(0, 8) : `o${Date.now()}${Math.floor(Math.random() * 1e4)}`)

// ── 3D scene pieces ──────────────────────────────────────────────────────────
function Openings3D({ ops, L, W }: { ops: { id: string; kind: string; wall: string; offset: number; width: number; height: number; sill: number }[]; L: number; W: number }) {
  return <>{ops.map(o => {
    const along = (o.offset + o.width / 2) / 1000, y = (o.sill + o.height / 2) / 1000, t = 0.06
    const pos: [number, number, number] = o.wall === 'S' ? [along, y, 0] : o.wall === 'N' ? [along, y, -W / 1000] : o.wall === 'W' ? [0, y, -along] : [L / 1000, y, -along]
    const size: [number, number, number] = o.wall === 'S' || o.wall === 'N' ? [o.width / 1000, o.height / 1000, t] : [t, o.height / 1000, o.width / 1000]
    return <mesh key={o.id} position={pos}><boxGeometry args={size} /><meshStandardMaterial color={o.kind === 'DOOR' ? '#a16207' : '#7dd3fc'} transparent opacity={o.kind === 'DOOR' ? 0.85 : 0.55} /></mesh>
  })}</>
}

function RoomShell({ L, W, H }: { L: number; W: number; H: number }) {
  const l = L / 1000, w = W / 1000, h = H / 1000
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[l / 2, 0, -w / 2]}>
        <planeGeometry args={[l, w]} /><meshStandardMaterial color="#f5f1ea" />
      </mesh>
      <Grid position={[l / 2, 0.003, -w / 2]} args={[l, w]} cellSize={0.5} cellThickness={0.6} cellColor="#d6d3d1"
        sectionSize={1} sectionThickness={1} sectionColor="#a8a29e" fadeDistance={40} infiniteGrid={false} />
      <mesh position={[l / 2, h / 2, -w - 0.05]}><boxGeometry args={[l + 0.1, h, 0.1]} /><meshStandardMaterial color="#d6d3d1" transparent opacity={0.35} /></mesh>
      <mesh position={[-0.05, h / 2, -w / 2]}><boxGeometry args={[0.1, h, w]} /><meshStandardMaterial color="#d6d3d1" transparent opacity={0.35} /></mesh>
      <mesh position={[l / 2, 0.01, -w / 2]}><boxGeometry args={[l, 0.02, w]} /><meshBasicMaterial visible={false} /><Edges color="#292524" /></mesh>
    </group>
  )
}

function Furniture({ o, selected, flagged, onDown, onMove, onUp, realistic, room }: {
  o: Obj; selected: boolean; flagged: boolean; realistic: boolean; room: { L: number; W: number }
  onDown: (id: string, p: THREE.Vector3) => void; onMove: (p: THREE.Vector3) => void; onUp: () => void
}) {
  const [x, y, z] = toThree(o)
  const base = o.colour || (COLOURS[o.category] ?? '#a8a29e')
  const f = realistic ? facing(o, room.L, room.W) : null
  return (
    <group position={[x, y, z]} rotation={[0, ((o.rotation ?? 0) * Math.PI) / 180, 0]}>
      <mesh
        onPointerDown={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation(); (e.target as any).setPointerCapture?.(e.pointerId)
          const p = hitFloor(e.ray); if (p) onDown(o.id, p)
        }}
        onPointerMove={(e: ThreeEvent<PointerEvent>) => { const p = hitFloor(e.ray); if (p) onMove(p) }}
        onPointerUp={(e: ThreeEvent<PointerEvent>) => { (e.target as any).releasePointerCapture?.(e.pointerId); onUp() }}
        onPointerOver={() => { document.body.style.cursor = 'grab' }}
        onPointerOut={() => { document.body.style.cursor = 'auto' }}
      >
        <boxGeometry args={[o.length / 1000, displayHeight(o) / 1000, o.width / 1000]} />
        {realistic ? <primitive object={M.hit()} attach="material" /> : <meshStandardMaterial color={flagged ? '#dc2626' : base} transparent opacity={0.88} roughness={0.7} />}
        {(!realistic || selected) && <Edges color={selected ? '#f59e0b' : '#44403c'} />}
      </mesh>
      {f && <group position={[0, -displayHeight(o) / 2000, 0]} rotation={[0, f.yaw, 0]}>
        <FurnitureModel category={o.category} name={o.name} l={f.l / 1000} d={f.d / 1000} h={Math.max(o.height, 20) / 1000} colour={o.colour} /></group>}
      {realistic && flagged && <mesh material={M.red()}><boxGeometry args={[o.length / 1000 + 0.02, displayHeight(o) / 1000 + 0.02, o.width / 1000 + 0.02]} /></mesh>}
      {(!realistic || selected) && <Html center position={[0, displayHeight(o) / 2000 + 0.12, 0]} style={{ pointerEvents: 'none' }}>
        <div className={cn('text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap shadow-sm', selected ? 'bg-amber-600 text-white font-semibold' : 'bg-white/80 text-stone-700')}>{o.name}</div>
      </Html>}
    </group>
  )
}

/** Top view is ORTHOGRAPHIC (no parallax, so tall objects don't look displaced); 3D view is a steep perspective so tall furniture doesn't hide the room. */
function CameraRig({ view, L, W, eye }: { view: 'perspective' | 'top' | 'eye'; L: number; W: number; eye?: { pos: [number, number, number] } }) {
  const { size } = useThree()
  const cx = L / 2000, cz = -W / 2000, span = Math.max(L, W) / 1000
  const k = 1.5 / Math.min(1, size.width / size.height)   // back the camera off on narrow canvases so the whole room stays in frame
  const zoom = Math.min(size.width / ((L / 1000) * 1.3), size.height / ((W / 1000) * 1.3))   // pixels per metre
  if (view === 'eye') return <PerspectiveCamera makeDefault position={eye?.pos ?? [cx, 1.6, cz]} fov={68} near={0.05} far={200} />   // standing in the doorway / a free corner, eye height
  return view === 'top'
    ? <OrthographicCamera makeDefault position={[cx, 30, cz + 0.001]} zoom={zoom} near={0.1} far={100} />
    : <PerspectiveCamera makeDefault position={[cx + span * 0.55 * k, span * 1.15 * k, cz + span * 0.85 * k]} fov={45} near={0.1} far={100} />
}

// ── Editor ───────────────────────────────────────────────────────────────────
export function Editor3D() {
  const [sel, setSel] = useState({ roomId: '', projectId: '', roomType: '' })
  const [realistic, setRealistic] = useState(true)          // real furniture shapes, walls, sun, shadows (off = fast boxes)
  const [hour, setHour] = useState(10.5)
  const [lightsOn, setLightsOn] = useState(false)
  const [finishes, setFinishes] = useState<DesignDetail['finishes']>(null)   // the room's design concept (drawn in Realistic view)
  const canvasWrap = useRef<HTMLDivElement>(null)
  const [ops, setOps] = useState<{ id: string; kind: string; wall: string; offset: number; width: number; height: number; sill: number }[]>([])
  const [shell, setShell] = useState<Shell | null>(null)               // M41: room outline, sloped ceiling, beams/columns
  useEffect(() => { setOps([]); setShell(null); if (sel.roomId) api.get<{ openings: typeof ops; shape: Shell | null }>(`/rooms/${sel.roomId}/openings`).then(r => { setOps(r.openings); setShell(r.shape ?? null) }).catch(() => {}) }, [sel.roomId])
  const [dims, setDims] = useState<{ L: number; W: number; H: number } | null>(null)
  const [hist, setHist] = useState<History>(createHistory([]))
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [snapOn, setSnapOn] = useState(true)
  const [view, setView] = useState<'perspective' | 'top' | 'eye'>('perspective')
  const [versions, setVersions] = useState<DesignVersion[]>([])
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null)
  const [savedJson, setSavedJson] = useState('[]')
  const [catalogue, setCatalogue] = useState<CatalogueItem[]>([])
  const [pick, setPick] = useState('')
  const [val, setVal] = useState<Validation | null>(null)
  const [checking, setChecking] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [dragging, setDragging] = useState(false)

  const objects = hist.present
  const selected = objects.find(o => o.id === selectedId) ?? null
  const flagged = new Set(val?.flagged ?? [])
  const dirty = JSON.stringify(objects) !== savedJson

  const histRef = useRef(hist); histRef.current = hist
  const drag = useRef<{ id: string; offX: number; offZ: number; base: Obj[]; moved: boolean } | null>(null)
  const snapRef = useRef(snapOn); snapRef.current = snapOn

  // ── load room: dimensions, versions, latest design, catalogue ──
  const loadRoom = useCallback(async () => {
    setDims(null); setHist(createHistory([])); setSavedJson('[]'); setSelectedId(null); setVal(null); setVersions([]); setLoadedVersion(null); setMsg(null); setFinishes(null)
    if (!sel.roomId) return
    try {
      const [ms, vs] = await Promise.all([api.get<Measurement[]>(`/rooms/${sel.roomId}/measurements`), api.get<DesignVersion[]>(`/rooms/${sel.roomId}/designs`)])
      const get = (k: string) => ms.find(m => m.label.toLowerCase().includes(k))?.value
      const L = get('length'), W = get('width')
      if (!L || !W) return
      setDims({ L, W, H: get('ceiling') ?? 2750 }); setVersions(vs)
      if (vs.length) {
        const d = await api.get<DesignDetail>(`/rooms/${sel.roomId}/designs/latest`)
        setHist(createHistory(d.objects)); setSavedJson(JSON.stringify(d.objects)); setLoadedVersion(d.version); setFinishes(d.finishes ?? null)
      }
    } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed to load room' }) }
  }, [sel.roomId])
  useEffect(() => { loadRoom() }, [loadRoom])
  useEffect(() => { api.get<CatalogueItem[]>('/catalogue/furniture?in_stock=true').then(c => { setCatalogue(c); if (c.length) setPick(c[0].sku) }).catch(() => {}) }, [])

  // ── server-side validation (single source of geometry truth), debounced, stale responses ignored ──
  const seq = useRef(0)
  useEffect(() => {
    if (!sel.roomId || !dims) return
    if (objects.length === 0) { setVal(null); setChecking(false); return }
    const n = ++seq.current; setChecking(true)
    const t = setTimeout(() => {
      api.post<Validation>(`/rooms/${sel.roomId}/designs/validate`, { objects })
        .then(r => { if (n === seq.current) setVal(r) })
        .catch(e => { if (n === seq.current) setMsg({ ok: false, text: e.message }) })
        .finally(() => { if (n === seq.current) setChecking(false) })
    }, 200)
    return () => clearTimeout(t)
  }, [objects, sel.roomId, dims])

  useEffect(() => {   // don't lose work on tab close / refresh
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', h); return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  // ── actions ──
  const edit = (fn: (o: Obj) => Obj) => { if (!selectedId) return; setHist(h => push(h, h.present.map(o => (o.id === selectedId ? fn(o) : o)))) }
  const actions = {
    undo: () => setHist(h => undo(h)), redo: () => setHist(h => redo(h)),
    rotate: () => edit(rotate90),
    remove: () => { if (!selectedId) return; setHist(h => push(h, h.present.filter(o => o.id !== selectedId))); setSelectedId(null) },
    copy: () => {
      const o = histRef.current.present.find(x => x.id === selectedId); if (!o) return
      const c = duplicate(o, newId()); setHist(h => push(h, [...h.present, c])); setSelectedId(c.id)
    },
    nudge: (dx: number, dy: number) => edit(o => ({ ...o, x: o.x + dx, y: o.y + dy })),
  }
  const actionsRef = useRef(actions); actionsRef.current = actions
  const selectedRef = useRef(selectedId); selectedRef.current = selectedId

  useEffect(() => {   // keyboard shortcuts (bound once, always call the latest actions)
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const a = actionsRef.current, k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey
      if (mod && k === 'z') { e.preventDefault(); e.shiftKey ? a.redo() : a.undo(); return }
      if (mod && k === 'y') { e.preventDefault(); a.redo(); return }
      if (!selectedRef.current) return
      const step = e.shiftKey ? 10 : SNAP_MM
      if (k === 'delete' || k === 'backspace') { e.preventDefault(); a.remove() }
      else if (mod && k === 'd') { e.preventDefault(); a.copy() }
      else if (k === 'r' && !mod) a.rotate()
      else if (k === 'arrowleft') { e.preventDefault(); a.nudge(-step, 0) }
      else if (k === 'arrowright') { e.preventDefault(); a.nudge(step, 0) }
      else if (k === 'arrowup') { e.preventDefault(); a.nudge(0, step) }
      else if (k === 'arrowdown') { e.preventDefault(); a.nudge(0, -step) }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ── drag (live updates; ONE undo step per drag) ──
  const endDrag = useCallback(() => {
    const d = drag.current; drag.current = null; setDragging(false)
    if (d?.moved) setHist(h => commitDrag(h, d.base))
  }, [])
  useEffect(() => { window.addEventListener('pointerup', endDrag); return () => window.removeEventListener('pointerup', endDrag) }, [endDrag])

  const onDown = (id: string, p: THREE.Vector3) => {
    const o = histRef.current.present.find(x => x.id === id); if (!o) return
    const [X, , Z] = toThree(o)
    drag.current = { id, offX: X - p.x, offZ: Z - p.z, base: histRef.current.present, moved: false }
    setSelectedId(id); setDragging(true)
  }
  const onMove = (p: THREE.Vector3) => {
    const d = drag.current; if (!d) return
    const o = histRef.current.present.find(x => x.id === d.id); if (!o) return
    let { x, y } = fromThreeCenter(p.x + d.offX, p.z + d.offZ, o)
    if (snapRef.current) { x = snap(x); y = snap(y) }
    if (x === o.x && y === o.y) return
    d.moved = true
    setHist(h => replacePresent(h, h.present.map(q => (q.id === d.id ? { ...q, x, y } : q))))
  }

  const addItem = () => {
    const item = catalogue.find(c => c.sku === pick); if (!item || !dims) return
    const o = fromCatalogue(item, newId(), dims.L, dims.W)
    setHist(h => push(h, [...h.present, o])); setSelectedId(o.id)
  }
  const loadVersion = async (v: number) => {
    if (dirty && !confirm('Discard unsaved changes and load this version?')) return
    try {
      const d = await api.get<DesignDetail>(`/rooms/${sel.roomId}/designs/${v}`)
      setHist(createHistory(d.objects)); setSavedJson(JSON.stringify(d.objects)); setLoadedVersion(d.version); setSelectedId(null); setMsg(null); setFinishes(d.finishes ?? null)
    } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Load failed' }) }
  }
  // photo render (path traced): quality = samples per pixel; the camera holds still while it renders
  const [photo, setPhoto] = useState<{ target: number; scale: number; n: number; done: boolean } | null>(null)
  const [quality, setQuality] = useState('good')
  const QUALITY: Record<string, { samples: number; scale: number }> = { draft: { samples: 96, scale: 0.75 }, good: { samples: 256, scale: 1 }, best: { samples: 800, scale: 1 } }
  const startPhoto = () => { setSelectedId(null); setMsg(null); setPhoto({ target: QUALITY[quality].samples, scale: QUALITY[quality].scale, n: 0, done: false }) }
  const snapshot = async () => {
    const c = canvasWrap.current?.querySelector('canvas'); if (!c || !sel.projectId) return
    const blob: Blob | null = await new Promise(res => c.toBlob(b => res(b), 'image/png'))
    if (!blob) { setMsg({ ok: false, text: 'Could not capture the view' }); return }
    const form = new FormData(); form.append('file', blob, `render-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`); form.append('category', 'RENDER'); form.append('room_id', sel.roomId)
    try { await api.upload(`/projects/${sel.projectId}/documents`, form); setMsg({ ok: true, text: 'Snapshot saved — see Design → Renders.' }) }
    catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Snapshot failed' }) }
  }
  const save = async () => {
    if (val && !val.valid && !confirm('This layout has validation errors. Save it anyway as a version flagged invalid?')) return
    try {
      const r = await api.post<{ version: number; is_valid: boolean }>(`/rooms/${sel.roomId}/designs`, { tier: 'Balanced', objects })
      setSavedJson(JSON.stringify(objects)); setLoadedVersion(r.version)
      setVersions(await api.get<DesignVersion[]>(`/rooms/${sel.roomId}/designs`))
      setMsg({ ok: true, text: `Saved as version ${r.version}${r.is_valid ? '' : ' (flagged invalid)'}.` })
    } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Save failed' }) }
  }

  const g = selected && dims ? gaps(selected, dims.L, dims.W) : null
  const eye = useMemo(() => (dims && view === 'eye' ? eyePoint(dims.L, dims.W, ops, objects, shell?.outline) : undefined), [dims, view, ops, shell]) // eslint-disable-line react-hooks/exhaustive-deps
  const total = objects.reduce((a, o) => a + o.price, 0)
  const tbtn = 'flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border transition-colors disabled:opacity-35 disabled:cursor-not-allowed'

  return (
    <div className="-m-6 flex flex-col" style={{ height: 'calc(100vh - 56px)' }}>
      {/* toolbar */}
      <div className="bg-white border-b border-stone-200 px-4 py-2 flex items-center gap-2 flex-wrap">
        <ProjectRoomPicker guard={() => !dirty || confirm('You have unsaved changes in this room. Discard them and switch?')} onChange={s => setSel({ roomId: s.roomId, projectId: s.projectId, roomType: s.room?.room_type ?? '' })} />
        <div className="w-px h-6 bg-stone-200 mx-1" />
        <button className={cn(tbtn, 'border-stone-200 hover:bg-stone-50')} onClick={actions.undo} disabled={!canUndo(hist)} title="Undo (Ctrl+Z)"><Undo2 className="w-3.5 h-3.5" />Undo</button>
        <button className={cn(tbtn, 'border-stone-200 hover:bg-stone-50')} onClick={actions.redo} disabled={!canRedo(hist)} title="Redo (Ctrl+Shift+Z)"><Redo2 className="w-3.5 h-3.5" />Redo</button>
        <button className={cn(tbtn, snapOn ? 'bg-amber-50 border-amber-300 text-amber-800' : 'border-stone-200')} onClick={() => setSnapOn(s => !s)} title="Snap to 50mm"><Magnet className="w-3.5 h-3.5" />Snap {SNAP_MM}mm</button>
        <button className={cn(tbtn, view === 'perspective' ? 'bg-stone-900 text-white border-stone-900' : 'border-stone-200')} onClick={() => setView('perspective')}><Eye className="w-3.5 h-3.5" />3D</button>
        <button className={cn(tbtn, view === 'top' ? 'bg-stone-900 text-white border-stone-900' : 'border-stone-200')} onClick={() => setView('top')}><Grid3x3 className="w-3.5 h-3.5" />Top</button>
        <button className={cn(tbtn, view === 'eye' ? 'bg-stone-900 text-white border-stone-900' : 'border-stone-200')} onClick={() => setView('eye')} title="Stand in the room at eye height"><PersonStanding className="w-3.5 h-3.5" />Eye level</button>
        <div className="w-px h-6 bg-stone-200 mx-1" />
        <button className={cn(tbtn, realistic ? 'bg-amber-50 border-amber-300 text-amber-800' : 'border-stone-200')} onClick={() => setRealistic(r => !r)} aria-pressed={realistic} title="Real furniture, walls, sunlight and shadows (off = quick boxes)"><Sparkles className="w-3.5 h-3.5" />Realistic</button>
        {realistic && <label className="flex items-center gap-1.5 text-[11px] text-stone-600" title="Time of day (sun position)"><Sun className="w-3.5 h-3.5 text-amber-600" />
          <input type="range" aria-label="Time of day" min={6} max={21} step={0.25} value={hour} onChange={e => setHour(Number(e.target.value))} className="w-24 accent-amber-700" />
          <span className="w-10 font-mono">{`${Math.floor(hour)}:${String(Math.round((hour % 1) * 60)).padStart(2, '0')}`}</span></label>}
        {realistic && <button className={cn(tbtn, lightsOn || isNight(hour) ? 'bg-amber-50 border-amber-300 text-amber-800' : 'border-stone-200')} onClick={() => setLightsOn(v => !v)} aria-pressed={lightsOn} title="Ceiling lights"><Lightbulb className="w-3.5 h-3.5" />Lights</button>}
        {realistic && <div className="flex items-center gap-1">
          <select aria-label="Photo quality" value={quality} onChange={e => setQuality(e.target.value)} disabled={!!photo} className="text-xs border border-stone-200 rounded px-1.5 py-1.5 bg-white" title="More samples = cleaner image, longer render">
            <option value="draft">Draft</option><option value="good">Good</option><option value="best">Best</option></select>
          <button className={cn(tbtn, 'bg-amber-700 text-white border-amber-700 hover:bg-amber-800')} onClick={startPhoto} disabled={!dims || !!photo} title="Path-traced photo of this view: real light bounce, soft shadows, daylight through the windows"><Camera className="w-3.5 h-3.5" />Photo render</button></div>}
        <div className="flex-1" />
        {versions.length > 0 && (
          <select value={loadedVersion ?? ''} onChange={e => loadVersion(Number(e.target.value))} className="text-xs border border-stone-200 rounded px-2 py-1.5 bg-white">
            {versions.map(v => <option key={v.id} value={v.version}>v{v.version}{v.is_valid ? '' : ' (invalid)'}</option>)}
          </select>)}
        {dirty && <span className="text-[11px] text-amber-700 font-medium">● Unsaved</span>}
        <button className={cn(tbtn, 'border-stone-200')} onClick={snapshot} disabled={!dims || !sel.projectId} title="Save this view as a render (Design → Renders)"><Camera className="w-3.5 h-3.5" />Snapshot</button>
        <button className={cn(tbtn, 'bg-stone-900 text-white border-stone-900 hover:bg-stone-800')} onClick={save} disabled={!dims || objects.length === 0 || !dirty}><Save className="w-3.5 h-3.5" />Save version</button>
      </div>
      {msg && <p className={cn('text-xs px-4 py-1.5 border-b', msg.ok ? 'text-green-700 bg-green-50 border-green-200' : 'text-red-600 bg-red-50 border-red-200')}>{msg.text}</p>}

      {!sel.roomId ? <p className="p-8 text-sm text-stone-500">Pick a room. Create projects and rooms under Projects and Survey → Rooms.</p>
        : !dims ? <p className="p-8 text-sm text-amber-800">This room needs Length and Width measurements. <Link href="/survey/rooms" className="underline font-medium">Add them in Rooms →</Link></p>
        : (
        <div className="flex-1 flex min-h-0">
          {/* left: objects + add */}
          <div className="w-60 bg-white border-r border-stone-200 flex flex-col">
            <div className="px-3 py-2.5 border-b border-stone-100 text-xs font-semibold text-stone-700 flex items-center gap-2"><Box className="w-3.5 h-3.5 text-amber-700" />Objects ({objects.length})</div>
            <div className="flex-1 overflow-y-auto">
              {objects.length === 0 && <p className="p-3 text-[11px] text-stone-400">Empty room. Add furniture below, or generate a design in AI Designer and save it.</p>}
              {objects.map(o => (
                <button key={o.id} onClick={() => setSelectedId(o.id)} className={cn('w-full flex items-center gap-2 px-3 py-2 text-left text-xs border-b border-stone-50', selectedId === o.id ? 'bg-amber-50' : 'hover:bg-stone-50')}>
                  <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: flagged.has(o.id) ? '#dc2626' : COLOURS[o.category] ?? '#a8a29e' }} />
                  <span className="flex-1 truncate">{o.name}</span>{flagged.has(o.id) && <ShieldAlert className="w-3.5 h-3.5 text-red-500" />}
                </button>))}
            </div>
            <div className="p-3 border-t border-stone-100 space-y-2">
              <select value={pick} onChange={e => setPick(e.target.value)} className="w-full text-xs border border-stone-200 rounded px-2 py-1.5 bg-white">
                {catalogue.map(c => <option key={c.sku} value={c.sku}>{c.name}</option>)}
              </select>
              <button onClick={addItem} disabled={!catalogue.length} className="w-full flex items-center justify-center gap-1.5 text-xs bg-amber-700 hover:bg-amber-800 disabled:opacity-40 text-white py-1.5 rounded font-medium"><Plus className="w-3.5 h-3.5" />Add to room</button>
              <p className="text-[10px] text-stone-400">Est. furniture: {fmt(total)}</p>
            </div>
          </div>

          {/* canvas */}
          <div ref={canvasWrap} className="flex-1 relative bg-stone-100">
            <Canvas key={realistic ? 'real' : 'quick'} frameloop="demand" shadows={realistic ? 'soft' : false} dpr={[1, 2]} gl={{ preserveDrawingBuffer: true, antialias: true }} camera={{ fov: 45, near: 0.1, far: 100 }} onPointerMissed={() => setSelectedId(null)}>
              {realistic ? <>
                <Lighting L={dims.L / 1000} W={dims.W / 1000} H={dims.H / 1000} hour={hour} />
                <RealisticRoom L={dims.L / 1000} W={dims.W / 1000} H={dims.H / 1000} ops={ops} hour={hour} lightsOn={lightsOn} wet={['BATHROOM', 'UTILITY', 'KITCHEN', 'WASH_AREA'].includes(sel.roomType)} finishes={finishes} shell={shell} />
                {photo ? <PhotoRender samples={photo.target} scale={photo.scale} onProgress={n => setPhoto(p => p && { ...p, n })} onDone={() => setPhoto(p => p && { ...p, done: true })} /> : <RealisticFx />}
              </> : <>
                <color attach="background" args={['#f0ece6']} />
                <ambientLight intensity={0.8} /><directionalLight position={[6, 10, 4]} intensity={1.1} /><hemisphereLight args={['#ffffff', '#d6d3d1', 0.4]} />
                <RoomShell L={dims.L} W={dims.W} H={dims.H} />
                <Openings3D ops={ops} L={dims.L} W={dims.W} />
              </>}
              <CameraRig view={view} L={dims.L} W={dims.W} eye={eye} />
              {objects.map(o => <Furniture key={o.id} o={o} selected={o.id === selectedId} flagged={flagged.has(o.id)} onDown={onDown} onMove={onMove} onUp={endDrag} realistic={realistic} room={dims} />)}
              <OrbitControls key={view} makeDefault target={view === 'eye' && eye ? eye.target : [dims.L / 2000, 0, -dims.W / 2000]} enabled={!dragging && !photo} enableRotate={view !== 'top'} enableDamping dampingFactor={0.08}
                maxPolarAngle={view === 'eye' ? Math.PI * 0.62 : Math.PI / 2 - 0.02} minDistance={view === 'eye' ? 0.3 : 0.5} />
            </Canvas>
            {photo && <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-white/95 border border-stone-200 rounded-lg shadow px-4 py-2.5 text-xs flex items-center gap-3" data-testid="photo-status">
              {photo.done ? <span className="text-green-700 font-medium">Photo ready ({photo.target} samples)</span>
                : <><Loader2 className="w-3.5 h-3.5 animate-spin text-amber-700" /><span>Rendering photo… {photo.n} / {photo.target} samples</span>
                  <span className="w-28 h-1.5 bg-stone-200 rounded overflow-hidden"><span className="block h-full bg-amber-600" style={{ width: `${Math.min(100, photo.n / photo.target * 100)}%` }} /></span></>}
              <button className="text-xs px-2 py-1 rounded bg-stone-900 text-white" onClick={snapshot} disabled={!photo.done && photo.n < 16}>Save photo</button>
              <button className="text-xs px-2 py-1 rounded border border-stone-300" onClick={() => setPhoto(null)}>{photo.done ? 'Back to editing' : 'Stop'}</button></div>}
            <div className="absolute bottom-3 left-3 text-[11px] bg-white/90 border border-stone-200 rounded px-2.5 py-1.5 text-stone-500">
              Room {dims.L} × {dims.W} × {dims.H} mm · drag to move · R rotate · Ctrl+D duplicate · Del delete · arrows nudge
            </div>
          </div>

          {/* right: validation + properties */}
          <div className="w-64 bg-white border-l border-stone-200 flex flex-col overflow-y-auto">
            <div className={cn('px-3 py-3 border-b text-xs', !val ? 'border-stone-100' : val.valid ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200')}>
              <div className="flex items-center gap-1.5 font-semibold">
                {checking ? <><Loader2 className="w-3.5 h-3.5 animate-spin text-stone-400" /><span className="text-stone-500">Checking…</span></>
                  : !val ? <span className="text-stone-400">No objects to check</span>
                  : val.valid ? <><ShieldCheck className="w-4 h-4 text-green-600" /><span className="text-green-800">Valid · {(val.occupancy * 100).toFixed(0)}% occupied</span></>
                  : <><ShieldAlert className="w-4 h-4 text-red-600" /><span className="text-red-800">{val.errors.length} problem(s)</span></>}
              </div>
              {val && [...val.errors, ...val.warnings].map((m, i) => <p key={i} className="mt-1 text-stone-600">• {m}</p>)}
              <p className="mt-1.5 text-[10px] text-stone-400">Checked by the server — the same validator used for saving, CAD and BOQ.</p>
            </div>
            {!selected ? <p className="p-4 text-[11px] text-stone-400">Select an object to edit it.</p> : (
              <div className="p-3 space-y-3 text-xs">
                <div><p className="font-semibold text-stone-800">{selected.name}</p><p className="text-[11px] text-stone-400">{selected.category} · {fmt(selected.price)}</p></div>
                <div className="grid grid-cols-3 gap-2">
                  {(['x', 'y', 'z'] as const).map(k => (
                    <label key={k} className="block"><span className="text-[10px] text-stone-400 uppercase">{k === 'x' ? 'X (east) mm' : k === 'y' ? 'Y (north) mm' : 'Above floor'}</span>
                      <input key={`${selected.id}-${k}-${selected[k] ?? 0}`} type="number" step={SNAP_MM} min={0} aria-label={k === 'z' ? 'Height above floor' : undefined} defaultValue={selected[k] ?? 0}
                        onBlur={e => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && v >= 0 && v !== (selected[k] ?? 0)) edit(o => ({ ...o, [k]: v })) }}
                        onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        className="w-full mt-0.5 border border-stone-200 rounded px-2 py-1 font-mono bg-stone-50 outline-none focus:border-amber-400" /></label>))}
                </div>
                <div className="grid grid-cols-2 gap-2 items-end">
                  <label className="block"><span className="text-[10px] text-stone-400 uppercase">Rotation °</span>
                    <input key={`${selected.id}-rot-${selected.rotation ?? 0}`} type="number" step={15} aria-label="Rotation degrees" defaultValue={selected.rotation ?? 0}
                      onBlur={e => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && v !== (selected.rotation ?? 0)) edit(o => rotateBy({ ...o, rotation: 0 }, v)) }}
                      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                      className="w-full mt-0.5 border border-stone-200 rounded px-2 py-1 font-mono bg-stone-50 outline-none focus:border-amber-400" /></label>
                  <div className="flex gap-1"><button className="flex-1 border border-stone-200 rounded py-1 hover:bg-stone-50" aria-label="Turn 15 degrees anticlockwise" onClick={() => edit(o => rotateBy(o, 15))}>⟲ 15°</button>
                    <button className="flex-1 border border-stone-200 rounded py-1 hover:bg-stone-50" aria-label="Turn 15 degrees clockwise" onClick={() => edit(o => rotateBy(o, -15))}>⟳ 15°</button></div>
                </div>
                <div className="flex items-center gap-2"><span className="text-[10px] text-stone-400 uppercase">Colour</span>
                  <input type="color" aria-label="Object colour" value={selected.colour || '#a8a29e'} onChange={e => { const v = e.target.value; edit(o => ({ ...o, colour: v })) }} className="w-8 h-6 border border-stone-200 rounded cursor-pointer" />
                  {selected.colour && <button className="text-[11px] text-stone-500 hover:underline" onClick={() => edit(o => ({ ...o, colour: null }))}>Default</button>}</div>
                <div className="bg-stone-50 border border-stone-100 rounded p-2 font-mono text-[11px] text-stone-600 space-y-0.5">
                  <div>Size {selected.length}×{selected.width}×{selected.height} mm{selected.rotation ? ` · turned ${selected.rotation}°` : ''}</div>
                  {g && <><div>To west wall  {g.west} mm</div><div>To east wall  {g.east} mm</div><div>To south wall {g.south} mm</div><div>To north wall {g.north} mm</div></>}
                </div>
                <div className="flex gap-1.5">
                  <button onClick={actions.rotate} className={cn(tbtn, 'flex-1 justify-center border-stone-200 hover:bg-stone-50')}><RotateCw className="w-3.5 h-3.5" />90°</button>
                  <button onClick={actions.copy} className={cn(tbtn, 'flex-1 justify-center border-stone-200 hover:bg-stone-50')}><Copy className="w-3.5 h-3.5" />Copy</button>
                  <button onClick={actions.remove} className={cn(tbtn, 'flex-1 justify-center border-red-200 text-red-600 hover:bg-red-50')}><Trash2 className="w-3.5 h-3.5" />Del</button>
                </div>
              </div>)}
          </div>
        </div>)}
    </div>
  )
}
