'use client'
// M34: Finance → Accounting export — Tally XML (Gateway of Tally → Import → Vouchers) or a day-book CSV for any software. Nothing is posted anywhere.
import { useEffect, useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { api, downloadFile } from '@/lib/api'
import { Alert, btn, Card, Empty, Field, hasRole, input, Ok, PageHeader, useAction, useLoad, useRole } from '@/components/ui/kit'

interface TallySettings { values: Record<string, string>; labels: Record<string, string>; kinds: string[] }
const KIND_LABEL: Record<string, string> = { sales: 'Sales (invoices)', credit: 'Credit notes', receipt: 'Receipts (client payments)', purchase: 'Purchases (supplier bills)', payment: 'Payments (to suppliers)' }
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
function monthStart() { const d = new Date(); return iso(new Date(d.getFullYear(), d.getMonth(), 1)) }

export function AccountingExport() {
  const role = useRole(); const admin = hasRole(role, ['ADMIN'])
  const { data: st, setData, error } = useLoad<TallySettings>('/settings/tally')
  const [from, setFrom] = useState(monthStart()); const [to, setTo] = useState(iso(new Date()))
  const [kinds, setKinds] = useState<string[]>(['sales', 'credit', 'receipt', 'purchase', 'payment']); const [masters, setMasters] = useState(true)
  const [sum, setSum] = useState<{ vouchers: number; by_type: Record<string, number>; parties: number } | null>(null)
  const [f, setF] = useState<Record<string, string>>({}); const a = useAction(); const s = useAction()
  useEffect(() => { if (st) setF(st.values) }, [st])
  const q = `date_from=${from}&date_to=${to}&kinds=${kinds.join(',')}`
  useEffect(() => { setSum(null); if (!kinds.length || !from || !to) return; api.get<typeof sum>(`/exports/summary?${q}`).then(setSum).catch(e => a.setError(e.message)) }, [q]) // eslint-disable-line
  const toggle = (k: string) => setKinds(kinds.includes(k) ? kinds.filter(x => x !== k) : [...kinds, k])
  return (
    <div className="space-y-5 max-w-[1000px]">
      <PageHeader title="Accounting export" subtitle="Take invoices, credit notes, receipts, supplier bills and payments into Tally (or any accounting software). Nothing is posted automatically — you download a file and import it." />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      <Card title="Export">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="From"><input type="date" aria-label="From date" value={from} onChange={e => setFrom(e.target.value)} className={input} /></Field>
          <Field label="To"><input type="date" aria-label="To date" value={to} onChange={e => setTo(e.target.value)} className={input} /></Field>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">{(st?.kinds ?? Object.keys(KIND_LABEL)).map(k => <label key={k} className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={kinds.includes(k)} onChange={() => toggle(k)} aria-label={KIND_LABEL[k]} />{KIND_LABEL[k]}</label>)}</div>
        <label className="flex items-center gap-1.5 text-sm mt-2"><input type="checkbox" checked={masters} onChange={e => setMasters(e.target.checked)} />Include ledger masters (clients, suppliers, sales/GST/bank ledgers) — needed the first time</label>
        <p className="text-xs text-stone-600 mt-3" data-testid="export-summary">{!kinds.length ? 'Pick at least one kind.' : !sum ? 'Counting…' :
          sum.vouchers === 0 ? 'Nothing in this period.' : `${sum.vouchers} voucher(s): ${Object.entries(sum.by_type).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(', ')} · ${sum.parties} part${sum.parties === 1 ? 'y' : 'ies'}.`}</p>
        <div className="flex gap-2 mt-3 flex-wrap">
          <button disabled={!sum?.vouchers || !!a.busy} onClick={() => a.run('xml', () => downloadFile(`/exports/tally.xml?${q}&masters=${masters}`, `tally-${from}-to-${to}.xml`))} className={btn.primary}>
            {a.busy === 'xml' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}Tally XML</button>
          <button disabled={!sum?.vouchers || !!a.busy} onClick={() => a.run('csv', () => downloadFile(`/exports/daybook.csv?${q}`, `daybook-${from}-to-${to}.csv`))} className={btn.ghost}>
            <Download className="w-3.5 h-3.5" />Day book (CSV)</button></div>
        <p className="text-[11px] text-stone-500 mt-3">In Tally Prime: Gateway of Tally → Import → Vouchers (masters first if you exported them separately) → choose the file. Every voucher balances; GST goes to the ledgers named below. Re-importing the same period creates duplicates — export each period once.</p>
      </Card>
      <Card title="Ledger names (must match your Tally company)">
        {!st ? <Empty>Loading…</Empty> : <form onSubmit={e => { e.preventDefault(); s.run('save', async () => setData(await api.put<TallySettings>('/settings/tally', f)), 'Ledger names saved') }} className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">{Object.keys(st.values).map(k => <Field key={k} label={st.labels[k]}>
            <input aria-label={st.labels[k]} value={f[k] ?? ''} onChange={e => setF({ ...f, [k]: e.target.value })} disabled={!admin} className={input} /></Field>)}</div>
          {s.error && <Alert>{s.error}</Alert>}{s.ok && <Ok>{s.ok}</Ok>}
          {admin ? <button disabled={!!s.busy} className={btn.primary}>Save ledger names</button> : <p className="text-xs text-stone-400">Only an admin can change these.</p>}
        </form>}
      </Card>
    </div>
  )
}
