import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { setActingPractitioner } from '../agent.ts'
import { search } from '../fhir.ts'

export interface Clinician {
  id: string
  name: string
  specialty: string
}

interface ClinicianState {
  clinicians: Clinician[]
  current?: Clinician
  choose: (id: string | null) => void
}

const STORAGE_KEY = 'acting-practitioner'
const ClinicianContext = createContext<ClinicianState>({ clinicians: [], choose: () => {} })

/** Who is using the app. A demo stand-in for sign-in: it names the practitioner on marks and in the audit log. */
export const useClinician = () => useContext(ClinicianContext)

function stored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function ClinicianProvider({ children }: { children: ReactNode }) {
  const [clinicians, setClinicians] = useState<Clinician[]>([])
  const [currentId, setCurrentId] = useState<string | null>(() => {
    const id = stored()
    setActingPractitioner(id)
    return id
  })

  useEffect(() => {
    const controller = new AbortController()
    search<fhir4.Practitioner>('Practitioner', {}, controller.signal)
      .then((found) =>
        setClinicians(
          found
            .map((practitioner) => ({
              id: practitioner.id ?? '',
              name: practitioner.name?.[0]?.text ?? practitioner.id ?? '',
              specialty: practitioner.qualification?.[0]?.code?.text ?? '',
            }))
            .sort((a, b) => a.name.localeCompare(b.name, 'tr')),
        ),
      )
      .catch(() => {})
    return () => controller.abort()
  }, [])

  const choose = (id: string | null) => {
    setActingPractitioner(id)
    setCurrentId(id)
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id)
      else localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Private windows may refuse storage; the choice still holds for this page.
    }
  }

  const current = clinicians.find((clinician) => clinician.id === currentId)
  return <ClinicianContext value={{ clinicians, current, choose }}>{children}</ClinicianContext>
}

export function ClinicianPicker() {
  const { clinicians, current, choose } = useClinician()
  return (
    <label className="flex items-center gap-2 text-sm text-slate-500">
      <span className="hidden md:inline">Viewing as</span>
      <select
        value={current?.id ?? ''}
        onChange={(event) => choose(event.target.value || null)}
        title="Demo stand-in for sign-in: names you on review marks and in the audit log"
        className="max-w-[13rem] rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800 focus:border-teal-600 focus:outline-none focus:ring-1 focus:ring-teal-600"
      >
        <option value="">Choose clinician…</option>
        {clinicians.map((clinician) => (
          <option key={clinician.id} value={clinician.id}>
            {clinician.name} · {clinician.specialty}
          </option>
        ))}
      </select>
    </label>
  )
}
