'use client'
// Settings → Backups (admins): every table + the uploads folder in one checksummed zip; restore works into SQLite or Postgres.
import { useRef, useState } from 'react'
import { CheckCircle2, Download, Loader2, RotateCcw, ShieldCheck, Trash2, Upload, DatabaseBackup } from 'lucide-react'
import { api, downloadFile } from '@/lib/api'
import { Alert, btn, Card, Drawer, Empty, Field, hasRole, input, Ok, PageHeader, Pill, Table, useAction, useLoad, useRole } from '@/components/ui/kit'

interface Backup { name: string; kind: string; size_bytes: number; created_at?: string; created_by?: string | null; database?: string; schema_revision?: string
  tables?: number; rows?: number; files?: number; files_bytes?: number; include_files?: boolean; error?: string }
interface List { backups: Backup[]; dir: string; database: string; daily: { enabled: boolean; after_hour: number; keep: number; last_day: string | null } }
interface Verify extends Backup { ok: boolean; problems: string[] }
interface Restored { restored: string; rows: number; files: number; safety_backup: string | null; schema_revision_in_backup: string; schema_revision_now: string }

const KIND: Record<string, string> = { auto: 'Daily', manual: 'Manual', 'pre-restore': 'Before restore', uploaded: 'Uploaded', damaged: 'Damaged' }
export function size(b: number) { return b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB` }
const when = (s?: string) => (s ? new Date(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—')

export function BackupsView() {
  const role = useRole(); const admin = hasRole(role, ['ADMIN'])
  const { data, error, reload } = useLoad<List>(admin ? '/backups' : null)
  const [files, setFiles] = useState(true); const [checked, setChecked] = useState<Verify | null>(null); const [restoring, setRestoring] = useState<Backup | null>(null)
  const [done, setDone] = useState<Restored | null>(null)
  const a = useAction(); const up = useRef<HTMLInputElement>(null)
  if (role && !admin) return <div className="max-w-3xl"><PageHeader title="Backups" subtitle="Only admins can see or restore backups." /></div>
  const create = () => a.run('create', async () => { const b = await api.postLong<Backup>('/backups', { include_files: files }); await reload(); return b }, 'Backup created')
  const verify = (b: Backup) => a.run('v' + b.name, async () => setChecked(await api.postLong<Verify>(`/backups/${b.name}/verify`)))
  const upload = (f: File) => a.run('upload', async () => { const form = new FormData(); form.append('file', f); setChecked(await api.upload<Verify>('/backups/upload', form, 600_000)); await reload() })
  const remove = (b: Backup) => { const t = window.prompt(`Type the file name to delete it:\n${b.name}`); if (t) a.run('d' + b.name, async () => { await api.post(`/backups/${b.name}/delete`, { confirm: t }); await reload() }) }
  return (
    <div className="space-y-5 max-w-[1200px]">
      <PageHeader title="Backups" subtitle="One zip holds every table and the uploads folder, with a checksum for each. A backup restores into SQLite or Postgres — also how you move to Postgres.">
        <label className="flex items-center gap-1.5 text-xs text-stone-600"><input type="checkbox" checked={files} onChange={e => setFiles(e.target.checked)} />Include uploaded files</label>
        <button onClick={create} disabled={!!a.busy} className={btn.primary}>{a.busy === 'create' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <DatabaseBackup className="w-3.5 h-3.5" />}Back up now</button>
        <button onClick={() => up.current?.click()} disabled={!!a.busy} className={btn.ghost}><Upload className="w-3.5 h-3.5" />Upload a backup</button>
        <input ref={up} type="file" accept=".zip,application/zip" className="hidden" aria-label="Backup file" onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = '' }} />
      </PageHeader>
      {error && <Alert>{error}</Alert>}{a.error && <Alert>{a.error}</Alert>}{a.ok && <Ok>{a.ok}</Ok>}
      {done && <div data-testid="restore-done" className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900">
        <CheckCircle2 className="w-4 h-4 inline mr-1" />Restored <b>{done.restored}</b>: {done.rows} rows{done.files ? `, ${done.files} files` : ''} (schema {done.schema_revision_in_backup} → {done.schema_revision_now}).
        {done.safety_backup && <> The data from just before is saved as <b>{done.safety_backup}</b>.</>} Everyone may need to sign in again.</div>}
      {checked && <div data-testid="verify-result" className={`rounded-lg border px-4 py-3 text-sm ${checked.ok ? 'border-green-200 bg-green-50 text-green-900' : 'border-red-200 bg-red-50 text-red-800'}`}>
        <ShieldCheck className="w-4 h-4 inline mr-1" />{checked.name}: {checked.ok ? `all ${checked.tables} tables and ${checked.files} files match their checksums (${checked.rows} rows).` : 'problems found:'}
        {checked.problems.map(p => <p key={p}>• {p}</p>)}</div>}
      {data && <div className="grid md:grid-cols-3 gap-4">
        <Card title="Daily backup"><p className="text-sm" data-testid="daily-status">{data.daily.enabled ? <>On — once a day after {String(data.daily.after_hour).padStart(2, '0')}:00, keeping the last {data.daily.keep}. Last: {data.daily.last_day ?? 'not yet'}</> : 'Off (BACKUP_DAILY=false in apps/api/.env)'}</p></Card>
        <Card title="Saved in"><p className="text-xs font-mono break-all">{data.dir}</p><p className="text-[11px] text-stone-500 mt-1">Copy backups somewhere else too (another disk, cloud drive) — a backup on the same disk doesn't survive a disk failure.</p></Card>
        <Card title="Database"><p className="text-sm">{data.database === 'postgresql' ? 'PostgreSQL' : 'SQLite'}</p><p className="text-[11px] text-stone-500 mt-1">Backups contain client data and password hashes — treat the files as confidential.</p></Card>
      </div>}
      <div className="bg-white border border-stone-200 rounded-lg shadow-sm">{!data ? <Empty>Loading…</Empty> : data.backups.length === 0 ? <Empty>No backups yet. Click “Back up now”.</Empty> :
        <Table head={['Backup', 'Made', 'Contents', 'Size', '']}>{data.backups.map(b => <tr key={b.name} data-backup={b.name}>
          <td className="px-4 py-2"><p className="font-mono text-xs text-stone-800">{b.name}</p><Pill tone={b.kind === 'damaged' ? 'red' : b.kind === 'pre-restore' ? 'amber' : undefined} label={KIND[b.kind] ?? b.kind} /></td>
          <td className="px-4 py-2 text-xs text-stone-600">{when(b.created_at)}{b.created_by ? <span className="block text-stone-400">{b.created_by}</span> : null}</td>
          <td className="px-4 py-2 text-xs text-stone-600">{b.error ? <span className="text-red-700">{b.error}</span> : <>{b.rows} rows · {b.include_files ? `${b.files} files` : 'no files'}<span className="block text-stone-400">{b.database} · schema {b.schema_revision}</span></>}</td>
          <td className="px-4 py-2 text-xs">{size(b.size_bytes)}</td>
          <td className="px-4 py-2"><div className="flex gap-1 justify-end">
            <button onClick={() => downloadFile(`/backups/${b.name}/download`, b.name)} className={btn.small} aria-label={`Download ${b.name}`}><Download className="w-3 h-3" /></button>
            {!b.error && <button onClick={() => verify(b)} disabled={!!a.busy} className={btn.small} aria-label={`Verify ${b.name}`}>{a.busy === 'v' + b.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}Verify</button>}
            {!b.error && <button onClick={() => setRestoring(b)} className={btn.small} aria-label={`Restore ${b.name}`}><RotateCcw className="w-3 h-3" />Restore</button>}
            <button onClick={() => remove(b)} className={btn.small} aria-label={`Delete ${b.name}`}><Trash2 className="w-3 h-3" /></button></div></td></tr>)}</Table>}</div>
      {restoring && <RestoreDialog b={restoring} onClose={() => setRestoring(null)} onDone={r => { setRestoring(null); setDone(r); reload() }} />}
    </div>
  )
}

function RestoreDialog({ b, onClose, onDone }: { b: Backup; onClose: () => void; onDone: (r: Restored) => void }) {
  const [confirm, setConfirm] = useState(''); const [withFiles, setWithFiles] = useState(!!b.include_files); const a = useAction()
  const go = () => a.run('r', async () => onDone(await api.postLong<Restored>(`/backups/${b.name}/restore`, { confirm, restore_files: withFiles })))
  return <Drawer label="Restore backup" title={`Restore ${b.name}`} onClose={onClose}>
    <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900 space-y-1">
      <p><b>This replaces ALL current data</b> with the backup from {when(b.created_at)} ({b.rows} rows).</p>
      <p>A safety backup of the current data is taken first, and if anything goes wrong nothing is changed.</p></div>
    {b.include_files && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={withFiles} onChange={e => setWithFiles(e.target.checked)} />Also restore the uploaded files ({b.files}) — the current folder is kept beside it</label>}
    <Field label="Type RESTORE to confirm"><input aria-label="Confirm restore" value={confirm} onChange={e => setConfirm(e.target.value)} className={input} autoComplete="off" /></Field>
    {a.error && <Alert>{a.error}</Alert>}
    <button onClick={go} disabled={confirm !== 'RESTORE' || !!a.busy} className={btn.danger + ' w-full'}>{a.busy ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />Restoring…</> : 'Restore now'}</button>
  </Drawer>
}
