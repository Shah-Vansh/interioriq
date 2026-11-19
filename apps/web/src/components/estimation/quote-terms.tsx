'use client'
// M26: payment schedule + terms — company default (Settings → Company) and each quotation's own copy (BOQ screen).
// Amounts always come from the server; the browser only checks that the percentages add up to 100 while typing.
import { useEffect, useState } from 'react'
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { inrStr } from '@/lib/utils'
import { Milestone, pctTotal } from '@/lib/quote-terms-logic'
import { Alert, btn, Card, Empty, hasRole, input, Ok, useAction, useLoad, useRole } from '@/components/ui/kit'

interface Terms { schedule: Milestone[]; terms: string[] }
interface BoqTerms extends Terms { boq_id: string; grand_total: string; own: boolean; editable: boolean; locked_reason: string | null }

function Editor({ value, onSave, onCancel, saveLabel }: { value: Terms; onSave: (v: Terms) => Promise<unknown>; onCancel?: () => void; saveLabel: string }) {
  const [rows, setRows] = useState<Milestone[]>(value.schedule.map(r => ({ label: r.label, pct: r.pct })))
  const [terms, setTerms] = useState(value.terms.join('\n')); const a = useAction()
  const total = pctTotal(rows); const ok = total === 10000 && rows.every(r => r.label.trim())
  const set = (i: number, k: 'label' | 'pct', v: string) => setRows(rows.map((r, j) => j === i ? { ...r, [k]: v } : r))
  return <div className="space-y-3" data-testid="terms-editor">
    <table className="w-full text-sm"><thead><tr className="text-[11px] text-stone-400 uppercase"><th className="text-left font-medium pb-1">Milestone</th><th className="text-right font-medium pb-1 w-24">%</th><th className="w-8" /></tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>
        <td className="pr-2 py-1"><input aria-label={`Milestone ${i + 1} name`} value={r.label} onChange={e => set(i, 'label', e.target.value)} maxLength={80} className={input + ' py-1'} /></td>
        <td className="py-1"><input aria-label={`Milestone ${i + 1} percent`} value={r.pct} onChange={e => set(i, 'pct', e.target.value)} inputMode="decimal" className={input + ' py-1 text-right font-mono'} /></td>
        <td className="pl-1"><button type="button" aria-label={`Remove milestone ${i + 1}`} disabled={rows.length <= 1} onClick={() => setRows(rows.filter((_, j) => j !== i))} className="p-1 text-stone-400 hover:text-red-600 disabled:opacity-30"><Trash2 className="w-3.5 h-3.5" /></button></td></tr>)}</tbody>
      <tfoot><tr><td className="pt-1">{rows.length < 10 && <button type="button" onClick={() => setRows([...rows, { label: '', pct: '' }])} className={btn.small}><Plus className="w-3 h-3" />Add milestone</button>}</td>
        <td className={`text-right font-mono text-xs pt-1 ${total === 10000 ? 'text-green-700' : 'text-red-700'}`} data-testid="pct-total">{total === null ? '—' : `${(total / 100).toFixed(2).replace(/\.00$/, '')}%`}</td><td /></tr></tfoot></table>
    {total !== null && total !== 10000 && <p className="text-[11px] text-red-700">The milestones must add up to exactly 100%.</p>}
    <label className="block"><span className="text-[11px] font-medium text-stone-500">Terms and conditions — one per line</span>
      <textarea aria-label="Terms and conditions" rows={6} value={terms} onChange={e => setTerms(e.target.value)} className={input + ' mt-1 text-xs'} /></label>
    {a.error && <Alert>{a.error}</Alert>}
    <div className="flex gap-2"><button type="button" disabled={!ok || !!a.busy} onClick={() => a.run('save', () => onSave({ schedule: rows.map(r => ({ label: r.label.trim(), pct: r.pct.trim() })), terms: terms.split('\n').map(t => t.trim()).filter(Boolean) }))} className={btn.primary}>
      {a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{saveLabel}</button>
      {onCancel && <button type="button" onClick={onCancel} className={btn.ghost}>Cancel</button>}</div>
  </div>
}

/** BOQ screen: this quotation's schedule (amounts from the server) + terms; editable until approved / paid / invoiced. */
export function QuoteTermsCard({ boqId, onChanged }: { boqId: string; onChanged?: () => void }) {
  const { data, setData, error } = useLoad<BoqTerms>(`/boqs/${boqId}/terms`, [boqId])
  const [editing, setEditing] = useState(false); const [ok, setOk] = useState('')
  useEffect(() => { setEditing(false); setOk('') }, [boqId])
  if (error) return <Alert>{error}</Alert>
  if (!data) return <div className="bg-white border border-stone-200 rounded-lg p-5"><Empty>Loading…</Empty></div>
  return <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-5" data-testid="quote-terms">
    <div className="flex items-center gap-2 mb-3"><h3 className="text-sm font-semibold flex-1">Payment schedule & terms</h3>
      {data.editable && !editing && <button onClick={() => { setEditing(true); setOk('') }} className={btn.small}><Pencil className="w-3 h-3" />Edit</button>}</div>
    {ok && <Ok>{ok}</Ok>}
    {editing ? <Editor value={data} saveLabel="Save for this quotation" onCancel={() => setEditing(false)}
      onSave={async v => { setData(await api.put<BoqTerms>(`/boqs/${boqId}/terms`, v)); setEditing(false); setOk('Saved — the quotation PDF now uses this schedule.'); onChanged?.() }} /> : <>
      <table className="w-full text-xs"><tbody className="divide-y divide-stone-50">{data.schedule.map(r => <tr key={r.label}><td className="py-1.5">{r.label}</td><td className="py-1.5 text-right font-mono text-stone-500 w-16">{r.pct}%</td>
        <td className="py-1.5 text-right font-mono w-32">Rs. {inrStr(r.amount ?? '0')}</td></tr>)}</tbody></table>
      {data.terms.length > 0 ? <ol className="mt-3 list-decimal pl-4 space-y-0.5 text-[11px] text-stone-600">{data.terms.map((t, i) => <li key={i}>{t}</li>)}</ol>
        : <p className="mt-3 text-[11px] text-stone-400">No terms printed on this quotation.</p>}
      {data.locked_reason && <p className="mt-2 text-[11px] text-stone-400">{data.locked_reason}</p>}
      {!data.own && <p className="mt-1 text-[11px] text-stone-400">Saved before schedules could be edited — this is the standard schedule it was printed with.</p>}
    </>}
  </div>
}

/** Settings → Company: the default that every NEW quotation starts with. */
export function DefaultQuoteTerms() {
  const role = useRole(); const can = hasRole(role, ['ADMIN', 'PROJECT_MANAGER'])
  const { data, setData, error } = useLoad<Terms & { customised: boolean }>('/settings/quote-terms')
  const [k, setK] = useState(0); const a = useAction()
  return <Card title="Default payment schedule & terms">
    <p className="text-xs text-stone-500 mb-3">Every new quotation starts with this. You can change it on each quotation (Estimation → BOQ) until it is approved. Changing it here never alters quotations already made.</p>
    {error && <Alert>{error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}{a.error && <Alert>{a.error}</Alert>}
    {!data ? <Empty>Loading…</Empty> : can ? <div data-testid="default-terms"><Editor key={k} value={data} saveLabel="Save default"
      onSave={async v => { setData(await api.put('/settings/quote-terms', v)); a.setOk('Default saved — new quotations will use it.') }} />
      {data.customised && <button onClick={() => a.run('reset', async () => { setData(await api.delete('/settings/quote-terms')); setK(k + 1) }, 'Back to the standard schedule')} className={btn.ghost + ' mt-2'}>Reset to standard</button>}</div>
      : <ul className="text-xs space-y-0.5">{data.schedule.map(r => <li key={r.label}>{r.label} — {r.pct}%</li>)}</ul>}
  </Card>
}
