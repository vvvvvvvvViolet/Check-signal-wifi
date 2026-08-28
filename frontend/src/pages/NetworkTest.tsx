import { useState } from 'react'
import { api } from '../api/client'
import type { ConnectivityChain, PingResult } from '../api/types'
import { Banner, Card, Field, Spinner } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { ms, pct, text } from '../lib/format'

const STATE_STYLE = {
  ok: { border: '#16a34a', bg: '#16a34a15', text: '#4ade80', icon: '✓' },
  failed: { border: '#ef4444', bg: '#ef444415', text: '#f87171', icon: '✕' },
  blocked: { border: '#64748b', bg: '#64748b15', text: '#94a3b8', icon: '·' },
} as const

export function NetworkTestPage() {
  const { data, error, loading, refresh } = usePolling<ConnectivityChain>(
    () => api.get('/api/nettest/chain'),
    { intervalMs: 0 },
  )

  const [target, setTarget] = useState('8.8.8.8')
  const [manual, setManual] = useState<PingResult | null>(null)
  const [manualError, setManualError] = useState<string | null>(null)
  const [pinging, setPinging] = useState(false)

  const runPing = async () => {
    setPinging(true)
    setManualError(null)
    try {
      setManual(await api.get<PingResult>('/api/nettest/ping', { target, count: 5 }))
    } catch (err) {
      setManualError(err instanceof Error ? err.message : String(err))
      setManual(null)
    } finally {
      setPinging(false)
    }
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Network Test</h1>
          <p className="text-sm text-slate-400">
            Probe each hop so a break can be located, not just reported
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => void refresh()} disabled={loading}>
          ⟳ Run test
        </button>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      {loading && !data ? (
        <Spinner label="Probing the path…" />
      ) : data ? (
        <>
          {data.healthy ? (
            <Banner kind="success">Every hop responded — the path is clear end to end.</Banner>
          ) : (
            <Banner kind="warning">
              First failure at <strong>{data.broken_at}</strong>. Hops that still passed are
              shown as passing — ICMP to the gateway is often filtered while everything above
              it works.
            </Banner>
          )}

          <Card title="Path">
            <ol className="space-y-2">
              {data.steps.map((step, index) => {
                const style = STATE_STYLE[step.state]
                return (
                  <li key={step.key}>
                    <div
                      className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3"
                      style={{ borderColor: `${style.border}55`, backgroundColor: style.bg }}
                    >
                      <span
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold"
                        style={{ backgroundColor: `${style.border}30`, color: style.text }}
                      >
                        {style.icon}
                      </span>
                      <span className="w-36 font-semibold" style={{ color: style.text }}>
                        {step.label}
                      </span>
                      <span className="flex-1 font-mono text-xs text-slate-400">
                        {step.detail}
                      </span>
                      <span className="tabular text-sm text-slate-300">
                        {ms(step.latency_ms)}
                      </span>
                    </div>
                    {index < data.steps.length - 1 && (
                      <div className="ml-3.5 h-3 border-l-2 border-dashed border-slate-700" />
                    )}
                  </li>
                )
              })}
            </ol>
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            {(['gateway', 'server', 'dns'] as const).map((key) => (
              <PingCard key={key} title={key} result={data.ping[key]} />
            ))}
          </div>

          <Card title="DNS resolution">
            <dl className="grid gap-3 sm:grid-cols-3 text-sm">
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Hostname</dt>
                <dd className="mt-0.5 font-mono text-xs">{data.dns.hostname}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Resolve time</dt>
                <dd className="mt-0.5 tabular">{ms(data.dns.elapsed_ms)}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Addresses</dt>
                <dd className="mt-0.5 font-mono text-xs">
                  {data.dns.addresses.join(', ') || text(data.dns.error)}
                </dd>
              </div>
            </dl>
          </Card>
        </>
      ) : null}

      <Card title="Manual ping">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1">
            <Field label="Target host or IP">
              <input
                className="input"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void runPing()}
              />
            </Field>
          </div>
          <button className="btn" onClick={() => void runPing()} disabled={pinging || !target}>
            {pinging ? 'Pinging…' : 'Ping'}
          </button>
        </div>
        {manualError && (
          <div className="mt-3">
            <Banner kind="error">{manualError}</Banner>
          </div>
        )}
        {manual && (
          <div className="mt-4">
            <PingCard title={manual.target} result={manual} />
          </div>
        )}
      </Card>
    </div>
  )
}

function PingCard({ title, result }: { title: string; result: PingResult | undefined }) {
  if (!result) return null
  // Never render "0 ms / 0% loss" for a probe that did not run.
  const unavailable = !result.available
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <span className="card-title capitalize">{title}</span>
        <span
          className={`text-xs font-semibold ${
            unavailable ? 'text-slate-500' : result.reachable ? 'text-emerald-400' : 'text-red-400'
          }`}
        >
          {unavailable ? 'not measured' : result.reachable ? 'reachable' : 'unreachable'}
        </span>
      </div>
      <div className="mt-1 font-mono text-xs text-slate-400">{result.target || '—'}</div>
      {unavailable ? (
        <p className="mt-3 text-xs text-slate-500">{result.error}</p>
      ) : (
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <Metric label="Average" value={ms(result.rtt_avg_ms)} />
          <Metric label="Loss" value={pct(result.packet_loss_pct)} />
          <Metric label="Min / Max" value={`${ms(result.rtt_min_ms)} / ${ms(result.rtt_max_ms)}`} />
          <Metric label="Jitter" value={ms(result.jitter_ms)} />
        </dl>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="tabular text-slate-200">{value}</dd>
    </div>
  )
}
