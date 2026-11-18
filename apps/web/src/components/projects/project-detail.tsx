'use client'
import Link from 'next/link'
import { useState } from 'react'
import { Check } from 'lucide-react'
import { api } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { timeAgo } from '@/lib/crm-logic'
import { fmtDate, Overview, STAGE_LABEL, TimelineEvent } from '@/lib/ops'
import { Alert, btn, Card, Empty, Field, hasRole, input, Ok, PageHeader, Pill, Table, useAction, useLoad, useRole } from '@/components/ui/kit'
import { Payments, QuoteActions } from './quote-tools'
import { ProjectInvoices } from '@/components/estimation/invoices'
import { MessagesCard } from '@/components/notify/send'
import { TeamCard } from './team-card'
import { EXP_WRITE, ExpensesCard, MONEY, ProfitCard } from '@/components/insights/profit-views'

export function StageStepper({ stages, index }: { stages: string[]; index: number }) {
  return <ol className="flex flex-wrap gap-1" data-testid="stepper">{stages.map((s, i) => (
    <li key={s} className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-full border ${i < index ? 'bg-green-50 border-green-200 text-green-800' : i === index ? 'bg-amber-700 border-amber-700 text-white font-semibold' : 'bg-white border-stone-200 text-stone-400'}`}>
      {i < index && <Check className="w-3 h-3" />}{STAGE_LABEL[s] ?? s}</li>))}</ol>
}

export function ProjectDetail({ id }: { id: string }) {
  const role = useRole()
  const { data: o, error, reload } = useLoad<Overview>(`/projects/${id}/overview`)
  const { data: tl, reload: reloadTl } = useLoad<TimelineEvent[]>(`/projects/${id}/timeline`)
  const refresh = () => { reload(); reloadTl() }
  const a = useAction()
  const [edit, setEdit] = useState<{ target_date: string; site_address: string } | null>(null)
  const [profitKey, setProfitKey] = useState(0)
  if (error) return <Alert>{error}</Alert>
  if (!o) return <Empty>Loading…</Empty>
  const approved = o.quotations.filter(q => q.status === 'APPROVED')
  const isPM = hasRole(role, ['ADMIN', 'PROJECT_MANAGER'])
  const steps: [string, string, string][] = [
    ['Procurement', `${o.procurement.received}/${o.procurement.pos} POs received`, '/execution/procurement'],
    ['Manufacturing', `${o.manufacturing.ready}/${o.manufacturing.work_orders} units ready`, '/execution/manufacturing'],
    ['Delivery', `${o.delivery.delivered}/${o.delivery.notes} notes delivered`, '/execution/delivery'],
    ['Installation', `${o.installation.done}/${o.installation.tasks} tasks done`, '/execution/installation'],
    ['QC & handover', `${o.qc.passed}/${o.qc.checks} checks passed · ${o.qc.open_snags} open snags`, '/execution/qc']]
  const save = () => edit && a.run('edit', async () => { await api.patch(`/projects/${id}`, { target_date: edit.target_date || null, site_address: edit.site_address || null }); setEdit(null); refresh() }, 'Saved')
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title={`${o.project_number} · ${o.name}`} subtitle={<>{o.client_name ?? 'No client linked'}{o.site_address ? ` · ${o.site_address}` : ''}{o.target_date ? ` · handover due ${fmtDate(o.target_date)}` : ''}</>}>
        {o.archived && <Pill tone="stone" label="Archived" />}<Pill s={o.status} label={STAGE_LABEL[o.status]} />
        {isPM && <button className={btn.ghost} onClick={() => a.run('arch', async () => { await api.patch(`/projects/${id}`, { archived: !o.archived }); refresh() })}>{o.archived ? 'Restore' : 'Archive'}</button>}
      </PageHeader>
      <StageStepper stages={o.stages} index={o.stage_index} />
      {a.error && <Alert>{a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-8 space-y-4">
          <Card title="Quotations" right={<Link href="/estimation/boq" className="text-xs text-amber-700 hover:underline">Create a BOQ →</Link>}>
            {o.quotations.length === 0 ? <Empty>No BOQ yet. Save a design and price it in Estimation → BOQ.</Empty> :
              <Table head={['Quotation', 'Room', 'Total', 'Status', '']} right={[2]}>{o.quotations.map(q => <tr key={q.id}>
                <td className="px-4 py-2.5 font-mono text-xs">{q.quotation_no}</td><td className="px-4 py-2.5 text-xs">{q.room_name} · design v{q.design_version}</td>
                <td className="px-4 py-2.5 text-right font-semibold">{inr(q.grand_total)}</td>
                <td className="px-4 py-2.5"><Pill s={q.status} />{q.status_note && <p className="text-[11px] text-stone-400 max-w-48 truncate" title={q.status_note}>{q.status_note}</p>}</td>
                <td className="px-4 py-2.5"><QuoteActions q={q} canEdit={hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'SALES', 'ESTIMATOR'])} onChanged={refresh} /></td></tr>)}</Table>}
          </Card>
          <Card title="Execution">
            <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-2">{steps.map(([t, v, href]) => <Link key={t} href={href} className="border border-stone-200 rounded p-3 hover:bg-stone-50">
              <p className="text-xs font-semibold text-stone-800">{t}</p><p className="text-[11px] text-stone-500">{v}</p></Link>)}</div>
            {o.handover && <p className="mt-3 text-sm text-green-800">Handed over to <b>{o.handover.received_by}</b> on {fmtDate(o.handover.handed_over_on)} · warranty {o.handover.warranty_months} months.</p>}
          </Card>
          <Card title="Timeline">
            {!tl?.length ? <Empty>No activity yet.</Empty> : <ul className="divide-y divide-stone-50 max-h-[420px] overflow-y-auto" data-testid="timeline">{tl.map(e => <li key={e.id} className="py-2 text-sm flex justify-between gap-3">
              <span><Pill tone="stone" label={e.kind} /> <span className="text-stone-700">{e.text}</span></span><span className="text-[11px] text-stone-400 whitespace-nowrap">{e.user_name ?? 'System'} · {timeAgo(e.created_at)}</span></li>)}</ul>}
          </Card>
        </div>
        <div className="col-span-12 lg:col-span-4 space-y-4">
          {hasRole(role, MONEY) && <Card title="Profitability"><ProfitCard projectId={id} refreshKey={profitKey} /></Card>}
          {hasRole(role, [...EXP_WRITE, ...MONEY]) && <Card title="Expenses"><ExpensesCard projectId={id} onChanged={() => setProfitKey(k => k + 1)} /></Card>}
          <Card title="Team"><TeamCard projectId={id} /></Card>
          <Card title="Invoices"><ProjectInvoices projectId={id} onChanged={refresh} /></Card>
          <Card title="Messages"><MessagesCard projectId={id} /></Card>
          <Card title="Payments"><Payments projectId={id} summary={o.payments} approved={approved} canPay={hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'SALES'])} onChanged={refresh} /></Card>
          <Card title="Project details" right={isPM && !edit ? <button className={btn.small} onClick={() => setEdit({ target_date: o.target_date ?? '', site_address: o.site_address ?? '' })}>Edit</button> : undefined}>
            {edit ? <div className="space-y-2">
              <Field label="Target handover date"><input type="date" value={edit.target_date} onChange={e => setEdit({ ...edit, target_date: e.target.value })} className={input} /></Field>
              <Field label="Site address"><input value={edit.site_address} onChange={e => setEdit({ ...edit, site_address: e.target.value })} className={input} /></Field>
              <div className="flex gap-2"><button onClick={save} className={btn.primary}>Save</button><button onClick={() => setEdit(null)} className={btn.ghost}>Cancel</button></div></div>
              : <dl className="text-xs space-y-1.5"><div className="flex justify-between"><dt className="text-stone-400">Target handover</dt><dd>{fmtDate(o.target_date)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-stone-400">Site</dt><dd className="text-right">{o.site_address ?? '—'}</dd></div>
                <div className="flex justify-between"><dt className="text-stone-400">Progress</dt><dd>{o.progress}%</dd></div></dl>}
          </Card>
        </div>
      </div>
    </div>
  )
}
