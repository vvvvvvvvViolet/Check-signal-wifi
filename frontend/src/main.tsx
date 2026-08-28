import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/Dashboard'
import { DiagnosisPage } from './pages/Diagnosis'
import { HeatmapPage } from './pages/Heatmap'
import { HistoryPage } from './pages/History'
import { NetworkTestPage } from './pages/NetworkTest'
import { ReportPage } from './pages/Report'
import { RoamingPage } from './pages/Roaming'
import { ScannerPage } from './pages/Scanner'
import { SettingsPage } from './pages/Settings'
import { SignalMonitorPage } from './pages/SignalMonitor'
import './index.css'

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'monitor', element: <SignalMonitorPage /> },
      { path: 'scanner', element: <ScannerPage /> },
      { path: 'roaming', element: <RoamingPage /> },
      { path: 'heatmap', element: <HeatmapPage /> },
      { path: 'network-test', element: <NetworkTestPage /> },
      { path: 'diagnosis', element: <DiagnosisPage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'report', element: <ReportPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <DashboardPage /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
