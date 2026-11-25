'use client'
// Procedural furniture models for the 3D views — built from the item's real catalogue size (metres here), so what you see is exactly the
// footprint the server validates. Local frame: origin at the footprint centre on the floor, X = length (along the wall), Z = depth with the
// FRONT at +Z, Y up. Each model picks its look from the category; the object's colour (editor) tints the main finish.
import { RoundedBox } from '@react-three/drei'
import type * as THREE from 'three'
import { M, finish } from './materials'

type V3 = [number, number, number]
interface P { l: number; d: number; h: number; colour?: string | null; name?: string }

function B({ p, s, m, r }: { p: V3; s: V3; m: THREE.Material; r?: number }) {
  if (r) return <RoundedBox args={s} radius={Math.min(r, s[0] / 2.2, s[1] / 2.2, s[2] / 2.2)} smoothness={3} position={p} castShadow receiveShadow material={m} />
  return <mesh position={p} castShadow receiveShadow material={m}><boxGeometry args={s} /></mesh>
}
function C({ p, r, h, m, seg = 20 }: { p: V3; r: number; h: number; m: THREE.Material; seg?: number }) {
  return <mesh position={p} castShadow receiveShadow material={m}><cylinderGeometry args={[r, r, h, seg]} /></mesh>
}
const legs4 = (l: number, d: number, h: number, inset: number, r: number, m: THREE.Material) =>
  [[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([sx, sz], i) => <C key={i} p={[sx * (l / 2 - inset), h / 2, sz * (d / 2 - inset)]} r={r} h={h} m={m} />)

/** Carcass with shutters (wardrobe, kitchen units, TV unit, vanity …): body, door split every ~450 mm, vertical bar handles, optional plinth. */
function Cabinet({ l, d, h, body, front, plinth = 0, handle = 'bar', doors, drawers = 0, top }: { l: number; d: number; h: number; body: THREE.Material; front: THREE.Material
  plinth?: number; handle?: 'bar' | 'bottom' | 'none'; doors?: number; drawers?: number; top?: THREE.Material }) {
  const ch = h - plinth, n = drawers ? 0 : doors ?? Math.max(1, Math.round(l / 0.45)), gap = 0.003
  const parts = [<B key="body" p={[0, plinth + ch / 2, -0.009]} s={[l, ch, d - 0.018]} m={body} />]
  if (plinth) parts.push(<B key="plinth" p={[0, plinth / 2, -0.04]} s={[l - 0.02, plinth, d - 0.08]} m={M.black()} />)
  if (drawers) {
    const dh = ch / drawers
    for (let k = 0; k < drawers; k++) {
      parts.push(<B key={`dr${k}`} p={[0, plinth + dh * k + dh / 2, d / 2 - 0.009]} s={[l - gap * 2, dh - gap * 2, 0.018]} m={front} />)
      parts.push(<B key={`dh${k}`} p={[0, plinth + dh * (k + 1) - 0.05, d / 2 + 0.012]} s={[Math.min(0.3, l * 0.4), 0.012, 0.02]} m={M.metal()} />)
    }
  } else for (let k = 0; k < n; k++) {
    const w = l / n, x = -l / 2 + w * k + w / 2
    parts.push(<B key={`d${k}`} p={[x, plinth + ch / 2, d / 2 - 0.009]} s={[w - gap * 2, ch - gap * 2, 0.018]} m={front} />)
    if (handle !== 'none') {
      const hx = x + (k % 2 === 0 ? w / 2 - 0.04 : -w / 2 + 0.04) * (n === 1 ? 1 : 1)
      const hh = handle === 'bottom' ? 0.012 : Math.min(0.25, ch * 0.25)
      const hy = handle === 'bottom' ? plinth + 0.04 : plinth + (ch > 1.2 ? ch * 0.5 : ch - 0.12)
      parts.push(<B key={`h${k}`} p={[handle === 'bottom' ? x : hx, hy, d / 2 + 0.012]} s={handle === 'bottom' ? [Math.min(0.3, w * 0.6), hh, 0.02] : [0.012, hh, 0.02]} m={M.metal()} />)
    }
  }
  if (top) parts.push(<B key="top" p={[0, h + 0.02, 0.01]} s={[l, 0.04, d + 0.02]} m={top} />)
  return <>{parts}</>
}

// ── models ───────────────────────────────────────────────────────────────────
function Bed({ l, d, h, colour }: P) {
  const frame = finish('wood', colour, '#6b4226'), base = 0.32, mat = 0.22
  return <>
    <B p={[0, base / 2, 0.02]} s={[l, base, d - 0.04]} m={frame} r={0.02} />
    <B p={[0, base + mat / 2, 0.04]} s={[l - 0.06, mat, d - 0.12]} m={M.linen()} r={0.06} />
    <B p={[0, base + mat + 0.03, 0.25]} s={[l - 0.04, 0.05, d * 0.62]} m={M.fabric('#c9b79c')} r={0.025} />
    {[-1, 1].map(s => <B key={s} p={[s * l / 4.2, base + mat + 0.07, -d / 2 + 0.3]} s={[l / 2.4, 0.13, 0.42]} m={M.linen()} r={0.06} />)}
    <B p={[0, Math.max(h, 0.9) / 2, -d / 2 + 0.04]} s={[l + 0.04, Math.max(h, 0.9), 0.08]} m={M.fabric(colour ?? '#7c6f64')} r={0.03} />
  </>
}
function Wardrobe({ l, d, h, colour }: P) { return <Cabinet l={l} d={d} h={h} body={M.laminate('#efe9df')} front={finish('wood', colour, '#7a4a24')} /> }
function Sofa({ l, d, h, colour }: P) {
  const f = M.fabric(colour ?? '#7d8794'), seatH = 0.42, arm = 0.18, n = Math.max(1, Math.round((l - 2 * arm) / 0.7))
  const cw = (l - 2 * arm) / n
  return <>
    <B p={[0, 0.2, 0]} s={[l, 0.22, d]} m={f} r={0.04} />
    {[-1, 1].map(s => <B key={s} p={[s * (l / 2 - arm / 2), 0.31, 0]} s={[arm, 0.62, d]} m={f} r={0.06} />)}
    <B p={[0, Math.max(h, 0.75) / 2 + 0.05, -d / 2 + 0.11]} s={[l - 0.02, Math.max(h, 0.75) - 0.1, 0.22]} m={f} r={0.07} />
    {Array.from({ length: n }, (_, k) => <B key={k} p={[-l / 2 + arm + cw * k + cw / 2, seatH - 0.05, 0.07]} s={[cw - 0.02, 0.16, d - 0.3]} m={f} r={0.06} />)}
    {Array.from({ length: n }, (_, k) => <B key={`b${k}`} p={[-l / 2 + arm + cw * k + cw / 2, seatH + 0.22, -d / 2 + 0.3]} s={[cw - 0.06, 0.38, 0.16]} m={f} r={0.07} />)}
    {legs4(l, d, 0.08, 0.06, 0.018, M.black())}
  </>
}
function Armchair({ l, d, h, colour }: P) { return <Sofa l={l} d={d} h={h} colour={colour ?? '#2f6f73'} /> }
function Table({ l, d, h, colour, round = false }: P & { round?: boolean }) {
  const top = finish('wood', colour, '#6b4226')
  return <>
    {round ? <C p={[0, h - 0.02, 0]} r={Math.min(l, d) / 2} h={0.04} m={top} seg={40} /> : <B p={[0, h - 0.02, 0]} s={[l, 0.04, d]} m={top} r={0.008} />}
    {legs4(l, d, h - 0.04, 0.07, 0.022, top)}
  </>
}
function CoffeeTable({ l, d, h, colour }: P) {
  const top = finish('wood', colour, '#9a6b3f')
  return <><B p={[0, h - 0.025, 0]} s={[l, 0.05, d]} m={top} r={0.015} /><B p={[0, 0.1, 0]} s={[l - 0.1, 0.02, d - 0.1]} m={top} />{legs4(l, d, h - 0.05, 0.05, 0.02, M.black())}</>
}
function Chair({ l, d, h, colour }: P) {
  const w = finish('wood', colour, '#6b4226'), seat = 0.46
  return <>
    <B p={[0, seat, 0]} s={[l, 0.04, d]} m={w} r={0.01} />
    <B p={[0, seat + 0.03, 0.01]} s={[l - 0.04, 0.04, d - 0.06]} m={M.fabric('#b9ad9c')} r={0.015} />
    {legs4(l, d, seat, 0.03, 0.016, w)}
    <B p={[0, (seat + Math.max(h, 0.8)) / 2 + 0.02, -d / 2 + 0.025]} s={[l - 0.02, Math.max(h, 0.8) - seat, 0.03]} m={w} r={0.01} />
  </>
}
function OfficeChair({ l, d }: P) {
  return <>
    <C p={[0, 0.25, 0]} r={0.025} h={0.4} m={M.chrome()} />
    {[0, 1, 2, 3, 4].map(k => <B key={k} p={[Math.cos(k * 1.2566) * 0.2, 0.04, Math.sin(k * 1.2566) * 0.2]} s={[0.05, 0.03, 0.05]} m={M.black()} />)}
    <C p={[0, 0.05, 0]} r={0.28} h={0.02} m={M.black()} seg={5} />
    <B p={[0, 0.48, 0]} s={[l * 0.85, 0.08, d * 0.8]} m={M.fabric('#2b2f36')} r={0.04} />
    <B p={[0, 0.85, -d * 0.35]} s={[l * 0.8, 0.6, 0.07]} m={M.fabric('#2b2f36')} r={0.04} />
  </>
}
function TvUnit({ l, d, h, colour }: P) {
  return <>
    <Cabinet l={l} d={d} h={h} body={finish('wood', colour, '#5b3a22')} front={finish('wood', colour, '#5b3a22')} handle="none" doors={Math.max(2, Math.round(l / 0.6))} />
    <B p={[0, h + 0.38, -d / 2 + 0.06]} s={[Math.min(1.45, l * 0.8), 0.82, 0.04]} m={M.screen()} />
    <B p={[0, h + 0.02, -d / 2 + 0.12]} s={[0.3, 0.04, 0.18]} m={M.black()} />
  </>
}
function Desk({ l, d, h, colour }: P) {
  const w = finish('wood', colour, '#8a6a4a')
  return <>
    <B p={[0, h - 0.02, 0]} s={[l, 0.04, d]} m={w} r={0.006} />
    <B p={[-l / 2 + 0.22, (h - 0.04) / 2, 0]} s={[0.42, h - 0.04, d - 0.04]} m={M.laminate('#efe9df')} />
    <B p={[-l / 2 + 0.22, h * 0.75, d / 2 - 0.01]} s={[0.4, 0.15, 0.02]} m={w} />
    {[[1, -1], [1, 1]].map(([sx, sz], i) => <C key={i} p={[sx * (l / 2 - 0.05), (h - 0.04) / 2, sz * (d / 2 - 0.05)]} r={0.018} h={h - 0.04} m={M.black()} />)}
    <B p={[0.1, h + 0.12, -d / 2 + 0.15]} s={[0.55, 0.32, 0.02]} m={M.screen()} />
  </>
}
function Shelves({ l, d, h, colour }: P) {
  const w = finish('wood', colour, '#7a4a24'), n = Math.max(2, Math.round(h / 0.38))
  const books = ['#8c3b2f', '#2f4f6f', '#c7a24a', '#4a6b3f', '#6b4a7a', '#d9d4c7']
  return <>
    {[-1, 1].map(s => <B key={s} p={[s * (l / 2 - 0.009), h / 2, 0]} s={[0.018, h, d]} m={w} />)}
    <B p={[0, h / 2, -d / 2 + 0.004]} s={[l, h, 0.008]} m={w} />
    {Array.from({ length: n + 1 }, (_, k) => <B key={k} p={[0, (h - 0.018) * k / n + 0.009, 0]} s={[l - 0.036, 0.018, d]} m={w} />)}
    {Array.from({ length: n - 1 }, (_, k) => Array.from({ length: 9 }, (_, j) => {
      const bh = 0.2 + ((j * 7 + k * 3) % 5) * 0.025
      return <B key={`${k}-${j}`} p={[-l / 2 + 0.06 + j * (l - 0.12) / 9, (h - 0.018) * (k + 1) / n + 0.018 + bh / 2, 0.01]} s={[(l - 0.14) / 10, bh, d * 0.7]} m={M.laminate(books[(j + k) % books.length])} />
    }))}
  </>
}
function Kitchen({ l, d, h, colour, kind }: P & { kind: 'base' | 'tall' | 'wall' | 'sink' | 'hob' | 'filler' }) {
  const front = M.laminate(colour ?? '#e8e2d6'), body = M.laminate('#f2efe9')
  if (kind === 'filler') return <B p={[0, h / 2, 0]} s={[l, h, d]} m={front} />
  if (kind === 'wall') return <Cabinet l={l} d={d} h={h} body={body} front={front} handle="bottom" />
  if (kind === 'tall') return <Cabinet l={l} d={d} h={h} body={body} front={front} doors={1} />
  const counter = M.quartz(), plinth = 0.1
  return <>
    <Cabinet l={l} d={d} h={h - 0.04} body={body} front={front} plinth={plinth} drawers={kind === 'hob' ? 3 : 0} top={counter} />
    {kind === 'sink' && <>
      <B p={[0, h - 0.06, 0.02]} s={[Math.min(0.6, l - 0.15), 0.06, d * 0.7]} m={M.chrome()} />
      <B p={[0, h - 0.02, 0.02]} s={[Math.min(0.55, l - 0.2), 0.012, d * 0.62]} m={M.screen()} />
      <C p={[0, h + 0.12, -d / 2 + 0.08]} r={0.012} h={0.24} m={M.chrome()} />
      <B p={[0, h + 0.24, -d / 2 + 0.15]} s={[0.02, 0.02, 0.16]} m={M.chrome()} />
    </>}
    {kind === 'hob' && <>
      <B p={[0, h + 0.005, 0.02]} s={[Math.min(0.75, l - 0.1), 0.01, d * 0.85]} m={M.screen()} />
      {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([sx, sz], i) => <C key={i} p={[sx * Math.min(0.17, l / 5), h + 0.012, 0.02 + sz * d * 0.18]} r={0.08} h={0.004} m={M.black()} seg={32} />)}
      <B p={[0, 2.05, -d / 2 + 0.25]} s={[Math.min(0.9, l), 0.12, 0.5]} m={M.chrome()} />
      <B p={[0, 2.4, -d / 2 + 0.15]} s={[0.3, 0.6, 0.25]} m={M.chrome()} />
    </>}
  </>
}
function WC({ l, d, colour }: P) {
  return <>
    <B p={[0, 0.2, -d / 2 + 0.08]} s={[l * 0.9, 0.4, 0.16]} m={M.ceramic()} r={0.05} />
    <mesh position={[0, 0.25, 0.06]} castShadow receiveShadow material={M.ceramic()} scale={[l / 2 * 0.95, 0.15, d / 2 * 0.82]}><sphereGeometry args={[1, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2]} /></mesh>
    <B p={[0, 0.405, 0.06]} s={[l * 0.9, 0.02, d * 0.75]} m={colour ? M.laminate(colour) : M.ceramic()} r={0.01} />
    <B p={[0, 1.0, -d / 2 + 0.01]} s={[0.22, 0.14, 0.02]} m={M.chrome()} />
  </>
}
function Vanity({ l, d, h, colour }: P) {
  return <>
    <Cabinet l={l} d={d} h={h - 0.04} body={M.laminate('#f2efe9')} front={finish('wood', colour, '#7a5a3a')} plinth={0.1} handle="none" top={M.quartz()} />
    <mesh position={[0, h + 0.05, 0.03]} castShadow receiveShadow material={M.ceramic()} scale={[Math.min(0.24, l / 3), 0.06, Math.min(0.18, d / 3)]}><sphereGeometry args={[1, 28, 14]} /></mesh>
    <C p={[0, h + 0.13, -d / 2 + 0.07]} r={0.012} h={0.18} m={M.chrome()} />
  </>
}
function Shower({ l, d, h }: P) {
  return <>
    <B p={[0, 0.03, 0]} s={[l, 0.06, d]} m={M.ceramic()} />
    <B p={[0, h / 2, d / 2 - 0.005]} s={[l, h, 0.01]} m={M.glass()} />
    <B p={[l / 2 - 0.005, h / 2, 0]} s={[0.01, h, d]} m={M.glass()} />
    <B p={[0, h, d / 2]} s={[l, 0.02, 0.02]} m={M.chrome()} /><B p={[l / 2, h, 0]} s={[0.02, 0.02, d]} m={M.chrome()} />
    <C p={[-l / 2 + 0.15, h - 0.6, -d / 2 + 0.03]} r={0.012} h={1.2} m={M.chrome()} />
    <C p={[-l / 2 + 0.15, h - 0.02, -d / 2 + 0.15]} r={0.1} h={0.01} m={M.chrome()} />
  </>
}
function MirrorCabinet({ l, d, h, colour }: P) {
  return <><B p={[0, h / 2, -0.01]} s={[l, h, d - 0.02]} m={M.laminate(colour ?? '#f2efe9')} /><B p={[0, h / 2, d / 2 - 0.004]} s={[l - 0.02, h - 0.02, 0.006]} m={M.mirror()} />
    <B p={[0, -0.02, d / 2 - 0.02]} s={[l - 0.06, 0.012, 0.03]} m={M.emissive()} /></>
}
function Washer({ l, d, h }: P) {
  return <>
    <B p={[0, h / 2, 0]} s={[l, h, d]} m={M.appliance()} r={0.02} />
    <mesh position={[0, h * 0.45, d / 2 + 0.005]} rotation={[Math.PI / 2, 0, 0]} castShadow material={M.chrome()}><torusGeometry args={[Math.min(l, h) * 0.26, 0.025, 12, 40]} /></mesh>
    <mesh position={[0, h * 0.45, d / 2 + 0.002]} rotation={[Math.PI / 2, 0, 0]} material={M.glass()}><cylinderGeometry args={[Math.min(l, h) * 0.24, Math.min(l, h) * 0.24, 0.01, 40]} /></mesh>
    <B p={[0, h - 0.07, d / 2 + 0.003]} s={[l - 0.04, 0.1, 0.006]} m={M.black()} />
  </>
}
function Dresser({ l, d, h, colour }: P) {
  return <><Cabinet l={l} d={d} h={h} body={finish('wood', colour, '#7a4a24')} front={finish('wood', colour, '#7a4a24')} drawers={3} />
    <B p={[0, h + 0.45, -d / 2 + 0.02]} s={[Math.min(0.7, l * 0.6), 0.8, 0.02]} m={M.mirror()} /></>
}
export function Plant({ h }: { h: number }) {
  return <><C p={[0, 0.15, 0]} r={0.14} h={0.3} m={M.pot()} />{[0, 1, 2, 3, 4, 5].map(k => <mesh key={k} position={[Math.cos(k) * 0.1, 0.3 + h * 0.3 + (k % 3) * 0.08, Math.sin(k) * 0.1]} castShadow material={M.leaf()}><sphereGeometry args={[0.13 + (k % 2) * 0.04, 10, 8]} /></mesh>)}</>
}

function Pooja({ l, d, h, colour }: P) {
  const w = finish('wood', colour, '#8a5a2b'), base = Math.min(0.85, h * 0.45)
  return <>
    <Cabinet l={l} d={d} h={base} body={w} front={w} handle="bar" />
    <B p={[0, base + 0.02, 0]} s={[l, 0.04, d]} m={M.quartz()} />
    <B p={[0, (base + h) / 2 + 0.02, -d / 2 + 0.03]} s={[l - 0.04, h - base - 0.04, 0.03]} m={M.wood('#6b3f1c')} />
    {[-1, 1].map(s => <B key={s} p={[s * (l / 2 - 0.03), (base + h) / 2, 0]} s={[0.06, h - base, d]} m={w} />)}
    <B p={[0, h - 0.04, 0]} s={[l, 0.08, d]} m={w} />
    <mesh position={[0, h - 0.22, -d / 2 + 0.12]} castShadow material={M.laminate('#c9a227')}><sphereGeometry args={[Math.min(0.14, l / 6), 20, 10, 0, Math.PI * 2, 0, Math.PI / 2]} /></mesh>
    <C p={[0, base + 0.1, 0.05]} r={0.03} h={0.04} m={M.laminate('#c9a227')} />
    <mesh position={[0, base + 0.15, 0.05]} material={M.emissive()}><sphereGeometry args={[0.012, 8, 8]} /></mesh>
  </>
}

/** Pick a model from the category (catalogue categories, case-insensitive); unknown categories get a generic cabinet. */
export function FurnitureModel({ category, l, d, h, colour, name }: P & { category: string }) {
  const c = (category || '').toLowerCase(), p = { l, d, h, colour, name }
  if (c === 'bed') return <Bed {...p} />
  if (c === 'wardrobe') return <Wardrobe {...p} />
  if (c === 'sofa') return <Sofa {...p} />
  if (['armchair', 'accent chair', 'lounge chair'].includes(c)) return <Armchair {...p} />
  if (['coffee table', 'centre table', 'center table'].includes(c)) return <CoffeeTable {...p} />
  if (['bedside table', 'nightstand', 'side table'].includes(c)) return <Cabinet l={l} d={d} h={h} body={finish('wood', colour, '#7a4a24')} front={finish('wood', colour, '#7a4a24')} drawers={2} />
  if (['dining table', 'dining'].includes(c)) return <Table {...p} round={Math.abs(l - d) < 0.05} />
  if (['dining chair', 'chair', 'study chair'].includes(c)) return <Chair {...p} />
  if (c === 'office chair') return <OfficeChair {...p} />
  if (c === 'tv unit') return <TvUnit {...p} />
  if (['study', 'desk'].includes(c)) return <Desk {...p} />
  if (['bookshelf', 'bookcase', 'storage'].includes(c)) return <Shelves {...p} />
  if (['crockery', 'crockery unit'].includes(c)) return <Cabinet l={l} d={d} h={h} body={finish('wood', colour, '#5b3a22')} front={M.glass()} handle="bar" />
  if (c === 'dresser') return <Dresser {...p} />
  if (c === 'kitchen') return <Kitchen {...p} kind={h >= 1.8 ? 'tall' : 'base'} />
  if (c === 'kitchen sink') return <Kitchen {...p} kind="sink" />
  if (c === 'kitchen hob') return <Kitchen {...p} kind="hob" />
  if (c === 'kitchen wall' || c === 'utility wall') return <Kitchen {...p} kind="wall" />
  if (c === 'kitchen filler') return <Kitchen {...p} kind="filler" />
  if (['wc', 'toilet', 'water closet'].includes(c)) return <WC {...p} />
  if (['vanity', 'vanity unit', 'washbasin', 'wash basin'].includes(c)) return <Vanity {...p} />
  if (['shower enclosure', 'shower'].includes(c)) return <Shower {...p} />
  if (['mirror cabinet', 'bathroom mirror'].includes(c)) return <MirrorCabinet {...p} />
  if (c === 'washing machine') return <Washer {...p} />
  if (c === 'utility base' || c === 'utility cabinet') return <Kitchen {...p} kind="base" />
  if (c === 'utility tall' || c === 'linen cabinet' || c === 'broom cabinet') return <Cabinet l={l} d={d} h={h} body={M.laminate('#f2efe9')} front={M.laminate(colour ?? '#e8e2d6')} doors={1} />
  if (c === 'plant' || c === 'planter') return <Plant h={h} />
  if (c === 'outdoor chair') return <Armchair {...p} colour={colour ?? '#b08d57'} />
  if (c === 'outdoor table') return <CoffeeTable {...p} colour={colour ?? '#8a6a44'} />
  if (c === 'shoe rack') return <Cabinet l={l} d={d} h={h} body={finish('wood', colour, '#7a5a3a')} front={finish('wood', colour, '#7a5a3a')} doors={Math.max(2, Math.round(l / 0.45))} />
  if (c === 'console table' || c === 'console') return <><Table {...p} /><B p={[0, h + 0.45, -d / 2 + 0.02]} s={[Math.min(0.7, l * 0.6), 0.8, 0.02]} m={M.mirror()} /></>
  if (c === 'pooja unit' || c === 'mandir') return <Pooja {...p} />
  return <Cabinet l={l} d={d} h={Math.max(h, 0.05)} body={M.laminate('#f2efe9')} front={finish('laminate', colour, '#d9d2c5')} />
}
