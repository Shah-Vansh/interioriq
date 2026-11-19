import { describe, expect, it } from 'vitest'
import { pctTotal } from './quote-terms-logic'

describe('payment schedule percentages', () => {
  it('adds in hundredths so thirds still make exactly 100', () => {
    expect(pctTotal([{ label: 'A', pct: '33.33' }, { label: 'B', pct: '33.33' }, { label: 'C', pct: '33.34' }])).toBe(10000)
    expect(pctTotal([{ label: 'A', pct: '0.1' }, { label: 'B', pct: '0.2' }, { label: 'C', pct: '99.7' }])).toBe(10000)
  })
  it('reports a wrong total and refuses non-numbers', () => {
    expect(pctTotal([{ label: 'A', pct: '60' }, { label: 'B', pct: '30' }])).toBe(9000)
    expect(pctTotal([{ label: 'A', pct: 'abc' }])).toBeNull()
    expect(pctTotal([{ label: 'A', pct: ' ' }])).toBeNull()
  })
})
