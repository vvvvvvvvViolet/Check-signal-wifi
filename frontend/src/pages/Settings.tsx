import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppSettings, SettingsResponse } from '../api/types'
import { Banner, Card, Field, Spinner } from '../components/ui'
import { GRADE_COLOR, GRADE_LABEL, GRADE_RANGES } from '../lib/format'

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [backend, setBackend] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const response = await api.get<SettingsResponse>('/api/settings')
      setSettings(response.settings)
      setBackend(response.wifi_backend)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const save = async () => {
    if (!settings) return
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const response = await api.put<SettingsResponse>('/api/settings', settings)
      setSettings(response.settings)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    if (!window.confirm('Restore every setting to its default?')) return
    setBusy(true)
    try {
      const response = await api.post<SettingsResponse>('/api/settings/reset')
      setSettings(response.settings)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!settings) return error ? <Banner kind="error">{error}</Banner> : <Spinner />

  const patch = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    setSettings({ ...settings, [key]: value })

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Settings</h1>
          <p className="text-sm text-slate-400">
            Thresholds decide when the app warns; the grading scale decides what the colours mean
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={() => void reset()} disabled={busy}>
            Restore defaults
          </button>
          <button className="btn btn-primary" onClick={() => void save()} disabled={busy}>
            {busy ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </header>

      {error && <Banner kind="error">{error}</Banner>}
      {saved && <Banner kind="success">Settings saved.</Banner>}
      {backend === 'mock' && (
        <Banner kind="warning">
          Running against the simulated Wi-Fi backend — readings are generated, not measured.
          Set <code className="font-mono">CSW_WIFI_BACKEND</code> or install the platform Wi-Fi
          tooling for live data.
        </Banner>
      )}

      <Card title="Site">
        <Field label="Site name" hint="Appears on every exported report">
          <input
            className="input"
            value={settings.site_name}
            onChange={(e) => patch('site_name', e.target.value)}
          />
        </Field>
      </Card>

      <Card title="Alert thresholds">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <NumberField
            label="Signal warning (dBm)"
            value={settings.thresholds.rssi_warning}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, rssi_warning: v })
            }
            hint="Warn at or below this level"
          />
          <NumberField
            label="Signal critical (dBm)"
            value={settings.thresholds.rssi_critical}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, rssi_critical: v })
            }
          />
          <NumberField
            label="Ping warning (ms)"
            value={settings.thresholds.ping_warning_ms}
            step={1}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, ping_warning_ms: v })
            }
          />
          <NumberField
            label="Ping critical (ms)"
            value={settings.thresholds.ping_critical_ms}
            step={1}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, ping_critical_ms: v })
            }
          />
          <NumberField
            label="Packet loss warning (%)"
            value={settings.thresholds.loss_warning_pct}
            step={0.5}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, loss_warning_pct: v })
            }
          />
          <NumberField
            label="Packet loss critical (%)"
            value={settings.thresholds.loss_critical_pct}
            step={0.5}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, loss_critical_pct: v })
            }
          />
          <NumberField
            label="Jitter warning (ms)"
            value={settings.thresholds.jitter_warning_ms}
            step={1}
            onChange={(v) =>
              patch('thresholds', { ...settings.thresholds, jitter_warning_ms: v })
            }
          />
        </div>
      </Card>

      <Card title="Signal grading scale">
        <p className="mb-3 text-xs text-slate-500">
          These cut-offs decide the gauge and heatmap colours. They are independent of the alert
          thresholds above — a signal can be graded Fair without being worth a warning.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <NumberField
            label="Excellent at or above (dBm)"
            value={settings.bands.excellent}
            onChange={(v) => patch('bands', { ...settings.bands, excellent: v })}
          />
          <NumberField
            label="Good at or above (dBm)"
            value={settings.bands.good}
            onChange={(v) => patch('bands', { ...settings.bands, good: v })}
          />
          <NumberField
            label="Fair at or above (dBm)"
            value={settings.bands.fair}
            onChange={(v) => patch('bands', { ...settings.bands, fair: v })}
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-4">
          {GRADE_RANGES.map(({ grade, label }) => (
            <span key={grade} className="flex items-center gap-2 text-xs text-slate-400">
              <span className="h-3 w-3 rounded" style={{ backgroundColor: GRADE_COLOR[grade] }} />
              {GRADE_LABEL[grade]}
              <span className="text-slate-600">default {label}</span>
            </span>
          ))}
        </div>
      </Card>

      <Card title="Ping targets">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Gateway" hint="Use 'auto' to detect the default gateway at probe time">
            <input
              className="input"
              value={settings.ping.gateway}
              onChange={(e) => patch('ping', { ...settings.ping, gateway: e.target.value })}
            />
          </Field>
          <Field label="Server">
            <input
              className="input"
              value={settings.ping.server}
              onChange={(e) => patch('ping', { ...settings.ping, server: e.target.value })}
            />
          </Field>
          <Field label="DNS server">
            <input
              className="input"
              value={settings.ping.dns}
              onChange={(e) => patch('ping', { ...settings.ping, dns: e.target.value })}
            />
          </Field>
          <Field label="DNS test hostname" hint="Resolved to time real lookups">
            <input
              className="input"
              value={settings.ping.dns_hostname}
              onChange={(e) => patch('ping', { ...settings.ping, dns_hostname: e.target.value })}
            />
          </Field>
        </div>
      </Card>

      <Card title="Monitoring">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <NumberField
            label="Sample interval (s)"
            value={settings.monitor.interval_sec}
            step={0.5}
            onChange={(v) => patch('monitor', { ...settings.monitor, interval_sec: v })}
          />
          <NumberField
            label="Pings per sample"
            value={settings.monitor.ping_count}
            step={1}
            onChange={(v) => patch('monitor', { ...settings.monitor, ping_count: v })}
          />
          <NumberField
            label="Ping timeout (s)"
            value={settings.monitor.ping_timeout_sec}
            step={0.5}
            onChange={(v) => patch('monitor', { ...settings.monitor, ping_timeout_sec: v })}
          />
          <NumberField
            label="Retention (days)"
            value={settings.monitor.retention_days}
            step={1}
            onChange={(v) => patch('monitor', { ...settings.monitor, retention_days: v })}
          />
        </div>
      </Card>
    </div>
  )
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
  hint,
}: {
  label: string
  value: number
  onChange: (value: number) => void
  step?: number
  hint?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        className="input tabular"
        type="number"
        step={step}
        value={value}
        onChange={(e) => {
          const parsed = Number(e.target.value)
          if (!Number.isNaN(parsed)) onChange(parsed)
        }}
      />
    </Field>
  )
}
