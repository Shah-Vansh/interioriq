// Display helpers for the catalogue. No money arithmetic happens here: prices arrive as server strings and are only re-grouped for display.
import type { CatItem, CatKind } from './api'

export interface KindInfo { kind: CatKind; title: string; singular: string; subtitle: string; unit: string; needsSize: boolean; categories: string[] }
export const KINDS: Record<CatKind, KindInfo> = {
  FURNITURE: { kind: 'FURNITURE', title: 'Furniture', singular: 'furniture item', unit: 'No.', needsSize: true,
    subtitle: 'Items the AI Designer and 3D editor can place. Size is required; archived items are no longer offered.',
    categories: ['Bed', 'Wardrobe', 'Sofa', 'Chair', 'Side table', 'TV unit', 'Dining', 'Study', 'Dresser', 'Shoe rack', 'Kitchen'] },
  MATERIAL: { kind: 'MATERIAL', title: 'Materials', singular: 'material', unit: 'sheet', needsSize: false,
    subtitle: 'Boards, laminates, veneers, paint, flooring, glass and stone with their purchase unit.',
    categories: ['Plywood', 'MDF', 'Laminate', 'Veneer', 'Paint', 'Flooring', 'Glass', 'Stone', 'Fabric', 'Wallpaper', 'Edge band'] },
  LIGHTING: { kind: 'LIGHTING', title: 'Lighting', singular: 'light', unit: 'No.', needsSize: false,
    subtitle: 'Downlights, profiles, strips, pendants and drivers.',
    categories: ['Downlight', 'Spotlight', 'Profile light', 'LED strip', 'Pendant', 'Wall light', 'Driver', 'Fan'] },
  HARDWARE: { kind: 'HARDWARE', title: 'Hardware', singular: 'hardware item', unit: 'No.', needsSize: false,
    subtitle: 'Hinges, channels, handles, locks and kitchen fittings.',
    categories: ['Hinge', 'Channel', 'Handle', 'Lock', 'Tandem box', 'Lift-up', 'Basket', 'Profile', 'Screw', 'Adhesive'] },
}

/** '124000.00' → '₹1,24,000.00' (Indian grouping) by string manipulation only, so no float rounding can creep in. */
export function inr(price: string | null | undefined): string {
  if (price == null || price === '') return '—'
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(price.trim())
  if (!m) return price
  const [, sign, int, frac = ''] = m
  const last3 = int.slice(-3), rest = int.slice(0, -3)
  const grouped = rest ? rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3 : last3
  return `${sign}₹${grouped}.${(frac + '00').slice(0, 2)}`
}

export function dimsText(i: Pick<CatItem, 'length_mm' | 'width_mm' | 'height_mm'>): string {
  const d = [i.length_mm, i.width_mm, i.height_mm]
  if (d.every(v => v == null)) return ''
  return d.map(v => (v == null ? '?' : String(Math.round(v)))).join(' × ') + ' mm'
}

export function stockText(i: Pick<CatItem, 'stock' | 'stock_status' | 'unit' | 'min_stock'>): string {
  if (i.stock_status === 'OUT') return 'Out of stock'
  if (i.stock_status === 'LOW') return `Low: ${i.stock} ${i.unit} (reorder at ${i.min_stock})`
  return `${i.stock} ${i.unit}`
}

/** Validate the stock-change box before sending: whole non-zero number, and removal can't exceed stock (the server re-checks). */
export function parseDelta(raw: string, direction: 'in' | 'out', stock: number): { delta: number } | { error: string } {
  const s = raw.trim()
  if (!/^\d+$/.test(s)) return { error: 'Enter a whole number of units' }
  const n = parseInt(s, 10)
  if (n === 0) return { error: 'Quantity must be more than 0' }
  if (direction === 'out' && n > stock) return { error: `Only ${stock} in stock` }
  return { delta: direction === 'in' ? n : -n }
}

/** Price box → canonical string for the API, or an error. Accepts '1,24,000', '₹ 850.5'. Never parses to float. */
export function cleanPrice(raw: string): { price: string } | { error: string } {
  const s = raw.replace(/[₹,\s]/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return { error: 'Price must be a number with at most 2 decimals' }
  return { price: s }
}

export function csvTemplate(kind: CatKind): string {
  const ex: Record<CatKind, string> = {
    FURNITURE: 'BED-QN-OAK-001,Queen bed — Oak,FURNITURE,Bed,No.,68000,2,1,1650,2080,1100,Oak veneer,Natural,,',
    MATERIAL: 'PLY-BWP-18,BWP plywood 18mm 8x4,MATERIAL,Plywood,sheet,2850,40,10,,,,BWP,,,',
    LIGHTING: 'LGT-DL-7W-WW,LED downlight 7W warm white,LIGHTING,Downlight,No.,850,60,20,,,,Aluminium,White,,',
    HARDWARE: 'HNG-SC-110,Soft-close hinge 110°,HARDWARE,Hinge,No.,185,200,50,,,,Steel,Nickel,,',
  }
  return 'sku,name,kind,category,unit,price,stock,min_stock,length_mm,width_mm,height_mm,material,colour,supplier,description\n' + ex[kind] + '\n'
}

// Mirrors apps/api/app/routers/catalogue.py so buttons a role can't use aren't shown (the server still enforces it).
const WRITE = ['SUPER_ADMIN', 'ADMIN', 'PROJECT_MANAGER', 'PROCUREMENT_MANAGER']
export const canEditCatalogue = (role?: string | null) => !!role && WRITE.includes(role)
export const canMoveStock = (role?: string | null) => !!role && (WRITE.includes(role) || role === 'INVENTORY_MANAGER')
