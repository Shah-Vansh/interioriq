'use client'
import { OpeningsCard } from '@/components/survey/openings-card'
import { useCallback, useEffect, useState } from 'react'
import { Plus, CheckCircle2, AlertCircle, ShieldCheck } from 'lucide-react'
import { api, ApiError, Measurement } from '@/lib/api'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import { cn } from '@/lib/utils'

const SOURCES = ['USER_VERIFIED', 'SITE_SURVEY', 'FLOOR_PLAN', 'OCR', 'VLM', 'AI_ESTIMATE']
const LABELS = ['Length', 'Width', 'Ceiling Height']
const ROOM_TYPES = ['MASTER_BEDROOM', 'BEDROOM', 'LIVING', 'DINING', 'KITCHEN', 'BATHROOM', 'STUDY', 'OTHER']
const BADGE: Record<string, string> = {
  USER_VERIFIED: 'bg-green-50 text-green-700', SITE_SURVEY: 'bg-blue-50 text-blue-700', FLOOR_PLAN: 'bg-cyan-50 text-cyan-700',
  OCR: 'bg-purple-50 text-purple-700', VLM: 'bg-amber-50 text-amber-700', AI_ESTIMATE: 'bg-red-50 text-red-700',
}

export function RoomsView() {
  const [sel, setSel] = useState({ projectId: '', roomId: '' })
  const [refresh, setRefresh] = useState(0)
  const [ms, setMs] = useState<Measurement[]>([])
  const [label, setLabel] = useState(LABELS[0]); const [value, setValue] = useState(''); const [source, setSource] = useState('USER_VERIFIED')
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null)
  const [roomName, setRoomName] = useState(''); const [roomType, setRoomType] = useState(ROOM_TYPES[0])

  const loadMs = useCallback(() => {
    if (!sel.roomId) { setMs([]); return }
    api.get<Measurement[]>(`/rooms/${sel.roomId}/measurements`).then(setMs).catch(() => setMs([]))
  }, [sel.roomId])
  useEffect(() => { loadMs() }, [loadMs])

  const addRoom = async (e: React.FormEvent) => {
    e.preventDefault(); if (!sel.projectId) return
    try { await api.post(`/projects/${sel.projectId}/rooms`, { name: roomName, room_type: roomType }); setRoomName(''); setRefresh(k => k + 1) }
    catch (err) { setFeedback({ ok: false, text: err instanceof ApiError ? err.message : 'Failed' }) }
  }
  const saveMeasurement = async (e: React.FormEvent) => {
    e.preventDefault(); setFeedback(null)
    try {
      const r = await api.put<{ applied: boolean; reason: string | null }>(`/rooms/${sel.roomId}/measurements`,
        { label, value: parseFloat(value), source, confidence: source === 'USER_VERIFIED' ? 100 : 80 })
      setFeedback(r.applied ? { ok: true, text: `${label} saved from ${source}.` } : { ok: false, text: r.reason ?? 'Rejected' })
      setValue(''); loadMs()
    } catch (err) { setFeedback({ ok: false, text: err instanceof ApiError ? err.message : 'Failed' }) }
  }
  const input = 'text-sm border border-stone-200 rounded px-3 py-1.5 bg-white outline-none focus:border-amber-400'

  return (
    <div className="space-y-5 max-w-[1100px]">
      <div><h1 className="text-xl font-semibold text-stone-900">Rooms & Measurements</h1>
        <p className="text-sm text-stone-500 mt-0.5">Canonical Room Model. Higher-priority sources are never overwritten by lower ones.</p></div>
      <ProjectRoomPicker refreshKey={refresh} onChange={s => setSel({ projectId: s.projectId, roomId: s.roomId })} />

      <form onSubmit={addRoom} className="flex gap-2 flex-wrap items-center bg-white border border-stone-200 rounded-lg p-3 shadow-sm">
        <input value={roomName} onChange={e => setRoomName(e.target.value)} placeholder="New room name" required className={input + ' flex-1 min-w-40'} />
        <select value={roomType} onChange={e => setRoomType(e.target.value)} className={input}>{ROOM_TYPES.map(t => <option key={t}>{t}</option>)}</select>
        <button disabled={!sel.projectId} className="flex items-center gap-1.5 bg-amber-700 hover:bg-amber-800 disabled:opacity-50 text-white text-sm font-medium px-3 py-1.5 rounded"><Plus className="w-3.5 h-3.5" />Add room</button>
      </form>

      {sel.roomId && (<>
        <form onSubmit={saveMeasurement} className="flex gap-2 flex-wrap items-center bg-white border border-stone-200 rounded-lg p-3 shadow-sm">
          <select value={label} onChange={e => setLabel(e.target.value)} className={input}>{LABELS.map(l => <option key={l}>{l}</option>)}</select>
          <input value={value} onChange={e => setValue(e.target.value)} type="number" min="1" step="any" placeholder="mm" required className={input + ' w-28'} />
          <select value={source} onChange={e => setSource(e.target.value)} className={input}>{SOURCES.map(s => <option key={s}>{s}</option>)}</select>
          <button className="flex items-center gap-1.5 bg-stone-900 hover:bg-stone-800 text-white text-sm font-medium px-3 py-1.5 rounded"><ShieldCheck className="w-3.5 h-3.5" />Save measurement</button>
        </form>
        {feedback && <p className={cn('text-xs rounded px-3 py-2 border', feedback.ok ? 'text-green-700 bg-green-50 border-green-200' : 'text-red-600 bg-red-50 border-red-200')}>{feedback.text}</p>}
        <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
          {ms.length === 0 ? <p className="p-8 text-center text-sm text-stone-400">No measurements yet. Length and Width are required before designing.</p>
            : <table className="w-full text-sm"><thead><tr className="bg-stone-50 border-b border-stone-100">
                {['Dimension', 'Value', 'Source', 'Confidence', 'Verified'].map(h => <th key={h} className="text-left text-[11px] text-stone-400 uppercase tracking-wide px-5 py-3">{h}</th>)}</tr></thead>
                <tbody className="divide-y divide-stone-50">{ms.map(m => (
                  <tr key={m.label}><td className="px-5 py-3 font-medium">{m.label}</td>
                    <td className="px-5 py-3 font-mono">{m.value.toLocaleString()} {m.unit}</td>
                    <td className="px-5 py-3"><span className={cn('text-[11px] font-semibold px-2 py-0.5 rounded-full', BADGE[m.source])}>{m.source}</span></td>
                    <td className="px-5 py-3 text-stone-500">{m.confidence}%</td>
                    <td className="px-5 py-3">{m.verified ? <CheckCircle2 className="w-4 h-4 text-green-500" /> : <AlertCircle className="w-4 h-4 text-amber-400" />}</td></tr>))}</tbody></table>}
        </div>
        <OpeningsCard key={sel.roomId + ms.length} roomId={sel.roomId} L={ms.find(m => m.label === 'Length')?.value ?? null} W={ms.find(m => m.label === 'Width')?.value ?? null} />
      </>)}
    </div>
  )
}
