import { describe, expect, it } from 'vitest'
import type { Lead } from './api'
import { STAGES, canMove, compact, formatBudget, groupByStage, moveLead, timeAgo } from './crm-logic'
import { navigation } from './nav'

const lead = (id: string, stage: string, extra: Partial<Lead> = {}): Lead => ({
  id, name: id, phone: null, email: null, city: null, source: null, requirement: null, budget: null, stage,
  client_id: null, project_id: null, project_number: null, created_at: '', updated_at: '', ...extra,
})

describe('stages', () => {
  it('has the 9 spec stages in order', () => {
    expect(STAGES.map(s => s.key)).toEqual(['NEW', 'CONTACTED', 'QUALIFIED', 'SITE_VISIT', 'DESIGN', 'QUOTATION', 'NEGOTIATION', 'WON', 'LOST'])
  })
  it('groups leads into every column, including empty ones', () => {
    const g = groupByStage([lead('a', 'NEW'), lead('b', 'WON'), lead('c', 'NEW')])
    expect(Object.keys(g)).toHaveLength(9)
    expect(g.NEW.map(l => l.id)).toEqual(['a', 'c']); expect(g.LOST).toEqual([])
  })
})

describe('moving', () => {
  it('moveLead returns a new array and leaves the original intact (for rollback)', () => {
    const before = [lead('a', 'NEW')]; const after = moveLead(before, 'a', 'WON')
    expect(after[0].stage).toBe('WON'); expect(before[0].stage).toBe('NEW')
  })
  it('a converted lead can only stay Won', () => {
    expect(canMove(lead('a', 'WON', { project_id: 'p' }), 'LOST')).toBe(false)
    expect(canMove(lead('a', 'NEW'), 'LOST')).toBe(true)
    expect(canMove(lead('a', 'NEW'), 'NEW')).toBe(false)
  })
})

describe('formatting', () => {
  it('formats budgets in lakh/crore', () => {
    expect(formatBudget('2200000.00')).toBe('₹22 L'); expect(formatBudget('350000')).toBe('₹3.5 L')
    expect(formatBudget('12500000')).toBe('₹1.25 Cr'); expect(formatBudget('35000.00')).toBe('₹35,000')
    expect(formatBudget(null)).toBe(''); expect(formatBudget('abc')).toBe('')
  })
  it('timeAgo treats server timestamps without a zone as UTC', () => {
    const now = Date.parse('2026-01-10T12:00:00Z')
    expect(timeAgo('2026-01-10T11:59:30', now)).toBe('just now')
    expect(timeAgo('2026-01-10T10:00:00+00:00', now)).toBe('2h ago')
    expect(timeAgo('2026-01-07T12:00:00Z', now)).toBe('3d ago')
  })
  it('compact drops blank strings only', () => {
    expect(compact({ a: '', b: ' ', c: 'x', d: 0 })).toEqual({ c: 'x', d: 0 })
  })
})

describe('navigation', () => {
  it('shows no made-up counts in the menu (numbers must come from real data)', () => {
    const all = navigation.flatMap(n => [n, ...(n.children ?? [])])
    const numeric = all.filter(n => n.badge && /\d/.test(n.badge)).map(n => `${n.label}: ${n.badge}`)
    expect(numeric).toEqual([])
  })
})
