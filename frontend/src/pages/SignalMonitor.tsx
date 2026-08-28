import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, monitorSocketUrl } from '../api/client'
import type { MonitorStatus, Snapshot, Thresholds } from '../api/types'
import { Banner, Card, Field, GradePill, VerdictPill } from '../components/ui'
import { clockTime, dbm, ms, pct, text } from '../lib/format'

interface LivePoint {
  ts: string
  label: string
  rssi: number | null
  ping: number | null
  loss: number | null
  ssid: string | null
  bssid: string | null
  channel: number | null
  grade: Snapshot['summary']['grade']
  verdict: Snapshot['summary']['verdict']
}

const MAX_POINTS = 600

function toPoint(message: Snapshot): LivePoint {
  return {
    ts: message.ts,
    label: clockTime(message.ts),
    rssi: message.link.rssi,
    ping: message.summary.ping_ms,
    loss: message.summary.packet_loss_pct,
    ssid: message.link.ssid,
    bssid: message.link.bssid,
    channel: message.link.channel,
    grade: message.summary.grade,
    verdict: message.summary.verdict,
  }
}

export function SignalMonitorPage() {
  const [points, setPoints] = useState<LivePoint[]>([])
  const [status, setStatus] = useState<MonitorStatus | null>(null)
  const [thresholds, setThresholds] = useState<Thresholds | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ name: 'Monitor session', area: '', device: '', interval: 2 })
  const [busy, setBusy] = useState(false)

  const socketRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number | null>(null)
  const closedByUs = useRef(false)

  useEffect(() => {
    void api
      .get<{ settings: { thresholds: Thresholds; monitor: { interval_sec: number } } }>(
        '/api/settings',
      )
      .then((res) => {
        setThresholds(res.settings.thresholds)
        setForm((f) => ({ ...f, interval: res.settings.monitor.interval_sec }))
      })
      .catch(() => undefined)
  }, [])

  const connect = useCallback(() => {
    closedByUs.current = false
    const socket = new WebSocket(monitorSocketUrl())
    socketRef.current = socket

    socket.onopen = () => {
      setConnected(true)
      setError(null)
    }

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data as string)
      switch (message.type) {
        case 'hello':
          setStatus(message.status)
          setPoints((message.backfill as Snapshot[]).map(toPoint))
          break
        case 'sample':
          setPoints((prev) => [...prev, toPoint(message as Snapshot)].slice(-MAX_POINTS))
          break
        case 'error':
          setError(message.message)
          break
        default:
          break // 'ping' keepalives and roam events are handled elsewhere
      }
    }

    socket.onclose = () => {
      setConnected(false)
      socketRef.current = null
      // Reconnect unless we closed it deliberately - a survey tablet moving
      // between APs will drop this socket regularly.
      if (!closedByUs.current) {
        retryRef.current = window.setTimeout(connect, 2000)
      }
    }

    socket.onerror = () => setError('Live connection interrupted')
  }, [])

  useEffect(() => {
    connect()
    return () => {
      closedByUs.current = true
      if (retryRef.current) window.clearTimeout(retryRef.current)
      socketRef.current?.close()
    }
  }, [connect])

  const refreshStatus = useCallback(async () => {
    setStatus(await api.get<MonitorStatus>('/api/monitor/status'))
  }, [])

  useEffect(() => {
    void refreshStatus()
    const timer = window.setInterval(() => void refreshStatus(), 5000)
    return () => window.clearInterval(timer)
  }, [refreshStatus])

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      setPoints([])
      await api.post('/api/monitor/start', {
        name: form.name || 'Monitor session',
        area: form.area || null,
        device: form.device || null,
        interval_sec: form.interval,
      })
      await refreshStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const stop = async () => {
    setBusy(true)
    try {
      await api.post('/api/monitor/stop')
      await refreshStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const stats = useMemo(() => {
    const rssis = points.map((p) => p.rssi).filter((v): v is number => v !== null)
    const pings = points.map((p) => p.ping).filter((v): v is number => v !== null)
    return {
      count: points.length,
      rssiAvg: rssis.length ? rssis.reduce((a, b) => a + b, 0) / rssis.length : null,
      rssiMin: rssis.length ? Math.min(...rssis) : null,
      rssiMax: rssis.length ? Math.max(...rssis) : null,
      pingAvg: pings.length ? pings.reduce((a, b) => a + b, 0) / pings.length : null,
    }
  }, [points])

  const latest = points.at(-1)
  const running = status?.running ?? false

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Signal Monitor</h1>
          <p className="text-sm text-slate-400">
            Continuous RSSI, latency and loss sampling
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-slate-600'}`}
          />
          {connected ? 'Live stream connected' : 'Reconnecting…'}
        </div>
      </header>

      {error && <Banner kind="error">{error}</Banner>}
      {status?.last_error && <Banner kind="warning">Sampling error: {status.last_error}</Banner>}

      <Card title="Session">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Session name">
            <input
              className="input"
              value={form.name}
              disabled={running}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="Area">
            <input
              className="input"
              placeholder="Line-A"
              value={form.area}
              disabled={running}
              onChange={(e) => setForm({ ...form, area: e.target.value })}
            />
          </Field>
          <Field label="Device">
            <input
              className="input"
              placeholder="Scanner-01"
              value={form.device}
              disabled={running}
              onChange={(e) => setForm({ ...form, device: e.target.value })}
            />
          </Field>
          <Field label="Interval (s)">
            <input
              className="input"
              type="number"
              min={0.5}
              max={300}
              step={0.5}
              value={form.interval}
              disabled={running}
              onChange={(e) => setForm({ ...form, interval: Number(e.target.value) })}
            />
          </Field>
          <div className="flex items-end">
            {running ? (
              <button className="btn btn-danger w-full" onClick={() => void stop()} disabled={busy}>
                ■ Stop
              </button>
            ) : (
              <button
                className="btn btn-primary w-full"
                onClick={() => void start()}
                disabled={busy}
              >
                ▶ Start monitoring
              </button>
            )}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MiniStat label="Samples" value={String(stats.count)} />
        <MiniStat
          label="Average RSSI"
          value={stats.rssiAvg === null ? '—' : `${stats.rssiAvg.toFixed(1)} dBm`}
        />
        <MiniStat
          label="RSSI range"
          value={
            stats.rssiMin === null ? '—' : `${stats.rssiMin} … ${stats.rssiMax} dBm`
          }
        />
        <MiniStat label="Average ping" value={ms(stats.pingAvg)} />
      </div>

      <Card title="RSSI over time">
        {points.length < 2 ? (
          <p className="py-12 text-center text-sm text-slate-500">
            {running ? 'Waiting for samples…' : 'Start monitoring to plot the signal.'}
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={points}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke="#475569" fontSize={11} minTickGap={50} />
              <YAxis stroke="#475569" fontSize={11} domain={[-95, -25]} width={45} />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              {/* Threshold lines make "is this bad?" readable without a legend. */}
              {thresholds && (
                <ReferenceLine
                  y={thresholds.rssi_warning}
                  stroke="#f59e0b"
                  strokeDasharray="4 4"
                  label={{ value: 'warning', fill: '#f59e0b', fontSize: 10, position: 'right' }}
                />
              )}
              {thresholds && (
                <ReferenceLine
                  y={thresholds.rssi_critical}
                  stroke="#ef4444"
                  strokeDasharray="4 4"
                  label={{ value: 'critical', fill: '#ef4444', fontSize: 10, position: 'right' }}
                />
              )}
              <Line
                type="monotone"
                dataKey="rssi"
                name="RSSI (dBm)"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card title="Latency and packet loss">
        {points.length < 2 ? (
          <p className="py-8 text-center text-sm text-slate-500">No data yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={points}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke="#475569" fontSize={11} minTickGap={50} />
              <YAxis yAxisId="ping" stroke="#475569" fontSize={11} width={45} />
              <YAxis
                yAxisId="loss"
                orientation="right"
                stroke="#475569"
                fontSize={11}
                width={40}
                domain={[0, 100]}
              />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line
                yAxisId="ping"
                type="monotone"
                dataKey="ping"
                name="Ping (ms)"
                stroke="#a78bfa"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                yAxisId="loss"
                type="monotone"
                dataKey="loss"
                name="Loss (%)"
                stroke="#ef4444"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card title="Samples" action={latest && <GradePill grade={latest.grade} />}>
        <div className="table-wrap max-h-96 overflow-y-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>RSSI</th>
                <th>SSID</th>
                <th>BSSID</th>
                <th>CH</th>
                <th>Ping</th>
                <th>Loss</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {[...points]
                .reverse()
                .slice(0, 200)
                .map((p) => (
                  <tr key={p.ts}>
                    <td className="tabular text-slate-400">{p.label}</td>
                    <td className="tabular">{dbm(p.rssi)}</td>
                    <td>{text(p.ssid)}</td>
                    <td className="font-mono text-xs">{text(p.bssid)}</td>
                    <td className="tabular">{text(p.channel)}</td>
                    <td className="tabular">{ms(p.ping)}</td>
                    <td className="tabular">{pct(p.loss)}</td>
                    <td>
                      <VerdictPill verdict={p.verdict} />
                    </td>
                  </tr>
                ))}
              {points.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500">
                    No samples yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular">{value}</div>
    </div>
  )
}
