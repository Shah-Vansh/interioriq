'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { navigation, NavItem } from '@/lib/nav'
import { cn } from '@/lib/utils'
import * as Icons from 'lucide-react'
import { useRouter } from 'next/navigation'
import { session } from '@/lib/api'

const Icon = ({ name, cls }: { name: string; cls?: string }) => {
  const L = (Icons as any)[name]; if (!L) return null; return <L className={cls} />
}

// Highlight only the MOST SPECIFIC matching link, so /survey/documents doesn't also light up /survey.
const HREFS = navigation.flatMap(n => [n, ...(n.children ?? [])]).map(n => n.href).filter(Boolean) as string[]
const bestMatch = (path: string) => HREFS.filter(h => path === h || path.startsWith(h + '/')).sort((a, b) => b.length - a.length)[0]

function NItem({ item }: { item: NavItem }) {
  const pathname = usePathname()
  const [open, setOpen] = useState(() => !!item.children?.some(c => c.href && pathname.startsWith(c.href)))
  const active = !!item.href && item.href === bestMatch(pathname)
  const bc: Record<string,string> = { amber:'bg-amber-100 text-amber-700', green:'bg-green-100 text-green-700', blue:'bg-blue-100 text-blue-700' }

  if (item.children?.length) return (
    <div>
      <button onClick={() => setOpen(!open)} className={cn('w-full flex items-center gap-2.5 px-3 py-2 rounded text-left transition-colors text-stone-500 hover:text-stone-900 hover:bg-stone-100', open && 'text-stone-800')}>
        <Icon name={item.icon} cls="w-4 h-4 flex-shrink-0" />
        <span className="flex-1 text-sm font-medium">{item.label}</span>
        <Icons.ChevronRight className={cn('w-3.5 h-3.5 transition-transform', open && 'rotate-90')} />
      </button>
      {open && <div className="ml-4 mt-0.5 border-l border-stone-200 pl-2 space-y-0.5">{item.children.map(c => <NItem key={c.label} item={c} />)}</div>}
    </div>
  )
  return (
    <Link href={item.href!} className={cn('flex items-center gap-2.5 px-3 py-1.5 rounded text-sm transition-colors group', active ? 'bg-amber-50 text-amber-900 font-medium' : 'text-stone-500 hover:text-stone-900 hover:bg-stone-100')}>
      <Icon name={item.icon} cls={cn('w-3.5 h-3.5 flex-shrink-0', active ? 'text-amber-700' : 'text-stone-400 group-hover:text-stone-600')} />
      <span className="flex-1 truncate">{item.label}</span>
      {item.badge && <span className={cn('text-[10px] font-semibold px-1.5 py-0.5 rounded-full', bc[item.badgeColor||''] || 'bg-stone-100 text-stone-600')}>{item.badge}</span>}
    </Link>
  )
}

export function Sidebar() {
  const router = useRouter()
  const [user, setUser] = useState<{ name: string; role: string } | null>(null)
  useEffect(() => { setUser(session.user()) }, [])
  const logout = () => { session.clear(); router.replace('/login') }
  return (
    <aside className="w-60 flex-shrink-0 bg-white border-r border-stone-200 flex flex-col overflow-hidden">
      <div className="h-14 flex items-center gap-2.5 px-4 border-b border-stone-200 flex-shrink-0">
        <div className="w-7 h-7 rounded bg-amber-700 flex items-center justify-center flex-shrink-0">
          <Icons.Layers className="w-4 h-4 text-white" />
        </div>
        <div>
          <div className="text-sm font-semibold text-stone-900">InteriorIQ</div>
          <div className="text-[10px] text-stone-400 tracking-wide">Platform</div>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
        {(!user ? [] : user.role === 'CLIENT' ? navigation.filter(n => n.href === '/client-portal') : navigation).map(item => <NItem key={item.label} item={item} />)}
      </nav>
      <div className="border-t border-stone-200 p-3 flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-full bg-stone-200 flex items-center justify-center flex-shrink-0">
          <Icons.User className="w-3.5 h-3.5 text-stone-500" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-stone-800 truncate">{user?.name ?? "…"}</div>
          <div className="text-[10px] text-stone-400">{user?.role?.replace(/_/g, " ") ?? ""}</div>
        </div>
        <button onClick={logout} title="Sign out" className="p-1 hover:bg-stone-100 rounded"><Icons.LogOut className="w-3.5 h-3.5 text-stone-400" /></button>
      </div>
    </aside>
  )
}
