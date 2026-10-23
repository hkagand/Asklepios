import type { Point } from '../model.ts'

export function Sparkline({ points, width = 112, height = 26 }: { points: Point[]; width?: number; height?: number }) {
  if (points.length === 0) return null
  const times = points.map((point) => point.time)
  const values = points.map((point) => point.value)
  const [firstTime, lastTime] = [Math.min(...times), Math.max(...times)]
  const [low, high] = [Math.min(...values), Math.max(...values)]
  const x = (time: number) => (lastTime === firstTime ? width / 2 : 3 + ((time - firstTime) / (lastTime - firstTime)) * (width - 6))
  const y = (value: number) => (high === low ? height / 2 : height - 3 - ((value - low) / (high - low)) * (height - 6))
  const path = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.time).toFixed(1)},${y(point.value).toFixed(1)}`).join('')
  const last = points[points.length - 1]
  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden>
      {points.length > 1 && <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-slate-400" />}
      <circle
        cx={x(last.time)}
        cy={y(last.value)}
        r={2.75}
        className={last.flag === 'H' ? 'fill-rose-600' : last.flag === 'L' ? 'fill-blue-600' : 'fill-slate-700'}
      />
    </svg>
  )
}
