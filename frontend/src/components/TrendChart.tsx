import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { clockTime } from '../lib/format'

/**
 * The Dashboard's RSSI trend, in its own module so Recharts stays out of the
 * initial bundle. The dashboard has to answer "is the WiFi OK" immediately; the
 * chart is below the fold and can arrive a moment later.
 */
export default function TrendChart({
  data,
}: {
  data: { ts: string; rssi: number | null; ping_ms: number | null }[]
}) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data.map((t) => ({ ...t, label: clockTime(t.ts) }))}>
        <XAxis dataKey="label" stroke="#475569" fontSize={11} minTickGap={40} />
        <YAxis stroke="#475569" fontSize={11} domain={[-95, -25]} width={40} />
        <Tooltip
          contentStyle={{
            background: '#0f172a',
            border: '1px solid #1e293b',
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(value: number) => [`${value} dBm`, 'RSSI']}
        />
        <Line
          type="monotone"
          dataKey="rssi"
          stroke="#38bdf8"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
