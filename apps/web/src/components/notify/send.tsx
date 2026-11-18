'use client'
// Send a document by email (server outbox → SMTP) or WhatsApp (free click-to-chat link; the user presses send in WhatsApp).
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Loader2, Mail, MessageCircle, RotateCw, Send } from 'lucide-react'
import { api } from '@/lib/api'
import { timeAgo } from '@/lib/crm-logic'
import { Alert, btn, Drawer, Empty, Field, hasRole, input, Ok, Pill, useAction, useLoad, useRole } from '@/components/ui/kit'

export type NotifyKind = 'QUOTATION' | 'INVOICE' | 'PO' | 'DELIVERY' | 'HANDOVER' | 'PAYMENT'
interface Draft { kind: NotifyKind; ref_id: string; project_id: string | null; email: string | null; phone: string | null; subject: string; body: string; attachment: string | null; email_ready: boolean }
export interface MessageRow { id: string; channel: 'EMAIL' | 'WHATSAPP'; kind: string; trigger: 'MANUAL' | 'AUTO'; to: string; subject: string | null; body: string; attachment: string | null
  status: 'QUEUED' | 'SENDING' | 'SENT' | 'FAILED' | 'LINK' | 'SKIPPED'; error: string | null; attempts: number; user_name: string | null; created_at: string; sent_at: string | null }
export const SENDERS: Record<NotifyKind, string[]> = { QUOTATION: ['ADMIN', 'PROJECT_MANAGER', 'SALES', 'ESTIMATOR'], INVOICE: ['ADMIN', 'PROJECT_MANAGER', 'SALES'],
  PO: ['ADMIN', 'PROJECT_MANAGER', 'PROCUREMENT_MANAGER'], DELIVERY: ['ADMIN', 'PROJECT_MANAGER', 'INVENTORY_MANAGER', 'INSTALLATION_MANAGER'], HANDOVER: ['ADMIN', 'PROJECT_MANAGER'],
  PAYMENT: ['ADMIN', 'PROJECT_MANAGER', 'SALES'] }
const WHAT: Record<NotifyKind, string> = { QUOTATION: 'quotation', INVOICE: 'invoice', PO: 'purchase order', DELIVERY: 'delivery note', HANDOVER: 'handover certificate', PAYMENT: 'payment receipt' }

/** Small "Send" button that opens the drawer; hidden for roles that may not send this document. */
export function SendButton({ kind, refId, label = 'Send', canMarkSent, onSent, small = true }: { kind: NotifyKind; refId: string; label?: string; canMarkSent?: boolean; onSent?: () => void; small?: boolean }) {
  const role = useRole(); const [open, setOpen] = useState(false)
  if (!hasRole(role, SENDERS[kind])) return null
  return <>
    <button onClick={() => setOpen(true)} className={small ? btn.small : btn.ghost} aria-label={`${label} (${WHAT[kind]})`} data-send={kind}><Send className="w-3 h-3" />{label}</button>
    {open && <SendDrawer kind={kind} refId={refId} canMarkSent={canMarkSent} onClose={() => setOpen(false)} onSent={() => { setOpen(false); onSent?.() }} />}
  </>
}

function SendDrawer({ kind, refId, canMarkSent, onClose, onSent }: { kind: NotifyKind; refId: string; canMarkSent?: boolean; onClose: () => void; onSent: () => void }) {
  const { data: d, error } = useLoad<Draft>(`/notifications/draft?kind=${kind}&ref_id=${refId}`)
  const [channel, setChannel] = useState<'EMAIL' | 'WHATSAPP'>('EMAIL')
  const [to, setTo] = useState(''); const [subject, setSubject] = useState(''); const [body, setBody] = useState(''); const [attach, setAttach] = useState(true); const [markSent, setMarkSent] = useState(true)
  const a = useAction()
  useEffect(() => { if (d) { setChannel(d.email_ready ? 'EMAIL' : 'WHATSAPP'); setSubject(d.subject); setBody(d.body) } }, [d])
  useEffect(() => { if (d) setTo(channel === 'EMAIL' ? d.email ?? '' : d.phone ?? '') }, [channel, d])
  const send = () => a.run('s', async () => {
    const r = await api.post<MessageRow & { whatsapp_url: string | null }>('/notifications/send', { kind, ref_id: refId, channel, to, subject: channel === 'EMAIL' ? subject : undefined, body,
      attach, mark_sent: Boolean(canMarkSent && markSent) })
    if (r.whatsapp_url) window.open(r.whatsapp_url, '_blank', 'noopener')
    onSent()
  })
  const tab = (c: 'EMAIL' | 'WHATSAPP', Icon: typeof Mail, l: string) => <button type="button" role="tab" aria-selected={channel === c} onClick={() => setChannel(c)}
    className={`flex-1 flex items-center justify-center gap-1.5 text-sm py-1.5 rounded ${channel === c ? 'bg-white shadow-sm font-medium text-stone-900' : 'text-stone-500'}`}><Icon className="w-3.5 h-3.5" />{l}</button>
  return (
    <Drawer label={`Send ${WHAT[kind]}`} title={`Send ${WHAT[kind]}`} onClose={onClose}>
      {error ? <Alert>{error}</Alert> : !d ? <Empty>Loading…</Empty> : <div className="space-y-3">
        <div className="flex gap-1 bg-stone-100 rounded p-1" role="tablist">{tab('EMAIL', Mail, 'Email')}{tab('WHATSAPP', MessageCircle, 'WhatsApp')}</div>
        {channel === 'EMAIL' && !d.email_ready ? <div className="text-sm text-stone-700 bg-amber-50 border border-amber-200 rounded p-3" data-testid="email-not-ready">
          Email isn't set up yet. An admin can add an SMTP account (free with Gmail + an app password) — see <Link href="/settings/notifications" className="underline">Settings → Notifications</Link>. You can use WhatsApp meanwhile.</div> : <>
          <Field label={channel === 'EMAIL' ? 'To (comma-separated)' : 'WhatsApp number'}><input aria-label={channel === 'EMAIL' ? 'To' : 'WhatsApp number'} value={to} onChange={e => setTo(e.target.value)}
            placeholder={channel === 'EMAIL' ? 'client@example.com' : '+91 98765 43210'} className={input} /></Field>
          {!to && <p className="text-[11px] text-amber-800">No {channel === 'EMAIL' ? 'email address' : 'phone number'} is saved for this {kind === 'PO' ? 'supplier' : 'client'} — type one.</p>}
          {channel === 'EMAIL' && <Field label="Subject"><input aria-label="Subject" value={subject} onChange={e => setSubject(e.target.value)} className={input} /></Field>}
          <Field label="Message"><textarea aria-label="Message" rows={9} value={body} onChange={e => setBody(e.target.value)} className={input + ' font-[inherit]'} /></Field>
          {channel === 'EMAIL' && d.attachment && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={attach} onChange={e => setAttach(e.target.checked)} />Attach {d.attachment}</label>}
          {channel === 'WHATSAPP' && <p className="text-[11px] text-stone-500">WhatsApp opens with this message typed — you press send there. PDFs can't be attached through a link; download the PDF and attach it in WhatsApp if needed.</p>}
          {canMarkSent && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={markSent} onChange={e => setMarkSent(e.target.checked)} />Also mark the quotation as Sent</label>}
          {a.error && <Alert>{a.error}</Alert>}
          <button onClick={send} disabled={!to.trim() || !!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {channel === 'EMAIL' ? 'Send email' : 'Open WhatsApp'}</button>
          {channel === 'EMAIL' && <p className="text-[11px] text-stone-400">Emails are queued and sent in the background; the result appears in the project's Messages.</p>}
        </>}
      </div>}
    </Drawer>
  )
}

/** Message history (project page). */
export function MessagesCard({ projectId }: { projectId: string }) {
  const { data, reload } = useLoad<MessageRow[]>(`/messages?project_id=${projectId}`)
  const a = useAction()
  useEffect(() => {                                   // refresh while something is still being sent
    if (!data?.some(m => m.status === 'QUEUED' || m.status === 'SENDING')) return
    const t = setTimeout(reload, 3000); return () => clearTimeout(t)
  }, [data, reload])
  if (!data) return <Empty>Loading…</Empty>
  if (!data.length) return <p className="text-xs text-stone-400">Nothing sent yet. Use the Send buttons on quotations, invoices, deliveries and the handover certificate.</p>
  return <ul className="divide-y divide-stone-50 text-xs" data-testid="messages">{data.map(m => <li key={m.id} className="py-2 space-y-0.5" data-message={m.status}>
    <div className="flex items-center gap-2 flex-wrap">{m.channel === 'EMAIL' ? <Mail className="w-3 h-3 text-stone-400" /> : <MessageCircle className="w-3 h-3 text-green-600" />}
      <span className="font-medium text-stone-800">{m.subject ?? `WhatsApp — ${m.kind.toLowerCase()}`}</span><Pill s={m.status === 'LINK' ? 'DONE' : m.status === 'SKIPPED' ? 'CANCELLED' : m.status} label={m.status === 'LINK' ? 'Opened in WhatsApp' : m.status.toLowerCase()} />
      {m.trigger === 'AUTO' && <Pill tone="violet" label="auto" />}<span className="ml-auto text-stone-400">{timeAgo(m.created_at)}</span></div>
    <p className="text-stone-500">to {m.to}{m.attachment ? ` · ${m.attachment}` : ''}{m.user_name ? ` · by ${m.user_name}` : ''}</p>
    {m.error && <p className="text-red-700">{m.error}{['FAILED', 'SKIPPED'].includes(m.status) && m.channel === 'EMAIL' && <button onClick={() => a.run(m.id, async () => { await api.post(`/messages/${m.id}/retry`); await reload() })}
      className={btn.small + ' ml-2'}><RotateCw className="w-3 h-3" />Retry</button>}</p>}</li>)}
    {a.error && <li className="py-2"><Alert>{a.error}</Alert></li>}{a.ok && <li><Ok>{a.ok}</Ok></li>}</ul>
}
