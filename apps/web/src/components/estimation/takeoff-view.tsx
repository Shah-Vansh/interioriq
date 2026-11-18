'use client'
// Material & services take-off: map each measured quantity to a catalogue item (+ waste %), and preview what a saved design would add to its BOQ.
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api, CatItem, DesignVersion } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import { Alert, btn, Card, Empty, hasRole, input, Ok, PageHeader, Pill, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

interface Rule { key: string; label: string; unit: string; default_waste_pct: number; kinds: string[]; sku: string | null; waste_pct: string
  item: { id: string; name: string; unit: string; price: string; is_active: boolean } | null; unit_ok: boolean | null }
interface Row { key: string; label: string; unit: string; basis: string; measured: string; waste_pct: string; sku: string | null
  status: 'ADDED' | 'UNMAPPED' | 'MISSING' | 'ARCHIVED' | 'UNIT' | 'NONE'; item_name?: string; buy_qty?: string; buy_unit?: string; rate?: string }
const STATUS: Record<Row['status'], [string, string]> = { ADDED: ['green', 'added to BOQ'], UNMAPPED: ['amber', 'no item mapped'], MISSING: ['red', 'SKU not found'],
  ARCHIVED: ['red', 'item archived'], UNIT: ['red', 'unit mismatch'], NONE: ['stone', 'nothing measured'] }
const UNIT_HINT: Record<string, string> = { 'sq.m': 'sold per sq.m or sq.ft', 'r.m': 'sold per r.m or r.ft', 'No.': 'sold per No. / set / box' }

export function TakeoffView() {
  const role = useRole(); const can = hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'ESTIMATOR'])
  const { data: rules, setData: setRules, error } = useLoad<Rule[]>('/takeoff/rules')
  const { data: cat } = useLoad<CatItem[]>('/catalogue/items?status=active')
  const [edit, setEdit] = useState<Record<string, { sku: string; waste_pct: string }>>({})
  const a = useAction()
  useEffect(() => { if (rules) setEdit(Object.fromEntries(rules.map(r => [r.key, { sku: r.sku ?? '', waste_pct: r.waste_pct }]))) }, [rules])
  const save = () => a.run('save', async () => setRules(await api.put<Rule[]>('/takeoff/rules', Object.fromEntries(Object.entries(edit).map(([k, v]) => [k, { sku: v.sku || null, waste_pct: v.waste_pct }])))), 'Take-off rules saved — new BOQs use them')

  const [sel, setSel] = useState({ roomId: '' }); const [version, setVersion] = useState<number | null>(null)
  useEffect(() => { setVersion(null); if (!sel.roomId) return; api.get<DesignVersion[]>(`/rooms/${sel.roomId}/designs`).then(v => setVersion(v.length ? v[v.length - 1].version : null)).catch(() => {}) }, [sel.roomId])
  const { data: pv } = useLoad<{ version: number; rows: Row[]; skipped: string[]; lines: number; configured: boolean }>(sel.roomId && version ? `/rooms/${sel.roomId}/designs/${version}/takeoff` : null, [rules])
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Material take-off" subtitle="BOQs price the furniture from the design. The take-off adds what the furniture doesn't contain — false ceiling, lighting, electrical points, wall paint, flooring, skirting — measured from the saved design and priced by the catalogue item you map here (plus waste). In-house furniture keeps its own price, so nothing is counted twice." />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      <Card title="Rules" right={can && <button onClick={save} disabled={!!a.busy} className={btn.primary}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save rules</button>}>
        {!rules ? <Empty>Loading…</Empty> : <Table head={['Quantity', 'Measured in', 'Catalogue item', 'Waste %']}>{rules.map(r => {
          const opts = (cat ?? []).filter(i => r.kinds.includes(i.kind))
          return <tr key={r.key} data-rule={r.key}><td className="px-4 py-2 text-sm">{r.label}</td><td className="px-4 py-2 text-xs text-stone-500">{r.unit}<p className="text-[10px]">{UNIT_HINT[r.unit]}</p></td>
            <td className="px-4 py-2"><select aria-label={`Item for ${r.label}`} disabled={!can} value={edit[r.key]?.sku ?? ''} onChange={e => setEdit({ ...edit, [r.key]: { ...edit[r.key], sku: e.target.value } })} className={input + ' text-xs py-1'}>
              <option value="">— not included —</option>{r.sku && !opts.some(o => o.sku === r.sku) && <option value={r.sku}>{r.sku} (not active)</option>}
              {opts.map(o => <option key={o.id} value={o.sku}>{o.name} · {o.sku} · {inr(o.price)}/{o.unit}</option>)}</select>
              {r.item && r.unit_ok === false && <p className="text-[11px] text-red-700">Unit mismatch: sold per {r.item.unit}</p>}</td>
            <td className="px-4 py-2"><input aria-label={`Waste for ${r.label}`} disabled={!can} value={edit[r.key]?.waste_pct ?? ''} onChange={e => setEdit({ ...edit, [r.key]: { ...edit[r.key], waste_pct: e.target.value } })} inputMode="decimal" className={input + ' w-20 text-xs py-1'} /></td></tr> })}</Table>}
      </Card>
      <Card title="Preview for a saved design">
        <div className="mb-3"><ProjectRoomPicker onChange={s => setSel({ roomId: s.roomId })} /></div>
        {!sel.roomId ? <Empty>Pick a room.</Empty> : !version ? <Empty>This room has no saved design yet.</Empty> : !pv ? <Empty>Loading…</Empty> : <>
          <p className="text-xs text-stone-500 mb-2">Design v{pv.version}: <b>{pv.lines}</b> take-off line(s) would be added to a new BOQ.</p>
          <Table head={['Quantity', 'Measured', 'How', 'Status', 'Buys', 'Rate']} right={[1, 4, 5]}>{pv.rows.map(r => <tr key={r.key} data-takeoff={r.key}>
            <td className="px-4 py-1.5 text-xs">{r.label}</td><td className="px-4 py-1.5 text-right text-xs">{r.measured} {r.unit}</td><td className="px-4 py-1.5 text-[11px] text-stone-500">{r.basis}{r.waste_pct !== '0' ? ` · +${r.waste_pct}% waste` : ''}</td>
            <td className="px-4 py-1.5"><Pill tone={STATUS[r.status][0]} label={STATUS[r.status][1]} /></td>
            <td className="px-4 py-1.5 text-right text-xs">{r.buy_qty ? `${r.buy_qty} ${r.buy_unit}` : '—'}{r.item_name && <p className="text-[10px] text-stone-400">{r.item_name}</p>}</td>
            <td className="px-4 py-1.5 text-right text-xs">{r.rate ? inr(r.rate) : '—'}</td></tr>)}</Table></>}
      </Card>
    </div>
  )
}
