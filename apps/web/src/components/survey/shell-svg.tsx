'use client'
// Room outline + beams / columns / pillars / ceiling drops on a plan (north up). Shared by the survey cards and the design drawings.
import type { Pt, Structure } from '@/lib/room-shell'

export function OutlineSvg({ outline, sx, sy, fill = '#fff', stroke = '#292524', width = 4 }: { outline: Pt[]; sx: (x: number) => number; sy: (y: number) => number; fill?: string; stroke?: string; width?: number }) {
  return <polygon data-outline={outline.length} points={outline.map(([x, y]) => `${sx(x)},${sy(y)}`).join(' ')} fill={fill} stroke={stroke} strokeWidth={width} strokeLinejoin="miter" />
}

export function StructuresSvg({ items, sx, sy, labels = true }: { items: Structure[]; sx: (x: number) => number; sy: (y: number) => number; labels?: boolean }) {
  return <g>{items.map(s => {
    const x = sx(s.x), y = sy(s.y + s.width), w = sx(s.x + s.length) - sx(s.x), h = sy(s.y) - sy(s.y + s.width)
    const solid = s.kind === 'COLUMN' || s.kind === 'PILLAR'
    return <g key={s.id} data-structure={s.kind}>
      <rect x={x} y={y} width={w} height={h} fill={solid ? '#57534e' : 'rgba(192,38,211,0.08)'} stroke={solid ? '#292524' : '#c026d3'} strokeWidth={solid ? 1 : 1.2} strokeDasharray={solid ? undefined : '5 3'} />
      {solid && <><line x1={x} y1={y} x2={x + w} y2={y + h} stroke="#fff" strokeWidth={0.8} /><line x1={x + w} y1={y} x2={x} y2={y + h} stroke="#fff" strokeWidth={0.8} /></>}
      {labels && <text x={x + w / 2} y={solid ? y - 3 : y + h / 2 + 3} fontSize={9} textAnchor="middle" fill={solid ? '#44403c' : '#a21caf'}>{s.label}{solid ? '' : ` · ${s.depth} deep`}</text>}
    </g>
  })}</g>
}
