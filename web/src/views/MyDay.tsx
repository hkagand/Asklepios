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
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <h1 className="text-[32px] font-extrabold leading-[1.1] tracking-[-0.025em] text-slate-900">
            {greeting}, {data.clinician.name}
          </h1>
          <p className="mt-1.5 text-[15px] text-slate-600">
            {formatWeekday(data.day)}, {relativeDay(data.day, data.today)}
            {data.day !== data.today && !day && ' (your next clinic day)'}. Demo General Hospital.
          </p>
        </div>
        <div className="flex items-center gap-1 text-[14px] font-semibold">
          <button type="button" onClick={() => step(-1)} className="rounded-md px-2 py-1 text-slate-600 hover:bg-slate-200/60 hover:text-slate-900">
            ← Day before
          </button>
          <a href="#/day" className="rounded-md px-2 py-1 text-slate-900 underline decoration-mark decoration-[3px] underline-offset-4 hover:bg-slate-200/60">
            Next clinic day
          </a>
          <button type="button" onClick={() => step(1)} className="rounded-md px-2 py-1 text-slate-600 hover:bg-slate-200/60 hover:text-slate-900">
            Day after →
          </button>
        </div>
      </div>

      <p className="mt-6 max-w-[62ch] text-[18px] leading-relaxed text-slate-800">
        {totals.visits === 0 ? (
          'Nobody is booked with you on this day.'
        ) : (
          <>
            <Count value={totals.visits} one="patient is" many="patients are" /> booked.{' '}
            <Count value={totals.toReview} one="result is" many="results are" act /> waiting for your review,{' '}
            <Count value={totals.followUps} one="follow-up is" many="follow-ups are" act /> open and{' '}
            <Count value={totals.medications} one="medication list disagrees" many="medication lists disagree" act /> with
            the notes. Briefs are ready for {totals.briefsReady} of {totals.visits}.
          </>
        )}
      </p>
      <p className="mt-1 text-[12.5px] text-slate-500">These counts cover the patients booked with you on this day.</p>

      <section className="mt-8">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-slate-300 pb-2">
          <h2 className="text-[17px] font-bold text-slate-900">Clinic list</h2>
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
              className="rounded-md bg-slate-900 px-3 py-1.5 text-[14px] font-bold text-white hover:bg-slate-800 disabled:bg-slate-200 disabled:text-slate-500"
            >
              {preparing ? 'Preparing briefs…' : toPrepare === 0 ? 'All briefs ready' : `Prepare ${toPrepare} brief${toPrepare === 1 ? '' : 's'}`}
            </button>
          )}
        </div>
        {error && <p className="mb-2 text-sm text-rose-700">{error}</p>}
        {data.patients.length === 0 ? (
          <p className="py-6 text-[15px] text-slate-500">
            No appointments on {formatDate(data.day)}. Step to another day, or go to your next clinic day.
          </p>
        ) : (
          <ol className="relative">
            {data.patients.map((row, index) => (
              <Row key={row.patient} row={row} last={index === data.patients.length - 1} />
            ))}
          </ol>
        )}
      </section>
    </Page>
  )
}

function Page({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6">{children}</main>
}

/** A number in the day's summary; numbers that need the clinician's action are highlighted when above zero. */
function Count({ value, one, many, act = false }: { value: number; one: string; many: string; act?: boolean }) {
  return (
    <span className={`font-bold ${act && value > 0 ? 'mark' : ''}`}>
      {value} {value === 1 ? one : many}
    </span>
  )
}

function Row({ row, last }: { row: DayPatient; last: boolean }) {
  const brief = BRIEFS[row.brief.state]
  return (
    <li className="relative grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-4">
      <span className="pt-3.5 text-right font-mono text-[15px] font-semibold text-slate-900">{formatTime(row.appointment.start)}</span>
      {/* The time rail: one dot per visit, joined in clinic order. */}
      <span className="absolute left-[5.1rem] top-[1.35rem] h-2.5 w-2.5 rounded-full border-2 border-slate-900 bg-paper" aria-hidden />
      {!last && <span className="absolute bottom-0 left-[5.38rem] top-[2.1rem] w-px bg-slate-300" aria-hidden />}
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
        className="mb-2 ml-5 grid gap-x-4 gap-y-1.5 rounded-lg border border-slate-200 bg-sheet px-4 py-3 hover:border-slate-900 md:grid-cols-[minmax(0,1fr)_auto]"
      >
        <span className="min-w-0">
          <span className="block truncate text-[16px] font-bold text-slate-900">{row.name}</span>
          <span className="block truncate text-[14px] text-slate-600">
            {row.appointment.description ?? 'No reason given'}
            <span className="ml-2 font-mono text-[12.5px] text-slate-400">{row.mrn}</span>
          </span>
        </span>
        <span className="flex flex-wrap content-start gap-1.5 md:justify-end">
          <Badge
            tone={brief.tone}
            title={`${brief.hint}${row.brief.preparedAt ? `, ${formatDate(row.brief.preparedAt)} ${formatTime(row.brief.preparedAt)}` : ''}`}
          >
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
