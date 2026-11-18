'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, Measurement, Room } from '@/lib/api'
import { Card, Empty, PageHeader, Pill, ProjectPicker, Table } from '@/components/ui/kit'

const PRIORITY = ['USER_VERIFIED', 'SITE_SURVEY', 'FLOOR_PLAN', 'OCR', 'VLM', 'AI_ESTIMATE']

export function MeasurementsView() {
  const [pid, setPid] = useState('')
  const [rows, setRows] = useState<{ room: Room; ms: Measurement[] }[] | null>(null)
  useEffect(() => {
    if (!pid) return; setRows(null)
    api.get<Room[]>(`/projects/${pid}/rooms`).then(rooms => Promise.all(rooms.map(async room => ({ room, ms: await api.get<Measurement[]>(`/rooms/${room.id}/measurements`).catch(() => []) }))))
      .then(setRows).catch(() => setRows([]))
  }, [pid])
  return (
    <div className="space-y-5 max-w-[1100px]">
      <PageHeader title="Measurements" subtitle={<>All measurements of a project with where each value came from. Stronger sources win: {PRIORITY.join(' > ')}; a verified value is only replaced by another verified one. Add or correct values in <Link href="/survey/rooms" className="underline">Rooms</Link> or apply them from <Link href="/survey/documents" className="underline">Documents (OCR)</Link>.</>} />
      <ProjectPicker value={pid} onChange={setPid} />
      {!rows ? <Empty>Pick a project.</Empty> : rows.length === 0 ? <Empty>No rooms yet. Add one in Site Survey → Rooms.</Empty> : rows.map(({ room, ms }) => (
        <Card key={room.id} title={`${room.name} · ${room.room_type}`}>
          {ms.length === 0 ? <Empty>No measurements yet.</Empty> : <Table head={['Measurement', 'Value', 'Source', 'Confidence', 'Verified']} right={[1, 3]}>
            {ms.map(m => <tr key={m.label} data-m={`${room.name}:${m.label}`}><td className="px-4 py-2 text-sm">{m.label}</td><td className="px-4 py-2 text-right font-mono text-sm">{m.value} {m.unit}</td>
              <td className="px-4 py-2"><Pill tone={m.source === 'USER_VERIFIED' ? 'green' : m.source === 'OCR' ? 'blue' : 'stone'} label={m.source.replace('_', ' ')} /></td>
              <td className="px-4 py-2 text-right text-xs">{Math.round(m.confidence)}%</td><td className="px-4 py-2 text-xs">{m.verified ? '✓ verified' : '—'}</td></tr>)}
          </Table>}
        </Card>))}
    </div>
  )
}
