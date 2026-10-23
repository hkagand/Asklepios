import { useState } from 'react'
import { Copilot, SparkIcon } from '../components/Copilot.tsx'
import { SourceButton } from '../components/source.tsx'
import { Badge, ErrorPanel, Loading } from '../components/ui.tsx'
import { isSynthetic, medicalRecordNumber, patientName } from '../fhir.ts'
import { ageOn, formatDate, formatTime, isoDay, relativeDay, sexLabel, todayIso } from '../format.ts'
import { loadChart, nextAppointment, openOrders, participant, timeline, type Chart } from '../model.ts'
import { patientHref, type Tab } from '../route.ts'
import { useAsync } from '../useAsync.ts'
import { Labs } from './Labs.tsx'
import { Overview } from './Overview.tsx'
import { Reports } from './Reports.tsx'
import { Visits } from './Visits.tsx'

export function PatientView({ id, tab, item }: { id: string; tab: Tab; item?: string }) {
  const state = useAsync((signal) => loadChart(id, signal), [id])
  const [copilot, setCopilot] = useStoredFlag('copilot-open')
  return (
    <div className="flex items-start">
      <main className="mx-auto min-w-0 max-w-7xl flex-1 px-6 pb-16 pt-4">
        <a href="#/" className="text-sm text-slate-500 hover:text-teal-700">
          ← Worklist
        </a>
        {state.status === 'loading' && <Loading label="Loading the chart from the FHIR server…" />}
        {state.status === 'error' && <ErrorPanel error={state.error} />}
        {state.status === 'ready' && (
          <>
            <PatientHeader chart={state.data} />
            <TabBar chart={state.data} tab={tab} copilot={copilot} onCopilot={() => setCopilot(!copilot)} />
            <div className="mt-4">
              {tab === 'overview' && <Overview chart={state.data} />}
              {tab === 'labs' && <Labs chart={state.data} selected={item} />}
              {tab === 'visits' && <Visits chart={state.data} selected={item} />}
              {tab === 'reports' && <Reports chart={state.data} selected={item} />}
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
  return (
    <header className="mt-3 flex flex-wrap items-start justify-between gap-4 rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{patientName(patient)}</h1>
          <SourceButton resource={patient} />
          {isSynthetic(patient) && (
            <Badge tone="violet" title="Labelled HTEST (test health data)">
              Synthetic record
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-700">
          {ageOn(patient.birthDate, today)} y · {sexLabel(patient.gender)} · MRN{' '}
          <span className="font-medium">{medicalRecordNumber(patient)}</span> · Born {formatDate(patient.birthDate)}
        </p>
        <p className="mt-0.5 text-sm text-slate-500">
          {patient.address?.[0]?.city} · GP {patient.generalPractitioner?.[0]?.display}
        </p>
      </div>
      {next?.start && (
        <div className="flex max-w-md items-start gap-2 rounded-lg bg-teal-50 px-4 py-3 ring-1 ring-teal-100">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-teal-800">Next appointment · {when}</p>
            <p className="mt-0.5 text-sm font-medium text-slate-900">
              {formatDate(next.start)}, {formatTime(next.start)} · {participant(next, 'Practitioner')?.display}
            </p>
            <p className="mt-0.5 text-sm text-slate-600">{next.description}</p>
          </div>
          <SourceButton resource={next} />
        </div>
      )}
    </header>
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
  ]
  return (
    <nav className="mt-4 flex items-end gap-1 border-b border-slate-200" aria-label="Chart sections">
      {tabs.map(([key, label, count]) => (
        <a
          key={key}
          href={patientHref(id, key)}
          aria-current={key === tab ? 'page' : undefined}
          className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
            key === tab ? 'border-teal-700 text-teal-800' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          {label}
          {count !== undefined && (
            <span
              title={key === 'overview' ? 'Open orders' : undefined}
              className={`rounded-full px-1.5 text-[11px] ${key === 'overview' ? 'bg-amber-100 text-amber-800' : 'bg-slate-200/70 text-slate-600'}`}
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
        className={`mb-1.5 ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium shadow-sm ${
          copilot ? 'bg-teal-50 text-teal-800 ring-1 ring-teal-200' : 'bg-teal-700 text-white hover:bg-teal-800'
        }`}
      >
        <SparkIcon />
        ASKlepios
      </button>
    </nav>
  )
}
