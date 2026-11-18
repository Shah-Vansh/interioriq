'use client'
import dynamic from 'next/dynamic'

// Three.js needs the browser (WebGL), so this page must not be server-rendered.
const Editor3D = dynamic(() => import('@/components/design/editor-3d').then(m => m.Editor3D), {
  ssr: false,
  loading: () => <div className="flex items-center justify-center text-sm text-stone-400" style={{ height: 'calc(100vh - 56px)' }}>Loading 3D editor…</div>,
})
export default function Editor3DPage() { return <Editor3D /> }
