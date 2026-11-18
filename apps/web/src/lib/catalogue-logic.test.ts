import { describe, expect, it } from 'vitest'
import { canEditCatalogue, canMoveStock, cleanPrice, csvTemplate, dimsText, inr, KINDS, parseDelta, stockText } from './catalogue-logic'
import { navigation } from './nav'

describe('inr — formats server price strings without float maths', () => {
  it.each([['124000.00', '₹1,24,000.00'], ['850.5', '₹850.50'], ['0.00', '₹0.00'], ['12345678.9', '₹1,23,45,678.90'], ['999', '₹999.00'],
    ['100000000.00', '₹10,00,00,000.00'], ['1000.10', '₹1,000.10']])('%s → %s', (a, b) => expect(inr(a)).toBe(b))
  it('keeps a huge value exact (a float would round it)', () => expect(inr('9007199254740993.07')).toBe('₹9,00,71,99,25,47,40,993.07'))
  it('shows a dash for nothing and leaves junk untouched', () => { expect(inr(null)).toBe('—'); expect(inr('n/a')).toBe('n/a') })
})

describe('price and stock boxes', () => {
  it('accepts Indian-formatted prices and refuses 3 decimals', () => {
    expect(cleanPrice('₹ 1,24,000')).toEqual({ price: '124000' })
    expect(cleanPrice('850.5')).toEqual({ price: '850.5' })
    expect(cleanPrice('12.345')).toHaveProperty('error')
    expect(cleanPrice('-5')).toHaveProperty('error')
    expect(cleanPrice('')).toHaveProperty('error')
  })
  it('stock in/out must be a positive whole number and cannot remove more than is there', () => {
    expect(parseDelta('5', 'in', 0)).toEqual({ delta: 5 })
    expect(parseDelta('3', 'out', 3)).toEqual({ delta: -3 })
    expect(parseDelta('4', 'out', 3)).toEqual({ error: 'Only 3 in stock' })
    expect(parseDelta('0', 'in', 3)).toHaveProperty('error')
    expect(parseDelta('1.5', 'in', 3)).toHaveProperty('error')
    expect(parseDelta('-2', 'in', 3)).toHaveProperty('error')
  })
})

describe('display', () => {
  it('sizes', () => {
    expect(dimsText({ length_mm: 1930, width_mm: 2030, height_mm: 1200 })).toBe('1930 × 2030 × 1200 mm')
    expect(dimsText({ length_mm: null, width_mm: null, height_mm: null })).toBe('')
    expect(dimsText({ length_mm: 2440, width_mm: 1220, height_mm: null })).toBe('2440 × 1220 × ? mm')
  })
  it('stock text', () => {
    expect(stockText({ stock: 0, stock_status: 'OUT', unit: 'No.', min_stock: 2 })).toBe('Out of stock')
    expect(stockText({ stock: 2, stock_status: 'LOW', unit: 'sheet', min_stock: 5 })).toBe('Low: 2 sheet (reorder at 5)')
    expect(stockText({ stock: 40, stock_status: 'OK', unit: 'sheet', min_stock: 5 })).toBe('40 sheet')
  })
  it('only furniture requires a size', () => {
    expect(Object.values(KINDS).filter(k => k.needsSize).map(k => k.kind)).toEqual(['FURNITURE'])
  })
  it('every CSV template has the same columns as its header row', () => {
    for (const k of Object.keys(KINDS) as (keyof typeof KINDS)[]) {
      const [head, row] = csvTemplate(k).trim().split('\n')
      expect(row.split(',').length).toBe(head.split(',').length)
      expect(row.split(',')[2]).toBe(k)
    }
  })
})

describe('roles (mirror of the API)', () => {
  it('who may edit and who may move stock', () => {
    expect(['SUPER_ADMIN', 'ADMIN', 'PROJECT_MANAGER', 'PROCUREMENT_MANAGER'].every(canEditCatalogue)).toBe(true)
    expect(canEditCatalogue('INVENTORY_MANAGER')).toBe(false)
    expect(canMoveStock('INVENTORY_MANAGER')).toBe(true)
    expect(['INTERIOR_DESIGNER', 'CLIENT', null, undefined].some(r => canEditCatalogue(r) || canMoveStock(r))).toBe(false)
  })
})

describe('sidebar', () => {
  it('lists all five catalogue screens', () => {
    const cat = navigation.find(s => s.label === 'Catalogue')!
    expect((cat.children ?? []).map(c => c.href)).toEqual(['/catalogue/furniture', '/catalogue/materials', '/catalogue/lighting', '/catalogue/hardware', '/catalogue/suppliers'])
  })
})
