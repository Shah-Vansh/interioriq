'use client'
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api, BoqParams } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { paise, Quotation } from '@/lib/ops'
import { Alert, btn, Card, ctl, Empty, Field, input, PageHeader, Switch, useAction, useLoad } from '@/components/ui/kit'

const ROWS: [keyof Preview['totals'], string][] = [['subtotal', 'Items + labour + lump sums'], ['overhead', 'Overhead'], ['margin', 'Margin'], ['pre_tax', 'Before discount'],
  ['discount', 'Discount'], ['after_discount', 'After discount'], ['gst', 'GST'], ['grand_total', 'Grand total']]
interface Preview { params: BoqParams; totals: Record<'subtotal' | 'overhead' | 'margin' | 'pre_tax' | 'discount' | 'after_discount' | 'gst' | 'grand_total', string>; saved_totals: Record<string, string>; delta: Record<string, string>; warnings: string[] }
const FIELDS: [keyof BoqParams, string][] = [['labour_pct', 'Labour % of rate'], ['overhead_pct', 'Overhead %'], ['margin_pct', 'Margin %'], ['discount_pct', 'Discount %'], ['gst_pct', 'GST %'], ['transport', 'Transport (₹)'], ['installation', 'Installation (₹)']]

export function CostingView() {
  const { data: quotes } = useLoad<Quotation[]>('/quotations')
  const [bid, setBid] = useState('')
  const [rates, setRates] = useState<BoqParams | null>(null)
  const [pv, setPv] = useState<Preview | null>(null)
  const a = useAction()
  useEffect(() => { if (!bid && quotes?.length) setBid(quotes[0].id) }, [quotes, bid])
  useEffect(() => { if (!bid) return; setPv(null); api.get<{ params: BoqParams; gst_enabled: boolean; include_takeoff?: boolean }>(`/boqs/${bid}`).then(b => setRates({ ...b.params, gst_enabled: b.gst_enabled, include_takeoff: Boolean(b.include_takeoff) })).catch(() => {}) }, [bid])
  const run = () => rates && a.run('pv', async () => setPv(await api.post<Preview>(`/boqs/${bid}/preview`, rates)))
  return (
    <div className="space-y-5 max-w-[1100px]">
      <PageHeader title="Costing (what-if)" subtitle="Try other margins, discounts or lump sums on a saved BOQ. The server re-prices it with today's catalogue; nothing is saved — create a new BOQ version in Estimation → BOQ to keep a change." />
      <select value={bid} onChange={e => setBid(e.target.value)} aria-label="Quotation" className={ctl + ' min-w-80'}>
        {!quotes?.length && <option value="">No BOQs yet</option>}{quotes?.map(q => <option key={q.id} value={q.id}>{q.quotation_no} · {q.project_name} · {q.room_name}</option>)}</select>
      {!quotes?.length ? <Empty>Create a BOQ first.</Empty> : rates && <div className="grid md:grid-cols-2 gap-4">
        <Card title="Rates">
          <div className="mb-3 space-y-2"><Switch label="Include GST" checked={rates.gst_enabled !== false && rates.gst_enabled !== 'false'} onChange={v => setRates({ ...rates, gst_enabled: v })} />
            <Switch label="Include material take-off" checked={rates.include_takeoff === true || rates.include_takeoff === 'true'} onChange={v => setRates({ ...rates, include_takeoff: v })} /></div>
          <div className="grid grid-cols-2 gap-3">{FIELDS.map(([k, l]) => <Field key={k} label={l}><input value={String(rates[k] ?? '')} onChange={e => setRates({ ...rates, [k]: e.target.value })}
            disabled={k === 'gst_pct' && (rates.gst_enabled === false || rates.gst_enabled === 'false')} inputMode="decimal" className={input} /></Field>)}</div>
          <button onClick={run} disabled={!!a.busy} className={btn.primary + ' mt-3 w-full'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Calculate</button>
          {a.error && <div className="mt-2"><Alert>{a.error}</Alert></div>}
        </Card>
        <Card title="Result vs the saved BOQ">
          {!pv ? <Empty>Change a rate and press Calculate.</Empty> : <table className="w-full text-sm" data-testid="preview"><tbody className="divide-y divide-stone-50">
            {ROWS.map(([k, l]) => { const d = pv.delta[k] ?? '0.00'; const neg = d.startsWith('-'); const zero = paise(d) === BigInt(0)
              return <tr key={k} className={k === 'grand_total' ? 'font-semibold' : ''}><td className="py-1.5 text-stone-600">{l}</td>
              <td className="py-1.5 text-right">{inr(pv.totals[k])}</td>
              <td className={`py-1.5 text-right text-xs ${zero ? 'text-stone-300' : neg ? 'text-green-700' : 'text-red-700'}`}>{zero ? '±0' : (neg ? '−' : '+') + inr(d.replace('-', ''))}</td></tr> })}
          </tbody></table>}
          {pv?.warnings.map((w, i) => <p key={i} className="text-xs text-amber-800 mt-2">{w}</p>)}
        </Card>
      </div>}
    </div>
  )
}
