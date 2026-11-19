export interface Milestone { label: string; pct: string; amount?: string }

/** Sum of percentages in hundredths (integers, so 33.33 + 66.67 is exactly 100). null when a value isn't a number. */
export function pctTotal(rows: Milestone[]): number | null {
  let t = 0
  for (const r of rows) { const v = Number(r.pct); if (!r.pct.trim() || !Number.isFinite(v)) return null; t += Math.round(v * 100) }
  return t
}
