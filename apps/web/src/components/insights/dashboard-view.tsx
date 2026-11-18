'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { session } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { timeAgo } from '@/lib/crm-logic'
import { Dashboard, STAGE_LABEL } from '@/lib/ops'
import { Alert, Card, Empty, PageHeader, Pill, Stat, Table, useLoad } from '@/components/ui/kit'

function greeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening' }

export function DashboardView() {
  const { data: d, error } = useLoad<Dashboard>('/dashboard')
  const [name, setName] = useState('')
  useEffect(() => { setName(session.user()?.name?.split(' ')[0] ?? '') }, [])
  const c = d?.cards ?? {}
  const max = Math.max(1, ...(d?.stages.map(s => s.count) ?? [1]))
  return (
    <div className="space-y-6 max-w-[1400px]">
      <PageHeader title={`${greeting()}${name ? ', ' + name : ''}`} subtitle="Live numbers from your projects, quotations, payments, purchase orders and stock." />
      {error && <Alert>{error}</Alert>}
      {!d ? <Empty>Loading…</Empty> : <>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
          <Link href="/crm/followups" className="block"><Stat label="My follow-ups due" value={c.my_followups_due ?? 0} hint={`${c.followups_overdue ?? 0} overdue across the team`} tone={Number(c.my_followups_due) ? 'amber' : 'green'} /></Link>
          <Stat label="Active projects" value={c.active_projects} hint={`${c.completed_projects} completed`} />
          <Stat label="Open leads" value={c.open_leads} hint={d.money_visible ? `pipeline ${inr(String(c.pipeline_value))}` : undefined} />
          <Stat label="Quotes awaiting client" value={c.quotes_awaiting} />
          {d.money_visible && <Stat label="Received this month" value={inr(String(c.received_this_month))} tone="green" />}
          {d.money_visible && <Stat label="Outstanding" value={inr(String(c.outstanding))} hint="approved quotations − payments" tone={c.outstanding !== '0.00' ? 'amber' : undefined} />}
          <Stat label="Open POs" value={c.open_pos} hint={Number(c.late_pos) ? `${c.late_pos} late` : 'none late'} tone={Number(c.late_pos) ? 'red' : undefined} />
          <Stat label="Low / out of stock" value={c.low_stock} tone={Number(c.low_stock) ? 'amber' : undefined} />
          <Stat label="High-risk alerts" value={c.high_alerts} tone={Number(c.high_alerts) ? 'red' : 'green'} />
        </div>
        <div className="grid grid-cols-12 gap-4">
          <Card title="Live projects (soonest deadline first)" className="col-span-12 lg:col-span-8" right={<Link href="/reports/projects" className="text-xs text-amber-700 hover:underline">All projects report →</Link>}>
            {d.projects.length === 0 ? <Empty>No live projects. Convert a lead or create a project.</Empty> :
              <Table head={['Project', 'Client', 'Stage', 'Progress', 'Due', 'Alerts']}>
                {d.projects.map(p => <tr key={p.id}>
                  <td className="px-4 py-2.5"><Link href={`/projects/${p.id}`} className="font-medium text-stone-900 hover:underline">{p.project_number}</Link><p className="text-[11px] text-stone-400">{p.name}</p></td>
                  <td className="px-4 py-2.5 text-xs text-stone-600">{p.client_name ?? '—'}</td>
                  <td className="px-4 py-2.5"><Pill s={p.status} label={STAGE_LABEL[p.status]} /></td>
                  <td className="px-4 py-2.5 w-36"><div className="h-1.5 bg-stone-100 rounded"><div className="h-1.5 bg-amber-600 rounded" style={{ width: `${p.progress}%` }} /></div><span className="text-[11px] text-stone-400">{p.progress}%</span></td>
                  <td className={`px-4 py-2.5 text-xs ${p.days_left !== null && p.days_left < 0 ? 'text-red-700 font-semibold' : 'text-stone-600'}`}>{p.days_left === null ? '—' : p.days_left < 0 ? `${-p.days_left}d late` : `${p.days_left}d`}</td>
                  <td className="px-4 py-2.5">{p.alerts ? <Pill tone="red" label={String(p.alerts)} /> : <span className="text-stone-300">—</span>}</td></tr>)}
              </Table>}
          </Card>
          <div className="col-span-12 lg:col-span-4 space-y-4">
            <Card title="AI project manager" right={<Link href="/reports/ai" className="text-xs text-amber-700 hover:underline">All alerts →</Link>}>
              {d.alerts.length === 0 ? <p className="text-sm text-green-700">No risks found by the rules right now.</p> :
                <ul className="space-y-2" data-testid="dash-alerts">{d.alerts.map((a, i) => <li key={i} className="text-xs flex gap-2"><AlertTriangle className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${a.severity === 'HIGH' ? 'text-red-600' : a.severity === 'MEDIUM' ? 'text-amber-600' : 'text-blue-500'}`} />
                  <span><b className="text-stone-800">{a.project_number ?? 'Stock'}</b> {a.text}</span></li>)}</ul>}
            </Card>
            <Card title="Pipeline by stage">
              <div className="space-y-1.5">{d.stages.map(s => <div key={s.stage} className="flex items-center gap-2 text-xs"><span className="w-24 text-stone-500">{STAGE_LABEL[s.stage]}</span>
                <div className="flex-1 h-2 bg-stone-100 rounded"><div className="h-2 bg-amber-600/80 rounded" style={{ width: `${(100 * s.count) / max}%` }} /></div><span className="w-6 text-right text-stone-700">{s.count}</span></div>)}</div>
            </Card>
          </div>
        </div>
        <Card title="Recent activity">
          {d.activity.length === 0 ? <Empty>Nothing yet.</Empty> : <ul className="divide-y divide-stone-50" data-testid="dash-activity">{d.activity.map(a => <li key={a.id} className="py-2 text-sm flex justify-between gap-3">
            <span className="text-stone-700">{a.project_number && <b className="text-stone-900 mr-1">{a.project_number}</b>}{a.text}</span>
            <span className="text-[11px] text-stone-400 whitespace-nowrap">{a.user_name ?? 'System'} · {timeAgo(a.created_at)}</span></li>)}</ul>}
        </Card>
      </>}
    </div>
  )
}
