'use client'
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Alert, btn, Card, Empty, Field, hasRole, input, Ok, PageHeader, Pill, Switch, useAction, useLoad, useRole } from '@/components/ui/kit'

interface Status { email_ready: boolean; smtp_host: string | null; smtp_port: number; smtp_security: string; from: string | null; public_url: string; auto: Record<string, boolean>
  auto_labels: Record<string, string>; queued: number; failed: number; how_to: string }
interface Tpl { subject: string; body: string; variables: string[]; customised: boolean }
const NAMES: Record<string, string> = { QUOTATION: 'Quotation', INVOICE: 'Invoice', PO: 'Purchase order (to supplier)', DELIVERY: 'Delivery', HANDOVER: 'Handover', PAYMENT: 'Payment receipt' }

export function NotificationSettings() {
  const role = useRole(); const admin = hasRole(role, ['ADMIN'])
  const { data: s, reload, error } = useLoad<Status>('/notifications/status')
  const { data: tpls, setData: setTpls } = useLoad<Record<string, Tpl>>('/notifications/templates')
  const [testTo, setTestTo] = useState(''); const [kind, setKind] = useState('QUOTATION'); const [edit, setEdit] = useState<{ subject: string; body: string } | null>(null)
  const a = useAction()
  useEffect(() => { if (tpls?.[kind]) setEdit({ subject: tpls[kind].subject, body: tpls[kind].body }) }, [tpls, kind])
  const saveTpl = () => edit && a.run('t', async () => { const t = await api.put<Tpl>(`/notifications/templates/${kind}`, edit); setTpls({ ...tpls!, [kind]: t }) }, 'Template saved')
  const resetTpl = () => a.run('r', async () => { const t = await api.delete<Tpl>(`/notifications/templates/${kind}`); setTpls({ ...tpls!, [kind]: t }) }, 'Template reset to the default')
  return (
    <div className="space-y-5 max-w-[1000px]">
      <PageHeader title="Notifications" subtitle="Send quotations, invoices, purchase orders, delivery updates and handover certificates by email or WhatsApp — at zero cost. Every message is logged on its project." />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {!s ? <Empty>Loading…</Empty> : <>
        <Card title="Email" right={<Pill tone={s.email_ready ? 'green' : 'amber'} label={s.email_ready ? 'Ready' : 'Not set up'} />}>
          {s.email_ready ? <div className="text-sm space-y-1" data-testid="smtp-ready"><p>Sending from <b>{s.from}</b> via {s.smtp_host}:{s.smtp_port} ({s.smtp_security}).</p>
            <p className="text-xs text-stone-500">{s.queued} queued · {s.failed} failed. The SMTP password is kept only in apps/api/.env and is never shown here.</p></div>
            : <p className="text-sm text-stone-700">{s.how_to}</p>}
          {admin && s.email_ready && <div className="flex gap-2 mt-3 items-end"><Field label="Send a test email to"><input aria-label="Test email address" value={testTo} onChange={e => setTestTo(e.target.value)} className={input + ' w-72'} /></Field>
            <button onClick={() => a.run('test', () => api.post('/notifications/test', { to: testTo }), `Test email sent to ${testTo}`)} disabled={!testTo.trim() || !!a.busy} className={btn.ghost}>
              {a.busy === 'test' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Send test</button></div>}
        </Card>
        <Card title="WhatsApp" right={<Pill tone="green" label="Ready" />}><p className="text-sm text-stone-700">Uses free WhatsApp click-to-chat links: the message opens in WhatsApp (app or web) already typed, and you press send. No WhatsApp Business account or paid API is needed.</p></Card>
        <Card title="Automatic emails to the client">
          <p className="text-xs text-stone-500 mb-3">Off by default. When on, the email goes out by itself after the event — only if email is set up and the client has an email address; otherwise it is logged as skipped with the reason.</p>
          <div className="space-y-3" data-testid="auto-switches">{Object.entries(s.auto_labels).map(([k, label]) => <Switch key={k} label={label} checked={s.auto[k]} disabled={!admin}
            onChange={v => a.run('auto' + k, async () => { await api.put('/notifications/auto', { [k]: v }); await reload() })} />)}</div>
        </Card>
        <Card title="Message templates">{!tpls || !edit ? <Empty>Loading…</Empty> : <div className="space-y-3">
          <div className="flex gap-1.5 flex-wrap" role="tablist">{Object.keys(tpls).map(k => <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
            className={`text-xs px-2.5 py-1 rounded-full border ${kind === k ? 'bg-amber-700 border-amber-700 text-white' : 'bg-white border-stone-200 text-stone-600'}`}>{NAMES[k]}{tpls[k].customised ? ' •' : ''}</button>)}</div>
          <Field label="Subject (email)"><input aria-label="Template subject" value={edit.subject} onChange={e => setEdit({ ...edit, subject: e.target.value })} disabled={!admin} className={input} /></Field>
          <Field label="Message"><textarea aria-label="Template message" rows={8} value={edit.body} onChange={e => setEdit({ ...edit, body: e.target.value })} disabled={!admin} className={input} /></Field>
          <p className="text-[11px] text-stone-500">Placeholders: {tpls[kind].variables.map(v => <code key={v} className="mr-1.5 text-stone-700">${v}</code>)}</p>
          {admin && <div className="flex gap-2"><button onClick={saveTpl} disabled={!!a.busy} className={btn.primary}>Save template</button>
            {tpls[kind].customised && <button onClick={resetTpl} className={btn.ghost}>Reset to default</button>}</div>}</div>}</Card>
      </>}
    </div>
  )
}
