'use client'
import { useEffect, useState } from 'react'
import { api, Project, Room } from '@/lib/api'

export function ProjectRoomPicker({ refreshKey = 0, onChange, guard }: {
  refreshKey?: number
  /** Called before the user switches project/room; return false to stay (e.g. unsaved edits). */
  guard?: () => boolean
  onChange: (sel: { projectId: string; roomId: string; room: Room | null }) => void
}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [rooms, setRooms] = useState<Room[]>([])
  const [pid, setPid] = useState('')
  const [rid, setRid] = useState('')

  useEffect(() => { api.get<Project[]>('/projects').then(p => { setProjects(p); if (p.length && !pid) setPid(p[0].id) }).catch(() => {}) }, [refreshKey]) // eslint-disable-line
  useEffect(() => {
    if (!pid) { setRooms([]); setRid(''); return }
    api.get<Room[]>(`/projects/${pid}/rooms`).then(r => { setRooms(r); setRid(cur => r.some(x => x.id === cur) ? cur : (r[0]?.id ?? '')) }).catch(() => {})
  }, [pid, refreshKey])
  useEffect(() => { onChange({ projectId: pid, roomId: rid, room: rooms.find(r => r.id === rid) ?? null }) }, [pid, rid, rooms]) // eslint-disable-line

  const sel = 'text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400'
  return (
    <div className="flex gap-3 flex-wrap">
      <select aria-label="Project" value={pid} onChange={e => { if (!guard || guard()) setPid(e.target.value) }} className={sel}>
        {projects.length === 0 && <option value="">No projects yet</option>}
        {projects.map(p => <option key={p.id} value={p.id}>{p.project_number} · {p.name}</option>)}
      </select>
      <select aria-label="Room" value={rid} onChange={e => { if (!guard || guard()) setRid(e.target.value) }} className={sel} disabled={!rooms.length}>
        {rooms.length === 0 && <option value="">No rooms yet</option>}
        {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
    </div>
  )
}
