import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { CoverageGrid, FloorPlan, Grade, HeatmapMetric, WalkReading } from '../api/types'
import { HeatmapCanvas } from '../components/HeatmapCanvas'
import { Banner, Card, Empty, Field, GradePill, Spinner } from '../components/ui'
import { dateTime, dbm, GRADE_COLOR, GRADE_LABEL, GRADE_RANGES, ms, text } from '../lib/format'

type Mode = 'measure' | 'walk' | 'ap' | 'view'

/** How often a walk takes a reading. Fast enough to resolve an aisle, slow
 *  enough that each reading is a real probe rather than a cached one. */
const WALK_INTERVAL_MS = 1500

const REDUNDANCY_LEGEND = [
  { label: 'No alternative AP', color: '#ef4444', hint: 'client drops when it moves' },
  { label: '1 alternative', color: '#facc15', hint: 'no margin' },
  { label: '2 alternatives', color: '#4ade80', hint: '' },
  { label: '3 or more', color: '#16a34a', hint: '' },
]

interface Filters {
  ssid: string
  bssid: string
  band: string
}

export function HeatmapPage() {
  const [plans, setPlans] = useState<FloorPlan[]>([])
  const [planId, setPlanId] = useState<number | null>(null)
  const [coverage, setCoverage] = useState<CoverageGrid | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  const [opacity, setOpacity] = useState(0.62)
  const [gridSize, setGridSize] = useState(56)
  const [metric, setMetric] = useState<HeatmapMetric>('rssi')
  const [filters, setFilters] = useState<Filters>({ ssid: '', bssid: '', band: '' })
  const [mode, setMode] = useState<Mode>('measure')
  const [pointLabel, setPointLabel] = useState('')
  const [apName, setApName] = useState('')
  const [scanOnCapture, setScanOnCapture] = useState(true)

  // --- walk state -----------------------------------------------------------
  const [walkStart, setWalkStart] = useState<{ x: number; y: number } | null>(null)
  const [walkCount, setWalkCount] = useState(0)
  const walkSamples = useRef<{ elapsed_ms: number; reading: WalkReading }[]>([])
  const walkTimer = useRef<number | null>(null)
  const walkT0 = useRef(0)

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
        await api.get<CoverageGrid>(`/api/heatmap/plans/${planId}/grid`, {
          grid_size: gridSize,
          metric,
          ssid: filters.ssid || undefined,
          bssid: filters.bssid || undefined,
          band: filters.band || undefined,
        }),
      )
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [planId, gridSize, metric, filters])

  useEffect(() => {
    void loadCoverage()
  }, [loadCoverage])

  // Stop any walk in progress if the page goes away mid-survey.
  useEffect(() => () => stopWalkTimer(), [])

  function stopWalkTimer() {
    if (walkTimer.current !== null) {
      window.clearInterval(walkTimer.current)
      walkTimer.current = null
    }
  }

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
      setFilters({ ssid: '', bssid: '', band: '' })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const beginWalk = (x: number, y: number) => {
    walkSamples.current = []
    walkT0.current = Date.now()
    setWalkStart({ x, y })
    setWalkCount(0)
    setError(null)

    const tick = async () => {
      try {
        const reading = await api.get<WalkReading>('/api/heatmap/measure')
        walkSamples.current.push({ elapsed_ms: Date.now() - walkT0.current, reading })
        setWalkCount(walkSamples.current.length)
      } catch {
        // A dropped reading mid-walk is not worth aborting the run for; the
        // remaining samples still describe the route.
      }
    }
    void tick()
    walkTimer.current = window.setInterval(() => void tick(), WALK_INTERVAL_MS)
  }

  const finishWalk = async (x: number, y: number) => {
    stopWalkTimer()
    const start = walkStart
    const collected = walkSamples.current
    setWalkStart(null)
    setWalkCount(0)
    walkSamples.current = []

    if (!start || planId === null) return
    if (collected.length === 0) {
      setError('No readings were captured during that walk')
      return
    }

    setBusy(true)
    try {
      await api.post(`/api/heatmap/plans/${planId}/walk`, {
        start_x: start.x,
        start_y: start.y,
        end_x: x,
        end_y: y,
        label_prefix: pointLabel || null,
        samples: collected.map(({ elapsed_ms, reading }) => ({
          elapsed_ms,
          ssid: reading.ssid,
          bssid: reading.bssid,
          channel: reading.channel,
          band: reading.band,
          rssi: reading.rssi,
          ping_ms: reading.ping_ms,
          packet_loss_pct: reading.packet_loss_pct,
        })),
      })
      await loadCoverage()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const cancelWalk = () => {
    stopWalkTimer()
    walkSamples.current = []
    setWalkStart(null)
    setWalkCount(0)
  }

  const pick = async (x: number, y: number) => {
    if (planId === null || mode === 'view') return

    if (mode === 'walk') {
      if (walkStart === null) beginWalk(x, y)
      else await finishWalk(x, y)
      return
    }

    setBusy(true)
    setError(null)
    try {
      if (mode === 'measure') {
        await api.post(`/api/heatmap/plans/${planId}/points`, {
          x,
          y,
          label: pointLabel || null,
          measure: true,
          scan: scanOnCapture,
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

  const markers = useMemo(
    () => (walkStart ? [{ ...walkStart, label: 'Walk start' }] : []),
    [walkStart],
  )

  if (loading) return <Spinner label="Loading floor plans…" />

  const available = coverage?.available_filters
  const isRedundancy = metric === 'redundancy'

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold tracking-tight">Heatmap</h1>
        <p className="text-sm text-slate-400">
          Upload a plan, walk the floor and capture readings along the route
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
                onChange={(e) => {
                  setPlanId(e.target.value ? Number(e.target.value) : null)
                  setFilters({ ssid: '', bssid: '', band: '' })
                  cancelWalk()
                }}
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
          {walkStart && (
            <Banner kind="info">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span>
                  Walking — <strong>{walkCount}</strong> reading{walkCount === 1 ? '' : 's'}{' '}
                  captured. Click the plan where you finish.
                </span>
                <button className="btn px-2 py-1 text-xs" onClick={cancelWalk}>
                  Cancel walk
                </button>
              </div>
            </Banner>
          )}

          <Card
            title="Capture"
            action={
              <div className="flex gap-1 rounded-lg border border-slate-700 p-0.5 text-xs">
                {(
                  [
                    ['measure', 'Point'],
                    ['walk', 'Walk'],
                    ['ap', 'Place AP'],
                    ['view', 'View only'],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => {
                      cancelWalk()
                      setMode(value)
                    }}
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
              {(mode === 'measure' || mode === 'walk') && (
                <Field label={mode === 'walk' ? 'Route name' : 'Point label (optional)'}>
                  <input
                    className="input"
                    value={pointLabel}
                    placeholder={mode === 'walk' ? 'Aisle 3' : 'By the press'}
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

            {mode === 'measure' && (
              <label className="mt-3 flex items-center gap-2 text-sm text-slate-400">
                <input
                  type="checkbox"
                  checked={scanOnCapture}
                  onChange={(e) => setScanOnCapture(e.target.checked)}
                  className="accent-sky-500"
                />
                Scan for other APs at each point
                <span className="text-xs text-slate-600">
                  — slower, but required for the redundancy map
                </span>
              </label>
            )}

            <p className="mt-3 text-xs text-slate-500">
              {mode === 'view'
                ? 'Viewing only — clicks are ignored.'
                : mode === 'walk'
                  ? 'Click where you start, walk the aisle at a steady pace, then click where you finish. Readings are spread along the line by when they were taken, so keep the route straight and the pace even.'
                  : mode === 'measure'
                    ? 'Stand at the location, then click the matching spot on the plan. The reading is taken live.'
                    : 'Click where the access point physically sits.'}
              {busy && ' · working…'}
            </p>
          </Card>

          <Card
            title={coverage.plan.name}
            action={
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex gap-1 rounded-lg border border-slate-700 p-0.5 text-xs">
                  {(
                    [
                      ['rssi', 'Coverage'],
                      ['redundancy', 'Redundancy'],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      onClick={() => setMetric(value)}
                      className={`rounded px-2 py-1 transition ${
                        metric === value
                          ? 'bg-sky-600 text-white'
                          : 'text-slate-400 hover:bg-slate-800'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {coverage.grid && (
                  <span className="text-xs text-slate-500">
                    {coverage.grid.covered_pct}% within measurement range
                  </span>
                )}
              </div>
            }
          >
            {available && (available.bssids.length > 1 || available.bands.length > 1) && (
              <div className="mb-3 grid gap-3 sm:grid-cols-3">
                <FilterSelect
                  label="SSID"
                  value={filters.ssid}
                  options={available.ssids}
                  onChange={(v) => setFilters({ ...filters, ssid: v })}
                />
                <FilterSelect
                  label="Access point"
                  value={filters.bssid}
                  options={available.bssids}
                  onChange={(v) => setFilters({ ...filters, bssid: v })}
                  hint="Shows where one AP actually reaches"
                />
                <FilterSelect
                  label="Band"
                  value={filters.band}
                  options={available.bands}
                  onChange={(v) => setFilters({ ...filters, band: v })}
                  hint="2.4 and 5 GHz cover very differently"
                />
              </div>
            )}

            <HeatmapCanvas
              data={coverage}
              imageUrl={`/api/heatmap/plans/${planId}/image`}
              opacity={opacity}
              markers={markers}
              onPick={mode === 'view' ? undefined : pick}
            />

            <div className="mt-3 flex flex-wrap items-center gap-4">
              {isRedundancy
                ? REDUNDANCY_LEGEND.map((entry) => (
                    <span
                      key={entry.label}
                      className="flex items-center gap-1.5 text-xs text-slate-400"
                    >
                      <span
                        className="h-3 w-3 rounded"
                        style={{ backgroundColor: entry.color }}
                      />
                      {entry.label}
                      {entry.hint && <span className="text-slate-600">{entry.hint}</span>}
                    </span>
                  ))
                : GRADE_RANGES.map(({ grade, label }) => (
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

            {isRedundancy && (
              <p className="mt-3 text-xs text-slate-500">
                How many <em>other</em> access points are usable from each spot (at least{' '}
                {coverage.redundancy_min_rssi ?? -70} dBm). Coverage answers whether there is
                signal; this answers whether there is anywhere to roam to. A red area is where a
                moving client drops rather than hands over — even if its signal reads green.
              </p>
            )}

            {coverage.message && <p className="mt-3 text-sm text-slate-500">{coverage.message}</p>}
          </Card>

          {isRedundancy ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryStat label="Scanned points" value={String(coverage.scanned_points ?? 0)} />
              <SummaryStat
                label="Blind spots"
                value={String(coverage.summary.blind_spots ?? 0)}
                tone={coverage.summary.blind_spots ? 'bad' : 'good'}
              />
              <SummaryStat
                label="Average alternatives"
                value={coverage.summary.avg?.toFixed(2) ?? '—'}
              />
              <SummaryStat label="Best" value={String(coverage.summary.max ?? '—')} />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryStat label="Survey points" value={String(coverage.summary.total_points)} />
              <SummaryStat label="Average RSSI" value={dbm(coverage.summary.rssi_avg)} />
              <SummaryStat label="Weakest point" value={dbm(coverage.summary.rssi_min)} />
              <SummaryStat label="Strongest point" value={dbm(coverage.summary.rssi_max)} />
            </div>
          )}

          <Card title={isRedundancy ? 'Roaming readiness' : 'Coverage breakdown'}>
            <div className="space-y-2">
              {breakdownRows(metric).map(({ label, bucket, color }) => {
                const percent = coverage.summary.percent[bucket] ?? 0
                const count = coverage.summary.counts[bucket] ?? 0
                return (
                  <div key={bucket} className="flex items-center gap-3">
                    <span className="w-36 text-xs text-slate-400">{label}</span>
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${percent}%`, backgroundColor: color }}
                      />
                    </div>
                    <span className="w-24 text-right text-xs tabular text-slate-400">
                      {count} pts · {percent}%
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
                    <th>Alt APs</th>
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
                      <td className="tabular">
                        {point.neighbors === null ? (
                          <span className="text-slate-600" title="Captured without a scan">
                            not scanned
                          </span>
                        ) : (
                          usableCount(point.neighbors, coverage.redundancy_min_rssi ?? -70)
                        )}
                      </td>
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
                      <td colSpan={11} className="py-8 text-center text-slate-500">
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

/** The backend keys `counts`/`percent` by grade name for coverage and by
 *  redundancy bucket label for redundancy, so the mapping is explicit. */
function breakdownRows(
  metric: HeatmapMetric,
): { label: string; bucket: string; color: string }[] {
  if (metric === 'redundancy') {
    return REDUNDANCY_LEGEND.map((entry) => ({
      label: entry.label,
      bucket: entry.label,
      color: entry.color,
    }))
  }
  return (Object.keys(GRADE_LABEL) as Grade[])
    .filter((grade) => grade !== 'UNKNOWN')
    .map((grade) => ({
      label: GRADE_LABEL[grade],
      bucket: grade,
      color: GRADE_COLOR[grade],
    }))
}


function usableCount(
  neighbors: { bssid: string | null; rssi: number | null }[],
  minRssi: number,
): number {
  const seen = new Set<string>()
  for (const n of neighbors) {
    if (n.bssid && n.rssi !== null && n.rssi >= minRssi) seen.add(n.bssid)
  }
  return seen.size
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  hint,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
  hint?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </Field>
  )
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'good' | 'bad'
}) {
  const color = tone === 'bad' ? '#ef4444' : tone === 'good' ? '#16a34a' : undefined
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  )
}
