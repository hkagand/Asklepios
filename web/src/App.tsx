import { useEffect, useState } from 'react'
import { agentHealth, resetDemo, type AgentHealth } from './agent.ts'
import { ClinicianPicker, ClinicianProvider } from './components/clinician.tsx'
import { SourceProvider } from './components/source.tsx'
import { Badge } from './components/ui.tsx'
import { formatDate, formatWeekday, now, setClinicToday } from './format.ts'
import { useRoute } from './route.ts'
import { PatientView } from './views/PatientView.tsx'
import { MyDay } from './views/MyDay.tsx'
import { Onboard } from './views/Onboard.tsx'
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
        <TopBar page={route.page} fixedDay={clinicDay?.fixedToday ? clinicDay.today : undefined} canReset={clinicDay?.demoReset ?? false} />
        {route.page === 'patient' ? (
          <PatientView key={route.id} id={route.id} tab={route.tab} item={route.item} />
        ) : route.page === 'day' ? (
          <MyDay day={route.day} />
        ) : route.page === 'onboard' ? (
          <Onboard />
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

const RESET_NOTICE = 'demo-reset'

/** Puts the demo back to the synthetic data as loaded (agent/demo.py), then reloads the app from the worklist. */
function ResetDemo() {
  const [busy, setBusy] = useState(false)
  const reset = async () => {
    const sure = window.confirm(
      'Reset the demo?\n\nEverything done since the synthetic data was loaded is removed: onboarded patients and their ' +
        'imported history, visits and signed notes, review and "patient told" marks, and the national record ' +
        "service's consent codes. Every chart goes back to how it was loaded.",
    )
    if (!sure) return
    setBusy(true)
    try {
      const done = await resetDemo()
      const removed = Object.values(done.deleted).reduce((sum, count) => sum + count, 0)
      try {
        sessionStorage.setItem(RESET_NOTICE, `Demo reset in ${done.seconds} s: ${removed} record${removed === 1 ? '' : 's'} written during the demo removed, ${done.visits} visit${done.visits === 1 ? '' : 's'} cleared.`)
      } catch {
        // The notice is a courtesy; the reset is done either way.
      }
      window.location.hash = '#/'
      window.location.reload()
    } catch (failure) {
      setBusy(false)
      window.alert(`The demo reset failed: ${failure instanceof Error ? failure.message : String(failure)}`)
    }
  }
  return (
    <>
      <button
        type="button"
        onClick={reset}
        disabled={busy}
        title="Put every chart back to the synthetic data as loaded, to run the demo again"
        className="whitespace-nowrap rounded-md border border-slate-300 px-2.5 py-1 text-[13px] font-semibold text-slate-600 hover:border-slate-900 hover:text-slate-900 disabled:cursor-wait"
      >
        {busy ? 'Resetting…' : 'Reset demo'}
      </button>
      {busy && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-paper/80 backdrop-blur-sm" role="status">
          <p className="flex items-center gap-3 rounded-lg border border-slate-200 bg-sheet px-5 py-4 text-[15px] font-semibold text-slate-800 shadow-lg">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-800 motion-reduce:animate-none" />
            Resetting the demo to the data as loaded…
          </p>
        </div>
      )}
    </>
  )
}

/** After a reset, one line saying what it did; dismissed with a click. */
function ResetNotice() {
  const [text, setText] = useState<string | null>(() => {
    try {
      const found = sessionStorage.getItem(RESET_NOTICE)
      sessionStorage.removeItem(RESET_NOTICE)
      return found
    } catch {
      return null
    }
  })
  if (!text) return null
  return (
    <div className="border-b border-teal-200 bg-teal-50">
      <p className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2 text-[13.5px] text-teal-900 sm:px-6">
        <span className="min-w-0 flex-1">{text}</span>
        <button type="button" onClick={() => setText(null)} className="font-semibold hover:underline">
          Dismiss
        </button>
      </p>
    </div>
  )
}

function TopBar({ page, fixedDay, canReset }: { page: string; fixedDay?: string; canReset: boolean }) {
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
          {link('#/onboard', 'New patient', page === 'onboard')}
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
          {canReset && <ResetDemo />}
          <ClinicianPicker />
        </div>
      </div>
      <ResetNotice />
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
