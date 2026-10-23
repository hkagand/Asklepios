import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { attachmentText, code, refId, resourceUrl, type Resource } from '../fhir.ts'
import { patientHref } from '../route.ts'

const SourceContext = createContext<(resource: Resource) => void>(() => {})

export const useSource = () => useContext(SourceContext)

export function SourceProvider({ children }: { children: ReactNode }) {
  const [resource, setResource] = useState<Resource | null>(null)
  useEffect(() => {
    if (!resource) return
    const close = (event: KeyboardEvent) => event.key === 'Escape' && setResource(null)
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [resource])
  return (
    <SourceContext value={setResource}>
      {children}
      {resource && <SourceDrawer resource={resource} onClose={() => setResource(null)} />}
    </SourceContext>
  )
}

export function SourceButton({ resource, label }: { resource: Resource; label?: string }) {
  const open = useSource()
  return (
    <button
      type="button"
      title={`Show the FHIR source: ${resource.resourceType}/${resource.id}`}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        open(resource)
      }}
      className="inline-flex shrink-0 items-center gap-1 rounded px-1 py-0.5 text-[11px] font-medium text-slate-400 hover:bg-slate-100 hover:text-teal-700 focus-visible:outline-2 focus-visible:outline-teal-600"
    >
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
        <path d="M5.5 4 2 8l3.5 4M10.5 4 14 8l-3.5 4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label}
    </button>
  )
}

function documentText(resource: Resource): string | undefined {
  if (resource.resourceType === 'DocumentReference') return attachmentText(resource.content.map((content) => content.attachment))
  if (resource.resourceType === 'DiagnosticReport') return attachmentText(resource.presentedForm)
  return undefined
}

/** Where the resource is shown in the chart view, if it has a place there. */
function chartLink(resource: Resource): string | undefined {
  switch (resource.resourceType) {
    case 'Observation': {
      const patient = refId(resource.subject)
      const key = code(resource.component?.[0]?.code) ?? code(resource.code)
      return patient && key ? patientHref(patient, 'labs', key) : undefined
    }
    case 'DiagnosticReport': {
      const patient = refId(resource.subject)
      const lab = resource.category?.some((category) => code(category) === 'LAB')
      return patient && !lab && resource.id ? patientHref(patient, 'reports', resource.id) : undefined
    }
    case 'DocumentReference': {
      const patient = refId(resource.subject)
      const visit = refId(resource.context?.encounter?.[0]) ?? resource.id
      return patient && visit ? patientHref(patient, 'visits', visit) : undefined
    }
    case 'Encounter': {
      const patient = refId(resource.subject)
      return patient && resource.id ? patientHref(patient, 'visits', resource.id) : undefined
    }
  }
  return undefined
}

function SourceDrawer({ resource, onClose }: { resource: Resource; onClose: () => void }) {
  const decoded = documentText(resource)
  const link = chartLink(resource)
  const json = JSON.stringify(
    resource,
    (key, value) => (key === 'data' && typeof value === 'string' ? `<base64, ${value.length} characters${decoded ? ', decoded above' : ''}>` : value),
    2,
  )
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="FHIR source">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
        <header className="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">FHIR source</p>
            <p className="truncate font-mono text-sm text-slate-900">
              {resource.resourceType}/{resource.id}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {link && (
              <a href={link} onClick={onClose} className="rounded-md px-2 py-1 text-sm text-teal-700 hover:bg-teal-50">
                Show in chart
              </a>
            )}
            <a
              href={resourceUrl(resource)}
              target="_blank"
              rel="noreferrer"
              className="rounded-md px-2 py-1 text-sm text-teal-700 hover:bg-teal-50"
            >
              Open on server ↗
            </a>
            <button type="button" onClick={onClose} className="rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100">
              Close
            </button>
          </div>
        </header>
        <div className="flex-1 space-y-4 overflow-auto p-5">
          {decoded && (
            <section>
              <p className="mb-1 text-xs font-medium text-slate-500">Attachment text</p>
              <pre className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-800 ring-1 ring-slate-200">
                {decoded}
              </pre>
            </section>
          )}
          <section>
            <p className="mb-1 text-xs font-medium text-slate-500">Resource JSON</p>
            <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">{json}</pre>
          </section>
        </div>
      </aside>
    </div>
  )
}
