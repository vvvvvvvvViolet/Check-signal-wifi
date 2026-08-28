import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/Dashboard'
import './index.css'

// The Dashboard is eager: it is the landing screen, and making it wait on a
// second request would trade a smaller bundle for a slower first answer.
// Everything else loads on navigation, which keeps Recharts, the heatmap canvas
// and the export screens out of the initial download.
const SignalMonitorPage = lazy(() =>
  import('./pages/SignalMonitor').then((m) => ({ default: m.SignalMonitorPage })),
)
const ScannerPage = lazy(() =>
  import('./pages/Scanner').then((m) => ({ default: m.ScannerPage })),
)
const RoamingPage = lazy(() =>
  import('./pages/Roaming').then((m) => ({ default: m.RoamingPage })),
)
const HeatmapPage = lazy(() =>
  import('./pages/Heatmap').then((m) => ({ default: m.HeatmapPage })),
)
const NetworkTestPage = lazy(() =>
  import('./pages/NetworkTest').then((m) => ({ default: m.NetworkTestPage })),
)
const DiagnosisPage = lazy(() =>
  import('./pages/Diagnosis').then((m) => ({ default: m.DiagnosisPage })),
)
const HistoryPage = lazy(() =>
  import('./pages/History').then((m) => ({ default: m.HistoryPage })),
)
const ReportPage = lazy(() => import('./pages/Report').then((m) => ({ default: m.ReportPage })))
const SettingsPage = lazy(() =>
  import('./pages/Settings').then((m) => ({ default: m.SettingsPage })),
)

function Loading() {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-700 border-t-sky-400" />
      Loading…
    </div>
  )
}

/** Every lazy route needs a boundary; one wrapper keeps the table readable. */
function lazyRoute(Component: React.ComponentType) {
  return (
    <Suspense fallback={<Loading />}>
      <Component />
    </Suspense>
  )
}

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'monitor', element: lazyRoute(SignalMonitorPage) },
      { path: 'scanner', element: lazyRoute(ScannerPage) },
      { path: 'roaming', element: lazyRoute(RoamingPage) },
      { path: 'heatmap', element: lazyRoute(HeatmapPage) },
      { path: 'network-test', element: lazyRoute(NetworkTestPage) },
      { path: 'diagnosis', element: lazyRoute(DiagnosisPage) },
      { path: 'history', element: lazyRoute(HistoryPage) },
      { path: 'report', element: lazyRoute(ReportPage) },
      { path: 'settings', element: lazyRoute(SettingsPage) },
      { path: '*', element: <DashboardPage /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
