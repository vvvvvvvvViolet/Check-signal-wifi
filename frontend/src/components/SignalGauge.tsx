import type { Grade } from '../api/types'
import { GRADE_COLOR, GRADE_LABEL } from '../lib/format'

const FLOOR = -90
const CEILING = -30
const RADIUS = 80
const STROKE = 16
// A 240-degree arc: open at the bottom so the reading sits in the gap.
const SWEEP = 240
const START = 150

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

function arcPath(cx: number, cy: number, r: number, from: number, to: number) {
  const start = polar(cx, cy, r, from)
  const end = polar(cx, cy, r, to)
  const largeArc = Math.abs(to - from) > 180 ? 1 : 0
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`
}

/** Where a dBm value sits along the arc, clamped to the dial's range. */
function angleFor(rssi: number): number {
  const ratio = Math.min(1, Math.max(0, (rssi - FLOOR) / (CEILING - FLOOR)))
  return START + ratio * SWEEP
}

// The four bands drawn as coloured arc segments, matching the grading scale.
const BANDS: { grade: Grade; from: number; to: number }[] = [
  { grade: 'POOR', from: FLOOR, to: -72 },
  { grade: 'FAIR', from: -72, to: -65 },
  { grade: 'GOOD', from: -65, to: -55 },
  { grade: 'EXCELLENT', from: -55, to: CEILING },
]

export function SignalGauge({
  rssi,
  grade,
  size = 200,
}: {
  rssi: number | null
  grade: Grade
  size?: number
}) {
  const cx = size / 2
  const cy = size / 2
  const r = RADIUS * (size / 200)
  const color = GRADE_COLOR[grade]
  const needleAngle = rssi === null ? null : angleFor(rssi)

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size * 0.82} viewBox={`0 0 ${size} ${size * 0.82}`} role="img"
           aria-label={`Signal ${rssi ?? 'unknown'} dBm, ${GRADE_LABEL[grade]}`}>
        {/* Track */}
        <path
          d={arcPath(cx, cy, r, START, START + SWEEP)}
          fill="none"
          stroke="#1e293b"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />
        {/* Bands */}
        {BANDS.map((band) => (
          <path
            key={band.grade}
            d={arcPath(cx, cy, r, angleFor(band.from), angleFor(band.to))}
            fill="none"
            stroke={GRADE_COLOR[band.grade]}
            strokeWidth={STROKE}
            opacity={grade === band.grade ? 1 : 0.28}
          />
        ))}
        {/* Needle */}
        {needleAngle !== null && (
          <>
            <line
              x1={polar(cx, cy, r - STROKE, needleAngle).x}
              y1={polar(cx, cy, r - STROKE, needleAngle).y}
              x2={polar(cx, cy, r + STROKE / 2, needleAngle).x}
              y2={polar(cx, cy, r + STROKE / 2, needleAngle).y}
              stroke="#e2e8f0"
              strokeWidth={3}
              strokeLinecap="round"
            />
            <circle cx={cx} cy={cy} r={5} fill="#e2e8f0" />
          </>
        )}
        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          className="tabular"
          fill={color}
          fontSize={size * 0.17}
          fontWeight={700}
        >
          {rssi ?? '—'}
        </text>
        <text x={cx} y={cy + size * 0.09} textAnchor="middle" fill="#94a3b8" fontSize={size * 0.06}>
          dBm
        </text>
      </svg>
      <div className="text-sm font-semibold" style={{ color }}>
        {GRADE_LABEL[grade]}
      </div>
      <div className="mt-0.5 flex gap-3 text-[10px] text-slate-500 tabular">
        <span>{FLOOR}</span>
        <span>weakest → strongest</span>
        <span>{CEILING}</span>
      </div>
    </div>
  )
}
