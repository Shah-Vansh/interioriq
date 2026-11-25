'use client'
// The design concept in 3D (room frame, metres): feature wall, false ceiling with cove LEDs / island / rafters / grid, curtains & blinds,
// rug, wall art, plants, pendant lights and chandeliers. Positions come from the server's concept (mm); nothing here decides design.
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { RectAreaLightUniformsLib } from 'three/examples/jsm/lights/RectAreaLightUniformsLib.js'
import { M } from './materials'
import { Plant } from './models'

export interface Finishes {
  style?: string; palette?: Record<string, string>; walls?: { colour: string }
  accent?: { wall: string; from: number; to: number; z0: number; height: number; type: string; colour: string } | null
  ceiling?: { type: string; drop?: number; border?: number }; floor?: { kind: string; tone: string }
  curtains?: { wall: string; offset: number; width: number; sill: number; height: number; kind: string; colour: string }[]
  rug?: { x: number; y: number; length: number; width: number; colour: string } | null
  art?: { wall: string; pos: number; width: number; height: number; z: number; colours: string[] }[]
  plants?: { x: number; y: number }[]; lights?: { kind: string; x: number; y: number; count?: number; drop?: number }[]
}
type Wall = 'N' | 'E' | 'S' | 'W'
let areaLightsReady = false
if (typeof window !== 'undefined' && !areaLightsReady) { RectAreaLightUniformsLib.init(); areaLightsReady = true }   // cove LED glow
const INSET = 0.012

/** A point u (m) along a wall + inward offset d (m) → world position and the yaw that faces into the room. */
function onWall(wall: Wall, u: number, d: number, L: number, W: number): { p: [number, number]; yaw: number } {
  if (wall === 'S') return { p: [u, -d], yaw: Math.PI }
  if (wall === 'N') return { p: [u, -W + d], yaw: 0 }
  if (wall === 'W') return { p: [d, -u], yaw: Math.PI / 2 }
  return { p: [L - d, -u], yaw: -Math.PI / 2 }
}

/** Things fixed to a wall (feature wall, curtains, art) hide together with that wall when the camera looks in from outside it (dollhouse cut-away). */
function WallCut({ wall, L, W, H, children }: { wall: Wall; L: number; W: number; H: number; children: React.ReactNode }) {
  const ref = useRef<THREE.Group>(null)
  const n = { S: [0, 0, 1], N: [0, 0, -1], W: [-1, 0, 0], E: [1, 0, 0] }[wall], c = { S: [L / 2, 0, 0], N: [L / 2, 0, -W], W: [0, 0, -W / 2], E: [L, 0, -W / 2] }[wall]
  useFrame(({ camera }) => {
    if (!ref.current) return
    const out = (camera.position.x - c[0]) * n[0] + (camera.position.z - c[2]) * n[2] > 0.05
    ref.current.visible = !(out && camera.position.y < H * 6)
  })
  return <group ref={ref}>{children}</group>
}

/** Flooring material for a concept floor. */
export function floorMaterial(f: Finishes | null | undefined, L: number, W: number, wet: boolean) {
  const k = f?.floor?.kind, t = f?.floor?.tone
  if (k === 'MARBLE') return M.marbleFloor()
  if (k === 'TILE' || (!k && wet)) return M.tiles(t ?? '#d6d1c8', L, W)
  if (k === 'TERRAZZO') return M.terrazzo(t)
  if (k === 'CONCRETE') return M.wall(t ?? '#a8a29e')
  if (k === 'STONE') return M.tiles(t ?? '#c9b48e', L * 0.6, W * 0.6)
  return M.floor(t ?? '#b88a5a', L, W)
}

function FeatureWall({ a, L, W, H, ops }: { a: NonNullable<Finishes['accent']>; L: number; W: number; H: number; ops: { wall: string; offset: number; width: number; kind: string; sill: number; height: number }[] }) {
  const wall = a.wall as Wall, from = a.from / 1000, to = a.to / 1000, z0 = a.z0 / 1000, h = Math.min(a.height / 1000, H - z0)
  // pieces between openings on this wall
  const holes = ops.filter(o => o.wall === wall).map(o => [o.offset / 1000, (o.offset + o.width) / 1000] as const).sort((p, q) => p[0] - q[0])
  const pieces: [number, number][] = []; let cur = from
  for (const [x0, x1] of holes) { if (x1 <= cur || x0 >= to) continue; if (x0 > cur) pieces.push([cur, Math.min(x0, to)]); cur = Math.max(cur, x1) }
  if (cur < to) pieces.push([cur, to])
  const t = a.type
  const mat = t === 'WALLPAPER' ? M.wallpaper(a.colour) : t === 'STONE' ? M.stone('#b9ab95') : t === 'BRICK' ? M.brick(a.colour) : t === 'JAALI' ? M.jaali(a.colour)
    : t === 'TILE' ? M.tiles(a.colour, 1.2, 1.2) : t === 'FLUTED_WOOD' ? M.wood(a.colour) : M.paint(a.colour)
  return <>{pieces.map(([u0, u1], i) => {
    const w = u1 - u0, mid = onWall(wall, (u0 + u1) / 2, INSET + 0.01, L, W)
    return <group key={i} position={[mid.p[0], z0 + h / 2, mid.p[1]]} rotation={[0, mid.yaw, 0]}>
      {t === 'FLUTED_WOOD' ? <>
        <mesh receiveShadow material={M.wood(a.colour)}><boxGeometry args={[w, h, 0.012]} /></mesh>
        {Array.from({ length: Math.min(160, Math.floor(w / 0.045)) }, (_, k) => <mesh key={k} position={[-w / 2 + 0.022 + k * 0.045, 0, 0.012]} castShadow receiveShadow material={M.wood(a.colour)}><boxGeometry args={[0.028, h, 0.02]} /></mesh>)}
      </> : t === 'PANELLING' ? <>
        <mesh receiveShadow material={M.paint(a.colour)}><boxGeometry args={[w, h, 0.01]} /></mesh>
        {Array.from({ length: Math.max(1, Math.round(w / 0.7)) }, (_, k, n = Math.max(1, Math.round(w / 0.7))) => {
          const pw = w / n - 0.12, px = -w / 2 + (k + 0.5) * (w / n)
          return [[px, h * 0.22, pw, h * 0.3], [px, -h * 0.17, pw, h * 0.45]].map(([x, y, ww, hh], j) => <group key={`${k}${j}`} position={[x, y, 0.012]}>
            {[[0, hh / 2, ww, 0.025], [0, -hh / 2, ww, 0.025], [-ww / 2, 0, 0.025, hh], [ww / 2, 0, 0.025, hh]].map(([mx, my, mw, mh], q) =>
              <mesh key={q} position={[mx, my, 0]} castShadow material={M.paint(a.colour)}><boxGeometry args={[mw, mh, 0.02]} /></mesh>)}</group>)
        })}
      </> : t === 'JAALI' ? <>
        <mesh material={M.led()}><boxGeometry args={[w, h, 0.005]} /></mesh>
        <mesh position={[0, 0, 0.02]} material={mat}><boxGeometry args={[w, h, 0.012]} /></mesh>
      </> : <mesh receiveShadow material={mat}><boxGeometry args={[w, h, t === 'STONE' || t === 'BRICK' ? 0.025 : 0.008]} /></mesh>}
    </group>
  })}</>
}

function CeilingDesign({ c, L, W, H }: { c: NonNullable<Finishes['ceiling']>; L: number; W: number; H: number }) {
  const ref = useRef<THREE.Group>(null)
  useFrame(({ camera }) => { if (ref.current) ref.current.visible = camera.position.y < H - 0.05 })
  const drop = (c.drop ?? 250) / 1000, b = (c.border ?? 600) / 1000, th = 0.08, y = H - drop + th / 2
  const gyp = M.ceiling()
  if (c.type === 'COVE') return <group ref={ref}>
    {[[L / 2, -b / 2, L, b], [L / 2, -W + b / 2, L, b], [b / 2, -W / 2, b, W - 2 * b], [L - b / 2, -W / 2, b, W - 2 * b]].map(([x, z, w, d], i) =>
      <mesh key={i} position={[x, y, z]} material={gyp} receiveShadow><boxGeometry args={[w, th, d]} /></mesh>)}
    {[[L / 2, -b - 0.01, L - 2 * b, 0.015], [L / 2, -W + b + 0.01, L - 2 * b, 0.015], [b + 0.01, -W / 2, 0.015, W - 2 * b], [L - b - 0.01, -W / 2, 0.015, W - 2 * b]].map(([x, z, w, d], i) =>
      <mesh key={`l${i}`} position={[x, H - drop + th + 0.01, z]} material={M.led()}><boxGeometry args={[w, 0.012, d]} /></mesh>)}
    {[[L / 2, -b - 0.06, L - 2 * b, 0.1], [L / 2, -W + b + 0.06, L - 2 * b, 0.1], [b + 0.06, -W / 2, 0.1, W - 2 * b], [L - b - 0.06, -W / 2, 0.1, W - 2 * b]].map(([x, z, w, d], i) =>
      <mesh key={`u${i}`} position={[x, y + 0.08, z]} material={gyp}><boxGeometry args={[w, 0.12, d]} /></mesh>)}
    <rectAreaLight position={[L / 2, H - 0.02, -W / 2]} rotation={[-Math.PI / 2, 0, 0]} width={L - 2 * b} height={W - 2 * b} intensity={1.2} color="#ffe3b5" />
  </group>
  if (c.type === 'ISLAND') {
    const iw = Math.max(0.6, L - 2 * b), id = Math.max(0.6, W - 2 * b)
    return <group ref={ref}>
      <mesh position={[L / 2, y, -W / 2]} material={gyp} receiveShadow><boxGeometry args={[iw, th, id]} /></mesh>
      {[[L / 2, -W / 2 + id / 2 + 0.005, iw, 0.012], [L / 2, -W / 2 - id / 2 - 0.005, iw, 0.012], [L / 2 - iw / 2 - 0.005, -W / 2, 0.012, id], [L / 2 + iw / 2 + 0.005, -W / 2, 0.012, id]].map(([x, z, w, d], i) =>
        <mesh key={i} position={[x, y + th / 2 + 0.006, z]} material={M.led()}><boxGeometry args={[w, 0.012, d]} /></mesh>)}
      <rectAreaLight position={[L / 2, H - drop + 0.12, -W / 2]} rotation={[Math.PI / 2, 0, 0]} width={iw + 0.3} height={id + 0.3} intensity={1.6} color="#ffe3b5" />
    </group>
  }
  if (c.type === 'RAFTER') {
    const n = Math.max(2, Math.round(Math.min(L, W) / 0.6)), along = L >= W
    return <group ref={ref}>{Array.from({ length: n }, (_, k) => {
      const t = (k + 0.5) / n
      return <mesh key={k} position={along ? [L * t, H - 0.08, -W / 2] : [L / 2, H - 0.08, -W * t]} castShadow material={M.wood('#5b3a22')}><boxGeometry args={along ? [0.1, 0.16, W] : [L, 0.16, 0.1]} /></mesh>
    })}</group>
  }
  if (c.type === 'GRID') return <group ref={ref}><mesh position={[L / 2, H - 0.01, -W / 2]} rotation={[Math.PI / 2, 0, 0]} material={M.tiles('#f4f2ee', L * 0.6, W * 0.6)}><planeGeometry args={[L, W]} /></mesh></group>
  return null
}

function CurtainPanel({ w, h, colour }: { w: number; h: number; colour: string }) {
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(w, h, Math.max(8, Math.round(w * 40)), 1)
    const p = g.attributes.position
    for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin(p.getX(i) * 55) * 0.025)
    g.computeVertexNormals(); return g
  }, [w, h])
  return <mesh geometry={geo} castShadow receiveShadow material={M.curtain(colour)} />
}

/** All decor of a concept for one room (room frame, metres). */
export function ConceptDecor({ f, L, W, H, ops, lightsOn }: { f: Finishes; L: number; W: number; H: number
  ops: { wall: string; offset: number; width: number; kind: string; sill: number; height: number }[]; lightsOn: boolean }) {
  return <group>
    {f.accent && <WallCut wall={f.accent.wall as Wall} L={L} W={W} H={H}><FeatureWall a={f.accent} L={L} W={W} H={H} ops={ops} /></WallCut>}
    {f.ceiling && <CeilingDesign c={f.ceiling} L={L} W={W} H={H} />}
    {(f.curtains ?? []).map((c, i) => {
      const wall = c.wall as Wall, u0 = c.offset / 1000, u1 = (c.offset + c.width) / 1000, top = (c.sill + c.height) / 1000 + 0.15
      const rod = onWall(wall, (u0 + u1) / 2, 0.12, L, W)
      if (c.kind === 'BLIND') return <WallCut key={i} wall={wall} L={L} W={W} H={H}><group position={[rod.p[0], (c.sill + c.height) / 1000 - c.height / 2000 * 0.55, rod.p[1]]} rotation={[0, rod.yaw, 0]}>
        <mesh castShadow material={M.curtain(c.colour)}><boxGeometry args={[u1 - u0 + 0.06, c.height / 1000 * 0.55, 0.01]} /></mesh></group></WallCut>
      const pw = Math.max(0.35, (u1 - u0) * 0.3), h = Math.min(top - 0.02, H - 0.05)
      return <WallCut key={i} wall={wall} L={L} W={W} H={H}><group position={[rod.p[0], 0, rod.p[1]]} rotation={[0, rod.yaw, 0]}>
        <mesh position={[0, top, 0]} material={M.black()}><boxGeometry args={[u1 - u0 + 0.5, 0.02, 0.02]} /></mesh>
        {[-1, 1].map(s => <group key={s} position={[s * ((u1 - u0) / 2 + 0.25 - pw / 2), h / 2 + 0.02, 0]}><CurtainPanel w={pw} h={h} colour={c.colour} /></group>)}
      </group></WallCut>
    })}
    {f.rug && <mesh position={[(f.rug.x + f.rug.length / 2) / 1000, 0.004, -(f.rug.y + f.rug.width / 2) / 1000]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow material={M.rug(f.rug.colour)}>
      <planeGeometry args={[f.rug.length / 1000, f.rug.width / 1000]} /></mesh>}
    {(f.art ?? []).map((a, i) => {
      const at = onWall(a.wall as Wall, (a.pos + a.width / 2) / 1000, 0.02, L, W), w = a.width / 1000, h = a.height / 1000
      return <WallCut key={i} wall={a.wall as Wall} L={L} W={W} H={H}><group position={[at.p[0], (a.z + a.height / 2) / 1000, at.p[1]]} rotation={[0, at.yaw, 0]}>
        <mesh castShadow material={M.black()}><boxGeometry args={[w + 0.05, h + 0.05, 0.03]} /></mesh>
        <mesh position={[0, 0, 0.0165]} material={M.art(a.colours)}><planeGeometry args={[w, h]} /></mesh>
      </group></WallCut>
    })}
    {(f.plants ?? []).map((p, i) => <group key={i} position={[p.x / 1000, 0, -p.y / 1000]}><Plant h={1.2} /></group>)}
    {(f.lights ?? []).map((l, i) => {
      const x = l.x / 1000, z = -l.y / 1000, n = l.count ?? 1, bottom = l.kind === 'CHANDELIER' ? H - 0.7 : l.drop ? H - l.drop / 1000 : 1.55
      if (l.kind === 'CHANDELIER') return <group key={i} position={[x, bottom, z]}>
        <mesh position={[0, (H - bottom) / 2, 0]} material={M.black()}><cylinderGeometry args={[0.006, 0.006, H - bottom, 6]} /></mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]} material={M.laminate('#b08d57')}><torusGeometry args={[0.35, 0.012, 8, 40]} /></mesh>
        {Array.from({ length: 10 }, (_, k) => <mesh key={k} position={[Math.cos(k * 0.628) * 0.35, -0.05, Math.sin(k * 0.628) * 0.35]} material={M.emissive()}><sphereGeometry args={[0.025, 10, 8]} /></mesh>)}
        {lightsOn && <pointLight intensity={6} distance={6} color="#ffe3b5" />}
      </group>
      return <group key={i}>{Array.from({ length: n }, (_, k) => {
        const off = (k - (n - 1) / 2) * 0.5
        return <group key={k} position={[x + off, bottom, z]}>
          <mesh position={[0, (H - bottom) / 2, 0]} material={M.black()}><cylinderGeometry args={[0.004, 0.004, H - bottom, 6]} /></mesh>
          <mesh castShadow material={M.laminate('#2b2b2b')}><coneGeometry args={[0.13, 0.18, 24, 1, true]} /></mesh>
          <mesh position={[0, -0.05, 0]} material={M.emissive()}><sphereGeometry args={[0.03, 10, 8]} /></mesh>
          {lightsOn && k === 0 && <pointLight position={[0, -0.1, 0]} intensity={3} distance={3.5} color="#ffd9a0" />}
        </group>
      })}</group>
    })}
  </group>
}
