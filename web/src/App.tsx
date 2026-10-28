import { useEffect, useState } from 'react'
import { agentHealth, type AgentHealth } from './agent.ts'
import { ClinicianPicker, ClinicianProvider } from './components/clinician.tsx'
import { SourceProvider } from './components/source.tsx'
import { Badge } from './components/ui.tsx'
import { formatDate, formatWeekday, now, setClinicToday } from './format.ts'
import { useRoute } from './route.ts'
import { PatientView } from './views/PatientView.tsx'
import { MyDay } from './views/MyDay.tsx'
import { Worklist } from './views/Worklist.tsx'

export default function App() {
  const route = useRoute()
  const patientId = route.page === 'patient' ? route.id : undefined
  const clinicDay = useClinicDay()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [patientId])
  // Wait for the agent's clinic day, so nothing renders with the wrong "today" first.
  if (clinicDay === undefined) return null
  return (
    <ClinicianProvider>
      <SourceProvider>
        <TopBar page={route.page} fixedDay={clinicDay?.fixedToday ? clinicDay.today : undefined} />
        {route.page === 'patient' ? (
          <PatientView key={route.id} id={route.id} tab={route.tab} item={route.item} />
        ) : route.page === 'day' ? (
          <MyDay day={route.day} />
        ) : (
          <Worklist />
        )}
      </SourceProvider>
    </ClinicianProvider>
  )
}

/** The agent's clinic day, applied to the clock; null when the agent does not answer within two seconds. */
function useClinicDay(): AgentHealth | null | undefined {
  const [health, setHealth] = useState<AgentHealth | null | undefined>(undefined)
  useEffect(() => {
    let current = true
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 2000)
    agentHealth(controller.signal)
      .then((found) => {
        if (!current) return
        if (found.fixedToday) setClinicToday(found.today)
        setHealth(found)
      })
      .catch(() => current && setHealth(null))
      .finally(() => clearTimeout(timer))
    return () => {
      current = false
      clearTimeout(timer)
      controller.abort()
    }
  }, [])
  return health
}

function TopBar({ page, fixedDay }: { page: string; fixedDay?: string }) {
  const link = (href: string, label: string, active: boolean) => (
    <a
      href={href}
      aria-current={active ? 'page' : undefined}
      className={`relative whitespace-nowrap px-1 py-1 text-[14px] font-semibold ${
        active
          ? 'text-slate-900 after:absolute after:inset-x-1 after:-bottom-0.5 after:h-[3px] after:bg-mark'
          : 'text-slate-500 hover:text-slate-900'
      }`}
    >
      {label}
    </a>
  )
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-paper/95 backdrop-blur">
      <div className="mx-auto flex min-h-14 max-w-7xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 sm:px-6">
        <a href="#/day" className="flex items-center gap-2.5" aria-label="Asklepios, my day">
          <RodOfAsclepius />
          <span className="hidden text-[17px] font-extrabold tracking-[-0.02em] text-slate-900 sm:inline">Asklepios</span>
        </a>
        <nav className="flex items-center gap-4" aria-label="Pages">
          {link('#/day', 'My day', page === 'day')}
          {link('#/', 'All appointments', page === 'worklist')}
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <span className="hidden text-[13px] text-slate-500 xl:block">
            {formatWeekday(now())}, Demo General Hospital
          </span>
          {fixedDay && (
            <Badge tone="amber" title="AGENT_TODAY fixes the clinic day, so the demo cohort reads as it was loaded">
              Demo date {formatDate(fixedDay)}
            </Badge>
          )}
          <span className="hidden md:inline-flex">
            <Badge tone="violet" title="Every record is synthetic and labelled HTEST (test health data)">
              Synthetic data
            </Badge>
          </span>
          <ClinicianPicker />
        </div>
      </div>
    </header>
  )
}

/** A staff with one serpent: the sign of Asklepios (not the two-snake caduceus). */
function RodOfAsclepius() {
  return (
    <span className="grid h-8 w-8 place-items-center rounded-md bg-slate-900" aria-hidden>
      <svg viewBox="0 0 32 32" className="h-6 w-6" fill="none" strokeLinecap="round">
        <path d="M16 5v22" stroke="var(--color-mark)" strokeWidth="2.4" />
        <path d="M19.5 8.5c-3.8-.4-6.2 1.6-3.5 3.6 2.9 2.2 3.2 4.3-.4 5.6-3.3 1.2-2.9 3.6.4 4.6" stroke="white" strokeWidth="2" />
      </svg>
    </span>
  )
}
