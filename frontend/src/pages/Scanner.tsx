import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { ScanResult } from '../api/types'
import { Banner, Card, Empty, GradePill, Spinner } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { dbm, GRADE_COLOR, text } from '../lib/format'

const BAND_FILTERS = [
  { value: '', label: 'All bands' },
  { value: '2.4', label: '2.4 GHz' },
  { value: '5', label: '5 GHz' },
  { value: '6', label: '6 GHz' },
]

export function ScannerPage() {
  const [ssid, setSsid] = useState('')
  const [band, setBand] = useState('')
  const [auto, setAuto] = useState(false)

  const { data, error, loading, refresh } = usePolling<ScanResult>(
    () => api.get('/api/scan', { ssid: ssid || undefined, band: band || undefined }),
    { intervalMs: auto ? 15000 : 0 },
  )

  // Re-scan when a filter changes. Debounced so typing into the SSID box does
  // not fire a scan per keystroke - a real scan takes seconds and hits the radio.
  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 300)
    return () => window.clearTimeout(timer)
  }, [ssid, band, refresh])

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">WiFi Scanner</h1>
          <p className="text-sm text-slate-400">
            Every BSSID in range{data ? ` · ${data.count} found` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={auto}
              onChange={(e) => setAuto(e.target.checked)}
              className="accent-sky-500"
            />
            Auto-refresh
          </label>
          <button className="btn" onClick={() => void refresh()} disabled={loading}>
            ⟳ Scan
          </button>
        </div>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <span className="label">SSID contains</span>
            <input
              className="input"
              value={ssid}
              placeholder="Factory"
              onChange={(e) => setSsid(e.target.value)}
            />
          </div>
          <div>
            <span className="label">Band</span>
            <select className="input" value={band} onChange={(e) => setBand(e.target.value)}>
              {BAND_FILTERS.map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {loading && !data ? (
        <Spinner label="Scanning…" />
      ) : !data || data.networks.length === 0 ? (
        <Empty>No networks matched. Widen the filters or rescan.</Empty>
      ) : (
        <>
          <Card title="Networks">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>SSID</th>
                    <th>BSSID</th>
                    <th>CH</th>
                    <th>Band</th>
                    <th>Signal</th>
                    <th>Quality</th>
                    <th>Security</th>
                  </tr>
                </thead>
                <tbody>
                  {data.networks.map((net) => (
                    <tr key={`${net.bssid}-${net.channel}`}>
                      <td className="font-medium">{text(net.ssid)}</td>
                      <td className="font-mono text-xs text-slate-400">{text(net.bssid)}</td>
                      <td className="tabular">{text(net.channel)}</td>
                      <td className="text-slate-400">{text(net.band)}</td>
                      <td className="tabular font-semibold" style={{ color: net.grade_color }}>
                        {dbm(net.rssi)}
                      </td>
                      <td>
                        <GradePill grade={net.grade} />
                      </td>
                      <td className="text-xs text-slate-400">{text(net.security)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Channel usage">
              <p className="mb-3 text-xs text-slate-500">
                Radios sharing a channel share airtime. Crowded channels show up as latency,
                not as weak signal.
              </p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.channel_usage}>
                  <XAxis dataKey="channel" stroke="#475569" fontSize={11} />
                  <YAxis stroke="#475569" fontSize={11} allowDecimals={false} width={30} />
                  <Tooltip
                    cursor={{ fill: '#1e293b55' }}
                    contentStyle={{
                      background: '#0f172a',
                      border: '1px solid #1e293b',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(value: number) => [`${value} radios`, 'Count']}
                    labelFormatter={(label) => `Channel ${label}`}
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {data.channel_usage.map((entry) => (
                      <Cell
                        key={entry.channel}
                        fill={entry.count >= 3 ? GRADE_COLOR.POOR : '#38bdf8'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card title="Networks by SSID">
              <div className="table-wrap">
                <table className="table min-w-0">
                  <thead>
                    <tr>
                      <th>SSID</th>
                      <th>APs</th>
                      <th>Best</th>
                      <th>Channels</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ssid_groups.map((group) => (
                      <tr key={group.ssid}>
                        <td className="font-medium">{group.ssid}</td>
                        <td className="tabular">{group.bssid_count}</td>
                        <td className="tabular">{dbm(group.best_rssi)}</td>
                        <td className="tabular text-xs text-slate-400">
                          {group.channels.join(', ') || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
