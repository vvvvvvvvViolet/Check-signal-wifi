import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { Dashboard } from '../api/types'
import { Banner, Card, GradePill, Spinner, Stat, StatusDot } from '../components/ui'
import { SignalGauge } from '../components/SignalGauge'
import { usePolling } from '../hooks/usePolling'
import { clockTime, dbm, ms, pct, text, VERDICT_COLOR } from '../lib/format'

export function DashboardPage() {
  const { data, error, loading, refresh } = usePolling<Dashboard>(
    () => api.get('/api/dashboard'),
    { intervalMs: 5000 },
  )

  if (loading && !data) return <Spinner label="Reading the radio…" />
  if (error && !data) return <Banner kind="error">Could not reach the service: {error}</Banner>
  if (!data) return null

  const { link, summary, ping } = data
  const gateway = ping.gateway
  const server = ping.server

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-sm text-slate-400">
            Updated {clockTime(data.ts)} · refreshes every 5s
          </p>
        </div>
        <button className="btn" onClick={() => void refresh()}>
          ⟳ Refresh now
        </button>
      </header>

      {link.warnings.length > 0 && (
        <Banner kind="warning">{link.warnings.join(' · ')}</Banner>
      )}
      {error && <Banner kind="warning">Last refresh failed: {error}</Banner>}

      {/* The headline answer: is the WiFi OK right now? */}
      <div
        className="rounded-xl border p-4 text-lg font-semibold"
        style={{
          borderColor: `${VERDICT_COLOR[summary.verdict]}55`,
          backgroundColor: `${VERDICT_COLOR[summary.verdict]}12`,
          color: VERDICT_COLOR[summary.verdict],
        }}
      >
        {data.status_text}
        {summary.incomplete && (
          <div className="mt-1 text-sm font-normal text-slate-400">
            Latency and packet loss could not be measured, so the network cannot be
            confirmed healthy on signal strength alone.
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Signal" className="flex items-center justify-center lg:row-span-2">
          <SignalGauge rssi={link.rssi} grade={summary.grade} />
        </Card>

        <Card title="Connection" className="lg:col-span-2">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
            <Detail label="SSID" value={text(link.ssid)} />
            <Detail label="BSSID" value={text(link.bssid)} mono />
            <Detail label="Channel" value={text(link.channel)} mono />
            <Detail label="Band" value={text(link.band)} />
            <Detail label="Security" value={text(link.security)} />
            <Detail label="IP address" value={text(link.ip_address)} mono />
            <Detail
              label="PHY rate"
              value={link.tx_rate_mbps ? `${link.tx_rate_mbps} Mbps` : '—'}
              mono
            />
            <Detail label="Interface" value={text(link.interface)} mono />
            <Detail
              label="Quality"
              value={<GradePill grade={summary.grade} />}
            />
          </dl>
        </Card>

        <Card title="Reachability" className="lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <Probe
              name="Gateway"
              target={data.gateway.address}
              suffix={data.gateway.auto_detected ? ' (auto)' : ''}
              rtt={gateway?.rtt_avg_ms ?? null}
              loss={gateway?.packet_loss_pct ?? null}
              available={gateway?.available ?? false}
              errorText={gateway?.error ?? null}
            />
            <Probe
              name="Server"
              target={server?.target ?? null}
              rtt={server?.rtt_avg_ms ?? null}
              loss={server?.packet_loss_pct ?? null}
              available={server?.available ?? false}
              errorText={server?.error ?? null}
            />
          </div>
        </Card>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="RSSI" value={dbm(link.rssi)} color={summary.grade_color} />
        <Stat
          label="Latency"
          value={ms(summary.ping_ms)}
          sub={<span>warn &gt; {data.thresholds.ping_warning_ms} ms</span>}
        />
        <Stat
          label="Packet loss"
          value={pct(summary.packet_loss_pct)}
          sub={<span>warn &gt; {data.thresholds.loss_warning_pct}%</span>}
        />
        <Stat label="Jitter" value={ms(summary.jitter_ms)} />
      </div>

      <Card title="Recent trend">
        {data.trend.length < 2 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            Not enough samples yet. Start the Signal Monitor to build a trend.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data.trend.map((t) => ({ ...t, label: clockTime(t.ts) }))}>
              <XAxis dataKey="label" stroke="#475569" fontSize={11} minTickGap={40} />
              <YAxis
                stroke="#475569"
                fontSize={11}
                domain={[-95, -25]}
                width={40}
                tickFormatter={(v) => `${v}`}
              />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value: number) => [`${value} dBm`, 'RSSI']}
              />
              <Line
                type="monotone"
                dataKey="rssi"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>
    </div>
  )
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className={`mt-0.5 ${mono ? 'font-mono text-xs' : ''} text-slate-100`}>{value}</dd>
    </div>
  )
}

function Probe({
  name,
  target,
  suffix = '',
  rtt,
  loss,
  available,
  errorText,
}: {
  name: string
  target: string | null
  suffix?: string
  rtt: number | null
  loss: number | null
  available: boolean
  errorText: string | null
}) {
  // "Not measured" and "unreachable" look nothing alike to a technician, so
  // they must not look alike here either.
  const status = !available ? 'unknown' : loss === null ? 'unknown' : loss >= 100 ? 'critical' : loss > 0 ? 'warning' : 'ok'
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{name}</span>
        <StatusDot status={status} title={errorText ?? undefined} />
      </div>
      <div className="mt-1 font-mono text-xs text-slate-400">
        {target ?? 'not found'}
        {suffix}
      </div>
      {available ? (
        <div className="mt-2 flex gap-4 text-sm tabular">
          <span>{ms(rtt)}</span>
          <span className="text-slate-400">loss {pct(loss)}</span>
        </div>
      ) : (
        <div className="mt-2 text-xs text-slate-500">{errorText ?? 'not measured'}</div>
      )}
    </div>
  )
}
