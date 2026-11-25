// Room shell (M41): outline (L-shaped / angled rooms), sloped or uneven ceiling, beams / columns / pillars / ceiling drops.
// The SERVER decides (validation, layouts, drawings, take-off); this file only draws what it sends and previews a form before saving.
// Plan coordinates in mm: origin at the south-west corner of the room's L × W box, x east, y north.

export type Pt = [number, number]
export interface ShellEdge { i: number; x0: number; y0: number; x1: number; y1: number; length: number; wall: 'N' | 'E' | 'S' | 'W'; side: 'N' | 'E' | 'S' | 'W' | null }
export interface Structure { id: string; kind: 'BEAM' | 'COLUMN' | 'PILLAR' | 'CEILING_DROP'; x: number; y: number; length: number; width: number; depth: number; label: string }
export type Ceiling = { type: 'FLAT' } | { type: 'SLOPED'; low: number; high: number; high_wall: 'N' | 'E' | 'S' | 'W' } | { type: 'UNEVEN'; points: [number, number, number][] }
export type Shape = { type: 'RECT' } | { type: 'CUTS'; cuts: Partial<Record<'SW' | 'SE' | 'NE' | 'NW', [number, number]>> } | { type: 'POLYGON'; points: Pt[] }
export interface Shell { L: number; W: number; H: number; shape: Shape; outline: Pt[]; edges: ShellEdge[]; area_sqm: number; ceiling: Ceiling; ceiling_min: number; ceiling_max: number; structures: Structure[] }

export const CORNERS = ['SW', 'SE', 'NE', 'NW'] as const
export const KIND_LABEL: Record<Structure['kind'], string> = { BEAM: 'Beam', COLUMN: 'Column (against a wall)', PILLAR: 'Pillar (free-standing)', CEILING_DROP: 'Ceiling drop / bulkhead' }

/** Outline of a rectangle with corner cuts — same order as the server (counter-clockwise from the south-west). */
export function cutsOutline(L: number, W: number, cuts: Partial<Record<(typeof CORNERS)[number], [number, number]>>): Pt[] {
  const c = (k: (typeof CORNERS)[number]) => { const v = cuts[k]; return v && v[0] > 0 && v[1] > 0 ? v : null }
  const pts: Pt[] = []
  let v = c('SW'); pts.push(...(v ? [[0, v[1]], [v[0], v[1]], [v[0], 0]] as Pt[] : [[0, 0]] as Pt[]))
  v = c('SE'); pts.push(...(v ? [[L - v[0], 0], [L - v[0], v[1]], [L, v[1]]] as Pt[] : [[L, 0]] as Pt[]))
  v = c('NE'); pts.push(...(v ? [[L, W - v[1]], [L - v[0], W - v[1]], [L - v[0], W]] as Pt[] : [[L, W]] as Pt[]))
  v = c('NW'); pts.push(...(v ? [[v[0], W], [v[0], W - v[1]], [0, W - v[1]]] as Pt[] : [[0, W]] as Pt[]))
  return pts
}

export function area(pts: Pt[]): number {
  let a = 0
  for (let i = 0; i < pts.length; i++) { const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length]; a += x0 * y1 - x1 * y0 }
  return Math.abs(a) / 2
}

/** "x, y" (or "x, y, h") per line → numbers; null when a line can't be read. */
export function parsePoints(text: string, n: 2 | 3): number[][] | null {
  const rows = text.split(/\n+/).map(l => l.trim()).filter(Boolean)
  const out: number[][] = []
  for (const r of rows) {
    const p = r.split(/[\s,;]+/).filter(Boolean).map(Number)
    if (p.length !== n || p.some(x => !Number.isFinite(x))) return null
    out.push(p)
  }
  return out
}

/** Ceiling height (mm) at a plan point — the same rule as the server (linear slope; inverse-distance between measured spots). */
export function ceilingAt(c: Ceiling | null | undefined, H: number, L: number, W: number, x: number, y: number): number {
  if (!c || c.type === 'FLAT') return H
  if (c.type === 'SLOPED') {
    const f = { N: y / W, S: 1 - y / W, E: x / L, W: 1 - x / L }[c.high_wall]
    return c.low + (c.high - c.low) * Math.min(1, Math.max(0, f))
  }
  let num = 0, den = 0
  for (const [px, py, h] of c.points) { const d2 = (x - px) ** 2 + (y - py) ** 2; if (d2 < 1) return h; num += h / d2; den += 1 / d2 }
  return num / den
}

/** A door/window's two ends on its wall line + inward normal (server-resolved when present; else the N/E/S/W + offset rule). */
export function openingSpan(o: { wall: string; offset: number; width: number; x0?: number; y0?: number; x1?: number; y1?: number; nx?: number; ny?: number }, L: number, W: number): [Pt, Pt, Pt] {
  if (o.x0 !== undefined && o.y0 !== undefined && o.x1 !== undefined && o.y1 !== undefined) return [[o.x0, o.y0], [o.x1, o.y1], [o.nx ?? 0, o.ny ?? 0]]
  const a = o.offset, w = o.width
  return ({ S: [[a, 0], [a + w, 0], [0, 1]], N: [[a, W], [a + w, W], [0, -1]], W: [[0, a], [0, a + w], [1, 0]], E: [[L, a], [L, a + w], [-1, 0]] } as Record<string, [Pt, Pt, Pt]>)[o.wall]
}

/** Wall choices for a door/window: the four sides, plus every wall that isn't on a side (inner walls of an L, angled walls) by number. */
export function wallChoices(edges: ShellEdge[] | undefined): { value: string; label: string }[] {
  const base = [{ value: 'N', label: 'North (top of plan)' }, { value: 'E', label: 'East (right)' }, { value: 'S', label: 'South (bottom)' }, { value: 'W', label: 'West (left)' }]
  return [...base, ...(edges ?? []).filter(e => !e.side).map(e => ({ value: `e${e.i}`, label: `Wall ${e.i + 1} (${Math.round(e.length)} mm, faces ${e.wall}) — offset from its start` }))]
}
