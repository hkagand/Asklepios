import { useState, type ReactNode } from 'react'
import { Copilot, SparkIcon } from '../components/Copilot.tsx'
import { SourceButton } from '../components/source.tsx'
import { ErrorPanel, Loading } from '../components/ui.tsx'
import { isSynthetic, medicalRecordNumber, patientName, text } from '../fhir.ts'
import { ageOn, formatDate, formatTime, isoDay, relativeDay, sexLabel, todayIso } from '../format.ts'
import { loadChart, nextAppointment, openOrders, participant, timeline, type Chart } from '../model.ts'
import { patientHref, type Tab } from '../route.ts'
import { useAsync } from '../useAsync.ts'
import { Labs } from './Labs.tsx'
import { Medications } from './Medications.tsx'
import { Overview } from './Overview.tsx'
import { Reports } from './Reports.tsx'
import { Visits } from './Visits.tsx'

export function PatientView({ id, tab, item }: { id: string; tab: Tab; item?: string }) {
  const state = useAsync((signal) => loadChart(id, signal), [id])
  const [copilot, setCopilot] = useStoredFlag('copilot-open')
  return (
    <div className="flex items-start">
      <main className="mx-auto min-w-0 max-w-7xl flex-1 px-4 pb-16 pt-4 sm:px-6">
        <a href="#/" className="text-[13.5px] font-semibold text-slate-500 hover:text-slate-900">
          ← All appointments
        </a>
        {state.status === 'loading' && <Loading label="Loading the chart from the FHIR server…" />}
        {state.status === 'error' && <ErrorPanel error={state.error} />}
        {state.status === 'ready' && (
          <>
            <PatientHeader chart={state.data} />
            <TabBar chart={state.data} tab={tab} copilot={copilot} onCopilot={() => setCopilot(!copilot)} />
            <div className="@container mt-4">
              {tab === 'overview' && <Overview chart={state.data} />}
              {tab === 'labs' && <Labs chart={state.data} selected={item} />}
              {tab === 'visits' && <Visits chart={state.data} selected={item} />}
              {tab === 'reports' && <Reports chart={state.data} selected={item} />}
              {tab === 'medications' && <Medications chart={state.data} />}
            </div>
          </>
        )}
      </main>
      {copilot && state.status === 'ready' && (
        <aside
          aria-label="ASKlepios"
          className="fixed bottom-0 right-0 top-14 z-30 w-full max-w-md border-l border-slate-200 shadow-xl lg:sticky lg:z-auto lg:h-[calc(100vh-3.5rem)] lg:w-[26rem] lg:max-w-none lg:shrink-0 lg:shadow-none"
        >
          <Copilot chart={state.data} onClose={() => setCopilot(false)} />
        </aside>
      )}
    </div>
  )
}

function useStoredFlag(key: string): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(() => localStorage.getItem(key) === '1')
  const update = (next: boolean) => {
    localStorage.setItem(key, next ? '1' : '0')
    setValue(next)
  }
  return [value, update]
}

function PatientHeader({ chart }: { chart: Chart }) {
  const { patient } = chart
  const today = todayIso()
  const next = nextAppointment(chart.appointments, today)
  const when = next?.start ? relativeDay(isoDay(next.start), today) : ''
  const allergies = chart.allergies.map((allergy) => text(allergy.code)).filter(Boolean)
  const known = allergies.filter((name) => !/no known/i.test(name))
  return (
    <header className="mt-3 overflow-hidden rounded-lg bg-slate-900 text-white">
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3 px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="text-[26px] font-extrabold leading-tight tracking-[-0.02em]">{patientName(patient)}</h1>
            <span className="[&_button]:text-slate-300 [&_button:hover]:bg-white/10 [&_button:hover]:text-white">
              <SourceButton resource={patient} />
            </span>
            {isSynthetic(patient) && (
              <span className="rounded-sm border border-violet-300/60 px-1.5 text-[11.5px] font-semibold text-violet-200" title="Labelled HTEST (test health data)">
                Synthetic record
              </span>
            )}
          </div>
          <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-[14px]">
            <Fact label="Age">
              {ageOn(patient.birthDate, today)}, {sexLabel(patient.gender).toLowerCase()}
            </Fact>
            <Fact label="MRN">
              <span className="font-mono">{medicalRecordNumber(patient)}</span>
            </Fact>
            <Fact label="Born">{formatDate(patient.birthDate)}</Fact>
            {patient.address?.[0]?.city && <Fact label="Lives in">{patient.address[0].city}</Fact>}
            {patient.generalPractitioner?.[0]?.display && <Fact label="GP">{patient.generalPractitioner[0].display}</Fact>}
          </dl>
        </div>
        {next?.start && (
          <div className="flex max-w-md items-start gap-2 border-l-2 border-mark pl-4">
            <div className="min-w-0">
              <p className="text-[12.5px] font-semibold text-mark">Next appointment, {when}</p>
              <p className="mt-0.5 text-[14px] font-semibold">
                {formatDate(next.start)} at {formatTime(next.start)} with {participant(next, 'Practitioner')?.display}
              </p>
              <p className="mt-0.5 text-[13.5px] text-slate-300">{next.description}</p>
            </div>
            <span className="[&_button]:text-slate-300 [&_button:hover]:bg-white/10 [&_button:hover]:text-white">
              <SourceButton resource={next} />
            </span>
          </div>
        )}
      </div>
      <div
        className={`flex flex-wrap items-center gap-x-2 px-5 py-1.5 text-[13.5px] font-semibold ${
          known.length ? 'bg-rose-600 text-white' : 'bg-slate-800 text-slate-300'
        }`}
      >
        <span>Allergies:</span>
        <span className={known.length ? '' : 'font-normal'}>
          {known.length ? known.join(', ') : allergies.length ? allergies.join(', ') : 'Not recorded'}
        </span>
        {chart.allergies.map((allergy) => (
          <span key={allergy.id} className="[&_button]:text-current [&_button:hover]:bg-white/10">
            <SourceButton resource={allergy} />
          </span>
        ))}
      </div>
    </header>
  )
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-[12.5px] text-slate-400">{label}</dt>
      <dd className="font-semibold text-white">{children}</dd>
    </div>
  )
}

function TabBar({ chart, tab, copilot, onCopilot }: { chart: Chart; tab: Tab; copilot: boolean; onCopilot: () => void }) {
  const id = chart.patient.id ?? ''
  const awaiting = openOrders(chart).length
  const tabs: [Tab, string, number | undefined][] = [
    ['overview', 'Overview', awaiting || undefined],
    ['labs', 'Labs & vitals', chart.labs.length],
    ['visits', 'Visits & notes', timeline(chart).length],
    ['reports', 'Reports', chart.reports.length],
    ['medications', 'Medications', chart.medications.filter((medication) => medication.status === 'active').length],
  ]
  return (
    <nav className="mt-4 flex flex-wrap items-end gap-x-5 gap-y-1 border-b border-slate-300" aria-label="Chart sections">
      {tabs.map(([key, label, count]) => (
        <a
          key={key}
          href={patientHref(id, key)}
          aria-current={key === tab ? 'page' : undefined}
          className={`relative flex items-center gap-1.5 py-2.5 text-[14.5px] font-semibold ${
            key === tab
              ? 'text-slate-900 after:absolute after:inset-x-0 after:-bottom-px after:h-[3px] after:bg-slate-900'
              : 'text-slate-500 hover:text-slate-900'
          }`}
        >
          {label}
          {count !== undefined && (
            <span
              title={key === 'overview' ? 'Open orders' : undefined}
              className={`font-mono text-[12px] ${key === 'overview' ? 'mark-soft text-amber-800' : 'text-slate-400'}`}
            >
              {count}
            </span>
          )}
        </a>
      ))}
      <button
        type="button"
        onClick={onCopilot}
        aria-pressed={copilot}
        className={`mb-2 ml-auto inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[14px] font-bold ${
          copilot ? 'bg-mark text-slate-900' : 'bg-slate-900 text-white hover:bg-slate-800'
        }`}
      >
        <SparkIcon className={`h-4 w-4 ${copilot ? 'text-slate-900' : 'text-mark'}`} />
        {copilot ? 'ASKlepios open' : 'Ask ASKlepios'}
      </button>
    </nav>
  )
}