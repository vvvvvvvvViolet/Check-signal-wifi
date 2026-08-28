import { useCallback, useEffect, useRef, useState } from 'react'
import { api, monitorSocketUrl } from '../api/client'
import type { MonitorStatus, RoamEvent, Snapshot } from '../api/types'
import { Banner, Card, Empty, Spinner } from '../components/ui'
import { clockTime, dbm, duration, text } from '../lib/format'

interface TimelineEntry {
  id: string
  ts: string
  kind: 'sample' | 'roam' | 'reconnect' | 'network_change'
  rssi: number | null
  bssid: string | null
  ssid: string | null
  channel: number | null
  from?: string | null
  to?: string | null
  gapMs?: number | null
  delta?: number | null
}

const MAX_ENTRIES = 300

export function RoamingPage() {
  const [entries, setEntries] = useState<TimelineEntry[]>([])
  const [status, setStatus] = useState<MonitorStatus | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const socketRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number | null>(null)
  const closedByUs = useRef(false)
  const lastBssid = useRef<string | null>(null)

  const push = useCallback((entry: TimelineEntry) => {
    setEntries((prev) => [entry, ...prev].slice(0, MAX_ENTRIES))
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

      if (message.type === 'hello') {
        setStatus(message.status)
        return
      }

      if (message.type === 'roam') {
        const roam = message as RoamEvent & { kind: string }
        push({
          id: `roam-${roam.ts}-${roam.to_bssid}`,
          ts: roam.ts,
          kind: (roam.kind as TimelineEntry['kind']) ?? 'roam',
          rssi: roam.to_rssi,
          bssid: roam.to_bssid,
          ssid: roam.ssid,
          channel: roam.to_channel,
          from: roam.from_bssid,
          to: roam.to_bssid,
          gapMs: roam.gap_ms,
          delta: roam.rssi_delta ?? null,
        })
        return
      }

      if (message.type === 'sample') {
        const snapshot = message as Snapshot
        // Only record a sample when the AP changed or every reading would
        // bury the roams in noise.
        const bssid = snapshot.link.bssid
        if (bssid !== lastBssid.current) {
          lastBssid.current = bssid
        }
        push({
          id: `s-${snapshot.ts}`,
          ts: snapshot.ts,
          kind: 'sample',
          rssi: snapshot.link.rssi,
          bssid,
          ssid: snapshot.link.ssid,
          channel: snapshot.link.channel,
        })
      }
    }

    socket.onclose = () => {
      setConnected(false)
      socketRef.current = null
      if (!closedByUs.current) retryRef.current = window.setTimeout(connect, 2000)
    }
    socket.onerror = () => setError('Live connection interrupted')
  }, [push])

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

  const toggle = async () => {
    setBusy(true)
    setError(null)
    try {
      if (status?.running) {
        await api.post('/api/monitor/stop')
      } else {
        setEntries([])
        await api.post('/api/monitor/start', {
          name: 'Roaming test',
          interval_sec: 1,
        })
      }
      await refreshStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const roams = entries.filter((e) => e.kind !== 'sample')
  const running = status?.running ?? false

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Roaming Test</h1>
          <p className="text-sm text-slate-400">
            Walk the route; every AP hand-off is timestamped
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 text-xs text-slate-400">
            <span
              className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-slate-600'}`}
            />
            {connected ? 'Live' : 'Reconnecting…'}
          </span>
          <button
            className={`btn ${running ? 'btn-danger' : 'btn-primary'}`}
            onClick={() => void toggle()}
            disabled={busy}
          >
            {running ? '■ Stop walk test' : '▶ Start walk test'}
          </button>
        </div>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="card">
          <div className="card-title">Roam events</div>
          <div className="mt-1 text-2xl font-semibold tabular">{roams.length}</div>
        </div>
        <div className="card">
          <div className="card-title">Current AP</div>
          <div className="mt-1 font-mono text-sm">
            {text(entries.find((e) => e.bssid)?.bssid)}
          </div>
        </div>
        <div className="card">
          <div className="card-title">Average gap</div>
          <div className="mt-1 text-2xl font-semibold tabular">
            {roams.length === 0
              ? '—'
              : duration(
                  roams
                    .map((r) => r.gapMs ?? 0)
                    .reduce((a, b) => a + b, 0) / roams.length,
                )}
          </div>
        </div>
      </div>

      <Card title="Timeline">
        {entries.length === 0 ? (
          running ? (
            <Spinner label="Waiting for the first reading…" />
          ) : (
            <Empty>
              Start the walk test, then carry the device along the route. Each hand-off between
              access points is recorded with the signal before and after.
            </Empty>
          )
        ) : (
          <ol className="relative space-y-3 border-l border-slate-800 pl-6">
            {entries.slice(0, 120).map((entry) => (
              <li key={entry.id} className="relative">
                <span
                  className={`absolute -left-[1.65rem] top-1.5 h-3 w-3 rounded-full border-2 border-slate-950 ${
                    entry.kind === 'sample' ? 'bg-slate-600' : 'bg-sky-400'
                  }`}
                />
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-mono text-xs text-slate-500 tabular">
                    {clockTime(entry.ts)}
                  </span>
                  {entry.kind === 'sample' ? (
                    <>
                      <span className="tabular font-semibold">{dbm(entry.rssi)}</span>
                      <span className="font-mono text-xs text-slate-500">
                        {text(entry.bssid)}
                      </span>
                      {entry.channel !== null && (
                        <span className="text-xs text-slate-600">ch {entry.channel}</span>
                      )}
                    </>
                  ) : (
                    <div className="w-full rounded-lg border border-sky-500/40 bg-sky-500/10 p-3">
                      <div className="text-sm font-bold uppercase tracking-wide text-sky-300">
                        {entry.kind === 'roam'
                          ? 'Roam'
                          : entry.kind === 'reconnect'
                            ? 'Reconnect'
                            : 'Network change'}
                      </div>
                      <div className="mt-1 font-mono text-xs text-slate-300">
                        {text(entry.from)} → {text(entry.to)}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-4 text-xs text-slate-400 tabular">
                        <span>gap {duration(entry.gapMs)}</span>
                        {entry.delta !== null && entry.delta !== undefined && (
                          <span
                            className={entry.delta >= 0 ? 'text-emerald-400' : 'text-amber-400'}
                          >
                            {entry.delta >= 0 ? '+' : ''}
                            {entry.delta} dB
                          </span>
                        )}
                        <span>now {dbm(entry.rssi)}</span>
                      </div>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  )
}
