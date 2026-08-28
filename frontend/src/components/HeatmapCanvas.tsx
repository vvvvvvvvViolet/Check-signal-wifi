import { useEffect, useRef } from 'react'
import type { CoverageGrid, HeatmapMetric, NeighborReading } from '../api/types'
import { GRADE_COLOR } from '../lib/format'

/** Parse '#rrggbb' once per draw rather than per cell. */
function hexToRgb(hex: string): [number, number, number] {
  const value = parseInt(hex.replace('#', ''), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

// Colour stops in dBm, strongest first. Interpolating between them gives a
// continuous ramp instead of four hard bands, which reads much better over a
// floor plan while still lining up with the grade colours at the boundaries.
const STOPS: { dbm: number; color: [number, number, number] }[] = [
  { dbm: -45, color: hexToRgb(GRADE_COLOR.EXCELLENT) },
  { dbm: -55, color: hexToRgb(GRADE_COLOR.EXCELLENT) },
  { dbm: -65, color: hexToRgb(GRADE_COLOR.GOOD) },
  { dbm: -72, color: hexToRgb(GRADE_COLOR.FAIR) },
  { dbm: -85, color: hexToRgb(GRADE_COLOR.POOR) },
]

// Redundancy is a count, not a level, and zero has a hard meaning: no other AP
// is reachable here, so a client that moves will drop rather than roam. Giving
// it its own ramp keeps that unmistakable instead of borrowing dBm colours.
const REDUNDANCY_STOPS: { at: number; color: [number, number, number] }[] = [
  { at: 3, color: hexToRgb('#16a34a') },
  { at: 2, color: hexToRgb('#4ade80') },
  { at: 1, color: hexToRgb('#facc15') },
  { at: 0, color: hexToRgb('#ef4444') },
]

const RSSI_STOPS = STOPS.map((stop) => ({ at: stop.dbm, color: stop.color }))

/** Interpolate between ordered stops (highest first), clamping outside them. */
function ramp(
  value: number,
  stops: { at: number; color: [number, number, number] }[],
): [number, number, number] {
  if (value >= stops[0].at) return stops[0].color
  const last = stops[stops.length - 1]
  if (value <= last.at) return last.color

  for (let i = 0; i < stops.length - 1; i += 1) {
    const upper = stops[i]
    const lower = stops[i + 1]
    if (value <= upper.at && value >= lower.at) {
      const t = (value - lower.at) / (upper.at - lower.at)
      return [
        Math.round(lower.color[0] + t * (upper.color[0] - lower.color[0])),
        Math.round(lower.color[1] + t * (upper.color[1] - lower.color[1])),
        Math.round(lower.color[2] + t * (upper.color[2] - lower.color[2])),
      ]
    }
  }
  return last.color
}

function colorFor(value: number, metric: HeatmapMetric): [number, number, number] {
  return ramp(value, metric === 'redundancy' ? REDUNDANCY_STOPS : RSSI_STOPS)
}

/** Mirrors the backend's redundancy rule so dot captions match the surface. */
function countUsable(neighbors: NeighborReading[] | null, minRssi: number): number {
  if (!neighbors) return 0
  const seen = new Set<string>()
  for (const neighbor of neighbors) {
    if (neighbor.bssid && neighbor.rssi !== null && neighbor.rssi >= minRssi) {
      seen.add(neighbor.bssid)
    }
  }
  return seen.size
}

interface Props {
  data: CoverageGrid
  imageUrl: string
  opacity?: number
  showPoints?: boolean
  showAps?: boolean
  /** Extra markers over the plan, e.g. the start of a walk in progress. */
  markers?: { x: number; y: number; label?: string }[]
  onPick?: (x: number, y: number) => void
}

/**
 * Draws the interpolated coverage over the floor plan.
 *
 * The grid is rendered into a small offscreen canvas - one pixel per cell - and
 * then scaled up with smoothing. That gives a soft, continuous heatmap for
 * almost no cost, and keeps the work proportional to the grid rather than to
 * the size of the plan image.
 */
export function HeatmapCanvas({
  data,
  imageUrl,
  opacity = 0.62,
  showPoints = true,
  showAps = true,
  markers,
  onPick,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { plan, grid, points, access_points: aps, metric } = data
    const minRssi = data.redundancy_min_rssi ?? -70
    canvas.width = plan.width_px
    canvas.height = plan.height_px

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      if (imageRef.current?.complete && imageRef.current.naturalWidth > 0) {
        ctx.drawImage(imageRef.current, 0, 0, canvas.width, canvas.height)
      } else {
        ctx.fillStyle = '#0f172a'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
      }

      if (grid) {
        const offscreen = document.createElement('canvas')
        offscreen.width = grid.cols
        offscreen.height = grid.rows
        const offCtx = offscreen.getContext('2d')
        if (offCtx) {
          const image = offCtx.createImageData(grid.cols, grid.rows)
          for (let row = 0; row < grid.rows; row += 1) {
            for (let col = 0; col < grid.cols; col += 1) {
              const value = grid.matrix[row][col]
              const idx = (row * grid.cols + col) * 4
              if (value === null) {
                image.data[idx + 3] = 0 // unsurveyed floor stays transparent
                continue
              }
              const [r, g, b] = colorFor(value, metric)
              image.data[idx] = r
              image.data[idx + 1] = g
              image.data[idx + 2] = b
              image.data[idx + 3] = 255
            }
          }
          offCtx.putImageData(image, 0, 0)

          ctx.save()
          ctx.globalAlpha = opacity
          ctx.imageSmoothingEnabled = true
          ctx.imageSmoothingQuality = 'high'
          ctx.drawImage(offscreen, 0, 0, canvas.width, canvas.height)
          ctx.restore()
        }
      }

      const scale = Math.max(1, canvas.width / 900)

      if (showPoints) {
        for (const point of points) {
          const usable = countUsable(point.neighbors, minRssi)
          // A point captured without a scan has no redundancy answer. Colouring
          // it red would read as "blind spot" when the truth is "not measured",
          // so it gets the neutral unknown colour instead.
          const color =
            metric === 'redundancy'
              ? point.neighbors === null
                ? GRADE_COLOR.UNKNOWN
                : `rgb(${colorFor(usable, metric).join(',')})`
              : GRADE_COLOR[point.grade ?? 'UNKNOWN']
          ctx.beginPath()
          ctx.arc(point.x, point.y, 6 * scale, 0, Math.PI * 2)
          ctx.fillStyle = color
          ctx.fill()
          ctx.lineWidth = 2 * scale
          ctx.strokeStyle = '#0f172a'
          ctx.stroke()

          // A point captured without a scan has no redundancy answer, so it
          // gets no caption rather than a misleading zero.
          const caption =
            metric === 'redundancy'
              ? point.neighbors === null
                ? null
                : String(usable)
              : point.rssi !== null
                ? String(point.rssi)
                : null
          if (caption !== null) {
            ctx.font = `${11 * scale}px ui-monospace, monospace`
            ctx.fillStyle = '#e2e8f0'
            ctx.textAlign = 'center'
            ctx.strokeStyle = '#0f172a'
            ctx.lineWidth = 3 * scale
            ctx.strokeText(caption, point.x, point.y - 10 * scale)
            ctx.fillText(caption, point.x, point.y - 10 * scale)
          }
        }
      }

      if (showAps) {
        for (const ap of aps) {
          const size = 11 * scale
          ctx.beginPath()
          ctx.moveTo(ap.x, ap.y - size)
          ctx.lineTo(ap.x + size, ap.y)
          ctx.lineTo(ap.x, ap.y + size)
          ctx.lineTo(ap.x - size, ap.y)
          ctx.closePath()
          ctx.fillStyle = '#0ea5e9'
          ctx.fill()
          ctx.lineWidth = 2 * scale
          ctx.strokeStyle = '#e0f2fe'
          ctx.stroke()

          ctx.font = `bold ${11 * scale}px ui-sans-serif, system-ui`
          ctx.fillStyle = '#e0f2fe'
          ctx.textAlign = 'center'
          ctx.strokeStyle = '#0c4a6e'
          ctx.lineWidth = 3 * scale
          ctx.strokeText(ap.name, ap.x, ap.y + size + 13 * scale)
          ctx.fillText(ap.name, ap.x, ap.y + size + 13 * scale)
        }
      }

      for (const marker of markers ?? []) {
        ctx.beginPath()
        ctx.arc(marker.x, marker.y, 9 * scale, 0, Math.PI * 2)
        ctx.strokeStyle = '#38bdf8'
        ctx.lineWidth = 3 * scale
        ctx.stroke()
        ctx.beginPath()
        ctx.arc(marker.x, marker.y, 3 * scale, 0, Math.PI * 2)
        ctx.fillStyle = '#38bdf8'
        ctx.fill()
        if (marker.label) {
          ctx.font = `bold ${11 * scale}px ui-sans-serif, system-ui`
          ctx.textAlign = 'center'
          ctx.strokeStyle = '#0c4a6e'
          ctx.lineWidth = 3 * scale
          ctx.strokeText(marker.label, marker.x, marker.y - 16 * scale)
          ctx.fillStyle = '#e0f2fe'
          ctx.fillText(marker.label, marker.x, marker.y - 16 * scale)
        }
      }
    }

    if (imageRef.current?.src !== imageUrl) {
      const image = new Image()
      image.onload = draw
      image.onerror = draw // a missing plan image must not blank the heatmap
      image.src = imageUrl
      imageRef.current = image
    } else {
      draw()
    }
  }, [data, imageUrl, opacity, showPoints, showAps, markers])

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!onPick) return
    const canvas = event.currentTarget
    const rect = canvas.getBoundingClientRect()
    // Map the click from displayed size back to floor-plan pixel coordinates.
    const x = ((event.clientX - rect.left) / rect.width) * canvas.width
    const y = ((event.clientY - rect.top) / rect.height) * canvas.height
    onPick(Math.round(x), Math.round(y))
  }

  return (
    <canvas
      ref={canvasRef}
      onClick={handleClick}
      className={`w-full rounded-lg border border-slate-800 ${onPick ? 'cursor-crosshair' : ''}`}
      style={{ imageRendering: 'auto' }}
    />
  )
}
