'use client'
import { useEffect, useState } from 'react'
import { Check, Loader2, Plus, X } from 'lucide-react'
import { api, Client } from '@/lib/api'
import { ROLE_LABEL, UserRow } from '@/lib/ops'
import { Alert, btn, Card, ctl, Drawer, Empty, Field, hasRole, input, Ok, PageHeader, Pill, Switch, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

// ── Company ───────────────────────────────────────────────────────────────────
interface CompanyResp { values: Record<string, string | number | boolean>; fields: { key: string; label: string; type: 'int' | 'text' | 'bool' }[] }
export function CompanySettings() {
  const role = useRole(); const can = hasRole(role, ['ADMIN'])
  const { data, error, setData } = useLoad<CompanyResp>('/settings/company')
  const [f, setF] = useState<Record<string, string>>({}); const a = useAction()
  useEffect(() => { if (data) setF(Object.fromEntries(Object.entries(data.values).map(([k, v]) => [k, String(v ?? '')]))) }, [data])
  const save = (e: React.FormEvent) => { e.preventDefault(); a.run('s', async () => setData(await api.put<CompanyResp>('/settings/company', { ...f, gst_enabled: f.gst_enabled === 'true' })), 'Saved — new quotations, POs, challans and certificates use these details') }
  return (
    <div className="space-y-5 max-w-[900px]">
      <PageHeader title="Company" subtitle="Printed on every quotation, purchase order, delivery challan and handover certificate. The board SKUs let Procurement order sheets and edge band straight from the cutting lists." />
      {(error || a.error) && <Alert>{error || a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {!data ? <Empty>Loading…</Empty> : <form onSubmit={save}><Card title="Company profile"><div className="grid md:grid-cols-2 gap-3">
        {data.fields.filter(fl => fl.type === 'bool').map(fl => <div key={fl.key} className="md:col-span-2 border border-stone-200 rounded p-3">
          <Switch label={fl.label} checked={f[fl.key] === 'true'} disabled={!can} onChange={v => setF({ ...f, [fl.key]: String(v) })}
            hint={fl.key === 'gst_enabled' ? 'You can still switch GST on or off for each quotation. Turn this off if your firm is not GST-registered.' : undefined} /></div>)}
        {data.fields.filter(fl => fl.type !== 'bool').map(fl => <Field key={fl.key} label={fl.label} className={fl.key === 'address' ? 'md:col-span-2' : ''}>
          <input value={f[fl.key] ?? ''} onChange={e => setF({ ...f, [fl.key]: e.target.value })} disabled={!can} inputMode={fl.type === 'int' ? 'numeric' : undefined} className={input + (fl.key.endsWith('sku') || fl.key === 'gstin' ? ' font-mono uppercase' : '')} /></Field>)}</div>
        {can ? <button disabled={!!a.busy} className={btn.primary + ' mt-4'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save</button> : <p className="text-xs text-stone-400 mt-3">Only an admin can change these.</p>}</Card></form>}
    </div>
  )
}

// ── Users ─────────────────────────────────────────────────────────────────────
const ROLES = ['ADMIN', 'PROJECT_MANAGER', 'SALES', 'INTERIOR_DESIGNER', 'ESTIMATOR', 'SITE_ENGINEER', 'PROCUREMENT_MANAGER', 'INVENTORY_MANAGER', 'MANUFACTURING_MANAGER', 'INSTALLATION_MANAGER', 'QC_MANAGER', 'CLIENT', 'SUPER_ADMIN']
export function UserManagement() {
  const role = useRole(); const can = hasRole(role, ['ADMIN'])
  const { data: users, error, reload } = useLoad<UserRow[]>('/users'); const [edit, setEdit] = useState<UserRow | 'new' | null>(null)
  return (
    <div className="space-y-5 max-w-[1200px]">
      <PageHeader title="Users" subtitle="Each person gets one role (see Roles for what each can do). Deactivating someone or changing their role takes effect on their very next click. Client logins only see their own projects in the client portal.">
        {can && <button onClick={() => setEdit('new')} className={btn.primary}><Plus className="w-3.5 h-3.5" />Add user</button>}</PageHeader>
      {error && <Alert>{error}</Alert>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!users ? <Empty>Loading…</Empty> :
        <Table head={['Name', 'Email', 'Role', 'Client', 'Status']}>{users.map(u => <tr key={u.id} data-user={u.email} onClick={() => can && setEdit(u)} className={can ? 'cursor-pointer hover:bg-stone-50' : ''}>
          <td className="px-4 py-2.5 font-medium">{u.full_name}</td><td className="px-4 py-2.5 text-xs">{u.email}</td><td className="px-4 py-2.5 text-xs">{ROLE_LABEL(u.role)}</td>
          <td className="px-4 py-2.5 text-xs">{u.client_name ?? '—'}</td><td className="px-4 py-2.5"><Pill tone={u.is_active ? 'green' : 'stone'} label={u.is_active ? 'Active' : 'Disabled'} /></td></tr>)}</Table>}</div>
      {edit && <UserForm u={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </div>
  )
}

function UserForm({ u, onClose, onSaved }: { u: UserRow | null; onClose: () => void; onSaved: () => void }) {
  const { data: clients } = useLoad<Client[]>('/clients')
  const [f, setF] = useState({ email: u?.email ?? '', full_name: u?.full_name ?? '', role: u?.role ?? 'INTERIOR_DESIGNER', password: '', phone: u?.phone ?? '', client_id: u?.client_id ?? '', is_active: u?.is_active ?? true })
  const a = useAction()
  const save = (e: React.FormEvent) => {
    e.preventDefault()
    const client_id = f.role === 'CLIENT' ? f.client_id || null : null
    a.run('s', async () => {
      if (u) await api.patch(`/users/${u.id}`, { full_name: f.full_name, role: f.role, phone: f.phone || null, client_id, is_active: f.is_active, ...(f.password ? { password: f.password } : {}) })
      else await api.post('/users', { email: f.email, full_name: f.full_name, role: f.role, password: f.password, phone: f.phone || undefined, client_id: client_id ?? undefined })
      onSaved()
    })
  }
  return (
    <Drawer label={u ? 'Edit user' : 'New user'} title={u ? `Edit ${u.full_name}` : 'New user'} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        <Field label="Email *"><input type="email" value={f.email} onChange={e => setF({ ...f, email: e.target.value })} disabled={!!u} required className={input} /></Field>
        <Field label="Full name *"><input value={f.full_name} onChange={e => setF({ ...f, full_name: e.target.value })} required className={input} /></Field>
        <Field label="Role"><select aria-label="Role" value={f.role} onChange={e => setF({ ...f, role: e.target.value })} className={input}>{ROLES.map(r => <option key={r} value={r}>{ROLE_LABEL(r)}</option>)}</select></Field>
        {f.role === 'CLIENT' && <Field label="Client (whose projects they see)"><select aria-label="Linked client" value={f.client_id} onChange={e => setF({ ...f, client_id: e.target.value })} className={input}>
          <option value="">— pick a client —</option>{clients?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}
        <Field label={u ? 'New password (leave blank to keep)' : 'Password * (8+ characters, letters and digits)'}><input type="password" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} required={!u} autoComplete="new-password" className={input} /></Field>
        <Field label="Phone"><input value={f.phone} onChange={e => setF({ ...f, phone: e.target.value })} className={input} /></Field>
        {u && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={e => setF({ ...f, is_active: e.target.checked })} />Active (can sign in)</label>}
        {a.error && <Alert>{a.error}</Alert>}
        <button disabled={!!a.busy} className={btn.primary + ' w-full py-2'}>{a.busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{u ? 'Save changes' : 'Create user'}</button>
      </form>
    </Drawer>
  )
}

// ── Roles ─────────────────────────────────────────────────────────────────────
export function RolesView() {
  const { data, error } = useLoad<{ roles: string[]; capabilities: { name: string; roles: string[] }[] }>('/settings/roles')
  return (
    <div className="space-y-5 max-w-[1500px]">
      <PageHeader title="Roles & permissions" subtitle="Generated from the access checks in the server code, so this table is always what the system actually enforces. Super admin can do everything." />
      {error && <Alert>{error}</Alert>}
      {!data ? <Empty>Loading…</Empty> : <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-x-auto"><table className="text-xs" data-testid="roles-matrix">
        <thead><tr className="bg-stone-50"><th className="text-left px-3 py-2 sticky left-0 bg-stone-50">Capability</th>{data.roles.map(r => <th key={r} className="px-2 py-2 font-medium text-stone-500 whitespace-nowrap [writing-mode:vertical-rl] rotate-180">{ROLE_LABEL(r)}</th>)}</tr></thead>
        <tbody className="divide-y divide-stone-50">{data.capabilities.map(c => <tr key={c.name}><td className="px-3 py-1.5 sticky left-0 bg-white whitespace-nowrap">{c.name}</td>
          {data.roles.map(r => <td key={r} className="px-2 py-1.5 text-center">{c.roles.includes(r) ? <Check className="w-3.5 h-3.5 text-green-700 inline" aria-label="yes" /> : <X className="w-3 h-3 text-stone-200 inline" aria-label="no" />}</td>)}</tr>)}</tbody></table></div>}
    </div>
  )
}

// ── System ────────────────────────────────────────────────────────────────────
interface Sys { python: string; platform: string; database: { kind: string; size_bytes: number | null; tables: number; rows: Record<string, number> }; storage: { path: string; writable: boolean }
  ocr: Record<string, boolean>; pdf: boolean; pdf_fonts?: { rupee: boolean; gujarati: boolean; hindi: boolean; shaping: boolean; file: string | null; why: string }; dxf: boolean; ollama: { reachable: boolean; models: string[] }; token_minutes: number; warnings: string[]
  schema?: { revision: string | null; head: string | null; up_to_date: boolean; tool: string }
  jobs?: { backend: string; broker: string | null; queued_emails: number; sending_emails: number; waiting_documents: number; reading_documents: number } }
const yes = (b: boolean) => <Pill tone={b ? 'green' : 'stone'} label={b ? 'available' : 'not installed'} />
export function SystemStatus() {
  const { data: s, error } = useLoad<Sys>('/settings/system')
  return (
    <div className="space-y-5 max-w-[1100px]">
      <PageHeader title="System" subtitle="Live status of this installation (admin only)." />
      {error && <Alert>{error}</Alert>}
      {!s ? <Empty>Loading…</Empty> : <>
        {s.warnings.map(w => <Alert key={w}>{w}</Alert>)}
        <div className="grid md:grid-cols-2 gap-4">
          <Card title="Server"><dl className="text-sm space-y-1.5"><div className="flex justify-between"><dt>Python</dt><dd>{s.python}</dd></div><div className="flex justify-between gap-3"><dt>Platform</dt><dd className="text-right text-xs">{s.platform}</dd></div>
            <div className="flex justify-between"><dt>Database</dt><dd>{s.database.kind}{s.database.size_bytes != null ? ` · ${(s.database.size_bytes / 1048576).toFixed(1)} MB` : ''} · {s.database.tables} tables</dd></div>
            <div className="flex justify-between gap-3"><dt>Uploads folder</dt><dd className="text-right text-xs">{s.storage.path} {yes(s.storage.writable)}</dd></div><div className="flex justify-between"><dt>Sign-in lasts</dt><dd>{Math.round(s.token_minutes / 60)} h</dd></div></dl></Card>
          <Card title="Engines"><dl className="text-sm space-y-1.5" data-testid="engines">{[['PDF text layer', s.ocr.pdf_text_layer], ['PaddleOCR', s.ocr.paddleocr], ['RapidOCR', s.ocr.rapidocr], ['Tesseract', s.ocr.tesseract], ['PDF generation', s.pdf], ['DXF (CAD)', s.dxf], ['Local LLM (Ollama)', s.ollama.reachable]]
            .map(([l, v]) => <div key={String(l)} className="flex justify-between"><dt>{l}</dt><dd>{yes(Boolean(v))}</dd></div>)}
            {s.pdf_fonts && <div className="pt-2 mt-1 border-t border-stone-100 text-xs space-y-1" data-testid="pdf-fonts">
              <div className="flex justify-between"><dt>PDF: rupee sign ₹</dt><dd>{yes(s.pdf_fonts.rupee)}</dd></div>
              <div className="flex justify-between"><dt>PDF: Gujarati / Hindi text</dt><dd>{yes(s.pdf_fonts.gujarati && s.pdf_fonts.hindi && s.pdf_fonts.shaping)}</dd></div>
              <p className="text-stone-500">{s.pdf_fonts.file ? `Font: ${s.pdf_fonts.file} (${s.pdf_fonts.why})` : s.pdf_fonts.why}</p></div>}</dl></Card>
        </div>
        {s.schema && s.jobs && <div className="grid md:grid-cols-2 gap-4">
          <Card title="Database schema"><dl className="text-sm space-y-1.5" data-testid="schema-status">
            <div className="flex justify-between"><dt>Migrations</dt><dd>{s.schema.tool}</dd></div>
            <div className="flex justify-between"><dt>Database revision</dt><dd className="font-mono">{s.schema.revision ?? '—'}</dd></div>
            <div className="flex justify-between"><dt>Code expects</dt><dd className="font-mono">{s.schema.head}</dd></div>
            <div className="flex justify-between"><dt>Up to date</dt><dd>{yes(s.schema.up_to_date)}</dd></div></dl>
            {!s.schema.up_to_date && <p className="text-[11px] text-amber-800 mt-2">Run <code>cd apps/api &amp;&amp; alembic upgrade head</code> (or restart the API with AUTO_MIGRATE on).</p>}</Card>
          <Card title="Background jobs"><dl className="text-sm space-y-1.5" data-testid="jobs-status">
            <div className="flex justify-between"><dt>Runs on</dt><dd>{s.jobs.backend === 'celery' ? 'Celery workers' : 'This API process (threads)'}</dd></div>
            {s.jobs.broker && <div className="flex justify-between gap-3"><dt>Broker</dt><dd className="text-right text-xs font-mono">{s.jobs.broker}</dd></div>}
            <div className="flex justify-between"><dt>Emails waiting / sending</dt><dd>{s.jobs.queued_emails} / {s.jobs.sending_emails}</dd></div>
            <div className="flex justify-between"><dt>Documents waiting / reading</dt><dd>{s.jobs.waiting_documents} / {s.jobs.reading_documents}</dd></div></dl>
            <p className="text-[11px] text-stone-500 mt-2">{s.jobs.backend === 'celery' ? 'Start workers with: celery -A app.worker worker (add --pool=solo on Windows).' : 'Fine for one API server. For several servers set TASK_BACKEND=celery and run workers.'}</p></Card>
        </div>}
        <Card title="Records"><div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">{Object.entries(s.database.rows).map(([t, n]) => <div key={t} className="flex justify-between bg-stone-50 rounded px-2 py-1"><span>{t}</span><b>{n}</b></div>)}</div></Card>
      </>}
    </div>
  )
}

// ── AI ────────────────────────────────────────────────────────────────────────
interface AIResp { ollama: { url: string; model: string; reachable: boolean; models: string[]; model_installed: boolean }; features: { name: string; engine: string; note: string }[]; how_to_enable_llm: string }
export function AISettings() {
  const { data, error } = useLoad<AIResp>('/settings/ai')
  return (
    <div className="space-y-5 max-w-[1100px]">
      <PageHeader title="AI engines" subtitle="What each 'AI' feature really runs on. Everything works with zero paid services; a local LLM is optional and never does geometry or money." />
      {error && <Alert>{error}</Alert>}
      {!data ? <Empty>Loading…</Empty> : <>
        <Card title="Local LLM (Ollama)"><p className="text-sm">{data.ollama.reachable ? <>Running at {data.ollama.url}. Model <b>{data.ollama.model}</b> {data.ollama.model_installed ? 'is installed.' : 'is NOT pulled yet.'}</> : <>Not running at {data.ollama.url} — the AI Designer uses the rule-based brief parser instead.</>}</p>
          <p className="text-xs text-stone-500 mt-2">{data.how_to_enable_llm}</p></Card>
        <Card title="Features"><Table head={['Feature', 'Runs on', 'Notes']}>{data.features.map(f => <tr key={f.name}><td className="px-4 py-2 text-sm font-medium">{f.name}</td><td className="px-4 py-2 text-xs">{f.engine}</td><td className="px-4 py-2 text-xs text-stone-500">{f.note}</td></tr>)}</Table></Card>
      </>}
    </div>
  )
}
