import { loopSummary, type LoopCounts } from '../agent.ts'
import { LoopBadges } from '../components/OpenLoops.tsx'
import { Badge, ErrorPanel, Loading } from '../components/ui.tsx'
import { medicalRecordNumber, patientName } from '../fhir.ts'
import { ageOn, formatTime, formatWeekday, isoDay, relativeDay, todayIso } from '../format.ts'
import { loadWorklist, participant, type WorklistEntry } from '../model.ts'
import { patientHref } from '../route.ts'
import { useAsync } from '../useAsync.ts'

const COLUMNS = 'grid grid-cols-[4rem_minmax(0,1.1fr)_minmax(0,1.5fr)_minmax(0,1.4fr)_11rem] items-center gap-4'

export function Worklist() {
  const state = useAsync(loadWorklist, [])
  return (
    <main className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6">
      <div className="mb-6">
        <h1 className="text-[32px] font-extrabold leading-[1.1] tracking-[-0.025em] text-slate-900">All appointments</h1>
        <p className="mt-1.5 text-[15px] text-slate-600">
          Every upcoming appointment, with each patient&apos;s active problems and open loops.
        </p>
      </div>
      {state.status === 'loading' && <Loading label="Loading appointments from the FHIR server…" />}
      {state.status === 'error' && <ErrorPanel error={state.error} />}
      {state.status === 'ready' && <Days entries={state.data} />}
    </main>
  )
}

function Days({ entries }: { entries: WorklistEntry[] }) {
  const today = todayIso()
  const ids = entries.map((entry) => entry.patient.id ?? '').filter(Boolean)
  const summary = useAsync((signal) => loopSummary(ids, signal), [ids.join(',')])
  const loops = summary.status === 'ready' ? summary.data : undefined
  const days = new Map<string, WorklistEntry[]>()
  for (const entry of entries) {
    const day = entry.appointment?.start ? isoDay(entry.appointment.start) : ''
    days.set(day, [...(days.get(day) ?? []), entry])
  }
  return (
    <div className="space-y-6">
      {[...days].map(([day, list]) => (
        <section key={day || 'none'}>
          <h2 className="mb-2 flex items-baseline gap-2 text-[16px] font-bold text-slate-900">
            {day ? formatWeekday(day) : 'No upcoming appointment'}
            {day && <span className="text-[13px] font-normal text-slate-500">{relativeDay(day, today)},</span>}
            <span className="text-[13px] font-normal text-slate-500">{list.length} {list.length === 1 ? 'patient' : 'patients'}</span>
          </h2>
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-sheet">
            <div className={`${COLUMNS} border-b border-slate-200 bg-slate-50 px-4 py-2 text-[12px] font-semibold text-slate-500`}>
              <span>Time</span>
              <span>Patient</span>
              <span>Visit</span>
              <span>Active problems</span>
              <span className="text-right" title={loops ? 'Plans in notes and open orders, checked against the record' : 'Open loops not available; showing open orders'}>
                {loops ? 'Open loops' : 'Open orders'}
              </span>
            </div>
            <ul className="divide-y divide-slate-100">
              {list.map((entry) => (
                <Row key={entry.patient.id} entry={entry} today={today} loops={loops?.[entry.patient.id ?? '']} />
              ))}
            </ul>
          </div>
        </section>
      ))}
    </div>
  )
}

function Row({ entry, today, loops }: { entry: WorklistEntry; today: string; loops?: LoopCounts }) {
  const { patient, appointment } = entry
  const sex = patient.gender === 'male' ? 'M' : patient.gender === 'female' ? 'F' : '?'
  const upcoming = entry.open - entry.overdue
  return (
    <li>
      <a
        href={patientHref(patient.id ?? '')}
        className={`${COLUMNS} px-4 py-3 hover:bg-teal-50/50 focus-visible:bg-teal-50/50 focus-visible:outline-none`}
      >
        <span className="text-sm font-semibold tabular-nums text-slate-900">
          {appointment?.start ? formatTime(appointment.start) : '—'}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium text-slate-900">{patientName(patient)}</span>
          <span className="block text-xs text-slate-500">
            {ageOn(patient.birthDate, today)} y · {sex} · {medicalRecordNumber(patient)}
          </span>
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm text-slate-800">{appointment?.description ?? '—'}</span>
          {appointment && (
            <span className="block truncate text-xs text-slate-500">
              {participant(appointment, 'Practitioner')?.display} · {appointment.serviceType?.[0]?.text}
            </span>
          )}
        </span>
        <span className="min-w-0 text-sm leading-snug text-slate-600">
          <span className="line-clamp-2">{entry.problems.join(' · ') || '—'}</span>
        </span>
        <span className="flex flex-wrap justify-end gap-1.5">
          {loops?.statuses ? (
            <LoopBadges statuses={loops.statuses} />
          ) : (
            <>
              {entry.overdue > 0 && <Badge tone="rose">{entry.overdue} overdue</Badge>}
              {upcoming > 0 && <Badge>{upcoming} pending</Badge>}
              {entry.open === 0 && <span className="text-xs text-slate-400">None</span>}
            </>
          )}
        </span>
      </a>
    </li>
  )
}
