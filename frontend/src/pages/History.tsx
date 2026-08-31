import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HistoryFacets, HistoryPage as Page, TestRecord } from '../api/types'
import { Banner, Card, Field, GradePill, Spinner, VerdictPill } from '../components/ui'
import { dbm, ms, pct, shortDate, text } from '../lib/format'

interface Filters {
  date_from: string
  date_to: string
  area: string
  ssid: string
  bssid: string
  device: string
  result: string
}

const EMPTY: Filters = {
  date_from: '',
  date_to: '',
  area: '',
  ssid: '',
  bssid: '',
  device: '',
  result: '',
}

const PAGE_SIZE = 50

export function HistoryPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY)
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [facets, setFacets] = useState<HistoryFacets | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [captureArea, setCaptureArea] = useState('')
  const [captureDevice, setCaptureDevice] = useState('')

  const load = useCallback(async () => {
    try {
      const [rows, facetRows] = await Promise.all([
        api.get<Page>('/api/history', { ...filters, limit: PAGE_SIZE, offset }),
        api.get<HistoryFacets>('/api/history/facets'),
      ])
      setPage(rows)
      setFacets(facetRows)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [filters, offset])

  useEffect(() => {
    void load()
  }, [load])

  const update = (patch: Partial<Filters>) => {
    setOffset(0) // a new filter means a new result set; page 2 of the old one is meaningless
    setFilters((prev) => ({ ...prev, ...patch }))
  }

  const capture = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.post('/api/history', {
        area: captureArea || null,
        device: captureDevice || null,
        measure: true,
      })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (record: TestRecord) => {
    await api.delete(`/api/history/${record.id}`)
    await load()
  }

  const exportUrl = (format: string) =>
    api.downloadUrl('/api/report/history', { ...filters, format })

  const total = page?.total ?? 0
  const showing = page?.items.length ?? 0

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold tracking-tight">Test History</h1>
        <p className="text-sm text-slate-400">Saved spot-checks, filterable and exportable</p>
      </header>

      {error && <Banner kind="error">{error}</Banner>}

      <Card title="Capture a spot-check">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[12rem] flex-1">
            <Field label="Area">
              <input
                className="input"
                value={captureArea}
                placeholder="Line-A"
                onChange={(e) => setCaptureArea(e.target.value)}
              />
            </Field>
          </div>
          <div className="min-w-[12rem] flex-1">
            <Field label="Device">
              <input
                className="input"
                value={captureDevice}
                placeholder="Scanner-01"
                onChange={(e) => setCaptureDevice(e.target.value)}
              />
            </Field>
          </div>
          <button className="btn btn-primary" onClick={() => void capture()} disabled={busy}>
            {busy ? 'Measuring…' : '＋ Measure and save'}
          </button>
        </div>
      </Card>

      <Card
        title="Filters"
        action={
          <button className="text-xs text-slate-400 hover:text-slate-200" onClick={() => update(EMPTY)}>
            Clear all
          </button>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="From">
            <input
              className="input"
              type="date"
              value={filters.date_from}
              onChange={(e) => update({ date_from: e.target.value })}
            />
          </Field>
          <Field label="To">
            <input
              className="input"
              type="date"
              value={filters.date_to}
              onChange={(e) => update({ date_to: e.target.value })}
            />
          </Field>
          <Select
            label="Area"
            value={filters.area}
            options={facets?.areas ?? []}
            onChange={(v) => update({ area: v })}
          />
          <Select
            label="SSID"
            value={filters.ssid}
            options={facets?.ssids ?? []}
            onChange={(v) => update({ ssid: v })}
          />
          <Select
            label="Access point"
            value={filters.bssid}
            options={facets?.bssids ?? []}
            onChange={(v) => update({ bssid: v })}
          />
          <Select
            label="Device"
            value={filters.device}
            options={facets?.devices ?? []}
            onChange={(v) => update({ device: v })}
          />
          <Select
            label="Result"
            value={filters.result}
            options={facets?.results ?? []}
            onChange={(v) => update({ result: v })}
          />
        </div>
      </Card>

      <Card
        title={`Records — ${showing} of ${total}`}
        action={
          <div className="flex gap-2">
            {(['csv', 'xlsx', 'pdf'] as const).map((format) => (
              <a key={format} className="btn px-2 py-1 text-xs" href={exportUrl(format)}>
                {format.toUpperCase()}
              </a>
            ))}
          </div>
        }
      >
        {loading ? (
          <Spinner />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Area</th>
                    <th>Device</th>
                    <th>SSID</th>
                    <th>BSSID</th>
                    <th>RSSI</th>
                    <th>Ping</th>
                    <th>Loss</th>
                    <th>Quality</th>
                    <th>Result</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {page?.items.map((record) => (
                    <tr key={record.id}>
                      <td className="text-slate-400">{shortDate(record.ts)}</td>
                      <td className="font-medium">{text(record.area)}</td>
                      <td className="text-slate-400">{text(record.device)}</td>
                      <td>{text(record.ssid)}</td>
                      <td className="font-mono text-xs text-slate-400">{text(record.bssid)}</td>
                      <td className="tabular">{dbm(record.rssi)}</td>
                      <td className="tabular">{ms(record.ping_ms)}</td>
                      <td className="tabular">{pct(record.packet_loss_pct)}</td>
                      <td>
                        <GradePill grade={record.grade} />
                      </td>
                      <td>
                        <VerdictPill verdict={record.result} />
                      </td>
                      <td>
                        <button
                          className="text-xs text-slate-500 hover:text-red-400"
                          onClick={() => void remove(record)}
                        >
                          delete
                        </button>
                      </td>
                    </tr>
                  ))}
                  {showing === 0 && (
                    <tr>
                      <td colSpan={11} className="py-10 text-center text-slate-500">
                        No records match these filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {total > PAGE_SIZE && (
              <div className="mt-3 flex items-center justify-between text-sm">
                <button
                  className="btn px-3 py-1"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  ← Previous
                </button>
                <span className="text-slate-500 tabular">
                  {offset + 1}–{offset + showing} of {total}
                </span>
                <button
                  className="btn px-3 py-1"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Next →
                </button>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  )
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  return (
    <Field label={label}>
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
