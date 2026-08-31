import type { ReactNode } from 'react'
import type { Grade, MetricStatus, Verdict } from '../api/types'
import { GRADE_COLOR, GRADE_LABEL, VERDICT_COLOR } from '../lib/format'

export function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="card-title">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  sub,
  color,
  mono = true,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  color?: string
  mono?: boolean
}) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div
        className={`mt-1 text-2xl font-semibold ${mono ? 'tabular' : ''}`}
        style={color ? { color } : undefined}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
    </div>
  )
}

export function GradePill({ grade }: { grade: Grade | null }) {
  const key: Grade = grade ?? 'UNKNOWN'
  const color = GRADE_COLOR[key]
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold"
      style={{ backgroundColor: `${color}22`, color }}
    >
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {GRADE_LABEL[key]}
    </span>
  )
}

export function VerdictPill({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return <span className="text-slate-500">—</span>
  const color = VERDICT_COLOR[verdict]
  return (
    <span
      className="rounded px-2 py-0.5 text-xs font-bold tracking-wide"
      style={{ backgroundColor: `${color}22`, color }}
    >
      {verdict}
    </span>
  )
}

const STATUS_COLOR: Record<MetricStatus, string> = {
  ok: '#16a34a',
  warning: '#f59e0b',
  critical: '#ef4444',
  unknown: '#64748b',
}

export function StatusDot({ status, title }: { status: MetricStatus; title?: string }) {
  return (
    <span
      title={title}
      className="inline-block h-2.5 w-2.5 rounded-full"
      style={{ backgroundColor: STATUS_COLOR[status] }}
    />
  )
}

export function Banner({
  kind = 'info',
  children,
}: {
  kind?: 'info' | 'warning' | 'error' | 'success'
  children: ReactNode
}) {
  const styles = {
    info: 'border-sky-500/40 bg-sky-500/10 text-sky-200',
    warning: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    error: 'border-red-500/40 bg-red-500/10 text-red-200',
    success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  }[kind]
  return <div className={`rounded-lg border px-3 py-2 text-sm ${styles}`}>{children}</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-500">
      {children}
    </div>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-700 border-t-sky-400" />
      {label}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}
