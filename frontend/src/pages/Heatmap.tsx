import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { CoverageGrid, FloorPlan, Grade } from '../api/types'
import { HeatmapCanvas } from '../components/HeatmapCanvas'
import { Banner, Card, Empty, Field, GradePill, Spinner } from '../components/ui'
import { dateTime, dbm, GRADE_COLOR, GRADE_LABEL, GRADE_RANGES, ms, text } from '../lib/format'

export function HeatmapPage() {
  const [plans, setPlans] = useState<FloorPlan[]>([])
  const [planId, setPlanId] = useState<number | null>(null)
  const [coverage, setCoverage] = useState<CoverageGrid | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  const [opacity, setOpacity] = useState(0.62)
  const [gridSize, setGridSize] = useState(56)
  const [mode, setMode] = useState<'measure' | 'ap' | 'view'>('measure')
  const [pointLabel, setPointLabel] = useState('')
  const [apName, setApName] = useState('')

  const loadPlans = useCallback(async () => {
    const rows = await api.get<FloorPlan[]>('/api/heatmap/plans')
    setPlans(rows)
    setPlanId((current) => current ?? rows[0]?.id ?? null)
    setLoading(false)
  }, [])

  useEffect(() => {
    void loadPlans().catch((err) => {
      setError(err instanceof Error ? err.message : String(err))
      setLoading(false)
    })
  }, [loadPlans])

  const loadCoverage = useCallback(async () => {
    if (planId === null) {
      setCoverage(null)
      return
    }
    try {
      setCoverage(
        await api.get<CoverageGrid>(`/api/heatmap/plans/${planId}/grid`, { grid_size: gridSize }),
      )
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [planId, gridSize])

  useEffect(() => {
    void loadCoverage()
  }, [loadCoverage])

  const upload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    if (!(form.get('file') as File)?.size) {
      setError('Choose a floor plan image first')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const plan = await api.upload<FloorPlan>('/api/heatmap/plans', form)
      event.currentTarget.reset()
      await loadPlans()
      setPlanId(plan.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const pick = async (x: number, y: number) => {
    if (planId === null || mode === 'view') return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'measure') {
        await api.post(`/api/heatmap/plans/${planId}/points`, {
          x,
          y,
          label: pointLabel || null,
          measure: true,
        })
        setPointLabel('')
      } else {
        const name = apName.trim()
        if (!name) {
          setError('Give the access point a name before placing it')
          return
        }
        await api.post(`/api/heatmap/plans/${planId}/aps`, { name, x, y })
        setApName('')
      }
      await loadCoverage()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const deletePlan = async () => {
    if (planId === null) return
    if (!window.confirm('Delete this floor plan and every survey point on it?')) return
    await api.delete(`/api/heatmap/plans/${planId}`)
    setPlanId(null)
    setCoverage(null)
    await loadPlans()
  }

  const deletePoint = async (id: number) => {
    await api.delete(`/api/heatmap/points/${id}`)
    await loadCoverage()
  }

  if (loading) return <Spinner label="Loading floor plans…" />

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold tracking-tight">Heatmap</h1>
        <p className="text-sm text-slate-400">
          Upload a plan, walk the floor and capture a reading at each point
        </p>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      <Card title="Floor plan">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <Field label="Active plan">
              <select
                className="input"
                value={planId ?? ''}
                onChange={(e) => setPlanId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">— none —</option>
                {plans.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                    {plan.location ? ` · ${plan.location}` : ''}
                  </option>
                ))}
              </select>
            </Field>
            {planId !== null && (
              <button className="btn btn-danger" onClick={() => void deletePlan()}>
                Delete plan
              </button>
            )}
          </div>

          <form className="space-y-3" onSubmit={upload}>
            <Field label="Upload a new plan" hint="PNG, JPEG or WebP, up to 20 MB">
              <input
                className="input"
                type="file"
                name="file"
                accept="image/png,image/jpeg,image/webp"
                required
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name">
                <input className="input" name="name" placeholder="Production-A" required />
              </Field>
              <Field label="Location">
                <input className="input" name="location" placeholder="Building 1" />
              </Field>
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              Upload plan
            </button>
          </form>
        </div>
      </Card>

      {planId === null || !coverage ? (
        <Empty>Upload a floor plan to begin the survey.</Empty>
      ) : (
        <>
          <Card
            title="Capture"
            action={
              <div className="flex gap-1 rounded-lg border border-slate-700 p-0.5 text-xs">
                {(
                  [
                    ['measure', 'Measure point'],
                    ['ap', 'Place AP'],
                    ['view', 'View only'],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setMode(value)}
                    className={`rounded px-2 py-1 transition ${
                      mode === value ? 'bg-sky-600 text-white' : 'text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            }
          >
            <div className="grid gap-3 sm:grid-cols-3">
              {mode === 'measure' && (
                <Field label="Point label (optional)">
                  <input
                    className="input"
                    value={pointLabel}
                    placeholder="Aisle 3"
                    onChange={(e) => setPointLabel(e.target.value)}
                  />
                </Field>
              )}
              {mode === 'ap' && (
                <Field label="Access point name">
                  <input
                    className="input"
                    value={apName}
                    placeholder="AP-Factory-01"
                    onChange={(e) => setApName(e.target.value)}
                  />
                </Field>
              )}
              <Field label={`Overlay opacity — ${Math.round(opacity * 100)}%`}>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.02}
                  value={opacity}
                  onChange={(e) => setOpacity(Number(e.target.value))}
                  className="w-full accent-sky-500"
                />
              </Field>
              <Field label={`Grid resolution — ${gridSize}`}>
                <input
                  type="range"
                  min={16}
                  max={120}
                  step={4}
                  value={gridSize}
                  onChange={(e) => setGridSize(Number(e.target.value))}
                  className="w-full accent-sky-500"
                />
              </Field>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              {mode === 'view'
                ? 'Viewing only — clicks are ignored.'
                : mode === 'measure'
                  ? 'Stand at the location, then click the matching spot on the plan. The reading is taken live.'
                  : 'Click where the access point physically sits.'}
              {busy && ' · working…'}
            </p>
          </Card>

          <Card
            title={coverage.plan.name}
            action={
              coverage.grid && (
                <span className="text-xs text-slate-500">
                  {coverage.grid.covered_pct}% of the floor within measurement range
                </span>
              )
            }
          >
            <HeatmapCanvas
              data={coverage}
              imageUrl={`/api/heatmap/plans/${planId}/image`}
              opacity={opacity}
              onPick={mode === 'view' ? undefined : pick}
            />

            <div className="mt-3 flex flex-wrap items-center gap-4">
              {GRADE_RANGES.map(({ grade, label }) => (
                <span key={grade} className="flex items-center gap-1.5 text-xs text-slate-400">
                  <span
                    className="h-3 w-3 rounded"
                    style={{ backgroundColor: GRADE_COLOR[grade] }}
                  />
                  {GRADE_LABEL[grade]} <span className="text-slate-600">{label}</span>
                </span>
              ))}
              <span className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="h-3 w-3 rotate-45 bg-sky-500" /> Access point
              </span>
            </div>

            {coverage.message && (
              <p className="mt-3 text-sm text-slate-500">{coverage.message}</p>
            )}
          </Card>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryStat label="Survey points" value={String(coverage.summary.total_points)} />
            <SummaryStat label="Average RSSI" value={dbm(coverage.summary.rssi_avg)} />
            <SummaryStat label="Weakest point" value={dbm(coverage.summary.rssi_min)} />
            <SummaryStat label="Strongest point" value={dbm(coverage.summary.rssi_max)} />
          </div>

          <Card title="Coverage breakdown">
            <div className="space-y-2">
              {(Object.keys(GRADE_LABEL) as Grade[])
                .filter((grade) => grade !== 'UNKNOWN')
                .map((grade) => {
                  const percent = coverage.summary.percent[grade] ?? 0
                  return (
                    <div key={grade} className="flex items-center gap-3">
                      <span className="w-20 text-xs text-slate-400">{GRADE_LABEL[grade]}</span>
                      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${percent}%`, backgroundColor: GRADE_COLOR[grade] }}
                        />
                      </div>
                      <span className="w-24 text-right text-xs tabular text-slate-400">
                        {coverage.summary.counts[grade] ?? 0} pts · {percent}%
                      </span>
                    </div>
                  )
                })}
            </div>
          </Card>

          <Card title="Survey points">
            <div className="table-wrap max-h-96 overflow-y-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Label</th>
                    <th>Point</th>
                    <th>SSID</th>
                    <th>BSSID</th>
                    <th>CH</th>
                    <th>RSSI</th>
                    <th>Ping</th>
                    <th>Quality</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {coverage.points.map((point) => (
                    <tr key={point.id}>
                      <td className="text-xs text-slate-400">{dateTime(point.ts)}</td>
                      <td>{text(point.label)}</td>
                      <td className="tabular text-xs text-slate-400">
                        X={Math.round(point.x)}, Y={Math.round(point.y)}
                      </td>
                      <td>{text(point.ssid)}</td>
                      <td className="font-mono text-xs text-slate-400">{text(point.bssid)}</td>
                      <td className="tabular">{text(point.channel)}</td>
                      <td className="tabular font-semibold">{dbm(point.rssi)}</td>
                      <td className="tabular">{ms(point.ping_ms)}</td>
                      <td>
                        <GradePill grade={point.grade} />
                      </td>
                      <td>
                        <button
                          className="text-xs text-slate-500 hover:text-red-400"
                          onClick={() => void deletePoint(point.id)}
                        >
                          remove
                        </button>
                      </td>
                    </tr>
                  ))}
                  {coverage.points.length === 0 && (
                    <tr>
                      <td colSpan={10} className="py-8 text-center text-slate-500">
                        No points captured yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular">{value}</div>
    </div>
  )
}
