import { api } from '../api/client'
import type { DiagnosisReport, Finding } from '../api/types'
import { Banner, Card, Spinner } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { clockTime, dbm, ms, pct, text } from '../lib/format'

const SEVERITY = {
  critical: { color: '#ef4444', label: 'Critical', icon: '⛔' },
  warning: { color: '#f59e0b', label: 'Warning', icon: '⚠' },
  info: { color: '#38bdf8', label: 'Info', icon: 'ℹ' },
} as const

export function DiagnosisPage() {
  const { data, error, loading, refresh } = usePolling<DiagnosisReport>(
    () => api.get('/api/diagnosis', { include_scan: true }),
    { intervalMs: 0 },
  )

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Auto Diagnosis</h1>
          <p className="text-sm text-slate-400">
            Reads the radio and the network, then says which layer is at fault
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => void refresh()} disabled={loading}>
          ⟳ Run diagnosis
        </button>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      {loading && !data ? (
        <Spinner label="Measuring and scanning…" />
      ) : data ? (
        <>
          <div
            className="rounded-xl border p-4"
            style={{
              borderColor: `${SEVERITY[data.severity].color}55`,
              backgroundColor: `${SEVERITY[data.severity].color}12`,
            }}
          >
            <div
              className="text-lg font-semibold"
              style={{ color: SEVERITY[data.severity].color }}
            >
              {SEVERITY[data.severity].icon} {data.headline}
            </div>
            {data.ts && (
              <div className="mt-1 text-xs text-slate-500">Measured at {clockTime(data.ts)}</div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Measure label="Signal" value={dbm(data.measurements.rssi_dbm)} />
            <Measure label="Ping" value={ms(data.measurements.ping_ms)} />
            <Measure label="Packet loss" value={pct(data.measurements.packet_loss_pct)} />
          </div>

          {data.link && (
            <Card title="Connection under test">
              <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
                <span>
                  <span className="text-slate-500">SSID </span>
                  {text(data.link.ssid)}
                </span>
                <span>
                  <span className="text-slate-500">BSSID </span>
                  <span className="font-mono text-xs">{text(data.link.bssid)}</span>
                </span>
                <span>
                  <span className="text-slate-500">Channel </span>
                  {text(data.link.channel)}
                </span>
                <span>
                  <span className="text-slate-500">Band </span>
                  {text(data.link.band)}
                </span>
              </div>
            </Card>
          )}

          <div className="space-y-3">
            {data.findings.map((finding) => (
              <FindingCard key={finding.code} finding={finding} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}

function Measure({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular">{value}</div>
    </div>
  )
}

function FindingCard({ finding }: { finding: Finding }) {
  const severity = SEVERITY[finding.severity]
  return (
    <article
      className="rounded-xl border bg-slate-900/60 p-4"
      style={{ borderColor: `${severity.color}44` }}
    >
      <header className="flex flex-wrap items-center gap-2">
        <span
          className="rounded px-2 py-0.5 text-xs font-bold uppercase tracking-wide"
          style={{ backgroundColor: `${severity.color}22`, color: severity.color }}
        >
          {severity.label}
        </span>
        <h3 className="font-semibold">{finding.title}</h3>
      </header>
      <p className="mt-2 text-sm text-slate-300">{finding.summary}</p>

      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {finding.causes.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Possible problem
            </h4>
            <ul className="mt-1 space-y-1 text-sm text-slate-300">
              {finding.causes.map((cause) => (
                <li key={cause} className="flex gap-2">
                  <span className="text-slate-600">•</span>
                  {cause}
                </li>
              ))}
            </ul>
          </div>
        )}
        {finding.recommendations.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Recommendation
            </h4>
            <ul className="mt-1 space-y-1 text-sm text-slate-300">
              {finding.recommendations.map((rec) => (
                <li key={rec} className="flex gap-2">
                  <span className="text-emerald-500">›</span>
                  {rec}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </article>
  )
}
