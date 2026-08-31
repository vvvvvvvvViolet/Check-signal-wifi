import type { Grade, Verdict } from '../api/types'

export const GRADE_COLOR: Record<Grade, string> = {
  EXCELLENT: '#16a34a',
  GOOD: '#4ade80',
  FAIR: '#facc15',
  POOR: '#ef4444',
  UNKNOWN: '#94a3b8',
}

export const GRADE_LABEL: Record<Grade, string> = {
  EXCELLENT: 'Excellent',
  GOOD: 'Good',
  FAIR: 'Fair',
  POOR: 'Poor',
  UNKNOWN: 'Unknown',
}

/** The scale shown in the legend and in Settings, straight from the spec. */
export const GRADE_RANGES: { grade: Grade; label: string }[] = [
  { grade: 'EXCELLENT', label: '≥ -55 dBm' },
  { grade: 'GOOD', label: '-56 to -65 dBm' },
  { grade: 'FAIR', label: '-66 to -72 dBm' },
  { grade: 'POOR', label: '< -72 dBm' },
]

export const VERDICT_COLOR: Record<Verdict, string> = {
  PASS: '#16a34a',
  WARNING: '#f59e0b',
  FAIL: '#ef4444',
}

export function dbm(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value} dBm`
}

export function ms(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(digits)} ms`
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(digits)}%`
}

export function text(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

export function clockTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString()
}

export function dateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

export function shortDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString()
}

/** How long ago, for "last updated" captions. */
export function sinceNow(iso: string | null): string {
  if (!iso) return 'never'
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  return `${Math.round(seconds / 3600)}h ago`
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}
