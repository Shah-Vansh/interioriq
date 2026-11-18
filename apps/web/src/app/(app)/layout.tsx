import { Sidebar } from '@/components/layout/sidebar'
import { Topbar } from '@/components/layout/topbar'
import { AuthGuard } from '@/components/auth/auth-guard'
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: '#fafaf9' }}>
        <Sidebar />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Topbar />
          <main style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>{children}</main>
        </div>
      </div>
    </AuthGuard>
  )
}
