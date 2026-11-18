import { describe, expect, it } from 'vitest'
import { fitLabel } from './plan-label'

describe('plan labels fit their boxes', () => {
  it('keeps the full name when there is room', () => { expect(fitLabel('Study Desk', 200, 40)).toBe('Study Desk') })
  it('drops the finish after the dash, then falls back to the first word, then to nothing', () => {
    expect(fitLabel('3-Seater Sofa — Grey Linen', 110, 40)).toBe('3-Seater Sofa')
    expect(fitLabel('Kitchen Tall Unit 600 (fridge / pantry)', 140, 40)).toBe('Kitchen Tall Unit 600')
    expect(fitLabel('Kitchen Base Unit 900', 60, 40)).toBe('Kitchen')
    expect(fitLabel('Dining Chair — Walnut', 20, 40)).toBe('')
  })
  it('hides labels in boxes too thin for text', () => { expect(fitLabel('Bed', 300, 8)).toBe('') })
})
