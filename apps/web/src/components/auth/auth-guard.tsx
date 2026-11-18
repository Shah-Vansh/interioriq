'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { session } from '@/lib/api'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter(); const pathname = usePathname()
  const [ok, setOk] = useState(false)
  const [slow, setSlow] = useState(false)
  const [persistent, setPersistent] = useState(true)
  useEffect(() => {
    if (!session.token()) { router.replace('/login'); return }
    if (session.user()?.role === 'CLIENT' && !pathname.startsWith('/client-portal')) { setOk(false); router.replace('/client-portal'); return }   // clients only ever see their portal
    setOk(true); setPersistent(session.persistent())
  }, [router, pathname])
  useEffect(() => { const t = setTimeout(() => setSlow(true), 2500); return () => clearTimeout(t) }, [])   // never look "stuck": offer a way out
  if (!ok) return (
    <div className="h-screen flex flex-col items-center justify-center gap-2 text-sm text-stone-400">
      <span>{slow ? 'Taking longer than expected…' : 'Loading…'}</span>
      {slow && <Link href="/login" className="text-amber-700 underline font-medium">Go to sign in</Link>}
    </div>
  )
  return (
    <>
      {!persistent && <div role="status" className="fixed bottom-3 right-3 z-50 max-w-xs text-xs bg-amber-50 border border-amber-300 text-amber-900 rounded-lg shadow px-3 py-2">
        Your browser is blocking local storage, so you will be signed out if you reload this page. Open the site in a normal browser tab to stay signed in.</div>}
      {children}
    </>
  )
}
