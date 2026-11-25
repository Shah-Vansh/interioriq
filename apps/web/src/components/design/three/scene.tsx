'use client'
// Realistic room for the 3D views: plank floor (tiles in wet rooms), plaster walls with real door/window openings, glass, a door leaf,
// skirting, ceiling with downlights, sun placed by time of day (India: sun in the south at noon), sky, soft shadows, bounce light.
// Walls between the camera and the room hide themselves (dollhouse cut-away) so the furniture is always visible.
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { ContactShadows, Environment, Lightformer, Sky } from '@react-three/drei'
import * as THREE from 'three'
import { M } from './materials'
import { ConceptDecor, Finishes, floorMaterial } from './finishes'

export interface Opening3 { id: string; kind: string; wall: string; offset: number; width: number; height: number; sill: number }
const WALL_T = 0.12

/** Sun direction from local time: rises in the east, highest in the south at noon, sets in the west. North = −Z, east = +X. */
export function sunDirection(hour: number): THREE.Vector3 {
  const t = Math.min(1, Math.max(0, (hour - 6) / 12))
  const az = (90 + 180 * t) * Math.PI / 180                // 90° east → 180° south → 270° west
  const el = Math.max(2, 72 * Math.sin(Math.PI * t)) * Math.PI / 180
  return new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize()
}
export const isNight = (hour: number) => hour < 6.3 || hour > 18.2

/** Where a person would stand to look at the room (mm in, metres out): just inside the door if there is one, else the first free corner.
 *  A spot inside a piece of furniture (lower than eye height) is never used. */
export function eyePoint(L: number, W: number, ops: Opening3[], objs: { x: number; y: number; length: number; width: number; z?: number }[]): { pos: [number, number, number]; target: [number, number, number] } {
  const free = (x: number, y: number) => x > 150 && y > 150 && x < L - 150 && y < W - 150 &&
    !objs.some(o => (o.z ?? 0) < 1600 && x > o.x - 250 && x < o.x + o.length + 250 && y > o.y - 250 && y < o.y + o.width + 250)
  const cands: [number, number][] = []
  for (const d of ops.filter(o => o.kind === 'DOOR')) {
    const mid = d.offset + d.width / 2
    for (const k of [450, 700, 1000]) cands.push(d.wall === 'S' ? [mid, k] : d.wall === 'N' ? [mid, W - k] : d.wall === 'W' ? [k, mid] : [L - k, mid])
  }
  for (const k of [500, 800]) cands.push([k, k], [L - k, k], [k, W - k], [L - k, W - k], [L / 2, k], [L / 2, W - k], [k, W / 2], [L - k, W / 2])
  const [x, y] = cands.find(([a, b]) => free(a, b)) ?? [L / 2, W / 2]
  return { pos: [x / 1000, 1.6, -y / 1000], target: [L / 2000 + (L / 2000 - x / 1000) * 0.2, 1.15, -W / 2000 - (W / 2000 - y / 1000) * 0.2] }
}

/** Yaw (radians) that turns a model's back (−Z) to the nearest wall, plus the model's own length/depth for that wall. */
export function facing(o: { x: number; y: number; length: number; width: number }, L: number, W: number) {
  const c = [{ wall: 'S', d: o.y, yaw: Math.PI, along: true }, { wall: 'N', d: W - (o.y + o.width), yaw: 0, along: true },
             { wall: 'W', d: o.x, yaw: Math.PI / 2, along: false }, { wall: 'E', d: L - (o.x + o.length), yaw: -Math.PI / 2, along: false }]
  const best = c.reduce((a, b) => (b.d < a.d ? b : a))
  return { yaw: best.yaw, l: best.along ? o.length : o.width, d: best.along ? o.width : o.length, wall: best.wall }
}

function WallWithOpenings({ wall, L, W, H, ops, cutaway, tiles, colour }: { wall: 'S' | 'N' | 'W' | 'E'; L: number; W: number; H: number; ops: Opening3[]; cutaway: boolean; tiles: boolean; colour?: string }) {
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
    {!night && <directionalLight position={sunPos} target={target} intensity={5.5 * Math.min(1, 0.35 + dir.y * 1.6)} color={warm} castShadow
      shadow-mapSize-width={2048} shadow-mapSize-height={2048} shadow-bias={-0.0004} shadow-normalBias={0.02} shadow-radius={4}
      shadow-camera-left={-span} shadow-camera-right={span} shadow-camera-top={span} shadow-camera-bottom={-span} shadow-camera-near={1} shadow-camera-far={60} />}
    <hemisphereLight args={[night ? '#1e2a44' : '#e3ecf7', night ? '#3a3226' : '#d8c6ad', night ? 0.15 : 0.75]} />
    <ambientLight intensity={night ? 0.06 : 0.22} color="#fff4e6" />{/* stands in for light bounced off floor and walls */}
    <Environment resolution={128} frames={1}>
      <Lightformer form="rect" intensity={night ? 0.2 : 1.0} color={night ? '#334' : '#fff8ee'} position={[0, 6, 0]} rotation={[Math.PI / 2, 0, 0]} scale={[12, 12, 1]} />
      <Lightformer form="rect" intensity={night ? 0.05 : 0.8} color="#cfe0ff" position={[8, 3, 0]} rotation={[0, -Math.PI / 2, 0]} scale={[10, 4, 1]} />
      <Lightformer form="rect" intensity={night ? 0.05 : 0.6} color="#ffe2c2" position={[-8, 3, 0]} rotation={[0, Math.PI / 2, 0]} scale={[10, 4, 1]} />
    </Environment>
    <ContactShadows position={[L / 2, 0.002, -W / 2]} scale={[L * 1.05, W * 1.05]} opacity={0.45} blur={2.4} far={1.2} resolution={512} frames={1} />
  </>
}

/** The room itself: floor, walls with openings, skirting, ceiling + downlights. Wet rooms get tiles. */
export function RealisticRoom({ L, W, H, ops, hour, lightsOn, wet, finishes, ground = true }: { L: number; W: number; H: number; ops: Opening3[]; hour: number; lightsOn: boolean; wet: boolean
  finishes?: Finishes | null; ground?: boolean }) {
  const floor = floorMaterial(finishes, L, W, wet)
  const lit = lightsOn || isNight(hour)
  return <group>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2, 0, -W / 2]} receiveShadow material={floor}><planeGeometry args={[L, W]} /></mesh>
    {ground && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2, -0.01, -W / 2]} receiveShadow material={M.laminate('#d9d4cb')}><planeGeometry args={[L + 12, W + 12]} /></mesh>}
    {(['S', 'N', 'W', 'E'] as const).map(w => <WallWithOpenings key={w} wall={w} L={L} W={W} H={H} ops={ops} cutaway tiles={wet && !finishes?.walls} colour={finishes?.walls?.colour} />)}
    <Ceiling L={L} W={W} H={H} lightsOn={lit} />
    {finishes && <ConceptDecor f={finishes} L={L} W={W} H={H} ops={ops} lightsOn={lit} />}
  </group>
}
