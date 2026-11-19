'use client'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { Bell, Search, Plus, ChevronRight } from 'lucide-react'
import Link from 'next/link'
import { api, session } from '@/lib/api'

const LABELS: Record<string, string> = {
  dashboard: 'Dashboard', crm: 'CRM', leads: 'Leads', clients: 'Clients', contacts: 'Contacts', followups: 'Follow-ups',
  projects: 'Projects', active: 'Active', completed: 'Completed', archived: 'Archived',
  survey: 'Site Survey', rooms: 'Rooms', measurements: 'Measurements', photos: 'Photos', documents: 'Documents',
  design: 'Design Studio', '3d': '3D Editor', renders: 'Renders', plans: 'Floor Plans',
  elevations: 'Elevations', ceiling: 'Ceiling', electrical: 'Electrical', cad: 'CAD', versions: 'Versions',
  catalogue: 'Catalogue', furniture: 'Furniture', materials: 'Materials', lighting: 'Lighting', hardware: 'Hardware', suppliers: 'Suppliers',
  estimation: 'Estimation', boq: 'BOQ', costing: 'Costing', takeoff: 'Take-off', quotations: 'Quotations', invoices: 'Invoices',
  execution: 'Execution', procurement: 'Procurement', po: 'Purchase Orders', inventory: 'Inventory',
  manufacturing: 'Manufacturing', cutting: 'Cutting Lists', delivery: 'Delivery', installation: 'Installation', qc: 'Quality Control',
  'client-portal': 'Client Portal', finance: 'Finance', payables: 'Payables', 'accounting-export': 'Accounting export', reports: 'Reports', revenue: 'Revenue', profitability: 'Profitability',
  settings: 'Settings', notifications: 'Notifications', company: 'Company', users: 'Users', roles: 'Roles', system: 'System', backups: 'Backups',
}
const AI_LABEL: Record<string, string> = { design: 'AI Designer', reports: 'AI Project Manager', settings: 'AI Engines' }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i
const NEW_MENU: [string, string][] = [['Lead', '/crm/leads'], ['Client', '/crm/clients'], ['Project', '/projects'], ['Room & measurements', '/survey/rooms'],
  ['AI design', '/design/ai'], ['BOQ / quotation', '/estimation/boq'], ['Catalogue item', '/catalogue/furniture'], ['Supplier', '/catalogue/suppliers']]

export function Topbar() {
  const pathname = usePathname(); const router = useRouter()
  const [client, setClient] = useState(false)
  const [high, setHigh] = useState(0)
  const [q, setQ] = useState(''); const [hits, setHits] = useState<{ type: string; label: string; href: string }[] | null>(null)
  const [menu, setMenu] = useState(false); const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const isClient = session.user()?.role === 'CLIENT'; setClient(isClient)
    if (!isClient) api.get<{ counts: Record<string, number> }>('/ai/alerts').then(a => setHigh(a.counts.HIGH ?? 0)).catch(() => {})
  }, [pathname])
  useEffect(() => {
    if (q.trim().length < 2) { setHits(null); return }
    const t = setTimeout(() => api.get<{ type: string; label: string; href: string }[]>(`/search?q=${encodeURIComponent(q.trim())}`).then(setHits).catch(() => setHits([])), 250)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) { setHits(null); setMenu(false) } }
    const key = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); document.getElementById('global-search')?.focus() } }
    document.addEventListener('mousedown', close); window.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', close); window.removeEventListener('keydown', key) }
  }, [])
  const crumbs = pathname.split('/').filter(Boolean).map((seg, i, arr) => ({
    label: seg === 'ai' ? AI_LABEL[arr[i - 1]] ?? 'AI' : UUID.test(seg) ? 'Project' : LABELS[seg] || seg.charAt(0).toUpperCase() + seg.slice(1),
    href: '/' + arr.slice(0, i + 1).join('/'), isLast: i === arr.length - 1,
  }))
  const go = (href: string) => { setQ(''); setHits(null); setMenu(false); router.push(href) }
  return (
    <header className="h-14 border-b border-stone-200 bg-white flex items-center px-6 gap-4 flex-shrink-0">
      <nav className="flex items-center gap-1 flex-1 min-w-0">
        {crumbs.map((c, i) => (
          <div key={c.href} className="flex items-center gap-1 min-w-0">
            {i > 0 && <ChevronRight className="w-3.5 h-3.5 text-stone-300 flex-shrink-0" />}
            {c.isLast ? <span className="text-sm font-medium text-stone-900 truncate">{c.label}</span>
              : <Link href={c.href} className="text-sm text-stone-400 hover:text-stone-700 transition-colors truncate">{c.label}</Link>}
          </div>))}
      </nav>
      {!client && <div ref={box} className="flex items-center gap-2 flex-shrink-0 relative">
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-stone-400 absolute left-2.5 top-2.5" />
          <input id="global-search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search…  Ctrl K" aria-label="Search everything"
            className="text-sm bg-stone-100 focus:bg-white border border-transparent focus:border-amber-400 rounded pl-8 pr-3 py-1.5 w-56 outline-none" />
          {hits && <div className="absolute right-0 top-10 w-96 bg-white border border-stone-200 rounded-lg shadow-lg z-50 max-h-96 overflow-y-auto" role="listbox" aria-label="Search results">
            {hits.length === 0 ? <p className="p-3 text-sm text-stone-400">Nothing found.</p> : hits.map((h, i) => <button key={i} role="option" aria-selected={false} onClick={() => go(h.href)}
              className="w-full text-left px-3 py-2 hover:bg-stone-50 flex justify-between gap-3 text-sm"><span className="truncate">{h.label}</span><span className="text-[11px] text-stone-400 whitespace-nowrap">{h.type}</span></button>)}</div>}
        </div>
        <Link href="/reports/ai" aria-label={`AI alerts: ${high} high`} title={high ? `${high} high-risk alert(s)` : 'No high-risk alerts'} className="relative p-2 hover:bg-stone-100 rounded text-stone-500 hover:text-stone-900">
          <Bell className="w-4 h-4" />{high > 0 && <span data-testid="alert-count" className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 text-[10px] leading-4 text-center bg-red-600 text-white rounded-full">{high}</span>}
        </Link>
        <button onClick={() => setMenu(m => !m)} aria-expanded={menu} className="flex items-center gap-1.5 bg-amber-700 hover:bg-amber-800 text-white text-sm font-medium px-3 py-1.5 rounded transition-colors">
          <Plus className="w-3.5 h-3.5" />New</button>
        {menu && <div className="absolute right-0 top-10 w-56 bg-white border border-stone-200 rounded-lg shadow-lg z-50 py-1" role="menu">
          {NEW_MENU.map(([l, h]) => <button key={l} role="menuitem" onClick={() => go(h)} className="w-full text-left px-3 py-1.5 text-sm hover:bg-stone-50">{l}</button>)}</div>}
      </div>}
    </header>
  )
}
