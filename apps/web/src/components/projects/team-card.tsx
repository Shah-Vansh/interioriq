'use client'
// M22 project team: who works on this project. With Settings → Company 'Limit staff to their projects' on, only these people
// (plus admins and the roles that see every project) can open it.
import { useState } from 'react'
import { UserMinus, UserPlus } from 'lucide-react'
import { api } from '@/lib/api'
import { Alert, btn, hasRole, input, useAction, useLoad, useRole } from '@/components/ui/kit'

interface Member { user_id: string; name: string; email: string; role: string; active: boolean; added_by: string | null; added_at: string | null }
interface Team { limited: boolean; all_projects_roles: string[]; members: Member[]; can_add: { user_id: string; name: string; role: string }[]; sees_all: { user_id: string; name: string; role: string }[] }
const roleLabel = (r: string) => r.replace(/_/g, ' ').toLowerCase()

export function TeamCard({ projectId }: { projectId: string }) {
  const role = useRole(); const manage = hasRole(role, ['ADMIN', 'PROJECT_MANAGER'])
  const { data, error, setData } = useLoad<Team>(`/projects/${projectId}/team`)
  const [pick, setPick] = useState(''); const a = useAction()
  if (error) return <Alert>{error}</Alert>
  if (!data) return <p className="text-xs text-stone-400">Loading…</p>
  const add = () => a.run('add', async () => { setData(await api.post<Team>(`/projects/${projectId}/team`, { user_id: pick })); setPick('') })
  const remove = (m: Member) => a.run(m.user_id, async () => { setData(await api.delete<Team>(`/projects/${projectId}/team/${m.user_id}`)) })
  return (
    <div className="space-y-3" data-testid="project-team">
      <p className={`text-[11px] rounded px-2 py-1 ${data.limited ? 'bg-amber-50 text-amber-900' : 'bg-stone-50 text-stone-500'}`}>
        {data.limited ? 'Access is limited: only the people below (plus admins and ' + data.all_projects_roles.filter(r => !['ADMIN', 'SUPER_ADMIN'].includes(r)).map(roleLabel).join(', ') + ') can open this project.'
          : 'All staff can open every project. An admin can limit staff to their teams in Settings → Company.'}</p>
      {a.error && <Alert>{a.error}</Alert>}
      {data.members.length === 0 ? <p className="text-xs text-stone-500">Nobody yet.</p> :
        <ul className="divide-y divide-stone-50">{data.members.map(m => <li key={m.user_id} data-member={m.name} className="py-1.5 flex items-center gap-2 text-sm">
          <span className="flex-1"><span className="font-medium text-stone-800">{m.name}</span> <span className="text-[11px] text-stone-400">{roleLabel(m.role)}{m.active ? '' : ' · deactivated'}</span></span>
          {manage && <button onClick={() => remove(m)} disabled={!!a.busy} aria-label={`Remove ${m.name}`} className="text-stone-400 hover:text-red-600"><UserMinus className="w-3.5 h-3.5" /></button>}</li>)}</ul>}
      {manage && data.can_add.length > 0 && <div className="flex gap-2">
        <select aria-label="Add team member" value={pick} onChange={e => setPick(e.target.value)} className={input + ' py-1 text-xs'}>
          <option value="">Add a person…</option>{data.can_add.map(u => <option key={u.user_id} value={u.user_id}>{u.name} — {roleLabel(u.role)}</option>)}</select>
        <button onClick={add} disabled={!pick || !!a.busy} className={btn.small}><UserPlus className="w-3 h-3" />Add</button></div>}
      {data.limited && data.sees_all.length > 0 && <p className="text-[11px] text-stone-400">Also see it (role): {data.sees_all.map(u => u.name).join(', ')}</p>}
    </div>
  )
}
