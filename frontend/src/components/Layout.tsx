import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { sinceNow } from '../lib/format'

interface Health {
  status: string
  version: string
  wifi_backend: string
  simulated: boolean
  monitor: { running: boolean; last_sample_at: string | null }
}

const NAV = [
  { to: '/', label: 'Dashboard', icon: '🏠', end: true },
  { to: '/monitor', label: 'Signal Monitor', icon: '📶' },
  { to: '/scanner', label: 'WiFi Scanner', icon: '🔍' },
  { to: '/roaming', label: 'Roaming Test', icon: '🔄' },
  { to: '/heatmap', label: 'Heatmap', icon: '🗺️' },
  { to: '/network-test', label: 'Network Test', icon: '🧪' },
  { to: '/diagnosis', label: 'Diagnosis', icon: '🚨' },
  { to: '/history', label: 'History', icon: '📊' },
  { to: '/report', label: 'Report', icon: '📄' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

export function Layout() {
  const [open, setOpen] = useState(false)
  const { data: health } = usePolling<Health>(() => api.get('/api/health'), { intervalMs: 15000 })

  return (
    <div className="min-h-screen lg:flex">
      {/* Mobile top bar - the app is used on a tablet while walking a floor. */}
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-4 py-3 lg:hidden">
        <span className="font-semibold tracking-tight">📶 Check Signal WiFi</span>
        <button className="btn px-2 py-1" onClick={() => setOpen((v) => !v)} aria-label="Toggle menu">
          ☰
        </button>
      </header>

      <aside
        className={`${open ? 'block' : 'hidden'} border-b border-slate-800 bg-slate-900 lg:sticky lg:top-0 lg:block lg:h-screen lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r`}
      >
        <div className="hidden px-5 py-5 lg:block">
          <div className="text-lg font-bold tracking-tight">📶 CHECK SIGNAL WIFI</div>
          <div className="mt-0.5 text-xs text-slate-500">
            Site survey &amp; coverage analysis
          </div>
        </div>

        <nav className="space-y-0.5 p-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? 'bg-sky-500/15 font-semibold text-sky-300'
                    : 'text-slate-300 hover:bg-slate-800'
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-1 border-t border-slate-800 p-4 text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${health?.monitor.running ? 'animate-pulse bg-emerald-400' : 'bg-slate-600'}`}
            />
            {health?.monitor.running ? 'Monitoring' : 'Idle'}
            {health?.monitor.last_sample_at && (
              <span className="text-slate-600">· {sinceNow(health.monitor.last_sample_at)}</span>
            )}
          </div>
          <div>
            Backend: <span className="text-slate-400">{health?.wifi_backend ?? '…'}</span>
          </div>
          {health?.simulated && <div className="text-amber-400">⚠ Simulated data</div>}
          <div className="text-slate-600">v{health?.version ?? '—'}</div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 p-4 lg:p-6">
        <Outlet />
      </main>
    </div>
  )
}
