import { describe, expect, it } from 'vitest'
import { area, ceilingAt, cutsOutline, openingSpan, parsePoints, wallChoices } from './room-shell'

describe('room shell (M41)', () => {
  it('builds an L-shaped outline the same way as the server', () => {
    const o = cutsOutline(4500, 3600, { NE: [1500, 1200] })
    expect(o).toEqual([[0, 0], [4500, 0], [4500, 2400], [3000, 2400], [3000, 3600], [0, 3600]])
    expect(area(o)).toBe(4500 * 3600 - 1500 * 1200)
    expect(cutsOutline(4000, 3000, {})).toEqual([[0, 0], [4000, 0], [4000, 3000], [0, 3000]])
  })
  it('reads points typed one per line', () => {
    expect(parsePoints('0, 0\n4000,0\n 4000 3000 \n\n0;3000', 2)).toEqual([[0, 0], [4000, 0], [4000, 3000], [0, 3000]])
    expect(parsePoints('0, 0, 2700\n1, 2', 3)).toBeNull()
    expect(parsePoints('a, 1', 2)).toBeNull()
  })
  it('gives the ceiling height anywhere (sloped / uneven / flat)', () => {
    const sl = { type: 'SLOPED' as const, low: 2400, high: 3600, high_wall: 'N' as const }
    expect(ceilingAt(sl, 2750, 4000, 3000, 100, 0)).toBe(2400)
    expect(ceilingAt(sl, 2750, 4000, 3000, 100, 1500)).toBe(3000)
    expect(ceilingAt({ type: 'FLAT' }, 2750, 4000, 3000, 1, 1)).toBe(2750)
    const un = { type: 'UNEVEN' as const, points: [[0, 0, 2900], [4000, 3000, 2700], [2000, 1500, 2600]] as [number, number, number][] }
    expect(ceilingAt(un, 0, 4000, 3000, 2000, 1500)).toBe(2600)
    const mid = ceilingAt(un, 0, 4000, 3000, 500, 500); expect(mid).toBeGreaterThan(2600); expect(mid).toBeLessThan(2900)
  })
  it('places openings from server end points, else by wall + offset', () => {
    expect(openingSpan({ wall: 'N', offset: 300, width: 900, x0: 4200, y0: 2400, x1: 3300, y1: 2400, nx: 0, ny: -1 }, 4500, 3600)).toEqual([[4200, 2400], [3300, 2400], [0, -1]])
    expect(openingSpan({ wall: 'E', offset: 500, width: 900 }, 4000, 3000)).toEqual([[4000, 500], [4000, 1400], [-1, 0]])
  })
  it('offers numbered walls only for walls that are not on a side', () => {
    const c = wallChoices([{ i: 2, x0: 4500, y0: 2400, x1: 3000, y1: 2400, length: 1500, wall: 'N', side: null }, { i: 0, x0: 0, y0: 0, x1: 4500, y1: 0, length: 4500, wall: 'S', side: 'S' }])
    expect(c.map(x => x.value)).toEqual(['N', 'E', 'S', 'W', 'e2'])
    expect(c[4].label).toContain('Wall 3 (1500 mm, faces N)')
  })
})
