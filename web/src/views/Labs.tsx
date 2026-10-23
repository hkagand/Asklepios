import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Sparkline } from '../components/Sparkline.tsx'
import { SourceButton, useSource } from '../components/source.tsx'
import { Card, Empty, FlagMark, valueTone } from '../components/ui.tsx'
import { formatDate, formatDayMonth, formatMonthYear, formatNumber, signed } from '../format.ts'
import { percentChange, type Chart, type Point, type Series } from '../model.ts'
import { select } from '../route.ts'

const DAY_MS = 86_400_000
const FLAG_COLOURS = { H: '#e11d48', L: '#2563eb' }

export function Labs({ chart, selected }: { chart: Chart; selected?: string }) {
  const id = chart.patient.id ?? ''
  const all = [...chart.labs, ...chart.vitals]
  if (all.length === 0) {
    return (
      <Card>
        <Empty>No results on file.</Empty>
      </Card>
    )
  }
  const current = all.find((series) => series.key === selected) ?? chart.labs.find((series) => series.points.at(-1)?.flag) ?? all[0]
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
      <ResultsTable series={all} selected={current.key} onSelect={(key) => select(id, 'labs', key)} />
      <div className="lg:sticky lg:top-18">
        <Trend key={current.key} series={current} />
      </div>
    </div>
  )
}

function ResultsTable({ series, selected, onSelect }: { series: Series[]; selected: string; onSelect: (key: string) => void }) {
  const groups: [string, Series[]][] = []
  for (const item of series) {
    const last = groups.at(-1)
    if (last && last[0] === item.group) last[1].push(item)
    else groups.push([item.group, [item]])
  }
  return (
    <Card flush>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
            <th className="px-4 py-2 font-medium">Test</th>
            <th className="px-3 py-2 text-right font-medium">Latest</th>
            <th className="px-3 py-2 text-right font-medium">Previous</th>
            <th className="px-3 py-2 text-right font-medium">Change</th>
            <th className="px-4 py-2 font-medium">Trend</th>
          </tr>
        </thead>
        {groups.map(([group, items]) => (
          <tbody key={group}>
            <tr>
              <th colSpan={5} className="border-t border-slate-200 bg-slate-50 px-4 py-1.5 text-left text-xs font-semibold text-slate-600">
                {group}
              </th>
            </tr>
            {items.map((item) => (
              <ResultRow key={item.key} series={item} selected={item.key === selected} onSelect={onSelect} />
            ))}
          </tbody>
        ))}
      </table>
    </Card>
  )
}

function ResultRow({ series, selected, onSelect }: { series: Series; selected: boolean; onSelect: (key: string) => void }) {
  const latest = series.points[series.points.length - 1]
  const previous = series.points.at(-2)
  const percent = previous && percentChange(previous.value, latest.value)
  return (
    <tr
      tabIndex={0}
      aria-selected={selected}
      onClick={() => onSelect(series.key)}
      onKeyDown={(event) => event.key === 'Enter' && onSelect(series.key)}
      className={`cursor-pointer border-t border-slate-100 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-teal-600 ${
        selected ? 'bg-teal-50' : 'hover:bg-slate-50'
      }`}
    >
      <td className="px-4 py-2">
        <div className={`font-medium ${selected ? 'text-teal-900' : 'text-slate-800'}`}>{series.name}</div>
        <div className="text-[11px] text-slate-400">{series.range ?? series.unit}</div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
        <span className={`font-semibold ${valueTone(latest.flag)}`}>{formatNumber(latest.value, series.decimals)}</span>
        <FlagMark flag={latest.flag} />
        <div className="text-[11px] text-slate-400">{formatDate(latest.time)}</div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-600">
        {previous ? (
          <>
            {formatNumber(previous.value, series.decimals)}
            <FlagMark flag={previous.flag} />
            <div className="text-[11px] text-slate-400">{formatDate(previous.time)}</div>
          </>
        ) : (
          <span className="text-slate-300">—</span>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">
        {previous ? (
          <>
            {signed(latest.value - previous.value, series.decimals)}
            {percent !== undefined && <div className="text-[11px] text-slate-400">{signed(percent, 0)}%</div>}
          </>
        ) : (
          <span className="text-slate-300">—</span>
        )}
      </td>
      <td className="px-4 py-2">
        <Sparkline points={series.points} />
      </td>
    </tr>
  )
}

function monthTicks([start, end]: [number, number]): number[] {
  const months = (end - start) / (30.44 * DAY_MS)
  const step = [1, 2, 3, 6, 12, 24].find((size) => months / size <= 6) ?? 24
  const ticks: number[] = []
  const first = new Date(start)
  for (let month = first.getUTCMonth() + 1; ; month++) {
    const tick = Date.UTC(first.getUTCFullYear(), month, 1)
    if (tick > end) break
    if (new Date(tick).getUTCMonth() % step === 0) ticks.push(tick)
  }
  return ticks
}

function niceScale(low: number, high: number): { domain: [number, number]; ticks: number[] } {
  const rough = (high - low || Math.abs(high) || 1) / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((multiple) => multiple * magnitude).find((size) => size >= rough) ?? 10 * magnitude
  const start = Math.floor(low / step) * step
  const end = Math.ceil(high / step) * step
  const ticks: number[] = []
  for (let tick = start; tick <= end + step / 2; tick += step) ticks.push(Number(tick.toFixed(10)))
  return { domain: [ticks[0], ticks[ticks.length - 1]], ticks }
}

function Trend({ series }: { series: Series }) {
  const open = useSource()
  const { points } = series
  const latest = points[points.length - 1]
  const [first, last] = [points[0].time, latest.time]
  const timePad = Math.max((last - first) * 0.04, 4 * DAY_MS)
  const xDomain: [number, number] = [first - timePad, last + timePad]
  const short = xDomain[1] - xDomain[0] < 75 * DAY_MS
  const values = points.map((point) => point.value)
  const lowest = Math.min(...values, series.low ?? Number.POSITIVE_INFINITY)
  const highest = Math.max(...values, series.high ?? Number.NEGATIVE_INFINITY)
  const valuePad = (highest - lowest || Math.abs(highest) || 1) * 0.06
  const { domain: yDomain, ticks: yTicks } = niceScale(Math.max(0, lowest - valuePad), highest + valuePad)
  const hasRange = series.low !== undefined || series.high !== undefined

  return (
    <Card
      title={`${series.name}${series.unit ? ` (${series.unit})` : ''}`}
      subtitle={
        <>
          {series.range ? `Reference ${series.range}` : 'No reference range'} · {points.length}{' '}
          {points.length === 1 ? 'result' : 'results'}
          {points.length > 1 && `, ${formatDate(first)} – ${formatDate(last)}`}
        </>
      }
      action={<SourceButton resource={latest.observation} label="Latest" />}
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={points}
            margin={{ top: 8, right: 12, bottom: 0, left: 0 }}
            onClick={(state) => {
              const point = points[Number(state.activeTooltipIndex)]
              if (point) open(point.observation)
            }}
            className="cursor-pointer"
          >
            <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
            {hasRange && (
              <ReferenceArea
                y1={series.low ?? yDomain[0]}
                y2={series.high ?? yDomain[1]}
                fill="#10b981"
                fillOpacity={0.1}
                strokeOpacity={0}
                ifOverflow="hidden"
              />
            )}
            <XAxis
              dataKey="time"
              type="number"
              scale="time"
              domain={xDomain}
              ticks={short ? undefined : monthTicks(xDomain)}
              tickFormatter={(value: number) => (short ? formatDayMonth(value) : formatMonthYear(value))}
              tick={{ fontSize: 11, fill: '#64748b' }}
              axisLine={{ stroke: '#cbd5e1' }}
              tickLine={false}
            />
            <YAxis
              domain={yDomain}
              ticks={yTicks}
              tickFormatter={(value: number) => String(value)}
              tick={{ fontSize: 11, fill: '#64748b' }}
              axisLine={false}
              tickLine={false}
              width={44}
            />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: '#94a3b8', strokeDasharray: '3 3' }}
              content={({ active, payload }) => {
                const point = active ? (payload?.[0]?.payload as Point | undefined) : undefined
                if (!point) return null
                return (
                  <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
                    <p className="text-slate-500">{formatDate(point.time)}</p>
                    <p className={`text-sm font-semibold tabular-nums ${valueTone(point.flag)}`}>
                      {formatNumber(point.value, series.decimals)} {series.unit}
                      <FlagMark flag={point.flag} />
                    </p>
                    <p className="mt-0.5 text-[11px] text-slate-400">Click to view the source</p>
                  </div>
                )
              }}
            />
            <Line
              type="linear"
              dataKey="value"
              stroke="#0f766e"
              strokeWidth={2}
              isAnimationActive={false}
              dot={({ cx, cy, index, payload }) => (
                <circle
                  key={index}
                  cx={cx}
                  cy={cy}
                  r={3.5}
                  fill={(payload as Point).flag ? FLAG_COLOURS[(payload as Point).flag!] : '#0f766e'}
                  stroke="#fff"
                  strokeWidth={1.5}
                />
              )}
              activeDot={{ r: 6, stroke: '#0f766e', strokeWidth: 2, fill: '#fff' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">
        {hasRange && 'Shaded band: reference range. '}Click a point, or a row below, to see the FHIR source.
      </p>
      <div className="mt-3 max-h-72 overflow-y-auto rounded-lg border border-slate-100">
        <table className="w-full text-sm">
          <tbody>
            {[...points].reverse().map((point) => (
              <tr key={point.observation.id} className="border-t border-slate-100 first:border-t-0">
                <td className="px-3 py-1.5 text-slate-600">{formatDate(point.time)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
                  <span className={`font-medium ${valueTone(point.flag)}`}>{formatNumber(point.value, series.decimals)}</span>{' '}
                  <span className="text-xs text-slate-400">{series.unit}</span>
                  <FlagMark flag={point.flag} />
                </td>
                <td className="w-10 pr-2 text-right">
                  <SourceButton resource={point.observation} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
