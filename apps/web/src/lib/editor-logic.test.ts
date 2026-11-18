import { describe, expect, it } from 'vitest'
import {
  Obj, canRedo, canUndo, commitDrag, createHistory, duplicate, fromCatalogue, fromThreeCenter, gaps, push, redo,
  replacePresent, rotate90, snap, toThree, undo,
} from './editor-logic'

const bed: Obj = { id: 'b', name: 'Bed', category: 'Bed', x: 1160, y: 1520, length: 1930, width: 2030, height: 1200, price: 124000 }
const desk: Obj = { id: 'd', name: 'Desk', category: 'Study', x: 100, y: 100, length: 1200, width: 600, height: 760, price: 28000 }

describe('snap', () => {
  it('rounds to the nearest 50mm', () => { expect(snap(1174)).toBe(1150); expect(snap(1176)).toBe(1200); expect(snap(-30)).toBe(-50) })
})

describe('coordinates', () => {
  it('maps design mm to Three.js metres (north is -Z)', () => {
    const [X, Y, Z] = toThree(bed)
    expect(X).toBeCloseTo(2.125); expect(Y).toBeCloseTo(0.6); expect(Z).toBeCloseTo(-2.535)
  })
  it('round-trips: fromThreeCenter(toThree(o)) returns the original position', () => {
    const [X, , Z] = toThree(bed)
    expect(fromThreeCenter(X, Z, bed)).toEqual({ x: 1160, y: 1520 })
  })
})

describe('rotate90', () => {
  it('swaps footprint about the centre', () => {
    const r = rotate90(bed)
    expect(r.length).toBe(2030); expect(r.width).toBe(1930)
    expect(r.x + r.length / 2).toBeCloseTo(bed.x + bed.length / 2)   // centre unchanged
    expect(r.y + r.width / 2).toBeCloseTo(bed.y + bed.width / 2)
  })
  it('rotating twice restores the original', () => { expect(rotate90(rotate90(bed))).toEqual(bed) })
  it('does not mutate its input', () => { const c = { ...bed }; rotate90(bed); expect(bed).toEqual(c) })
})

describe('duplicate / gaps / catalogue', () => {
  it('duplicate gets a new id, a copy name (not stacked) and an offset', () => {
    const d1 = duplicate(desk, 'x1'); const d2 = duplicate(d1, 'x2')
    expect(d1.id).toBe('x1'); expect(d1.x).toBe(400); expect(d1.name).toBe('Desk (copy)'); expect(d2.name).toBe('Desk (copy)')
  })
  it('gaps are distances to each wall', () => {
    expect(gaps(desk, 4250, 3600)).toEqual({ west: 100, south: 100, east: 2950, north: 2900 })
  })
  it('catalogue items are centred and snapped', () => {
    const o = fromCatalogue({ sku: 's', name: 'Chair', category: 'Chair', length_mm: 750, width_mm: 800, height_mm: 850, price: 32000 }, 'n1', 4250, 3600)
    expect(o.x).toBe(1750); expect(o.y).toBe(1400)
    expect(o.sku).toBe('s')                                           // the SKU travels with the object so it can be priced
    expect(duplicate(o, 'n2').sku).toBe('s')                          // ...and survives duplication
  })
})

describe('history', () => {
  const A = [desk], B = [desk, bed], C = [bed]
  it('push → undo → redo', () => {
    let h = createHistory(A); h = push(h, B)
    expect(canUndo(h)).toBe(true); expect(canRedo(h)).toBe(false)
    h = undo(h); expect(h.present).toEqual(A); expect(canRedo(h)).toBe(true)
    h = redo(h); expect(h.present).toEqual(B)
  })
  it('a new edit after undo discards the redo branch', () => {
    let h = push(createHistory(A), B); h = undo(h); h = push(h, C)
    expect(canRedo(h)).toBe(false); expect(h.present).toEqual(C)
  })
  it('pushing an identical state creates no undo step', () => {
    const h = createHistory(A); expect(push(h, [{ ...desk }])).toBe(h)
  })
  it('undo/redo at the ends are no-ops', () => {
    const h = createHistory(A); expect(undo(h)).toBe(h); expect(redo(h)).toBe(h)
  })
  it('a whole drag is ONE undo step, and undo returns to the pre-drag state', () => {
    let h = createHistory(A); const base = h.present
    for (const x of [150, 200, 250, 300]) h = replacePresent(h, [{ ...desk, x }])   // many live moves
    h = commitDrag(h, base)
    expect(h.past.length).toBe(1)
    expect(undo(h).present).toEqual(A)
  })
  it('a drag that ends where it started records nothing', () => {
    let h = createHistory(A); const base = h.present
    h = replacePresent(h, [{ ...desk, x: 500 }]); h = replacePresent(h, [{ ...desk }])
    expect(commitDrag(h, base).past.length).toBe(0)
  })
  it('history is capped at 100 steps', () => {
    let h = createHistory(A)
    for (let i = 0; i < 150; i++) h = push(h, [{ ...desk, x: i }])
    expect(h.past.length).toBe(100)
  })
})


import { inrStr } from './utils'
describe('inrStr (display only)', () => {
  it.each([['0', '0.00'], ['999', '999.00'], ['1000', '1,000.00'], ['100000', '1,00,000.00'], ['476753.19', '4,76,753.19'], ['12345678.9', '1,23,45,678.90'], ['-1234567.5', '-12,34,567.50']])('%s -> %s', (i, o) => { expect(inrStr(i)).toBe(o) })
  it('leaves non-numeric input alone', () => { expect(inrStr('n/a')).toBe('n/a') })
})
