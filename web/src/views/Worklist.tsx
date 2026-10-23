import { Badge, ErrorPanel, Loading } from '../components/ui.tsx'
import { medicalRecordNumber, patientName } from '../fhir.ts'
import { ageOn, formatTime, formatWeekday, isoDay, relativeDay, todayIso } from '../format.ts'
import { loadWorklist, participant, type WorklistEntry } from '../model.ts'
import { patientHref } from '../route.ts'
import { useAsync } from '../useAsync.ts'

const COLUMNS = 'grid grid-cols-[4rem_minmax(0,1.1fr)_minmax(0,1.5fr)_minmax(0,1.4fr)_8.5rem] items-center gap-4'

export function Worklist() {
  const state = useAsync(loadWorklist, [])
  return (
    <main className="mx-auto max-w-7xl px-6 pb-16 pt-6">
      <div className="mb-5">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Clinic worklist</h1>
        <p className="mt-0.5 text-sm text-slate-500">Upcoming appointments, with each patient&apos;s active problems and open orders.</p>
      </div>
      {state.status === 'loading' && <Loading label="Loading appointments from the FHIR server…" />}
      {state.status === 'error' && <ErrorPanel error={state.error} />}
      {state.status === 'ready' && <Days entries={state.data} />}
    </main>
  )
}

function Days({ entries }: { entries: WorklistEntry[] }) {
  const today = todayIso()
  const days = new Map<string, WorklistEntry[]>()
  for (const entry of entries) {
    const day = entry.appointment?.start ? isoDay(entry.appointment.start) : ''
    days.set(day, [...(days.get(day) ?? []), entry])
  }
  return (
    <div className="space-y-6">
      {[...days].map(([day, list]) => (
        <section key={day || 'none'}>
          <h2 className="mb-2 flex items-baseline gap-2 text-sm font-semibold text-slate-700">
            {day ? formatWeekday(day) : 'No upcoming appointment'}
            {day && <span className="text-xs font-normal text-slate-500">{relativeDay(day, today)}</span>}
            <span className="text-xs font-normal text-slate-400">· {list.length} patients</span>
          </h2>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className={`${COLUMNS} border-b border-slate-100 bg-slate-50 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-500`}>
              <span>Time</span>
              <span>Patient</span>
              <span>Visit</span>
              <span>Active problems</span>
              <span className="text-right">Open orders</span>
            </div>
            <ul className="divide-y divide-slate-100">
              {list.map((entry) => (
                <Row key={entry.patient.id} entry={entry} today={today} />
              ))}
            </ul>
          </div>
        </section>
      ))}
    </div>
  )
}

function Row({ entry, today }: { entry: WorklistEntry; today: string }) {
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
          {entry.overdue > 0 && <Badge tone="rose">{entry.overdue} overdue</Badge>}
          {upcoming > 0 && <Badge>{upcoming} pending</Badge>}
          {entry.open === 0 && <span className="text-xs text-slate-400">None</span>}
        </span>
      </a>
    </li>
  )
}
