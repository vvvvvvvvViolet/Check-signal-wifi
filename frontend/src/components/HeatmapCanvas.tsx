import { useEffect, useRef } from 'react'
import type { CoverageGrid } from '../api/types'
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

function rampColor(rssi: number): [number, number, number] {
  if (rssi >= STOPS[0].dbm) return STOPS[0].color
  const last = STOPS[STOPS.length - 1]
  if (rssi <= last.dbm) return last.color

  for (let i = 0; i < STOPS.length - 1; i += 1) {
    const upper = STOPS[i]
    const lower = STOPS[i + 1]
    if (rssi <= upper.dbm && rssi >= lower.dbm) {
      const t = (rssi - lower.dbm) / (upper.dbm - lower.dbm)
      return [
        Math.round(lower.color[0] + t * (upper.color[0] - lower.color[0])),
        Math.round(lower.color[1] + t * (upper.color[1] - lower.color[1])),
        Math.round(lower.color[2] + t * (upper.color[2] - lower.color[2])),
      ]
    }
  }
  return last.color
}

interface Props {
  data: CoverageGrid
  imageUrl: string
  opacity?: number
  showPoints?: boolean
  showAps?: boolean
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
  onPick,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { plan, grid, points, access_points: aps } = data
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
              const [r, g, b] = rampColor(value)
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
          const color = GRADE_COLOR[point.grade ?? 'UNKNOWN']
          ctx.beginPath()
          ctx.arc(point.x, point.y, 6 * scale, 0, Math.PI * 2)
          ctx.fillStyle = color
          ctx.fill()
          ctx.lineWidth = 2 * scale
          ctx.strokeStyle = '#0f172a'
          ctx.stroke()

          if (point.rssi !== null) {
            ctx.font = `${11 * scale}px ui-monospace, monospace`
            ctx.fillStyle = '#e2e8f0'
            ctx.textAlign = 'center'
            ctx.strokeStyle = '#0f172a'
            ctx.lineWidth = 3 * scale
            ctx.strokeText(String(point.rssi), point.x, point.y - 10 * scale)
            ctx.fillText(String(point.rssi), point.x, point.y - 10 * scale)
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
  }, [data, imageUrl, opacity, showPoints, showAps])

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
