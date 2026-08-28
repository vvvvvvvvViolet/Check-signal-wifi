// Mirrors the backend response shapes. Kept hand-written rather than generated
// so the UI only declares the fields it actually reads.

export type Grade = 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR' | 'UNKNOWN'
export type Verdict = 'PASS' | 'WARNING' | 'FAIL'
export type MetricStatus = 'ok' | 'warning' | 'critical' | 'unknown'

export interface WifiLink {
  connected: boolean
  interface: string | null
  ssid: string | null
  bssid: string | null
  rssi: number | null
  quality_pct: number | null
  noise_dbm: number | null
  channel: number | null
  band: string | null
  frequency_mhz: number | null
  tx_rate_mbps: number | null
  rx_rate_mbps: number | null
  security: string | null
  ip_address: string | null
  backend: string
  warnings: string[]
}

export interface PingResult {
  target: string
  reachable: boolean
  available: boolean
  sent: number
  received: number
  packet_loss_pct: number | null
  rtt_min_ms: number | null
  rtt_avg_ms: number | null
  rtt_max_ms: number | null
  jitter_ms: number | null
  error: string | null
}

export interface Assessment {
  ping_ms: number | null
  packet_loss_pct: number | null
  jitter_ms: number | null
  grade: Grade
  grade_color: string
  signal_percent: number
  verdict: Verdict
  incomplete: boolean
  metrics: Record<string, { value: number | null; status: MetricStatus; label: string }>
}

export interface Snapshot {
  ts: string
  link: WifiLink
  gateway: { address: string | null; auto_detected: boolean }
  ping: Record<string, PingResult>
  summary: Assessment
}

export interface Dashboard extends Snapshot {
  status_text: string
  diagnosis: { severity: string; headline: string }
  internet_ok: boolean
  gateway_ok: boolean
  trend: { ts: string; rssi: number | null; ping_ms: number | null }[]
  monitor: MonitorStatus
  thresholds: Thresholds
  bands: SignalBands
}

export interface MonitorStatus {
  running: boolean
  session_id: number | null
  buffered_samples: number
  subscribers: number
  last_error: string | null
  last_sample_at: string | null
}

export interface MonitorSession {
  id: number
  name: string
  area: string | null
  device: string | null
  note: string | null
  started_at: string
  ended_at: string | null
  interval_sec: number
}

export interface Sample {
  id: number
  session_id: number | null
  ts: string
  ssid: string | null
  bssid: string | null
  channel: number | null
  band: string | null
  rssi: number | null
  quality_pct: number | null
  tx_rate_mbps: number | null
  ping_gateway_ms: number | null
  ping_server_ms: number | null
  ping_dns_ms: number | null
  jitter_ms: number | null
  packet_loss_pct: number | null
  grade: Grade | null
  verdict: Verdict | null
}

export interface RoamEvent {
  id?: number
  ts: string
  ssid: string | null
  from_bssid: string | null
  to_bssid: string | null
  from_rssi: number | null
  to_rssi: number | null
  from_channel: number | null
  to_channel: number | null
  gap_ms: number | null
  kind?: string
  rssi_delta?: number | null
}

export interface ScanNetwork {
  ssid: string | null
  bssid: string | null
  rssi: number | null
  channel: number | null
  band: string | null
  frequency_mhz: number | null
  security: string | null
  quality_pct: number | null
  grade: Grade
  grade_color: string
}

export interface ScanResult {
  backend: string
  count: number
  networks: ScanNetwork[]
  ssid_groups: {
    ssid: string
    bssid_count: number
    best_rssi: number | null
    channels: number[]
    bands: string[]
  }[]
  channel_usage: { channel: number; count: number; band: string | null }[]
  band_usage: { band: string; count: number }[]
}

export interface ChainStep {
  key: string
  label: string
  ok: boolean
  detail: string
  latency_ms: number | null
  state: 'ok' | 'failed' | 'blocked'
}

export interface ConnectivityChain {
  steps: ChainStep[]
  broken_at: string | null
  healthy: boolean
  ping: Record<string, PingResult>
  dns: { hostname: string; ok: boolean; elapsed_ms: number; addresses: string[]; error: string | null }
  internet: { host: string; port: number; ok: boolean; elapsed_ms: number; error: string | null }
  gateway_auto_detected: boolean
}

export interface Finding {
  code: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  summary: string
  causes: string[]
  recommendations: string[]
  evidence: Record<string, unknown>
}

export interface DiagnosisReport {
  severity: 'info' | 'warning' | 'critical'
  headline: string
  measurements: { rssi_dbm: number | null; ping_ms: number | null; packet_loss_pct: number | null }
  findings: Finding[]
  ts?: string
  link?: WifiLink
  summary?: Assessment
}

export interface FloorPlan {
  id: number
  name: string
  location: string | null
  image_filename: string
  width_px: number
  height_px: number
  meters_per_px: number | null
  created_at: string
}

export interface SurveyPoint {
  id: number
  floor_plan_id: number
  ts: string
  label: string | null
  x: number
  y: number
  ssid: string | null
  bssid: string | null
  channel: number | null
  band: string | null
  rssi: number | null
  ping_ms: number | null
  packet_loss_pct: number | null
  grade: Grade | null
  note: string | null
  neighbors: NeighborReading[] | null
}

export interface NeighborReading {
  bssid: string | null
  ssid: string | null
  rssi: number | null
  channel: number | null
  band: string | null
}

export interface ApMarker {
  id: number
  floor_plan_id: number
  name: string
  bssid: string | null
  x: number
  y: number
}

export type HeatmapMetric = 'rssi' | 'redundancy'

export interface CoverageSummary {
  total_points: number
  counts: Record<string, number>
  percent: Record<string, number>
  colors: Record<string, string>
  /** Coverage metric only. */
  rssi_min?: number | null
  rssi_max?: number | null
  rssi_avg?: number | null
  /** Redundancy metric only. */
  min?: number | null
  max?: number | null
  avg?: number | null
  blind_spots?: number
}

export interface CoverageGrid {
  plan: FloorPlan
  grid: {
    cols: number
    rows: number
    cell_width_px: number
    cell_height_px: number
    matrix: (number | null)[][]
    grades: (Grade | null)[][] | null
    min: number | null
    max: number | null
    covered_pct: number
    max_influence_px: number
    power: number
  } | null
  metric: HeatmapMetric
  summary: CoverageSummary
  points: SurveyPoint[]
  access_points: ApMarker[]
  colors: Record<Grade, string>
  available_filters: { ssids: string[]; bssids: string[]; bands: string[] }
  applied_filters?: { ssid: string | null; bssid: string | null; band: string | null }
  redundancy_min_rssi?: number
  scanned_points?: number
  message?: string
}

/** One live reading from `/api/heatmap/measure`, used while walking. */
export interface WalkReading {
  ts: string
  ssid: string | null
  bssid: string | null
  channel: number | null
  band: string | null
  rssi: number | null
  ping_ms: number | null
  packet_loss_pct: number | null
  grade: Grade
}

export interface TestRecord {
  id: number
  ts: string
  area: string | null
  device: string | null
  ssid: string | null
  bssid: string | null
  channel: number | null
  band: string | null
  rssi: number | null
  ping_ms: number | null
  jitter_ms: number | null
  packet_loss_pct: number | null
  grade: Grade | null
  result: Verdict | null
  note: string | null
}

export interface HistoryPage {
  items: TestRecord[]
  total: number
  limit: number
  offset: number
}

export interface HistoryFacets {
  areas: string[]
  ssids: string[]
  bssids: string[]
  devices: string[]
  results: Verdict[]
}

export interface SignalBands {
  excellent: number
  good: number
  fair: number
}

export interface Thresholds {
  rssi_warning: number
  rssi_critical: number
  ping_warning_ms: number
  ping_critical_ms: number
  loss_warning_pct: number
  loss_critical_pct: number
  jitter_warning_ms: number
  roam_gap_warning_ms: number
}

export interface AppSettings {
  bands: SignalBands
  thresholds: Thresholds
  ping: { gateway: string; server: string; dns: string; dns_hostname: string }
  monitor: {
    interval_sec: number
    ping_count: number
    ping_timeout_sec: number
    retention_days: number
    survey_ping_count: number
  }
  site_name: string
}

export interface SettingsResponse {
  settings: AppSettings
  stored: boolean
  wifi_backend: string
}
