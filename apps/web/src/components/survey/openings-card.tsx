'use client'
// Doors & windows of a room (survey data). The server checks they fit on the wall and don't overlap, and re-checks the latest design.
import { useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { fitScale } from '@/lib/ops'
import { Alert, btn, ctl, Empty, Field, hasRole, input, Ok, Pill, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

export interface Opening { id: string; kind: 'DOOR' | 'WINDOW'; wall: 'N' | 'E' | 'S' | 'W'; offset: number; width: number; height: number; sill: number; swing: string | null; label: string }
interface Resp { openings: Opening[]; latest_design: { version: number; valid: boolean; errors: string[]; warnings: string[] } | null }
const WALLS: Record<string, string> = { N: 'North (top of plan)', E: 'East (right)', S: 'South (bottom)', W: 'West (left)' }
const SWINGS: Record<string, string> = { INWARD_RIGHT: 'Opens inward, hinge at the far end (offset + width)', INWARD_LEFT: 'Opens inward, hinge at the offset end', OUTWARD: 'Opens outward', SLIDING: 'Sliding' }

/** Openings drawn on a plan (north up). Shared by the survey card and the design drawings. */
export function OpeningsSvg({ ops, L, W, sx, sy, s }: { ops: Opening[]; L: number; W: number; sx: (x: number) => number; sy: (y: number) => number; s: number }) {
  return <g>{ops.map(o => {
    const a = o.offset, w = o.width
    const [p0, p1, n] = ({ S: [[a, 0], [a + w, 0], [0, 1]], N: [[a, W], [a + w, W], [0, -1]], W: [[0, a], [0, a + w], [1, 0]], E: [[L, a], [L, a + w], [-1, 0]] } as const)[o.wall]
    if (o.kind === 'WINDOW') return <g key={o.id} data-opening="WINDOW"><line x1={sx(p0[0])} y1={sy(p0[1])} x2={sx(p1[0])} y2={sy(p1[1])} stroke="#38bdf8" strokeWidth={6} />
      <text x={sx((p0[0] + p1[0]) / 2 + n[0] * 260)} y={sy((p0[1] + p1[1]) / 2 + n[1] * 260)} fontSize={10} textAnchor="middle" fill="#0369a1">{o.label}</text></g>
    const inward = (o.swing ?? '').startsWith('INWARD'); const hinge = o.swing === 'INWARD_RIGHT' ? p1 : p0; const other = o.swing === 'INWARD_RIGHT' ? p0 : p1
    const leaf = [hinge[0] + n[0] * w, hinge[1] + n[1] * w]
    const r = w * s; const sweep = ((other[0] - hinge[0]) * n[1] - (other[1] - hinge[1]) * n[0]) > 0 ? 1 : 0
    return <g key={o.id} data-opening="DOOR"><line x1={sx(p0[0])} y1={sy(p0[1])} x2={sx(p1[0])} y2={sy(p1[1])} stroke="#fafaf9" strokeWidth={6} />
      {inward ? <><line x1={sx(hinge[0])} y1={sy(hinge[1])} x2={sx(leaf[0])} y2={sy(leaf[1])} stroke="#92400e" strokeWidth={2} />
        <path d={`M ${sx(leaf[0])} ${sy(leaf[1])} A ${r} ${r} 0 0 ${sweep} ${sx(other[0])} ${sy(other[1])}`} fill="none" stroke="#92400e" strokeDasharray="4 3" /></>
        : <line x1={sx(p0[0]) + n[0] * 4} y1={sy(p0[1]) - n[1] * 4} x2={sx(p1[0]) + n[0] * 4} y2={sy(p1[1]) - n[1] * 4} stroke="#92400e" strokeWidth={3} />}
      <text x={sx((p0[0] + p1[0]) / 2 + n[0] * (inward ? w + 180 : 260))} y={sy((p0[1] + p1[1]) / 2 + n[1] * (inward ? w + 180 : 260))} fontSize={10} textAnchor="middle" fill="#92400e">{o.label}</text></g>
  })}</g>
}

export function OpeningsCard({ roomId, L, W }: { roomId: string; L: number | null; W: number | null }) {
  const role = useRole(); const can = hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER', 'INTERIOR_DESIGNER'])
  const { data, setData, error } = useLoad<Resp>(`/rooms/${roomId}/openings`)
  const [f, setF] = useState({ kind: 'DOOR', wall: 'S', offset_mm: '', width_mm: '900', height_mm: '2100', sill_mm: '900', swing: 'INWARD_RIGHT', label: '' })
  const a = useAction()
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(p => ({ ...p, [k]: e.target.value, ...(k === 'kind' ? (e.target.value === 'WINDOW' ? { width_mm: '1200', height_mm: '1200' } : { width_mm: '900', height_mm: '2100' }) : {}) }))
  const add = (e: React.FormEvent) => {
    e.preventDefault()
    for (const k of (['offset_mm', 'width_mm', 'height_mm', ...(f.kind === 'WINDOW' ? ['sill_mm'] : [])] as (keyof typeof f)[])) if (!/^\d+(\.\d+)?$/.test(f[k])) { a.setError('Enter sizes in whole millimetres'); return }
    a.run('add', async () => setData(await api.post<Resp>(`/rooms/${roomId}/openings`, { kind: f.kind, wall: f.wall, offset_mm: Number(f.offset_mm), width_mm: Number(f.width_mm), height_mm: Number(f.height_mm),
      sill_mm: f.kind === 'WINDOW' ? Number(f.sill_mm) : 0, swing: f.kind === 'DOOR' ? f.swing : undefined, label: f.label || undefined })), `${f.kind === 'DOOR' ? 'Door' : 'Window'} added`)
  }
  const fit = L && W ? fitScale(L, W, 360, 260, 28) : null
  return (
    <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4 space-y-3" data-testid="openings-card">
      <div><h2 className="text-sm font-semibold text-stone-800">Doors & windows</h2>
        <p className="text-xs text-stone-500">Offset is measured along the wall from its left end on the plan — west end for the north/south walls, south end for the west/east walls. Doors keep their swing (or 450 mm in front) clear; the AI Designer and the validator respect them, the switchboard goes beside the door, and paint/skirting take them off.</p></div>
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {data?.latest_design && !data.latest_design.valid && <Alert>Latest design v{data.latest_design.version} now has problems: {data.latest_design.errors.join('; ')}. Open it in the 3D editor to fix and save a new version.</Alert>}
      {data?.latest_design?.warnings.filter(w => w.includes('covers')).map(w => <p key={w} className="text-xs text-amber-800">⚠ {w}</p>)}
      <div className="grid md:grid-cols-2 gap-4 items-start">
        {fit && data ? <svg viewBox={`0 0 ${fit.w} ${fit.h}`} className="w-full h-auto bg-stone-50 rounded" role="img" aria-label="Room openings plan">
          <rect x={fit.pad} y={fit.pad} width={L! * fit.s} height={W! * fit.s} fill="#fff" stroke="#292524" strokeWidth={4} />
          <OpeningsSvg ops={data.openings} L={L!} W={W!} s={fit.s} sx={x => fit.pad + x * fit.s} sy={y => fit.pad + (W! - y) * fit.s} />
          <text x={fit.w - 14} y={18} fontSize={11} fill="#b45309" fontWeight={700} textAnchor="middle">N ↑</text></svg>
          : <Empty>Add Length and Width to see the plan.</Empty>}
        <div>{!data ? <Empty>Loading…</Empty> : data.openings.length === 0 ? <p className="text-xs text-stone-400">No doors or windows recorded.</p> :
          <Table head={['', 'Wall', 'Offset', 'W × H', '']}>{data.openings.map(o => <tr key={o.id} data-opening-row={o.label}>
            <td className="px-2 py-1.5 text-xs"><Pill tone={o.kind === 'DOOR' ? 'amber' : 'blue'} label={o.label} /></td><td className="px-2 py-1.5 text-xs">{o.wall}</td>
            <td className="px-2 py-1.5 text-xs">{o.offset}</td><td className="px-2 py-1.5 text-xs">{o.width} × {o.height}{o.kind === 'WINDOW' ? ` @${o.sill}` : ''}<p className="text-[10px] text-stone-400">{o.swing ? SWINGS[o.swing] : ''}</p></td>
            <td className="px-2 py-1.5">{can && <button onClick={() => a.run(o.id, async () => setData(await api.delete<Resp>(`/openings/${o.id}`)))} aria-label={`Remove ${o.label}`} className={btn.small}><Trash2 className="w-3 h-3" /></button>}</td></tr>)}</Table>}</div>
      </div>
      {can && <form onSubmit={add} className="grid grid-cols-2 md:grid-cols-4 gap-2 items-end border-t border-stone-100 pt-3">
        <Field label="Type"><select aria-label="Opening type" value={f.kind} onChange={set('kind')} className={input}><option value="DOOR">Door</option><option value="WINDOW">Window</option></select></Field>
        <Field label="Wall"><select aria-label="Wall" value={f.wall} onChange={set('wall')} className={input}>{Object.entries(WALLS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Offset (mm)"><input aria-label="Offset" value={f.offset_mm} onChange={set('offset_mm')} inputMode="numeric" className={input} /></Field>
        <Field label="Width (mm)"><input aria-label="Opening width" value={f.width_mm} onChange={set('width_mm')} inputMode="numeric" className={input} /></Field>
        <Field label="Height (mm)"><input aria-label="Opening height" value={f.height_mm} onChange={set('height_mm')} inputMode="numeric" className={input} /></Field>
        {f.kind === 'WINDOW' ? <Field label="Sill height (mm)"><input aria-label="Sill height" value={f.sill_mm} onChange={set('sill_mm')} inputMode="numeric" className={input} /></Field>
          : <Field label="Swing"><select aria-label="Swing" value={f.swing} onChange={set('swing')} className={input}>{Object.entries(SWINGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>}
        <Field label="Label (optional)"><input aria-label="Opening label" value={f.label} onChange={set('label')} placeholder="Main door" className={input} /></Field>
        <button disabled={!!a.busy} className={btn.primary}>{a.busy === 'add' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}Add {f.kind === 'DOOR' ? 'door' : 'window'}</button>
      </form>}
    </div>
  )
}
