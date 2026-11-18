/** The name if it fits inside the box (≈6 px per character at 11 px), else its first word, else nothing (hover shows the full name). */
export function fitLabel(name: string, wpx: number, hpx: number): string {
  if (hpx < 13) return ''
  const fits = (t: string) => t.length * 6.2 + 6 <= wpx
  if (fits(name)) return name
  const short = name.split(/\s+[—–-]\s+|\s+\(/)[0]
  if (fits(short)) return short
  const first = name.split(' ')[0]
  return fits(first) ? first : ''
}
