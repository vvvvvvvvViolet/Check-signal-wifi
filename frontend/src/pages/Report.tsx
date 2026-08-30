import { Fragment, Suspense, lazy, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { FloorPlan, MonitorSession, MonitorSummary, Sample } from '../api/types'
import { Banner, Card, Empty, Field, Spinner, VerdictPill } from '../components/ui'
import { dateTime, dbm, ms, pct, text } from '../lib/format'

const TrendChart = lazy(() => import('../components/TrendChart'))

type Format = 'csv' | 'xlsx' | 'pdf'

const FORMATS: { value: Format; label: string; hint: string }[] = [
  { value: 'xlsx', label: 'Excel', hint: 'Coloured results plus a summary sheet' },
  { value: 'csv', label: 'CSV', hint: 'Raw rows for your own pivot' },
  { value: 'pdf', label: 'PDF', hint: 'One-page report with the diagnosis' },
]

export function ReportPage() {
  const [sessions, setSessions] = useState<MonitorSession[]>([])
  const [plans, setPlans] = useState<FloorPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [historyRange, setHistoryRange] = useState({ from: '', to: '' })
  const [sessionId, setSessionId] = useState<string>('')
  const [planId, setPlanId] = useState<string>('')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  useEffect(() => {
    Promise.all([
      api.get<MonitorSession[]>('/api/monitor/sessions'),
      api.get<FloorPlan[]>('/api/heatmap/plans'),
    ])
      .then(([sessionRows, planRows]) => {
        setSessions(sessionRows)
        setPlans(planRows)
        setSessionId(sessionRows[0] ? String(sessionRows[0].id) : '')
        setPlanId(planRows[0] ? String(planRows[0].id) : '')
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner label="Loading exportable data…" />

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold tracking-tight">Export Report</h1>
        <p className="text-sm text-slate-400">
          Excel, CSV or PDF — each format is shaped for a different reader
        </p>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      <Card title="Test history">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="From">
            <input
              className="input"
              type="date"
              value={historyRange.from}
              onChange={(e) => setHistoryRange({ ...historyRange, from: e.target.value })}
            />
          </Field>
          <Field label="To">
            <input
              className="input"
              type="date"
              value={historyRange.to}
              onChange={(e) => setHistoryRange({ ...historyRange, to: e.target.value })}
            />
          </Field>
        </div>
        <DownloadRow
          build={(format) =>
            api.downloadUrl('/api/report/history', {
              format,
              date_from: historyRange.from || undefined,
              date_to: historyRange.to || undefined,
            })
          }
        />
      </Card>

      <Card title="Monitor session">
        {sessions.length === 0 ? (
          <Empty>No monitor sessions recorded yet. Run the Signal Monitor first.</Empty>
        ) : (
          <>
            <Field label="Session">
              <select
                className="input"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
              >
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.name}
                    {session.area ? ` · ${session.area}` : ''} — {dateTime(session.started_at)}
                    {session.ended_at ? '' : ' (running)'}
                  </option>
                ))}
              </select>
            </Field>
            <DownloadRow
              disabled={!sessionId}
              build={(format) =>
                api.downloadUrl(`/api/report/session/${sessionId}`, { format })
              }
            />
          </>
        )}
      </Card>

      <Card title="Heatmap survey">
        {plans.length === 0 ? (
          <Empty>No floor plans uploaded yet.</Empty>
        ) : (
          <>
            <Field label="Floor plan">
              <select className="input" value={planId} onChange={(e) => setPlanId(e.target.value)}>
                {plans.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                    {plan.location ? ` · ${plan.location}` : ''}
                  </option>
                ))}
              </select>
            </Field>
            <DownloadRow
              disabled={!planId}
              build={(format) => api.downloadUrl(`/api/report/heatmap/${planId}`, { format })}
            />
          </>
        )}
      </Card>

      <Card title="Recorded sessions">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Area</th>
                <th>Device</th>
                <th>Started</th>
                <th>Ended</th>
                <th>Interval</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <Fragment key={session.id}>
                  <tr>
                    <td className="font-medium">{session.name}</td>
                    <td>{text(session.area)}</td>
                    <td>{text(session.device)}</td>
                    <td className="text-slate-400">{dateTime(session.started_at)}</td>
                    <td className="text-slate-400">
                      {session.ended_at ? dateTime(session.ended_at) : (
                        <span className="text-emerald-400">running</span>
                      )}
                    </td>
                    <td className="tabular">{session.interval_sec}s</td>
                    <td>
                      <button
                        className="text-xs text-sky-400 hover:text-sky-300"
                        onClick={() =>
                          setExpandedId(expandedId === session.id ? null : session.id)
                        }
                      >
                        {expandedId === session.id ? 'Hide' : 'View'}
                      </button>
                    </td>
                  </tr>
                  {expandedId === session.id && (
                    <tr>
                      <td colSpan={7} className="bg-slate-950/40 p-4">
                        <SessionPreview sessionId={session.id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {sessions.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    No sessions yet.
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

/**
 * Inline view of a past session - the samples/summary endpoints exist for
 * exactly this, but nothing rendered them before this panel: without it, the
 * only way to see a finished session's data was to export it and open the
 * file elsewhere.
 */
function SessionPreview({ sessionId }: { sessionId: number }) {
  const [summary, setSummary] = useState<MonitorSummary | null>(null)
  const [samples, setSamples] = useState<Sample[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setSummary(null)
    setSamples(null)
    setError(null)

    Promise.all([
      api.get<MonitorSummary>('/api/monitor/summary', { session_id: sessionId }),
      api.get<Sample[]>('/api/monitor/samples', { session_id: sessionId, limit: 2000 }),
    ])
      .then(([summaryRes, samplesRes]) => {
        if (cancelled) return
        setSummary(summaryRes)
        setSamples(samplesRes)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })

    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (error) return <Banner kind="error">{error}</Banner>
  if (!summary || !samples) return <Spinner label="Loading session…" />
  if (samples.length === 0) return <Empty>No samples were recorded in this session.</Empty>

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SessionStat label="Samples" value={String(summary.samples)} />
        <SessionStat
          label="Avg RSSI"
          value={summary.rssi.avg !== null ? dbm(summary.rssi.avg) : '—'}
          sub={
            summary.rssi.min !== null ? `${dbm(summary.rssi.min)} … ${dbm(summary.rssi.max)}` : undefined
          }
        />
        <SessionStat label="Avg ping" value={ms(summary.ping_ms.avg)} />
        <SessionStat label="Packet loss" value={pct(summary.packet_loss_pct)} />
      </div>

      <div className="flex flex-wrap gap-2">
        {Object.entries(summary.verdicts).map(([verdict, count]) => (
          <span key={verdict} className="flex items-center gap-1.5 text-xs">
            <VerdictPill verdict={verdict as 'PASS' | 'WARNING' | 'FAIL'} />
            <span className="text-slate-500">× {count}</span>
          </span>
        ))}
      </div>

      <Suspense fallback={<div className="h-[200px] animate-pulse rounded bg-slate-800/40" />}>
        <TrendChart
          data={samples.map((s) => ({ ts: s.ts, rssi: s.rssi, ping_ms: s.ping_server_ms }))}
        />
      </Suspense>
    </div>
  )
}

function SessionStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500 tabular">{sub}</div>}
    </div>
  )
}

function DownloadRow({
  build,
  disabled = false,
}: {
  build: (format: Format) => string
  disabled?: boolean
}) {
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {FORMATS.map((format) => (
        <a
          key={format.value}
          className={`btn ${disabled ? 'pointer-events-none opacity-50' : ''}`}
          href={disabled ? undefined : build(format.value)}
          title={format.hint}
        >
          ⤓ {format.label}
        </a>
      ))}
    </div>
  )
}
