'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { AlertCircle, CheckCircle2, FileText, Loader2, RefreshCw, ScanLine, Upload, XCircle } from 'lucide-react'
import { api, ApiError, ApplyResult, DocDetail, DocSummary, fetchBlob, OcrCandidate } from '@/lib/api'
import { ProjectRoomPicker } from '@/components/shared/project-room-picker'
import { cn } from '@/lib/utils'

const LABELS = ['Length', 'Width', 'Ceiling Height', 'Door Width', 'Door Height', 'Window Width', 'Window Height']
const BUSY = ['UPLOADED', 'PROCESSING']
const STATUS: Record<string, string> = { UPLOADED: 'bg-stone-100 text-stone-600', PROCESSING: 'bg-blue-50 text-blue-700', OCR_DONE: 'bg-green-50 text-green-700', FAILED: 'bg-red-50 text-red-700' }

interface Row { include: boolean; label: string; value: number; src: OcrCandidate }
const confClass = (c: number) => (c >= 90 ? 'bg-green-50 text-green-700' : c >= 70 ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700')
const toRows = (cs: OcrCandidate[]): Row[] => cs.map(c => ({ include: c.confidence >= 80 && !!c.label, label: c.label ?? '', value: c.value_mm, src: c }))   // low-confidence or unlabelled rows start UNticked

export function DocumentsView() {
  const [sel, setSel] = useState({ projectId: '', roomId: '' })
  const [docs, setDocs] = useState<DocSummary[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DocDetail | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [preview, setPreview] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [applied, setApplied] = useState<ApplyResult | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadList = useCallback(async () => {
    if (!sel.projectId) { setDocs([]); return }
    try { setDocs(await api.get<DocSummary[]>(`/projects/${sel.projectId}/documents?exclude_media=true`)) } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed to load documents' }) }
  }, [sel.projectId])
  useEffect(() => { setOpenId(null); setDetail(null); setApplied(null); loadList() }, [loadList])

  useEffect(() => {   // poll while anything is still being read
    if (!docs.some(d => BUSY.includes(d.status))) return
    const t = setInterval(loadList, 1500); return () => clearInterval(t)
  }, [docs, loadList])

  const open = useCallback(async (id: string) => {
    setOpenId(id); setApplied(null)
    try { const d = await api.get<DocDetail>(`/documents/${id}`); setDetail(d); setRows(toRows(d.candidates)) }
    catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed to open document' }) }
  }, [])
  const current = docs.find(d => d.id === openId)
  useEffect(() => { if (openId && current?.status === 'OCR_DONE' && detail?.status !== 'OCR_DONE') open(openId) }, [current?.status, openId, detail?.status, open])   // refresh detail when OCR finishes

  useEffect(() => {   // image preview via authenticated fetch (an <img src> cannot send the token)
    setPreview(null)
    if (!detail || !['png', 'jpg'].includes(detail.kind)) return
    let url = '', dead = false
    fetchBlob(`/documents/${detail.id}/file`).then(b => { if (!dead) { url = URL.createObjectURL(b); setPreview(url) } }).catch(() => {})
    return () => { dead = true; if (url) URL.revokeObjectURL(url) }
  }, [detail?.id, detail?.kind]) // eslint-disable-line

  const upload = async (files: FileList | null) => {
    if (!files?.length || !sel.projectId) return
    setUploading(true); setMsg(null)
    try {
      for (const f of Array.from(files)) {
        const form = new FormData(); form.append('file', f); if (sel.roomId) form.append('room_id', sel.roomId)
        const d = await api.upload<DocSummary>(`/projects/${sel.projectId}/documents`, form)
        if (d.duplicate) setMsg({ ok: true, text: `“${d.name}” was already uploaded — opened the existing copy.` })
        await loadList(); await open(d.id)
      }
    } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Upload failed' }) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }
  const rerun = async () => { if (!openId) return; try { await api.post(`/documents/${openId}/ocr`); setDetail(null); await loadList() } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Failed' }) } }

  const chosen = rows.filter(r => r.include && r.label && r.value > 0)
  const apply = async () => {
    if (!detail || !sel.roomId) return
    try { setApplied(await api.post<ApplyResult>(`/documents/${detail.id}/apply`, { room_id: sel.roomId, items: chosen.map(r => ({ label: r.label, value_mm: r.value, confidence: r.src.confidence })) })) }
    catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : 'Apply failed' }) }
  }
  const patch = (i: number, p: Partial<Row>) => setRows(rs => rs.map((r, k) => (k === i ? { ...r, ...p } : r)))
  const input = 'text-sm border border-stone-200 rounded px-2 py-1 bg-white outline-none focus:border-amber-400'

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div><h1 className="text-xl font-semibold text-stone-900">Documents & OCR</h1>
        <p className="text-sm text-stone-500 mt-0.5">Upload a floor plan. Dimensions are read as <em>proposals</em> — nothing reaches the Room Model until you review and apply it.</p></div>
      <div className="flex items-center gap-3 flex-wrap">
        <ProjectRoomPicker onChange={s => setSel({ projectId: s.projectId, roomId: s.roomId })} />
        <label className={cn('flex items-center gap-2 text-sm font-medium px-3 py-1.5 rounded text-white cursor-pointer', sel.projectId && !uploading ? 'bg-amber-700 hover:bg-amber-800' : 'bg-stone-300 pointer-events-none')}>
          {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}Upload PDF / PNG / JPG / TIFF
          <input ref={fileRef} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" className="hidden" data-testid="file-input" onChange={e => upload(e.target.files)} />
        </label>
      </div>
      {msg && <p className={cn('text-xs rounded px-3 py-2 border', msg.ok ? 'text-green-700 bg-green-50 border-green-200' : 'text-red-600 bg-red-50 border-red-200')}>{msg.text}</p>}

      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-12 lg:col-span-4 bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden self-start">
          <div className="px-4 py-3 border-b border-stone-100 text-sm font-semibold">Uploaded ({docs.length})</div>
          {docs.length === 0 ? <p className="p-5 text-xs text-stone-400">{sel.projectId ? 'No documents yet.' : 'Create a project first.'}</p>
            : docs.map(d => (
              <button key={d.id} onClick={() => open(d.id)} className={cn('w-full text-left px-4 py-3 border-b border-stone-50 last:border-0 flex items-center gap-3', openId === d.id ? 'bg-amber-50' : 'hover:bg-stone-50')}>
                <FileText className="w-4 h-4 text-stone-400 flex-shrink-0" />
                <div className="flex-1 min-w-0"><p className="text-xs font-medium text-stone-800 truncate">{d.name}</p>
                  <p className="text-[11px] text-stone-400">{d.kind.toUpperCase()} · {(d.size_bytes / 1024).toFixed(0)} KB{d.provider ? ` · ${d.provider}` : ''}</p></div>
                <span className={cn('text-[10px] font-semibold px-1.5 py-0.5 rounded-full flex items-center gap-1', STATUS[d.status])}>{BUSY.includes(d.status) && <Loader2 className="w-2.5 h-2.5 animate-spin" />}{d.status.replace('_', ' ')}</span>
              </button>))}
        </div>

        <div className="col-span-12 lg:col-span-8 space-y-4">
          {!openId ? <div className="bg-white border border-stone-200 rounded-lg p-14 text-center shadow-sm text-sm text-stone-400"><ScanLine className="w-8 h-8 mx-auto mb-2 text-stone-300" />Upload or select a document to review what was read.</div>
            : !detail || detail.status !== 'OCR_DONE' ? <div className="bg-white border border-stone-200 rounded-lg p-14 text-center shadow-sm text-sm text-stone-500 flex items-center justify-center gap-2">
                {(current?.status ?? detail?.status) === 'FAILED' ? <><XCircle className="w-4 h-4 text-red-500" />{current?.error ?? detail?.error}
                  <button onClick={rerun} className="ml-2 flex items-center gap-1 text-xs border border-stone-200 rounded px-2 py-1 hover:bg-stone-50"><RefreshCw className="w-3 h-3" />Retry</button></>
                  : <><Loader2 className="w-4 h-4 animate-spin" />Reading the document…</>}</div>
            : (<>
              {preview && <img src={preview} alt={detail.name} className="w-full max-h-72 object-contain bg-stone-50 border border-stone-200 rounded-lg" />}
              <div className="bg-white border border-stone-200 rounded-lg shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-stone-100 flex items-center gap-3">
                  <div className="flex-1"><p className="text-sm font-semibold">{detail.name}</p>
                    <p className="text-[11px] text-stone-400">Read by {detail.provider ?? '—'} · {detail.pages ?? 0} page(s) · {detail.candidates.length} possible dimension(s)</p></div>
                  <button onClick={rerun} className="flex items-center gap-1 text-xs border border-stone-200 rounded px-2 py-1 hover:bg-stone-50"><RefreshCw className="w-3 h-3" />Re-read</button>
                </div>
                {rows.length === 0 ? <p className="p-6 text-xs text-stone-400 text-center">No dimensions were found in this document.</p> : (
                  <table className="w-full text-xs"><thead><tr className="bg-stone-50 border-b border-stone-100">
                    {['Use', 'Dimension', 'mm', 'Confidence', 'Read as'].map(h => <th key={h} className="text-left text-[11px] text-stone-400 uppercase tracking-wide px-3 py-2">{h}</th>)}</tr></thead>
                    <tbody className="divide-y divide-stone-50">{rows.map((r, i) => (
                      <tr key={i} className={cn(!r.include && 'opacity-60')}>
                        <td className="px-3 py-2"><input type="checkbox" checked={r.include} disabled={!r.label} onChange={e => patch(i, { include: e.target.checked })} className="accent-amber-600" aria-label={`use row ${i + 1}`} /></td>
                        <td className="px-3 py-2"><select value={r.label} onChange={e => patch(i, { label: e.target.value, include: !!e.target.value && r.src.confidence >= 80 ? true : r.include })} className={input}>
                          <option value="">— choose —</option>{LABELS.map(l => <option key={l}>{l}</option>)}</select></td>
                        <td className="px-3 py-2"><input type="number" value={r.value} min={1} onChange={e => patch(i, { value: parseFloat(e.target.value) || 0 })} className={input + ' w-24 font-mono'} /></td>
                        <td className="px-3 py-2"><span className={cn('px-2 py-0.5 rounded-full font-semibold', confClass(r.src.confidence))}>{r.src.confidence.toFixed(0)}%</span></td>
                        <td className="px-3 py-2"><span className="font-mono text-stone-600">{r.src.raw}</span>{r.src.note && <p className="text-[10px] text-amber-700 flex items-center gap-1 mt-0.5"><AlertCircle className="w-3 h-3" />{r.src.note}</p>}</td>
                      </tr>))}</tbody></table>)}
                <div className="px-4 py-3 border-t border-stone-100 flex items-center gap-3">
                  <p className="text-[11px] text-stone-400 flex-1">Low-confidence or unlabelled rows start unticked. Values apply to the selected room as source <strong>OCR</strong>; verified values are never overwritten.</p>
                  <button onClick={apply} disabled={!chosen.length || !sel.roomId} className="text-sm font-medium bg-stone-900 hover:bg-stone-800 disabled:opacity-40 text-white px-3 py-1.5 rounded">
                    {sel.roomId ? `Apply ${chosen.length} to room` : 'Pick a room to apply'}</button>
                </div>
              </div>
              {applied && (
                <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-4 space-y-1.5">
                  <p className="text-sm font-semibold">{applied.applied} applied · {applied.rejected} kept as-is</p>
                  {applied.results.map((r, i) => (<p key={i} className={cn('text-xs flex items-start gap-1.5', r.applied ? 'text-green-700' : 'text-amber-700')}>
                    {r.applied ? <CheckCircle2 className="w-3.5 h-3.5 mt-0.5" /> : <AlertCircle className="w-3.5 h-3.5 mt-0.5" />}<span><strong>{r.label}</strong> — {r.applied ? 'applied as OCR (unverified)' : r.reason}</span></p>))}
                  <Link href="/survey/rooms" className="text-xs text-amber-700 underline font-medium inline-block pt-1">Review in Rooms & Measurements →</Link>
                </div>)}
            </>)}
        </div>
      </div>
    </div>
  )
}
