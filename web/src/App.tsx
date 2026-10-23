import { useEffect } from 'react'
import { SourceProvider } from './components/source.tsx'
import { Badge } from './components/ui.tsx'
import { formatWeekday } from './format.ts'
import { useRoute } from './route.ts'
import { PatientView } from './views/PatientView.tsx'
import { Worklist } from './views/Worklist.tsx'

export default function App() {
  const route = useRoute()
  const patientId = route.page === 'patient' ? route.id : undefined
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [patientId])
  return (
    <SourceProvider>
      <TopBar />
      {route.page === 'patient' ? (
        <PatientView key={route.id} id={route.id} tab={route.tab} item={route.item} />
      ) : (
        <Worklist />
      )}
    </SourceProvider>
  )
}

function TopBar() {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-6">
        <a href="#/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-teal-700">
            <svg viewBox="0 0 32 32" className="h-5 w-5" fill="none" stroke="white" strokeWidth="2.5" aria-hidden>
              <path d="M6 17h5l3-7 4 13 3-6h5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="font-semibold tracking-tight text-slate-900">Asklepios</span>
          <Badge tone="violet" title="Every record is synthetic and labelled HTEST (test health data)">
            Synthetic data
          </Badge>
        </a>
        <p className="hidden text-sm text-slate-500 sm:block">{formatWeekday(Date.now())} · Demo General Hospital</p>
      </div>
    </header>
  )
}
