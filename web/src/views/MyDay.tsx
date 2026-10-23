import { useEffect, useState, type ReactNode } from 'react'
import { clinicDay, prepareBriefs, type BriefState, type DayPatient } from '../agent.ts'
import { useClinician } from '../components/clinician.tsx'
import { LoopBadges } from '../components/OpenLoops.tsx'
import { Badge, ErrorPanel, Loading, type Tone } from '../components/ui.tsx'
import { formatDate, formatTime, formatWeekday, relativeDay } from '../format.ts'
import { patientHref } from '../route.ts'
import { useAsync } from '../useAsync.ts'

const BRIEFS: Record<BriefState, { label: string; tone: Tone; hint: string }> = {
  ready: { label: 'Brief ready', tone: 'teal', hint: 'Prepared from the chart as it is now' },
  outdated: { label: 'Brief outdated', tone: 'amber', hint: 'The chart has changed since the brief was prepared' },
  preparing: { label: 'Preparing…', tone: 'blue', hint: 'ASKlepios is writing the brief' },
  missing: { label: 'No brief', tone: 'slate', hint: 'Not prepared yet' },
}

/** The signed-in clinician's clinic day: what needs attention, and a brief per patient prepared in advance. */
export function MyDay({ day }: { day?: string }) {
  const { current } = useClinician()
  const [version, setVersion] = useState(0)
  const state = useAsync(
    (signal) => (current ? clinicDay(current.id, day, signal) : Promise.reject(new Error('Choose who is viewing (top right).'))),
    [current?.id, day, version],
  )
  const [error, setError] = useState<string>()
  const preparing = state.status === 'ready' && state.data.patients.some((row) => row.brief.state === 'preparing')

  // While briefs are being written, look again every few seconds.
  useEffect(() => {
    if (!preparing) return
    const timer = window.setTimeout(() => setVersion((value) => value + 1), 4000)
    return () => window.clearTimeout(timer)
  }, [preparing, version])

  if (!current) {
    return (
      <Page>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">My day</h1>
        <p className="mt-2 text-sm text-slate-600">Choose who is viewing (top right) to see that clinician&apos;s day.</p>
      </Page>
    )
  }
  if (state.status === 'loading' && version === 0) return <Page><Loading label="Gathering the clinic list, open loops and briefs…" /></Page>
  if (state.status === 'error') return <Page><ErrorPanel error={state.error} /></Page>
  if (state.status !== 'ready') return <Page><Loading label="Updating…" /></Page>

  const data = state.data
  const { totals } = data
  const shown = new Date(data.day)
  const step = (days: number) => {
    const next = new Date(shown)
    next.setDate(next.getDate() + days)
    window.location.hash = `#/day/${next.toISOString().slice(0, 10)}`
  }
  const toPrepare = data.patients.filter((row) => row.brief.state === 'missing' || row.brief.state === 'outdated').length
  const greeting = new Date().getHours() < 12 ? 'Good morning' : new Date().getHours() < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <Page>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            {greeting}, {data.clinician.name}
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Demo General Hospital · {formatWeekday(data.day)} ({relativeDay(data.day, data.today)})
            {data.day !== data.today && !day && ' · your next clinic day'}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => step(-1)} className="rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100">
            ← Day before
          </button>
          <a href="#/day" className="rounded-md px-2 py-1 text-sm text-teal-700 hover:bg-teal-50">
            Next clinic day
          </a>
          <button type="button" onClick={() => step(1)} className="rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100">
            Day after →
          </button>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tile value={totals.visits} label="Visits" />
        <Tile value={totals.toReview} label="Results to review" tone={totals.toReview ? 'amber' : undefined} />
        <Tile value={totals.followUps} label="Open follow-ups" tone={totals.followUps ? 'rose' : undefined} />
        <Tile value={totals.medications} label="Medication discrepancies" tone={totals.medications ? 'rose' : undefined} />
        <Tile value={`${totals.briefsReady}/${totals.visits}`} label="Briefs ready" />
      </div>
      <p className="mt-2 text-xs text-slate-500">Counts are for the patients booked with you on this day.</p>

      <section className="mt-6">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-700">Appointments</h2>
          {data.patients.length > 0 && (
            <button
              type="button"
              disabled={toPrepare === 0 || preparing}
              onClick={async () => {
                setError(undefined)
                try {
                  await prepareBriefs(current.id, data.day)
                  setVersion((value) => value + 1)
                } catch (problem) {
                  setError(problem instanceof Error ? problem.message : String(problem))
                }
              }}
              className="rounded-md bg-teal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:bg-slate-200 disabled:text-slate-500"
            >
              {preparing ? 'Preparing briefs…' : toPrepare === 0 ? 'All briefs ready' : `Prepare ${toPrepare} brief${toPrepare === 1 ? '' : 's'}`}
            </button>
          )}
        </div>
        {error && <p className="mb-2 text-sm text-rose-700">{error}</p>}
        {data.patients.length === 0 ? (
          <p className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">No appointments on {formatDate(data.day)}.</p>
        ) : (
          <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            {data.patients.map((row) => (
              <Row key={row.patient} row={row} />
            ))}
          </ul>
        )}
      </section>
    </Page>
  )
}

function Page({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-7xl px-6 pb-16 pt-6">{children}</main>
}

function Tile({ value, label, tone }: { value: number | string; label: string; tone?: Tone }) {
  const color = tone === 'rose' ? 'text-rose-700' : tone === 'amber' ? 'text-amber-700' : 'text-slate-900'
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className={`text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  )
}

function Row({ row }: { row: DayPatient }) {
  const brief = BRIEFS[row.brief.state]
  return (
    <li>
      <a
        href={patientHref(row.patient)}
        onClick={() => {
          // Open the chart with ASKlepios showing the prepared brief.
          try {
            localStorage.setItem('copilot-open', '1')
          } catch {
            // Storage may be refused; the chart still opens.
          }
        }}
        className="grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-4 gap-y-1.5 px-4 py-3 hover:bg-teal-50/50 md:grid-cols-[4rem_minmax(0,1.2fr)_minmax(0,1.5fr)_auto]"
      >
        <span className="text-sm font-semibold tabular-nums text-slate-900">{formatTime(row.appointment.start)}</span>
        <span className="min-w-0">
          <span className="block truncate font-medium text-slate-900">{row.name}</span>
          <span className="block text-xs text-slate-500">{row.mrn}</span>
        </span>
        <span className="col-start-2 min-w-0 truncate text-sm text-slate-700 md:col-start-auto">{row.appointment.description ?? '—'}</span>
        <span className="col-start-2 flex flex-wrap gap-1.5 md:col-start-auto md:justify-end">
          <Badge tone={brief.tone} title={`${brief.hint}${row.brief.preparedAt ? ` · ${formatDate(row.brief.preparedAt)} ${formatTime(row.brief.preparedAt)}` : ''}`}>
            {brief.label}
          </Badge>
          {row.medications > 0 && (
            <Badge tone="rose" title="Notes and medication orders disagree; see the Medications tab">
              {row.medications} medication
            </Badge>
          )}
          <LoopBadges statuses={row.loops} />
        </span>
      </a>
    </li>
  )
}
