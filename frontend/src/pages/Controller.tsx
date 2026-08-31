import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AppSettings,
  ControllerAp,
  ControllerClient,
  ControllerRawResult,
  ControllerSelfCheck,
  ControllerStatus,
  SettingsResponse,
} from '../api/types'
import { Banner, Card, Empty, Field, Spinner } from '../components/ui'
import { dbm, duration, text } from '../lib/format'

/** Cisco AireOS's own two-state vocabulary for AP and radio status. */
function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-500">—</span>
  const ok = status === 'up'
  return (
    <span
      className="rounded px-2 py-0.5 text-xs font-semibold"
      style={{
        backgroundColor: ok ? '#16a34a22' : '#ef444422',
        color: ok ? '#4ade80' : '#f87171',
      }}
    >
      {status}
    </span>
  )
}

export function ControllerPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [status, setStatus] = useState<ControllerStatus | null>(null)
  const [aps, setAps] = useState<ControllerAp[] | null>(null)
  const [clients, setClients] = useState<ControllerClient[] | null>(null)
  const [selfCheck, setSelfCheck] = useState<ControllerSelfCheck | null>(null)
  const [loadingData, setLoadingData] = useState(false)
  const [dataError, setDataError] = useState<string | null>(null)

  const [rawOid, setRawOid] = useState('1.3.6.1.4.1.14179.2.2.1.1')
  const [rawResult, setRawResult] = useState<ControllerRawResult | null>(null)
  const [rawError, setRawError] = useState<string | null>(null)
  const [rawLoading, setRawLoading] = useState(false)

  const loadSettings = useCallback(async () => {
    try {
      const response = await api.get<SettingsResponse>('/api/settings')
      setSettings(response.settings)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  const enabled = settings?.controller.enabled && settings.controller.host

  const loadData = useCallback(async () => {
    if (!enabled) return
    setLoadingData(true)
    setDataError(null)
    try {
      const [statusRes, apsRes, clientsRes, selfCheckRes] = await Promise.all([
        api.get<ControllerStatus>('/api/controller/status'),
        api.get<{ access_points: ControllerAp[] }>('/api/controller/aps'),
        api.get<{ clients: ControllerClient[] }>('/api/controller/clients'),
        api.get<ControllerSelfCheck>('/api/controller/self-check'),
      ])
      setStatus(statusRes)
      setAps(apsRes.access_points)
      setClients(clientsRes.clients)
      setSelfCheck(selfCheckRes)
    } catch (err) {
      setDataError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setLoadingData(false)
    }
  }, [enabled])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const save = async () => {
    if (!settings) return
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const response = await api.put<SettingsResponse>('/api/settings', settings)
      setSettings(response.settings)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2500)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const runRawWalk = async () => {
    setRawLoading(true)
    setRawError(null)
    try {
      setRawResult(await api.get<ControllerRawResult>('/api/controller/raw', { oid: rawOid }))
    } catch (err) {
      setRawError(err instanceof ApiError ? err.message : String(err))
      setRawResult(null)
    } finally {
      setRawLoading(false)
    }
  }

  if (!settings) return error ? <Banner kind="error">{error}</Banner> : <Spinner />

  const patchController = (patch: Partial<AppSettings['controller']>) =>
    setSettings({ ...settings, controller: { ...settings.controller, ...patch } })

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold tracking-tight">WLAN Controller</h1>
        <p className="text-sm text-slate-400">
          Cross-check the client's view of the network against what the Cisco WLC itself reports
        </p>
      </header>

      {error && <Banner kind="error">{error}</Banner>}
      {saved && <Banner kind="success">Settings saved.</Banner>}

      <Banner kind="info">
        This talks to enterprise infrastructure over SNMP, not just this machine's own radio — off
        by default. The community string is stored in this app's local settings; SNMPv2c sends it
        in cleartext on the wire, so this is only as safe as the network between here and the WLC.
      </Banner>

      <Card title="Connection">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex items-center gap-2 text-sm text-slate-300 sm:col-span-2 lg:col-span-4">
            <input
              type="checkbox"
              checked={settings.controller.enabled}
              onChange={(e) => patchController({ enabled: e.target.checked })}
              className="accent-sky-500"
            />
            Enable controller monitoring
          </label>
          <Field label="Host / IP">
            <input
              className="input"
              value={settings.controller.host}
              placeholder="10.0.0.1"
              onChange={(e) => patchController({ host: e.target.value })}
            />
          </Field>
          <Field label="Port">
            <input
              className="input tabular"
              type="number"
              value={settings.controller.port}
              onChange={(e) => patchController({ port: Number(e.target.value) })}
            />
          </Field>
          <Field label="SNMP version">
            <select
              className="input"
              value={settings.controller.version}
              onChange={(e) =>
                patchController({ version: e.target.value as 'v2c' | 'v3' })
              }
            >
              <option value="v2c">v2c</option>
              <option value="v3">v3</option>
            </select>
          </Field>
          <Field label="Timeout (s)">
            <input
              className="input tabular"
              type="number"
              step={0.5}
              value={settings.controller.timeout_sec}
              onChange={(e) => patchController({ timeout_sec: Number(e.target.value) })}
            />
          </Field>

          {settings.controller.version === 'v2c' ? (
            <Field label="Community string" hint="Travels in cleartext on the wire">
              <input
                className="input"
                type="password"
                value={settings.controller.community}
                onChange={(e) => patchController({ community: e.target.value })}
              />
            </Field>
          ) : (
            <>
              <Field label="v3 username">
                <input
                  className="input"
                  value={settings.controller.v3_user}
                  onChange={(e) => patchController({ v3_user: e.target.value })}
                />
              </Field>
              <Field label="v3 auth password">
                <input
                  className="input"
                  type="password"
                  value={settings.controller.v3_auth_password}
                  onChange={(e) => patchController({ v3_auth_password: e.target.value })}
                />
              </Field>
              <Field label="v3 privacy password">
                <input
                  className="input"
                  type="password"
                  value={settings.controller.v3_priv_password}
                  onChange={(e) => patchController({ v3_priv_password: e.target.value })}
                />
              </Field>
            </>
          )}
        </div>

        <div className="mt-4 flex gap-2">
          <button className="btn btn-primary" onClick={() => void save()} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          {enabled && (
            <button className="btn" onClick={() => void loadData()} disabled={loadingData}>
              ⟳ Refresh
            </button>
          )}
        </div>
      </Card>

      {!enabled ? (
        <Empty>
          Enter the WLC's management IP and community string above, enable monitoring, and save to
          see AP health, connected clients, and the self-check.
        </Empty>
      ) : (
        <>
          {dataError && <Banner kind="error">{dataError}</Banner>}

          <Card title="WLC status">
            {loadingData && !status ? (
              <Spinner />
            ) : status ? (
              status.reachable ? (
                <dl className="grid gap-3 sm:grid-cols-3 text-sm">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-500">System</dt>
                    <dd className="mt-0.5">{text(status.sys_name)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-500">Uptime</dt>
                    <dd className="mt-0.5 tabular">{duration((status.uptime_sec ?? 0) * 1000)}</dd>
                  </div>
                  <div className="sm:col-span-3">
                    <dt className="text-xs uppercase tracking-wide text-slate-500">Description</dt>
                    <dd className="mt-0.5 font-mono text-xs text-slate-400">
                      {text(status.sys_descr)}
                    </dd>
                  </div>
                </dl>
              ) : (
                <Banner kind="error">{status.error || 'Unreachable'}</Banner>
              )
            ) : null}
          </Card>

          {selfCheck && (
            <div
              className="rounded-xl border p-4"
              style={{
                borderColor:
                  selfCheck.agrees === false
                    ? '#ef444455'
                    : selfCheck.agrees === true
                      ? '#16a34a55'
                      : '#64748b55',
                backgroundColor:
                  selfCheck.agrees === false
                    ? '#ef444412'
                    : selfCheck.agrees === true
                      ? '#16a34a12'
                      : '#64748b12',
              }}
            >
              <div className="text-sm font-semibold">
                {selfCheck.agrees === true && '✓ Controller agrees with the client'}
                {selfCheck.agrees === false && '⚠ Controller disagrees with the client'}
                {selfCheck.agrees === null && '— Self-check not available'}
              </div>
              <p className="mt-1 text-sm text-slate-400">{selfCheck.reason}</p>
              {selfCheck.client_bssid && (
                <p className="mt-2 font-mono text-xs text-slate-500">
                  client: {selfCheck.client_bssid}
                  {selfCheck.controller_ap_mac && ` · controller: ${selfCheck.controller_ap_mac}`}
                </p>
              )}
            </div>
          )}

          <Card title={`Access points${aps ? ` — ${aps.length}` : ''}`}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>IP</th>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Radios</th>
                  </tr>
                </thead>
                <tbody>
                  {(aps ?? []).map((ap) => (
                    <tr key={ap.index}>
                      <td className="font-medium">{text(ap.name)}</td>
                      <td className="font-mono text-xs text-slate-400">{text(ap.ip_address)}</td>
                      <td className="text-slate-400">{text(ap.model)}</td>
                      <td>
                        <StatusPill status={ap.operation_status} />
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-2">
                          {ap.radios.map((radio) => (
                            <span
                              key={radio.radio_index}
                              className="rounded border border-slate-700 px-2 py-0.5 text-xs tabular"
                              title={`${radio.client_count ?? '—'} clients, ${radio.channel_utilization_pct ?? '—'}% utilisation`}
                            >
                              ch {text(radio.channel)} · {text(radio.client_count)} clients
                            </span>
                          ))}
                          {ap.radios.length === 0 && (
                            <span className="text-xs text-slate-600">no radio data</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {aps && aps.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-slate-500">
                        No access points returned. If this WLC genuinely has APs, use the raw walk
                        below to check the table layout.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title={`Connected clients${clients ? ` — ${clients.length}` : ''}`}>
            <div className="table-wrap max-h-96 overflow-y-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>MAC</th>
                    <th>AP</th>
                    <th>SSID</th>
                    <th>RSSI</th>
                    <th>SNR</th>
                  </tr>
                </thead>
                <tbody>
                  {(clients ?? []).map((row) => (
                    <tr key={row.mac_address}>
                      <td className="font-mono text-xs">{row.mac_address}</td>
                      <td className="font-mono text-xs text-slate-400">{text(row.ap_mac)}</td>
                      <td>{text(row.ssid)}</td>
                      <td className="tabular">{dbm(row.rssi)}</td>
                      <td className="tabular">{text(row.snr)}</td>
                    </tr>
                  ))}
                  {clients && clients.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-slate-500">
                        No clients returned.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <Card
            title="Raw OID walk"
            action={<span className="text-xs text-slate-500">verification tool</span>}
          >
            <p className="mb-3 text-xs text-slate-500">
              The AP/client table column numbers above come from Cisco's published
              AIRESPACE-WIRELESS-MIB, not from a live WLC 3504 this app has been tested against.
              Point this at a table root and compare the columns to your WLC's CLI or web UI if
              something above looks wrong.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[20rem] flex-1">
                <Field label="OID subtree">
                  <input
                    className="input font-mono text-xs"
                    value={rawOid}
                    onChange={(e) => setRawOid(e.target.value)}
                  />
                </Field>
              </div>
              <button className="btn" onClick={() => void runRawWalk()} disabled={rawLoading}>
                {rawLoading ? 'Walking…' : 'Walk'}
              </button>
            </div>
            {rawError && (
              <div className="mt-3">
                <Banner kind="error">{rawError}</Banner>
              </div>
            )}
            {rawResult && (
              <div className="table-wrap mt-3 max-h-72 overflow-y-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>OID</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rawResult.rows.map((row) => (
                      <tr key={row.oid}>
                        <td className="font-mono text-xs">{row.oid}</td>
                        <td className="font-mono text-xs text-slate-300">{String(row.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
