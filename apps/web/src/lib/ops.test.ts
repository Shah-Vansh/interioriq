import { existsSync, readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { describe, expect, it } from 'vitest'
import { fitScale, fmtDate, isoDay, paise, quoteActions, STAGE_LABEL, woNeighbours, WO_STAGES } from './ops'
import { navigation } from './nav'

describe('quotation actions mirror the API', () => {
  it('draft can be sent/approved/rejected; approved and superseded are final; rejected can be re-sent', () => {
    expect(quoteActions('DRAFT')).toEqual(['SENT', 'APPROVED', 'REJECTED'])
    expect(quoteActions('SENT')).toEqual(['APPROVED', 'REJECTED'])
    expect(quoteActions('REJECTED')).toEqual(['SENT'])
    expect(quoteActions('APPROVED')).toEqual([])
    expect(quoteActions('SUPERSEDED')).toEqual([])
  })
})

describe('work order stage buttons', () => {
  it('first and last stages have one neighbour', () => {
    expect(woNeighbours('PENDING')).toEqual({ prev: null, next: 'CUTTING' })
    expect(woNeighbours('READY')).toEqual({ prev: 'FINISHING', next: null })
    expect(woNeighbours('ASSEMBLY')).toEqual({ prev: 'EDGEBANDING', next: 'FINISHING' })
    expect(WO_STAGES).toHaveLength(6)
  })
})

describe('money and dates', () => {
  it('paise compares money strings exactly', () => {
    expect(paise('124000.50')).toBe(BigInt(12400050)); expect(paise('-0.05')).toBe(BigInt(-5)); expect(paise('7')).toBe(BigInt(700))
    expect(paise('9007199254740993.99') - paise('9007199254740993.98')).toBe(BigInt(1))      // beyond float precision
  })
  it('dates', () => {
    expect(fmtDate(null)).toBe('—'); expect(fmtDate('2026-11-17')).toMatch(/17.*Nov.*2026/)
    expect(isoDay(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
  it('plan scale fits the room in the box', () => {
    const f = fitScale(4250, 3600, 760, 560)
    expect(f.w).toBeLessThanOrEqual(760.0001); expect(f.h).toBeLessThanOrEqual(560.0001)
    expect(Math.abs(f.w - 760) < 0.01 || Math.abs(f.h - 560) < 0.01).toBe(true)
  })
  it('every lifecycle stage has a label', () => {
    expect(Object.keys(STAGE_LABEL)).toEqual(['LEAD', 'SURVEY', 'DESIGN', 'QUOTATION', 'PROCUREMENT', 'MANUFACTURING', 'DELIVERY', 'INSTALLATION', 'QC', 'HANDOVER', 'COMPLETED'])
  })
})

describe('no mock or stub screens', () => {
  const app = join(__dirname, '..', 'app', '(app)')
  const pages: string[] = []
  const walk = (d: string) => { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) walk(p); else if (f === 'page.tsx') pages.push(p) } }
  walk(app)
  it('every sidebar link has a page', () => {
    const hrefs = navigation.flatMap(n => [n, ...(n.children ?? [])]).map(n => n.href).filter(Boolean) as string[]
    for (const h of hrefs) expect(existsSync(join(app, ...h.split('/').filter(Boolean), 'page.tsx')), h).toBe(true)
  })
  it('no page is an "under development" placeholder', () => {
    expect(pages.length).toBeGreaterThan(40)
    for (const p of pages) expect(readFileSync(p, 'utf-8'), p).not.toMatch(/under active development|coming soon/i)
  })
  it('no component ships hard-coded sample records', () => {
    const comps = join(__dirname, '..', 'components'); const files: string[] = []
    const w = (d: string) => { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) w(p); else if (f.endsWith('.tsx')) files.push(p) } }
    w(comps)
    for (const f of files) expect(readFileSync(f, 'utf-8'), f).not.toMatch(/Urban Ladder|Godrej Interio|Pepperfry|Good morning, Admin|const (ITEMS|REV|CST|PROJECTS|LEADS)\s*=\s*\[/)
  })
})

describe('navigation', () => {
  it('no two menu items point at the same page (two links would light up at once)', () => {
    const hrefs = navigation.flatMap(n => [n, ...(n.children ?? [])]).map(n => n.href).filter(Boolean)
    expect(new Set(hrefs).size).toBe(hrefs.length)
  })
})
