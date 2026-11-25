'use client'
// Realistic room for the 3D views: plank floor (tiles in wet rooms), plaster walls with real door/window openings, glass, a door leaf,
// skirting, ceiling with downlights, sun placed by time of day (India: sun in the south at noon), sky, soft shadows, bounce light.
// Walls between the camera and the room hide themselves (dollhouse cut-away) so the furniture is always visible.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer, N8AO, SMAA, ToneMapping } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'
import { ContactShadows, Environment, Lightformer, Sky } from '@react-three/drei'
import * as THREE from 'three'
import { M } from './materials'
import { ConceptDecor, Finishes, floorMaterial } from './finishes'
import { ceilingAt, openingSpan, type Pt, type Shell } from '@/lib/room-shell'

export interface Opening3 { id: string; kind: string; wall: string; offset: number; width: number; height: number; sill: number; x0?: number; y0?: number; x1?: number; y1?: number; nx?: number; ny?: number }
const WALL_T = 0.12

/** Sun direction from local time: rises in the east, highest in the south at noon, sets in the west. North = −Z, east = +X. */
export function sunDirection(hour: number): THREE.Vector3 {
  const t = Math.min(1, Math.max(0, (hour - 6) / 12))
  const az = (90 + 180 * t) * Math.PI / 180                // 90° east → 180° south → 270° west
  const el = Math.max(2, 72 * Math.sin(Math.PI * t)) * Math.PI / 180
  return new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize()
}
export const isNight = (hour: number) => hour < 6.3 || hour > 18.2
/** 0 at night → 1 around midday: how much sky light comes in through the windows. */
export const daylight = (hour: number) => isNight(hour) ? 0 : Math.max(0.15, Math.sin(Math.PI * Math.min(1, Math.max(0, (hour - 6) / 12))))

/** Where a person would stand to look at the room (mm in, metres out): just inside the door if there is one, else the first free corner.
 *  A spot inside a piece of furniture (lower than eye height) is never used. */
export function eyePoint(L: number, W: number, ops: Opening3[], objs: { x: number; y: number; length: number; width: number; z?: number }[], outline?: Pt[]): { pos: [number, number, number]; target: [number, number, number] } {
  const inRoom = (x: number, y: number) => !outline || outline.length < 4 || [[150, 150], [-150, 150], [150, -150], [-150, -150]].every(([dx, dy]) => inside(outline, x + dx, y + dy))
  const free = (x: number, y: number) => x > 150 && y > 150 && x < L - 150 && y < W - 150 && inRoom(x, y) &&
    !objs.some(o => (o.z ?? 0) < 1600 && x > o.x - 250 && x < o.x + o.length + 250 && y > o.y - 250 && y < o.y + o.width + 250)
  const cands: [number, number][] = []
  for (const d of ops.filter(o => o.kind === 'DOOR')) {
    const [p0, p1, n] = openingSpan(d, L, W)                           // just inside the door, on whichever wall it is (M41: inner / angled walls)
    for (const k of [450, 700, 1000]) cands.push([(p0[0] + p1[0]) / 2 + n[0] * k, (p0[1] + p1[1]) / 2 + n[1] * k])
  }
  for (const k of [500, 800]) cands.push([k, k], [L - k, k], [k, W - k], [L - k, W - k], [L / 2, k], [L / 2, W - k], [k, W / 2], [L - k, W / 2])
  const [x, y] = cands.find(([a, b]) => free(a, b)) ?? cands.find(([a, b]) => inRoom(a, b)) ?? [L / 2, W / 2]
  return { pos: [x / 1000, 1.6, -y / 1000], target: [L / 2000 + (L / 2000 - x / 1000) * 0.2, 1.15, -W / 2000 - (W / 2000 - y / 1000) * 0.2] }
}

/** Yaw (radians) that turns a model's back (−Z) to the nearest wall, plus the model's own length/depth for that wall. */
export function facing(o: { x: number; y: number; length: number; width: number }, L: number, W: number) {
  const c = [{ wall: 'S', d: o.y, yaw: Math.PI, along: true }, { wall: 'N', d: W - (o.y + o.width), yaw: 0, along: true },
             { wall: 'W', d: o.x, yaw: Math.PI / 2, along: false }, { wall: 'E', d: L - (o.x + o.length), yaw: -Math.PI / 2, along: false }]
  const best = c.reduce((a, b) => (b.d < a.d ? b : a))
  return { yaw: best.yaw, l: best.along ? o.length : o.width, d: best.along ? o.width : o.length, wall: best.wall }
}

function WallWithOpenings({ wall, L, W, H, ops, cutaway, tiles, colour, daylight = 0 }: { wall: 'S' | 'N' | 'W' | 'E'; L: number; W: number; H: number; ops: Opening3[]; cutaway: boolean; tiles: boolean; colour?: string; daylight?: number }) {
  const len = wall === 'S' || wall === 'N' ? L : W
  const group = useRef<THREE.Group>(null)
  const normal = useMemo(() => ({ S: new THREE.Vector3(0, 0, 1), N: new THREE.Vector3(0, 0, -1), W: new THREE.Vector3(-1, 0, 0), E: new THREE.Vector3(1, 0, 0) }[wall]), [wall])
  const centre = useMemo(() => ({ S: new THREE.Vector3(L / 2, H / 2, 0), N: new THREE.Vector3(L / 2, H / 2, -W), W: new THREE.Vector3(0, H / 2, -W / 2), E: new THREE.Vector3(L, H / 2, -W / 2) }[wall]), [wall, L, W, H])
  useFrame(({ camera }) => {           // hide a wall when the camera looks at the room from its outside
    if (!group.current) return
    const out = camera.position.clone().sub(centre).dot(normal) > 0.05
    group.current.visible = !(cutaway && out && camera.position.y < H * 6)
  })
  const segs: { a: number; b: number; y0: number; y1: number }[] = []
  // offsets are from the west end (N/S walls) or the south end (W/E walls); the N and W walls are built running the other way, so flip them
  const flip = wall === 'N' || wall === 'W'
  const mine = ops.filter(o => o.wall === wall).map(o => {
    const a = o.offset / 1000, b = (o.offset + o.width) / 1000
    return { a: flip ? len - b : a, b: flip ? len - a : b, y0: o.sill / 1000, y1: (o.sill + o.height) / 1000, kind: o.kind }
  }).sort((p, q) => p.a - q.a)
  let cur = 0
  for (const o of mine) {
    if (o.a > cur) segs.push({ a: cur, b: o.a, y0: 0, y1: H })
    if (o.y0 > 0) segs.push({ a: o.a, b: o.b, y0: 0, y1: o.y0 })
    if (o.y1 < H) segs.push({ a: o.a, b: o.b, y0: o.y1, y1: H })
    cur = Math.max(cur, o.b)
  }
  if (cur < len) segs.push({ a: cur, b: len, y0: 0, y1: H })
  // local frame: along the wall = +X from the wall's start, the wall's inner face at z=0, outward = +Z
  const place = { S: { p: [0, 0, 0] as const, r: 0 }, N: { p: [L, 0, -W] as const, r: Math.PI }, W: { p: [0, 0, -W] as const, r: -Math.PI / 2 }, E: { p: [L, 0, 0] as const, r: Math.PI / 2 } }[wall]
  const wallMat = tiles ? M.tiles('#ece8e1', len, H) : M.wall(colour)
  return <group ref={group} position={place.p as unknown as [number, number, number]} rotation={[0, place.r, 0]}>
    {segs.map((s, i) => <mesh key={i} position={[(s.a + s.b) / 2, (s.y0 + s.y1) / 2, WALL_T / 2]} castShadow receiveShadow material={wallMat}><boxGeometry args={[s.b - s.a, s.y1 - s.y0, WALL_T]} /></mesh>)}
    {mine.filter(o => o.kind === 'WINDOW').map((o, i) => <group key={`w${i}`}>
      {daylight > 0.02 && <rectAreaLight position={[(o.a + o.b) / 2, (o.y0 + o.y1) / 2, WALL_T + 0.02]} width={o.b - o.a} height={o.y1 - o.y0} intensity={3.5 * daylight} color="#e9f2ff" />}
      <mesh position={[(o.a + o.b) / 2, (o.y0 + o.y1) / 2, WALL_T / 2]} material={M.glass()}><boxGeometry args={[o.b - o.a, o.y1 - o.y0, 0.01]} /></mesh>
      {[o.y0, o.y1].map((y, k) => <mesh key={k} position={[(o.a + o.b) / 2, y, WALL_T / 2]} castShadow material={M.appliance()}><boxGeometry args={[o.b - o.a, 0.05, WALL_T + 0.02]} /></mesh>)}
      {[o.a, (o.a + o.b) / 2, o.b].map((x, k) => <mesh key={`v${k}`} position={[x, (o.y0 + o.y1) / 2, WALL_T / 2]} castShadow material={M.appliance()}><boxGeometry args={[0.05, o.y1 - o.y0, WALL_T + 0.02]} /></mesh>)}
      <mesh position={[(o.a + o.b) / 2, o.y0 - 0.01, -0.06]} receiveShadow material={M.quartz()}><boxGeometry args={[o.b - o.a + 0.1, 0.03, 0.14]} /></mesh>
    </group>)}
    {mine.filter(o => o.kind === 'DOOR').map((o, i) => <group key={`d${i}`}>
      {[o.a - 0.03, o.b + 0.03].map((x, k) => <mesh key={k} position={[x, o.y1 / 2, -0.01]} castShadow material={M.wood('#d8c3a5')}><boxGeometry args={[0.06, o.y1, 0.04]} /></mesh>)}
      <mesh position={[(o.a + o.b) / 2, o.y1 + 0.03, -0.01]} castShadow material={M.wood('#d8c3a5')}><boxGeometry args={[o.b - o.a + 0.12, 0.06, 0.04]} /></mesh>
      <group position={[o.a, 0, 0]} rotation={[0, 0.35, 0]}>
        <mesh position={[(o.b - o.a) / 2, o.y1 / 2, -0.02]} castShadow receiveShadow material={M.wood('#b98d5f')}><boxGeometry args={[o.b - o.a - 0.01, o.y1 - 0.01, 0.035]} /></mesh>
        <mesh position={[o.b - o.a - 0.08, 1.0, -0.05]} material={M.chrome()}><boxGeometry args={[0.12, 0.02, 0.02]} /></mesh>
      </group>
    </group>)}
    {segs.filter(s => s.y0 === 0).map((s, i) => <mesh key={`sk${i}`} position={[(s.a + s.b) / 2, 0.05, -0.006]} castShadow material={M.laminate('#efe9df')}><boxGeometry args={[s.b - s.a, 0.1, 0.012]} /></mesh>)}
  </group>
}

function inside(pts: Pt[], x: number, y: number) {
  let c = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j]
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c
  }
  return c
}

/** One wall along an outline edge (M41: L-shaped rooms, angled walls) with its top following the ceiling (sloped / uneven) and real
 *  door/window openings. Plan mm in, metres out. Local frame: +X along the wall from p0, inner face at z=0, outward = +Z. */
function EdgeWall({ p0, p1, top, ops, cutaway, tiles, colour, daylight = 0 }: { p0: Pt; p1: Pt; top: (x: number, y: number) => number; ops: { a: number; b: number; y0: number; y1: number; kind: string }[]; cutaway: boolean; tiles: boolean; colour?: string; daylight?: number }) {
  const len = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 1000
  const ux = (p1[0] - p0[0]) / 1000 / len, uy = (p1[1] - p0[1]) / 1000 / len
  const group = useRef<THREE.Group>(null)
  const n = 8, tops = useMemo(() => Array.from({ length: n + 1 }, (_, k) => top(p0[0] + (p1[0] - p0[0]) * k / n, p0[1] + (p1[1] - p0[1]) * k / n) / 1000), [p0, p1, top])
  const Hm = Math.max(...tops), Hlo = Math.min(...tops)
  const normal = useMemo(() => new THREE.Vector3(uy, 0, ux), [ux, uy])
  const centre = useMemo(() => new THREE.Vector3((p0[0] + p1[0]) / 2000, Hm / 2, -(p0[1] + p1[1]) / 2000), [p0, p1, Hm])
  useFrame(({ camera }) => {
    if (!group.current) return
    const out = camera.position.clone().sub(centre).dot(normal) > 0.05
    group.current.visible = !(cutaway && out && camera.position.y < Hm * 6)
  })
  const mine = [...ops].sort((p, q) => p.a - q.a).map(o => ({ ...o, y1: Math.min(o.y1, Hlo - 0.02) }))
  const geom = useMemo(() => {
    const sh = new THREE.Shape(); sh.moveTo(0, 0)
    for (const o of mine.filter(o => o.y0 <= 0.001)) { sh.lineTo(o.a, 0); sh.lineTo(o.a, o.y1); sh.lineTo(o.b, o.y1); sh.lineTo(o.b, 0) }   // doors cut from the bottom
    sh.lineTo(len, 0)
    for (let k = n; k >= 0; k--) sh.lineTo(len * k / n, tops[k])
    sh.lineTo(0, 0)
    for (const o of mine.filter(o => o.y0 > 0.001)) { const h = new THREE.Path(); h.moveTo(o.a, o.y0); h.lineTo(o.b, o.y0); h.lineTo(o.b, o.y1); h.lineTo(o.a, o.y1); h.lineTo(o.a, o.y0); sh.holes.push(h) }
    const g = new THREE.ExtrudeGeometry(sh, { depth: WALL_T, bevelEnabled: false })
    const pos = g.attributes.position as THREE.BufferAttribute, uv = g.attributes.uv as THREE.BufferAttribute
    for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i) / len, pos.getY(i) / Hm)            // 0..1 like the old boxes (tile repeat per wall)
    uv.needsUpdate = true; g.computeVertexNormals(); return g
  }, [len, tops, JSON.stringify(mine)]) // eslint-disable-line react-hooks/exhaustive-deps
  const wallMat = tiles ? M.tiles('#ece8e1', len, Hm) : M.wall(colour)
  const skirt: [number, number][] = []; let cur = 0
  for (const o of mine.filter(o => o.y0 <= 0.001)) { if (o.a > cur) skirt.push([cur, o.a]); cur = Math.max(cur, o.b) }
  if (cur < len) skirt.push([cur, len])
  return <group ref={group} position={[p0[0] / 1000, 0, -p0[1] / 1000]} rotation={[0, Math.atan2(uy, ux), 0]}>
    <mesh geometry={geom} castShadow receiveShadow material={wallMat} />
    {mine.filter(o => o.kind === 'WINDOW').map((o, i) => <group key={`w${i}`}>
      {daylight > 0.02 && <rectAreaLight position={[(o.a + o.b) / 2, (o.y0 + o.y1) / 2, WALL_T + 0.02]} width={o.b - o.a} height={o.y1 - o.y0} intensity={3.5 * daylight} color="#e9f2ff" />}
      <mesh position={[(o.a + o.b) / 2, (o.y0 + o.y1) / 2, WALL_T / 2]} material={M.glass()}><boxGeometry args={[o.b - o.a, o.y1 - o.y0, 0.01]} /></mesh>
      {[o.y0, o.y1].map((y, k) => <mesh key={k} position={[(o.a + o.b) / 2, y, WALL_T / 2]} castShadow material={M.appliance()}><boxGeometry args={[o.b - o.a, 0.05, WALL_T + 0.02]} /></mesh>)}
      {[o.a, (o.a + o.b) / 2, o.b].map((x, k) => <mesh key={`v${k}`} position={[x, (o.y0 + o.y1) / 2, WALL_T / 2]} castShadow material={M.appliance()}><boxGeometry args={[0.05, o.y1 - o.y0, WALL_T + 0.02]} /></mesh>)}
      <mesh position={[(o.a + o.b) / 2, o.y0 - 0.01, -0.06]} receiveShadow material={M.quartz()}><boxGeometry args={[o.b - o.a + 0.1, 0.03, 0.14]} /></mesh>
    </group>)}
    {mine.filter(o => o.kind === 'DOOR').map((o, i) => <group key={`d${i}`}>
      {[o.a - 0.03, o.b + 0.03].map((x, k) => <mesh key={k} position={[x, o.y1 / 2, -0.01]} castShadow material={M.wood('#d8c3a5')}><boxGeometry args={[0.06, o.y1, 0.04]} /></mesh>)}
      <mesh position={[(o.a + o.b) / 2, o.y1 + 0.03, -0.01]} castShadow material={M.wood('#d8c3a5')}><boxGeometry args={[o.b - o.a + 0.12, 0.06, 0.04]} /></mesh>
      <group position={[o.a, 0, 0]} rotation={[0, 0.35, 0]}>
        <mesh position={[(o.b - o.a) / 2, o.y1 / 2, -0.02]} castShadow receiveShadow material={M.wood('#b98d5f')}><boxGeometry args={[o.b - o.a - 0.01, o.y1 - 0.01, 0.035]} /></mesh>
        <mesh position={[o.b - o.a - 0.08, 1.0, -0.05]} material={M.chrome()}><boxGeometry args={[0.12, 0.02, 0.02]} /></mesh>
      </group>
    </group>)}
    {skirt.map(([a, b], i) => <mesh key={`sk${i}`} position={[(a + b) / 2, 0.05, -0.006]} castShadow material={M.laminate('#efe9df')}><boxGeometry args={[b - a, 0.1, 0.012]} /></mesh>)}
  </group>
}

/** Openings assigned to the outline edge they sit on, as distances along it (m) — p0 → p1. */
function edgeOps(p0: Pt, p1: Pt, ops: Opening3[], L: number, W: number) {
  const len = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), ux = (p1[0] - p0[0]) / len, uy = (p1[1] - p0[1]) / len
  const out: { a: number; b: number; y0: number; y1: number; kind: string }[] = []
  for (const o of ops) {
    const [q0, q1] = openingSpan(o, L, W)
    const off = (q: Pt) => Math.abs((q[0] - p0[0]) * uy - (q[1] - p0[1]) * ux)                    // distance from the wall line
    if (off(q0) > 5 || off(q1) > 5) continue
    const t0 = (q0[0] - p0[0]) * ux + (q0[1] - p0[1]) * uy, t1 = (q1[0] - p0[0]) * ux + (q1[1] - p0[1]) * uy
    if (Math.min(t0, t1) < -5 || Math.max(t0, t1) > len + 5) continue
    out.push({ a: Math.min(t0, t1) / 1000, b: Math.max(t0, t1) / 1000, y0: o.sill / 1000, y1: (o.sill + o.height) / 1000, kind: o.kind })
  }
  return out
}

/** Ceiling that follows a sloped / uneven profile, only seen from inside; beams, drops, columns and pillars as solid boxes. */
function ShellCeiling({ shell, lightsOn }: { shell: Shell; lightsOn: boolean }) {
  const ref = useRef<THREE.Mesh>(null)
  const { L, W, H, ceiling, outline } = shell
  const hAt = (x: number, y: number) => ceilingAt(ceiling, H, L, W, x, y)
  useFrame(({ camera }) => { if (ref.current) ref.current.visible = camera.position.y < shell.ceiling_min / 1000 - 0.05 })
  const geom = useMemo(() => {
    let g: THREE.BufferGeometry
    if (ceiling.type === 'UNEVEN') {                                                      // fine grid, cells outside the outline dropped
      const step = 100, nx = Math.ceil(L / step), ny = Math.ceil(W / step), v: number[] = []
      const P = (x: number, y: number) => [x / 1000, hAt(x, y) / 1000, -y / 1000]
      for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
        const x0 = i * L / nx, x1 = (i + 1) * L / nx, y0 = j * W / ny, y1 = (j + 1) * W / ny
        if (!inside(outline, (x0 + x1) / 2, (y0 + y1) / 2)) continue
        v.push(...P(x0, y0), ...P(x1, y1), ...P(x1, y0), ...P(x0, y0), ...P(x0, y1), ...P(x1, y1))
      }
      g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3))
    } else {
      const sh = new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x / 1000, y / 1000)))
      g = new THREE.ShapeGeometry(sh)
      const pos = g.attributes.position as THREE.BufferAttribute
      for (let i = 0; i < pos.count; i++) { const x = pos.getX(i) * 1000, y = pos.getY(i) * 1000; pos.setXYZ(i, x / 1000, hAt(x, y) / 1000, -y / 1000) }
      g.index && g.setIndex(Array.from(g.index.array).reduce<number[]>((a, _, k, arr) => (k % 3 === 0 ? a.concat([arr[k], arr[k + 2], arr[k + 1]]) : a), []))
    }
    g.computeVertexNormals(); return g
  }, [JSON.stringify(outline), JSON.stringify(ceiling), L, W, H]) // eslint-disable-line react-hooks/exhaustive-deps
  const spots: [number, number][] = []
  const nx = Math.max(1, Math.round(L / 1300)), nz = Math.max(1, Math.round(W / 1300))
  for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) { const x = L * (i + 0.5) / nx, y = W * (j + 0.5) / nz; if (inside(outline, x, y)) spots.push([x, y]) }
  const lit = spots.length <= 6 ? spots : spots.filter((_, k) => k % Math.ceil(spots.length / 6) === 0)
  const ceilMat = useMemo(() => { const m = (M.ceiling() as THREE.MeshStandardMaterial).clone(); m.side = THREE.DoubleSide; return m }, [])
  return <group>
    <mesh ref={ref} geometry={geom} material={ceilMat} />
    {spots.map(([x, y], i) => <mesh key={i} position={[x / 1000, hAt(x, y) / 1000 - 0.005, -y / 1000]} rotation={[Math.PI / 2, 0, 0]} material={lightsOn ? M.emissive() : M.appliance()}><circleGeometry args={[0.05, 20]} /></mesh>)}
    {lightsOn && lit.map(([x, y], i) => <pointLight key={`p${i}`} position={[x / 1000, hAt(x, y) / 1000 - 0.15, -y / 1000]} intensity={4.5} distance={4.5} decay={2} color="#ffe6c4" />)}
    {shell.structures.map(st => {
      const solid = st.kind === 'COLUMN' || st.kind === 'PILLAR'
      const cs: Pt[] = [[st.x, st.y], [st.x + st.length, st.y], [st.x, st.y + st.width], [st.x + st.length, st.y + st.width]]
      const topH = Math.max(...cs.map(([x, y]) => hAt(x, y))), low = Math.min(...cs.map(([x, y]) => hAt(x, y)))
      const y0 = solid ? 0 : low - st.depth, h = topH - y0
      return <mesh key={st.id} position={[(st.x + st.length / 2) / 1000, (y0 + h / 2) / 1000, -(st.y + st.width / 2) / 1000]} castShadow receiveShadow material={M.wall('#ece7df')}>
        <boxGeometry args={[st.length / 1000, h / 1000, st.width / 1000]} /></mesh>
    })}
  </group>
}

function Ceiling({ L, W, H, lightsOn }: { L: number; W: number; H: number; lightsOn: boolean }) {
  const ref = useRef<THREE.Mesh>(null)
  useFrame(({ camera }) => { if (ref.current) ref.current.visible = camera.position.y < H - 0.05 })   // only seen from inside (eye level)
  const nx = Math.max(1, Math.round(L / 1.3)), nz = Math.max(1, Math.round(W / 1.3))
  const spots: [number, number][] = []
  for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) spots.push([L * (i + 0.5) / nx, -W * (j + 0.5) / nz])
  const lit = spots.length <= 6 ? spots : spots.filter((_, k) => k % Math.ceil(spots.length / 6) === 0)
  return <group>
    <mesh ref={ref} rotation={[Math.PI / 2, 0, 0]} position={[L / 2, H, -W / 2]} material={M.ceiling()}><planeGeometry args={[L, W]} /></mesh>
    {spots.map(([x, z], i) => <mesh key={i} position={[x, H - 0.005, z]} rotation={[Math.PI / 2, 0, 0]} material={lightsOn ? M.emissive() : M.appliance()}><circleGeometry args={[0.05, 20]} /></mesh>)}
    {lightsOn && lit.map(([x, z], i) => <pointLight key={`p${i}`} position={[x, H - 0.15, z]} intensity={4.5} distance={4.5} decay={2} color="#ffe6c4" />)}
  </group>
}

/** Sunlight + sky + soft bounce light + ground contact shadows. */
export function Lighting({ L, W, H, hour }: { L: number; W: number; H: number; hour: number }) {
  const night = isNight(hour), dir = sunDirection(hour)
  const target = useMemo(() => { const o = new THREE.Object3D(); o.position.set(L / 2, 0, -W / 2); return o }, [L, W])
  const sunPos: [number, number, number] = [L / 2 + dir.x * 25, dir.y * 25, -W / 2 + dir.z * 25]
  const warm = new THREE.Color().setHSL(0.09, 0.8, 0.5 + 0.45 * Math.min(1, dir.y * 2.2))
  const span = Math.max(L, W) * 1.2 + 2
  return <>
    {!night && <Sky distance={4500} sunPosition={[dir.x, dir.y, dir.z]} turbidity={6} rayleigh={1.2} mieCoefficient={0.006} mieDirectionalG={0.85} />}
    {night && <color attach="background" args={['#0b1020']} />}
    <primitive object={target} />
    {!night && <directionalLight position={sunPos} target={target} intensity={3.4 * Math.min(1, 0.35 + dir.y * 1.6)} color={warm} castShadow
      shadow-mapSize-width={2048} shadow-mapSize-height={2048} shadow-bias={-0.0004} shadow-normalBias={0.02} shadow-radius={4}
      shadow-camera-left={-span} shadow-camera-right={span} shadow-camera-top={span} shadow-camera-bottom={-span} shadow-camera-near={1} shadow-camera-far={60} />}
    <hemisphereLight args={[night ? '#1e2a44' : '#e3ecf7', night ? '#3a3226' : '#d8c6ad', night ? 0.12 : 0.45]} />
    <ambientLight intensity={night ? 0.04 : 0.1} color="#fff4e6" />{/* stands in for light bounced off floor and walls */}
    <Environment resolution={128} frames={1}>
      <Lightformer form="rect" intensity={night ? 0.15 : 0.55} color={night ? '#334' : '#fff8ee'} position={[0, 6, 0]} rotation={[Math.PI / 2, 0, 0]} scale={[12, 12, 1]} />
      <Lightformer form="rect" intensity={night ? 0.04 : 0.45} color="#cfe0ff" position={[8, 3, 0]} rotation={[0, -Math.PI / 2, 0]} scale={[10, 4, 1]} />
      <Lightformer form="rect" intensity={night ? 0.04 : 0.35} color="#ffe2c2" position={[-8, 3, 0]} rotation={[0, Math.PI / 2, 0]} scale={[10, 4, 1]} />
    </Environment>
    <ContactShadows position={[L / 2, 0.002, -W / 2]} scale={[L * 1.05, W * 1.05]} opacity={0.45} blur={2.4} far={1.2} resolution={512} frames={1} />
  </>
}

/** The room itself: floor, walls with openings, skirting, ceiling + downlights. Wet rooms get tiles. */
export function RealisticRoom({ L, W, H, ops, hour, lightsOn, wet, finishes, ground = true, shell }: { L: number; W: number; H: number; ops: Opening3[]; hour: number; lightsOn: boolean; wet: boolean
  finishes?: Finishes | null; ground?: boolean; shell?: Shell | null }) {
  const floor = floorMaterial(finishes, L, W, wet)
  const lit = lightsOn || isNight(hour)
  const odd = !!shell && (shell.outline.length > 4 || shell.ceiling.type !== 'FLAT' || shell.structures.length > 0)
  if (odd && shell) return <ShellRoom shell={shell} ops={ops} lit={lit} wet={wet} finishes={finishes} ground={ground} floor={floor} day={daylight(hour)} />
  return <group>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2, 0, -W / 2]} receiveShadow material={floor}><planeGeometry args={[L, W]} /></mesh>
    {ground && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2, -0.01, -W / 2]} receiveShadow material={M.laminate('#d9d4cb')}><planeGeometry args={[L + 12, W + 12]} /></mesh>}
    {(['S', 'N', 'W', 'E'] as const).map(w => <WallWithOpenings key={w} wall={w} L={L} W={W} H={H} ops={ops} cutaway tiles={wet && !finishes?.walls} colour={finishes?.walls?.colour} daylight={daylight(hour)} />)}
    <Ceiling L={L} W={W} H={H} lightsOn={lit} />
    {finishes && <ConceptDecor f={finishes} L={L} W={W} H={H} ops={ops} lightsOn={lit} />}
  </group>
}

/** M41: a room that isn't a plain box — floor and walls along the outline, ceiling following its profile, beams and columns. */
function ShellRoom({ shell, ops, lit, wet, finishes, ground, floor, day }: { shell: Shell; ops: Opening3[]; lit: boolean; wet: boolean; finishes?: Finishes | null; ground: boolean; floor: THREE.Material; day: number }) {
  const { L, W, H, outline, ceiling } = shell
  const top = useMemo(() => (x: number, y: number) => ceilingAt(ceiling, H, L, W, x, y), [JSON.stringify(ceiling), H, L, W]) // eslint-disable-line react-hooks/exhaustive-deps
  const floorGeom = useMemo(() => {
    const g = new THREE.ShapeGeometry(new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x / 1000, y / 1000))))
    const pos = g.attributes.position as THREE.BufferAttribute, uv = g.attributes.uv as THREE.BufferAttribute
    for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i) * 1000 / L, pos.getY(i) * 1000 / W)       // 0..1 over the L × W box, like the plain floor
    uv.needsUpdate = true; return g
  }, [JSON.stringify(outline), L, W]) // eslint-disable-line react-hooks/exhaustive-deps
  const edges = outline.map((p, i) => [p, outline[(i + 1) % outline.length]] as [Pt, Pt])
  return <group>
    <mesh geometry={floorGeom} rotation={[-Math.PI / 2, 0, 0]} receiveShadow material={floor} />
    {ground && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2000, -0.01, -W / 2000]} receiveShadow material={M.laminate('#d9d4cb')}><planeGeometry args={[L / 1000 + 12, W / 1000 + 12]} /></mesh>}
    {edges.map(([p0, p1], i) => <EdgeWall key={i} p0={p0} p1={p1} top={top} ops={edgeOps(p0, p1, ops, L, W)} cutaway tiles={wet && !finishes?.walls} colour={finishes?.walls?.colour} daylight={day} />)}
    <ShellCeiling shell={shell} lightsOn={lit} />
    {finishes && <ConceptDecor f={finishes} L={L / 1000} W={W / 1000} H={shell.ceiling_min / 1000} ops={ops} lightsOn={lit} />}
  </group>
}

/** Live 'realistic' look: ambient occlusion (soft contact shadows in corners, under and behind furniture — what makes 3D stop looking
 *  like toy blocks), gentle bloom on lamps / LED strips, anti-aliasing and filmic (ACES) tone mapping, like a camera exposes a room. */
export function RealisticFx() {
  const { gl } = useThree()
  const software = useMemo(() => {                                       // no GPU (software WebGL): the effects would freeze the page — skip them
    const c = gl.getContext(), e = c.getExtension('WEBGL_debug_renderer_info')
    return /swiftshader|llvmpipe|software|microsoft basic render/i.test(e ? String(c.getParameter(e.UNMASKED_RENDERER_WEBGL)) : '')
  }, [gl])
  if (software) return null
  return <EffectComposer multisampling={0} enableNormalPass={false}>
    <N8AO aoRadius={0.45} distanceFalloff={0.6} intensity={2.6} quality="medium" halfRes color="#2a2016" />
    <Bloom luminanceThreshold={1.0} luminanceSmoothing={0.2} intensity={0.35} mipmapBlur />
    <SMAA />
    <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
  </EffectComposer>
}

/** Photo render: the scene is PATH TRACED in the browser (three-gpu-pathtracer, free) — light really bounces between floor, walls and
 *  furniture, soft shadows, daylight through the windows from a sky, glass, gloss and fabric sheen. Each frame adds samples; the image
 *  gets cleaner until `samples` is reached, then stays (and can be saved as a render). Mount it only while rendering; the camera must hold still. */
export function PhotoRender({ samples, scale = 1, onProgress, onDone }: { samples: number; scale?: number; onProgress: (n: number) => void; onDone: () => void }) {
  const { gl, scene, camera, invalidate } = useThree()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pt = useRef<any>(null); const done = useRef(false)
  useEffect(() => {
    let off = false; const hidden: THREE.Object3D[] = []
    scene.traverse(o => {                                               // helpers that aren't part of the room: invisible hit boxes, flags, sky dome, contact-shadow plane
      const m = (o as THREE.Mesh).material as (THREE.Material & { isShaderMaterial?: boolean; isMeshBasicMaterial?: boolean }) | undefined
      const helper = o.userData?.noPhoto || (m && !Array.isArray(m) && (m.isShaderMaterial || m.isMeshBasicMaterial || (m.transparent && m.opacity < 0.05)))
      if (o.visible && helper) { o.visible = false; hidden.push(o) }
    })
    const env = scene.environment, bg = scene.background
    import('three-gpu-pathtracer').then(({ WebGLPathTracer, GradientEquirectTexture, DenoiseMaterial }) => {
      if (off) return
      const sky = new GradientEquirectTexture(256); sky.topColor.set('#9fc3ee'); sky.bottomColor.set('#e8dcc8'); sky.exponent = 0.6; sky.update()
      scene.environment = sky; scene.background = sky
      const p = new WebGLPathTracer(gl)
      p.tiles.set(2, 2); p.renderDelay = 0; p.minSamples = 1; p.fadeDuration = 0; p.dynamicLowRes = false
      p.renderScale = Math.min(1, scale / gl.getPixelRatio()); p.filterGlossyFactor = 0.5; p.multipleImportanceSampling = true
      p.bounces = 5; p.transmissiveBounces = 3                          // enough for interiors (walls → floor → furniture), far cheaper than the default
      // edge-aware denoise on the way to the screen: keeps edges, smooths the grain of the early samples
      const den = new DenoiseMaterial({ map: null, blending: THREE.NoBlending, premultipliedAlpha: gl.getContextAttributes().premultipliedAlpha })
      den.sigma = 5; den.kSigma = 2; den.threshold = 0.45           // strong enough for draft sample counts; edges still kept
      p.renderToCanvasCallback = (target: THREE.WebGLRenderTarget, renderer: THREE.WebGLRenderer, quad: { material: THREE.Material; render: (r: THREE.WebGLRenderer) => void }) => {
        (den as unknown as { map: THREE.Texture }).map = target.texture
        const old = quad.material, ac = renderer.autoClear; quad.material = den; renderer.autoClear = false; quad.render(renderer); renderer.autoClear = ac; quad.material = old
      }
      p.setScene(scene, camera); pt.current = p
    })
    return () => { off = true; pt.current?.dispose(); pt.current = null; hidden.forEach(o => { o.visible = true }); scene.environment = env; scene.background = bg }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useFrame(() => {
    const p = pt.current
    if (!p) { gl.render(scene, camera); invalidate(); return }           // the canvas only redraws on demand: keep frames coming while rendering
    if (p.samples < samples) { p.renderSample(); onProgress(Math.floor(p.samples)); invalidate() }
    else if (!done.current) { done.current = true; onDone() }
  }, 1)
  return null
}
