// Pure editor logic — no React, no Three.js — so it can be unit-tested.
// Design coordinates: millimetres, origin at the room's south-west corner, +x east, +y north.
// Three.js scene: metres, +X east, -Z north (so the default camera looks "north" into the room).
import type { PlacedObject } from './api'

export type Obj = PlacedObject
export const SNAP_MM = 50

export const snap = (v: number, step = SNAP_MM) => Math.round(v / step) * step
const r1 = (v: number) => Math.round(v * 10) / 10

/** Zero-height objects still get a thin visible slab so they can be selected. */
export const displayHeight = (o: Obj) => Math.max(o.height, 20)

/** Object centre in Three.js metres. */
export function toThree(o: Obj): [number, number, number] {
  return [(o.x + o.length / 2) / 1000, ((o.z ?? 0) + displayHeight(o) / 2) / 1000, -(o.y + o.width / 2) / 1000]   // z: wall cabinets hang above the floor
}
/** Inverse: Three.js floor-plane centre (X, Z in metres) → design x/y (mm, corner). */
export function fromThreeCenter(X: number, Z: number, o: Obj): { x: number; y: number } {
  return { x: r1(X * 1000 - o.length / 2), y: r1(-Z * 1000 - o.width / 2) }
}

/** Rotate 90° about the footprint centre by swapping length/width — keeps the model axis-aligned for the validator, CAD and BOQ. */
export function rotate90(o: Obj): Obj {
  const cx = o.x + o.length / 2, cy = o.y + o.width / 2
  return { ...o, length: o.width, width: o.length, x: r1(cx - o.width / 2), y: r1(cy - o.length / 2) }
}

export function duplicate(o: Obj, id: string, offset = 300): Obj {
  return { ...o, id, name: o.name.replace(/ \(copy\)$/, '') + ' (copy)', x: o.x + offset, y: o.y + offset }
}

export function gaps(o: Obj, L: number, W: number) {
  return { west: r1(o.x), east: r1(L - (o.x + o.length)), south: r1(o.y), north: r1(W - (o.y + o.width)) }
}

export interface CatalogueLike { sku: string; name: string; category: string; length_mm: number; width_mm: number; height_mm: number; price: number; mount_mm?: number | null }
export function fromCatalogue(item: CatalogueLike, id: string, L: number, W: number): Obj {
  return {
    id, sku: item.sku, name: item.name, category: item.category, length: item.length_mm, width: item.width_mm, height: item.height_mm, price: item.price,
    x: snap((L - item.length_mm) / 2), y: snap((W - item.width_mm) / 2),
    ...(item.mount_mm ? { z: item.mount_mm } : {}),
  }
}

// ── Undo / redo ──────────────────────────────────────────────────────────────
export interface History { past: Obj[][]; present: Obj[]; future: Obj[][] }
const LIMIT = 100
const same = (a: Obj[], b: Obj[]) => JSON.stringify(a) === JSON.stringify(b)

export const createHistory = (initial: Obj[]): History => ({ past: [], present: initial, future: [] })
export function push(h: History, next: Obj[]): History {
  if (same(h.present, next)) return h
  return { past: [...h.past, h.present].slice(-LIMIT), present: next, future: [] }
}
/** Live update during a drag: changes `present` without creating undo steps. */
export const replacePresent = (h: History, next: Obj[]): History => ({ ...h, present: next })
/** End of a drag: record ONE undo step from the state captured when the drag began. */
export function commitDrag(h: History, base: Obj[]): History {
  if (same(base, h.present)) return h
  return { past: [...h.past, base].slice(-LIMIT), present: h.present, future: [] }
}
export function undo(h: History): History {
  if (!h.past.length) return h
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] }
}
export function redo(h: History): History {
  if (!h.future.length) return h
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) }
}
export const canUndo = (h: History) => h.past.length > 0
export const canRedo = (h: History) => h.future.length > 0
