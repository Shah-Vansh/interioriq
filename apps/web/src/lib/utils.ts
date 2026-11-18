import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
export function fmt(n: number) { return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 }) }
export function fmtDate(d: string | Date) {
  return new Intl.DateTimeFormat('en-IN',{day:'2-digit',month:'short',year:'numeric'}).format(new Date(d))
}

/** Display only: Indian digit grouping for a decimal STRING from the API ('476753.19' -> '4,76,753.19'). Never used for arithmetic. */
export function inrStr(v: string | number): string {
  const m = String(v).trim().match(/^(-?)(\d+)(?:\.(\d+))?$/)
  if (!m) return String(v)
  const [, sign, whole, frac = ''] = m
  const head = whole.length > 3 ? whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + whole.slice(-3) : whole
  return `${sign}${head}.${(frac + '00').slice(0, 2)}`
}
