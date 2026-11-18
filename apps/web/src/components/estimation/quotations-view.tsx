'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, Project } from '@/lib/api'
import { inr } from '@/lib/catalogue-logic'
import { fmtDate, Quotation } from '@/lib/ops'
import { Alert, ctl, Empty, hasRole, PageHeader, Pill, Table, useLoad, useRole } from '@/components/ui/kit'
import { QuoteActions } from '@/components/projects/quote-tools'

const STATUSES = ['', 'DRAFT', 'SENT', 'APPROVED', 'REJECTED', 'SUPERSEDED']

export function QuotationsView() {
  const role = useRole()
  const [projects, setProjects] = useState<Project[]>([])
  const [pid, setPid] = useState(''); const [status, setStatus] = useState(''); const [q, setQ] = useState('')
  useEffect(() => { api.get<Project[]>('/projects').then(setProjects).catch(() => {}) }, [])
  const params = new URLSearchParams(); if (pid) params.set('project_id', pid); if (status) params.set('status', status); if (q.trim()) params.set('q', q.trim())
  const { data: rows, error, reload } = useLoad<Quotation[]>(`/quotations?${params}`)
  const canEdit = hasRole(role, ['ADMIN', 'PROJECT_MANAGER', 'SALES', 'ESTIMATOR'])
  return (
    <div className="space-y-5 max-w-[1300px]">
      <PageHeader title="Quotations" subtitle="Every BOQ version is a quotation. Send it, record the client's decision (approval is final — later changes need a new version), download the PDF, and track payments on the project page." />
      <div className="flex gap-2 flex-wrap">
        <select value={pid} onChange={e => setPid(e.target.value)} aria-label="Project filter" className={ctl + ' min-w-64'}>
          <option value="">All projects</option>{projects.map(p => <option key={p.id} value={p.id}>{p.project_number} · {p.name}</option>)}</select>
        <select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status filter" className={ctl}>{STATUSES.map(s => <option key={s} value={s}>{s || 'Any status'}</option>)}</select>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search number, client, room…" aria-label="Search quotations" className={ctl + ' w-64'} />
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">
        {!rows ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>No quotations match. Create a BOQ in Estimation → BOQ.</Empty> :
          <Table head={['Quotation', 'Project / client', 'Room', 'Created', 'Total (incl. GST)', 'Received', 'Status', '']} right={[4, 5]}>
            {rows.map(r => <tr key={r.id} data-quote={r.quotation_no} className="align-top">
              <td className="px-4 py-3 font-semibold font-mono text-xs">{r.quotation_no}</td>
              <td className="px-4 py-3 text-xs"><Link href={`/projects/${r.project_id}`} className="text-stone-900 hover:underline">{r.project_number} · {r.project_name}</Link><p className="text-stone-400">{r.client_name ?? 'No client'}</p></td>
              <td className="px-4 py-3 text-xs text-stone-600">{r.room_name} · v{r.design_version}</td>
              <td className="px-4 py-3 text-xs text-stone-500">{fmtDate(r.created_at)}</td>
              <td className="px-4 py-3 text-right font-semibold">{inr(r.grand_total)}</td>
              <td className="px-4 py-3 text-right text-xs">{r.paid === '0.00' ? '—' : inr(r.paid)}</td>
              <td className="px-4 py-3"><Pill s={r.status} />{r.status_note && <p className="text-[11px] text-stone-400 max-w-40 truncate" title={r.status_note}>{r.status_note}</p>}</td>
              <td className="px-4 py-3"><QuoteActions q={r} canEdit={canEdit} onChanged={reload} /></td></tr>)}
          </Table>}
      </div>
    </div>
  )
}
