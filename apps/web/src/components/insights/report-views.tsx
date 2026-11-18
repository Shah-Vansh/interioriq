'use client'
import Link from 'next/link'
import { useState } from 'react'
import { inr } from '@/lib/catalogue-logic'
import { Alert as AlertT, fmtDate, ProjectRow, STAGE_LABEL } from '@/lib/ops'
import { Alert, Card, ctl, Empty, PageHeader, Pill, Stat, Table, useLoad } from '@/components/ui/kit'

interface Revenue { months: { month: string; received: string; approved: string; gst_on_approved: string }[]; totals: { received: string; approved: string; all_time_received: string }; by_mode: { mode: string; amount: string }[] }
const MONTH = (k: string) => new Date(k + '-01T12:00:00').toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })

export function RevenueReport() {
  const [months, setMonths] = useState(12)
  const { data: r, error } = useLoad<Revenue>(`/reports/revenue?months=${months}`)
  // bar heights are display-only proportions of server totals (no money is computed or shown from them)
  const max = Math.max(1, ...(r?.months.flatMap(m => [Number(m.received), Number(m.approved)]) ?? [1]))
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Revenue" subtitle="Money actually received (payments) and the value of quotations approved, by month. GST shown is the tax inside the approved values.">
        <select value={months} onChange={e => setMonths(Number(e.target.value))} aria-label="Months" className={ctl}>{[3, 6, 12, 24].map(n => <option key={n} value={n}>Last {n} months</option>)}</select></PageHeader>
      {error && <Alert>{error}</Alert>}
      {!r ? <Empty>Loading…</Empty> : <>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3"><Stat label="Received in period" value={inr(r.totals.received)} tone="green" /><Stat label="Approved in period" value={inr(r.totals.approved)} /><Stat label="Received all time" value={inr(r.totals.all_time_received)} /></div>
        <Card title="By month">
          <div className="flex items-end gap-2 h-48 border-b border-stone-200 pb-1" role="img" aria-label="Monthly revenue chart">{r.months.map(m => <div key={m.month} className="flex-1 flex items-end justify-center gap-0.5 h-full" title={`${MONTH(m.month)}: received ${inr(m.received)}, approved ${inr(m.approved)}`}>
            <div className="w-1/2 bg-green-600 rounded-t" style={{ height: `${(100 * Number(m.received)) / max}%` }} /><div className="w-1/2 bg-amber-300 rounded-t" style={{ height: `${(100 * Number(m.approved)) / max}%` }} /></div>)}</div>
          <div className="flex gap-2 mt-1">{r.months.map(m => <span key={m.month} className="flex-1 text-center text-[10px] text-stone-400">{MONTH(m.month)}</span>)}</div>
          <p className="text-[11px] text-stone-500 mt-2"><span className="inline-block w-2 h-2 bg-green-600 mr-1" />received <span className="inline-block w-2 h-2 bg-amber-300 ml-3 mr-1" />approved</p>
          <Table head={['Month', 'Received', 'Approved', 'GST in approved']} right={[1, 2, 3]}>{[...r.months].reverse().map(m => <tr key={m.month} data-month={m.month}><td className="px-4 py-1.5 text-sm">{MONTH(m.month)}</td>
            <td className="px-4 py-1.5 text-right text-sm">{inr(m.received)}</td><td className="px-4 py-1.5 text-right text-sm">{inr(m.approved)}</td><td className="px-4 py-1.5 text-right text-xs text-stone-500">{inr(m.gst_on_approved)}</td></tr>)}</Table>
        </Card>
        <Card title="Received by payment mode (all time)">{r.by_mode.length === 0 ? <Empty>No payments recorded yet.</Empty> :
          <ul className="text-sm space-y-1">{r.by_mode.map(m => <li key={m.mode} className="flex justify-between"><span>{m.mode}</span><b>{inr(m.amount)}</b></li>)}</ul>}</Card>
      </>}
    </div>
  )
}

export function ProjectsReport() {
  const { data: rows, error } = useLoad<ProjectRow[]>('/reports/projects')
  const [show, setShow] = useState<'live' | 'all'>('live')
  const list = rows?.filter(r => show === 'all' || (!r.archived && r.status !== 'COMPLETED'))
  return (
    <div className="space-y-5 max-w-[1400px]">
      <PageHeader title="Projects report" subtitle="Stage, deadline, money and open issues for every project.">
        <select value={show} onChange={e => setShow(e.target.value as 'live' | 'all')} aria-label="Which projects" className={ctl}><option value="live">Live projects</option><option value="all">All projects</option></select></PageHeader>
      {error && <Alert>{error}</Alert>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!list ? <Empty>Loading…</Empty> : list.length === 0 ? <Empty>No projects.</Empty> :
        <Table head={['Project', 'Client', 'Stage', 'Due', 'Quoted', 'Received', 'Balance', 'Snags', 'Alerts']} right={[4, 5, 6, 7, 8]}>{list.map(p => <tr key={p.id} data-project={p.project_number}>
          <td className="px-4 py-2"><Link href={`/projects/${p.id}`} className="font-medium hover:underline">{p.project_number}</Link><p className="text-[11px] text-stone-400">{p.name}</p></td>
          <td className="px-4 py-2 text-xs">{p.client_name ?? '—'}</td><td className="px-4 py-2"><Pill s={p.status} label={STAGE_LABEL[p.status]} /></td>
          <td className={`px-4 py-2 text-xs ${p.days_left !== null && p.days_left < 0 ? 'text-red-700 font-semibold' : ''}`}>{fmtDate(p.target_date)}{p.days_left !== null ? ` (${p.days_left < 0 ? `${-p.days_left}d late` : `${p.days_left}d`})` : ''}</td>
          <td className="px-4 py-2 text-right text-xs">{p.quoted === null ? '—' : inr(p.quoted)}</td><td className="px-4 py-2 text-right text-xs">{p.paid === null ? '—' : inr(p.paid)}</td>
          <td className="px-4 py-2 text-right text-xs font-semibold">{p.balance === null ? '—' : inr(p.balance)}</td><td className="px-4 py-2 text-right text-xs">{p.open_snags || '—'}</td>
          <td className="px-4 py-2 text-right">{p.alerts ? <Pill tone="red" label={String(p.alerts)} /> : '—'}</td></tr>)}</Table>}</div>
    </div>
  )
}

export function AIReport() {
  const { data, error } = useLoad<{ alerts: AlertT[]; counts: Record<string, number>; rules: { rule: string; when: string }[] }>('/ai/alerts')
  return (
    <div className="space-y-5 max-w-[1200px]">
      <PageHeader title="AI project manager" subtitle="Risk alerts from deterministic rules over live data — every alert names the rule, the evidence and a next step. No LLM is involved, so nothing is invented." />
      {error && <Alert>{error}</Alert>}
      {!data ? <Empty>Loading…</Empty> : <>
        <div className="grid grid-cols-3 gap-3"><Stat label="High" value={data.counts.HIGH ?? 0} tone={data.counts.HIGH ? 'red' : 'green'} /><Stat label="Medium" value={data.counts.MEDIUM ?? 0} tone={data.counts.MEDIUM ? 'amber' : undefined} /><Stat label="Low" value={data.counts.LOW ?? 0} /></div>
        <Card title="Alerts">{data.alerts.length === 0 ? <p className="text-sm text-green-700">No risks found right now.</p> :
          <ul className="divide-y divide-stone-50" data-testid="ai-alerts">{data.alerts.map((a, i) => <li key={i} data-rule={a.rule} className="py-2.5 flex gap-3 items-start"><Pill s={a.severity} />
            <div><p className="text-sm text-stone-800">{a.project_id ? <Link href={`/projects/${a.project_id}`} className="font-semibold hover:underline">{a.project_number}</Link> : <b>Stock</b>} {a.text}</p>
              <p className="text-xs text-stone-500">→ {a.action} <span className="text-stone-300">({a.rule})</span></p></div></li>)}</ul>}</Card>
        <Card title="The rules"><Table head={['Rule', 'Fires when']}>{data.rules.map(r => <tr key={r.rule}><td className="px-4 py-1.5 font-mono text-[11px]">{r.rule}</td><td className="px-4 py-1.5 text-xs">{r.when}</td></tr>)}</Table></Card>
      </>}
    </div>
  )
}
