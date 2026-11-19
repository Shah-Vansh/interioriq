'use client'
// M35: design chat — what you type becomes options for the deterministic generator (or a catalogue question answered from the database).
// It never places furniture or computes money itself; every amount shown comes from the server.
import { useState } from 'react'
import { Loader2, MessageSquare, Send } from 'lucide-react'
import { api, GenerateResult } from '@/lib/api'
import { inrStr } from '@/lib/utils'

export interface ChatOptions { skip: string[]; tier: string; styles: string[]; kitchen_shape: string; seats: number | null }
interface ChatResp { reply: string; source: 'rules' | 'ollama'; options: ChatOptions; budget: string | null; result: GenerateResult | null
  items: { sku: string; name: string; category: string; price: string; size: string; stock: number; style: string | null }[] }
interface Msg { who: 'you' | 'iq'; text: string; items?: ChatResp['items']; source?: string }

export function DesignChat({ roomId, roomType, options, budget, prompt, inStock, onApply }: {
  roomId: string; roomType: string; options: ChatOptions; budget: string | null; prompt: string; inStock: boolean
  onApply: (r: { options: ChatOptions; budget: string | null; result: GenerateResult }) => void
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false)
  const send = async () => {
    const m = text.trim(); if (!m) return
    setMsgs(x => [...x, { who: 'you', text: m }]); setText(''); setBusy(true)
    try {
      const r = await api.post<ChatResp>(`/rooms/${roomId}/design-chat`, { message: m, room_type: roomType || undefined, options, budget: budget ?? undefined, prompt, catalogue_filter_in_stock: inStock })
      setMsgs(x => [...x, { who: 'iq', text: r.reply, items: r.items, source: r.source }])
      if (r.result) onApply({ options: r.options, budget: r.budget, result: r.result })
    } catch (e) { setMsgs(x => [...x, { who: 'iq', text: e instanceof Error ? e.message : 'Something went wrong' }]) } finally { setBusy(false) }
  }
  return <div className="bg-white border border-stone-200 rounded-lg p-4 shadow-sm" data-testid="design-chat">
    <h3 className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-2 flex items-center gap-1.5"><MessageSquare className="w-3.5 h-3.5" />Design chat</h3>
    <div className="space-y-2 max-h-72 overflow-y-auto mb-2" data-testid="chat-log">
      {msgs.length === 0 && <p className="text-[11px] text-stone-400">Try: “cheaper and more minimal”, “no armchair”, “add a bookshelf”, “under 2 lakh”, “L-shaped kitchen”, “6 seater”, or ask “which wardrobes under 60k?”</p>}
      {msgs.map((m, i) => <div key={i} className={m.who === 'you' ? 'text-right' : ''}>
        <div className={`inline-block text-xs px-2.5 py-1.5 rounded-lg max-w-[95%] text-left ${m.who === 'you' ? 'bg-amber-700 text-white' : 'bg-stone-100 text-stone-800'}`} data-chat={m.who}>{m.text}
          {m.items && m.items.length > 0 && <ul className="mt-1 space-y-0.5">{m.items.map(it => <li key={it.sku}>• {it.name} — Rs. {inrStr(it.price)} <span className="text-stone-500">({it.size} mm{it.stock ? '' : ', out of stock'})</span></li>)}</ul>}
          {m.source === 'ollama' && <span className="block text-[10px] text-stone-400 mt-0.5">read by the local AI model</span>}</div></div>)}
    </div>
    <div className="flex gap-1.5"><input aria-label="Design chat message" value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') send() }}
      placeholder="Tell the designer what to change…" className="flex-1 text-sm border border-stone-200 rounded px-2.5 py-1.5 bg-stone-50 outline-none focus:border-amber-400" />
      <button onClick={send} disabled={busy || !text.trim() || !roomId} aria-label="Send to design chat" className="px-2.5 rounded bg-amber-700 hover:bg-amber-800 text-white disabled:opacity-40">
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}</button></div>
  </div>
}
