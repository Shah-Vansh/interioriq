'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, CheckCircle2, Layers, Loader2 } from 'lucide-react'
import { api, ApiError, apiBase, session, SessionUser } from '@/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('admin@interioriq.com')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [apiUp, setApiUp] = useState<boolean | null>(null)     // null = still checking
  const isDev = process.env.NODE_ENV !== 'production'

  useEffect(() => { api.health().then(setApiUp) }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const r = await api.post<{ access_token: string; user: SessionUser }>('/auth/login', { email: email.trim(), password })
      session.save(r.access_token, r.user)
      router.replace('/dashboard')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
      if (err instanceof ApiError && err.status === 0) api.health().then(setApiUp)
    } finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen bg-stone-50 flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm bg-white border border-stone-200 rounded-xl shadow-sm p-8 space-y-4">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded bg-amber-700 flex items-center justify-center"><Layers className="w-4 h-4 text-white" /></div>
          <div><div className="text-base font-semibold text-stone-900 leading-none">InteriorIQ</div>
            <div className="text-[11px] text-stone-400 mt-0.5">Sign in to continue</div></div>
        </div>

        {apiUp === false && (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 flex gap-2" role="alert">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>The backend is not reachable at <code>{apiBase()}</code>.<br />Start it: <code>cd apps/api &amp;&amp; uvicorn app.main:app --reload</code><br />Then open this site at <code>http://localhost:3000</code>.</div>
          </div>)}
        {apiUp === true && <p className="text-[11px] text-green-700 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" />Backend connected</p>}

        <div>
          <label htmlFor="email" className="text-[11px] text-stone-400 font-medium uppercase tracking-wide block mb-1">Email</label>
          <input id="email" value={email} onChange={e => setEmail(e.target.value)} type="email" required
            className="w-full text-sm border border-stone-200 rounded px-3 py-2 bg-stone-50 outline-none focus:border-amber-400" />
        </div>
        <div>
          <label htmlFor="password" className="text-[11px] text-stone-400 font-medium uppercase tracking-wide block mb-1">Password</label>
          <input id="password" value={password} onChange={e => setPassword(e.target.value)} type="password" required autoFocus
            className="w-full text-sm border border-stone-200 rounded px-3 py-2 bg-stone-50 outline-none focus:border-amber-400" />
        </div>
        {error && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2" role="alert">{error}</p>}
        <button disabled={busy} className="w-full flex items-center justify-center gap-2 bg-amber-700 hover:bg-amber-800 disabled:opacity-60 text-white text-sm font-medium py-2.5 rounded">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />}Sign in
        </button>
        {isDev && <p className="text-[11px] text-stone-500 text-center bg-stone-50 border border-stone-100 rounded px-2 py-1.5" data-testid="dev-hint">Local dev login: <code>admin@interioriq.com</code> / <code>ChangeMe123!</code></p>}
      </form>
    </div>
  )
}
