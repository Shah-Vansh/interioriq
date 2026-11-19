'use client'
// M28: catalogue photos. Images need the sign-in token, so they are fetched as blobs (an <img src> can't send it) and cached per URL.
import { useEffect, useRef, useState } from 'react'
import { ImagePlus, Loader2, Trash2 } from 'lucide-react'
import { api, apiBase, ApiError, session } from '@/lib/api'

const cache = new Map<string, Promise<string>>()

function load(path: string): Promise<string> {
  let p = cache.get(path)
  if (!p) {
    p = fetch(`${apiBase()}/api${path}`, { headers: { Authorization: `Bearer ${session.token()}` } })
      .then(async r => { if (!r.ok) throw new ApiError(r.status, r.statusText); return URL.createObjectURL(await r.blob()) })
    p.catch(() => cache.delete(path)); cache.set(path, p)
  }
  return p
}

/** <img> for an authenticated API path; renders nothing until loaded (or if there is no photo). */
export function AuthImg({ path, alt, className }: { path: string | null; alt: string; className?: string }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => { let live = true; setUrl(null); if (path) load(path).then(u => live && setUrl(u)).catch(() => {}); return () => { live = false } }, [path])
  return url ? <img src={url} alt={alt} className={className} /> : null
}

export const photoPath = (i: { id: string; has_photo?: boolean; photo_v?: string | null }, size: 'thumb' | 'full' = 'thumb') =>
  i.has_photo ? `/catalogue/items/${i.id}/photo?size=${size}&v=${i.photo_v ?? ''}` : null

/** Photo block in the item drawer: preview + upload / replace / remove (catalogue writers only). */
export function ItemPhoto({ item, canEdit, onChanged }: { item: { id: string; name: string; has_photo?: boolean; photo_v?: string | null }; canEdit: boolean; onChanged: () => void }) {
  const input = useRef<HTMLInputElement>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const upload = async (f: File) => {
    setBusy(true); setError('')
    try { const fd = new FormData(); fd.append('file', f); await api.upload(`/catalogue/items/${item.id}/photo`, fd); onChanged() }
    catch (e) { setError(e instanceof Error ? e.message : 'Upload failed') } finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  const remove = async () => { setBusy(true); setError(''); try { await api.delete(`/catalogue/items/${item.id}/photo`); onChanged() } catch (e) { setError(e instanceof Error ? e.message : 'Failed') } finally { setBusy(false) } }
  const full = photoPath(item, 'full')
  return <div className="space-y-2" data-testid="item-photo">
    {full ? <AuthImg path={full} alt={item.name} className="w-full max-h-64 object-contain rounded border border-stone-200 bg-stone-50" />
      : <div className="h-24 rounded border border-dashed border-stone-300 grid place-items-center text-xs text-stone-400">No photo</div>}
    {canEdit && <div className="flex gap-2">
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" aria-label="Item photo file" className="hidden" onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
      <button type="button" disabled={busy} onClick={() => input.current?.click()} className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded border border-stone-200 bg-white hover:bg-stone-50">
        {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <ImagePlus className="w-3 h-3" />}{item.has_photo ? 'Replace photo' : 'Add photo'}</button>
      {item.has_photo && <button type="button" disabled={busy} onClick={remove} className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded border border-red-200 text-red-700 bg-white hover:bg-red-50"><Trash2 className="w-3 h-3" />Remove</button>}
    </div>}
    {canEdit && <p className="text-[11px] text-stone-400">JPG, PNG or WebP up to 10 MB. Printed beside the item on quotations.</p>}
    {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
  </div>
}
