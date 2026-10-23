import { useMemo, useState, type ReactNode } from 'react'
import { patientLoops, type Loop, type LoopStatus } from '../agent.ts'
import type { Resource } from '../fhir.ts'
import { formatDate } from '../format.ts'
import { resourceIndex, type Chart } from '../model.ts'
import { useAsync } from '../useAsync.ts'
import { SourceButton } from './source.tsx'
import { Badge, Card, Empty, type Tone } from './ui.tsx'

export const LOOP_STATUS: Record<LoopStatus, { label: string; tone: Tone; hint: string }> = {
  missing: { label: 'Not done', tone: 'rose', hint: 'The due date has passed and nothing was ordered, booked or resulted.' },
  dose_mismatch: {
    label: 'Other dose',
    tone: 'rose',
    hint: 'A medication order was written as planned, but at a different dose from the one in the plan.',
  },
  overdue: { label: 'Overdue', tone: 'rose', hint: 'Ordered or booked, but the due date has passed with no result.' },
  not_ordered: { label: 'Not ordered', tone: 'amber', hint: 'Planned, but nothing is ordered or booked yet.' },
  no_trace: { label: 'No record', tone: 'violet', hint: 'A call, meeting or step the record has no entry for. Check it another way.' },
  pending: { label: 'In progress', tone: 'blue', hint: 'Ordered or booked and not yet due.' },
  conditional: { label: 'If needed', tone: 'slate', hint: 'Only to be done if the stated condition arises.' },
  done: { label: 'Done', tone: 'teal', hint: 'The result, visit or change is on file.' },
}

const SECTIONS: { title: string; statuses: LoopStatus[] }[] = [
  { title: 'Needs action', statuses: ['missing', 'dose_mismatch', 'overdue', 'not_ordered'] },
  { title: 'Cannot be confirmed from the record', statuses: ['no_trace'] },
  { title: 'In progress', statuses: ['pending'] },
]
const CLOSED: LoopStatus[] = ['done', 'conditional']

const SOURCE_LABELS: Record<string, string> = {
  DocumentReference: 'Note',
  ServiceRequest: 'Order',
  Observation: 'Result',
  DiagnosticReport: 'Report',
  Appointment: 'Appointment',
  Encounter: 'Visit',
  MedicationRequest: 'Medication',
}

/** Each clinician's latest plan and the open orders, checked against the record by the agent service.
 * Shows `fallback` (the plain open orders) when the service cannot be reached. */
export function OpenLoops({ chart, fallback }: { chart: Chart; fallback: ReactNode }) {
  const id = chart.patient.id ?? ''
  const state = useAsync((signal) => patientLoops(id, signal), [id])
  const resources = useMemo(() => resourceIndex(chart), [chart])
  const [showClosed, setShowClosed] = useState(false)

  if (state.status === 'error') {
    return (
      <div>
        {fallback}
        <p className="mt-1.5 px-1 text-xs text-slate-500">Open loops are not available: {state.error.message}</p>
      </div>
    )
  }
  const loops = state.status === 'ready' ? state.data.loops : []
  const closed = loops.filter((loop) => CLOSED.includes(loop.status))
  const unread = state.status === 'ready' ? state.data.unread.length : 0
  return (
    <Card
      title="Open loops"
      subtitle="What each clinician's latest note planned, and open orders, checked against the record"
      flush
    >
      {state.status === 'loading' && (
        <div className="flex items-center gap-2 px-4 py-3 text-sm text-slate-500">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-teal-700" />
          Checking the plans against the record…
        </div>
      )}
      {state.status === 'ready' && loops.length === closed.length && (
        <div className="px-4 py-3">
          <Empty>Nothing outstanding.</Empty>
        </div>
      )}
      {SECTIONS.map(({ title, statuses }) => {
        const items = loops.filter((loop) => statuses.includes(loop.status))
        return items.length === 0 ? null : (
          <section key={title} className="border-b border-slate-100 last:border-b-0">
            <h3 className="px-4 pt-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{title}</h3>
            <ul className="divide-y divide-slate-100">
              {items.map((loop, index) => (
                <LoopRow key={index} loop={loop} resources={resources} />
              ))}
            </ul>
          </section>
        )
      })}
      {state.status === 'ready' && (
        <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-xs text-slate-500">
          {closed.length > 0 && (
            <button type="button" onClick={() => setShowClosed(!showClosed)} className="font-medium text-teal-700 hover:underline">
              {showClosed ? 'Hide' : 'Show'} {closed.length} done or conditional
            </button>
          )}
          {unread > 0 && <span className="text-amber-700">The plan in {unread} note(s) could not be read.</span>}
          <span>Plans are read from the notes by the language model; dates and matching come from the record.</span>
        </footer>
      )}
      {showClosed && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {closed.map((loop, index) => (
            <LoopRow key={index} loop={loop} resources={resources} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function LoopRow({ loop, resources }: { loop: Loop; resources: Map<string, Resource> }) {
  const status = LOOP_STATUS[loop.status]
  const refs = [...(loop.note ? [loop.note] : []), ...loop.evidence]
  const planned = loop.noteDate
    ? `Planned ${formatDate(loop.noteDate)}${loop.author ? ` by ${loop.author}` : ''}`
    : `Open ${loop.kind} order`
  return (
    <li className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-x-3 gap-y-1 px-4 py-2.5 sm:grid-cols-[6rem_minmax(0,1fr)_auto]">
      <div className="pt-0.5">
        <Badge tone={status.tone} title={status.hint}>
          {status.label}
        </Badge>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-900">
          <Highlighted line={loop.line} quote={loop.quote} />
        </p>
        <p className="text-xs text-slate-500">
          {planned}
          {loop.due && ` · due ${formatDate(loop.due)}`}
        </p>
        {loop.parts.length > 0 ? (
          <ul className="mt-1 space-y-0.5">
            {loop.parts.map((part, index) => (
              <li key={index} className="flex items-baseline gap-1.5 text-xs text-slate-600">
                <span className={`h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full ${DOTS[LOOP_STATUS[part.status].tone]}`} />
                <span>
                  <span className="font-medium text-slate-700">{part.name}</span>: {part.detail}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-0.5 text-xs text-slate-600">{capitalise(loop.detail)}</p>
        )}
      </div>
      <div className="col-start-2 -ml-1 flex flex-wrap gap-0.5 sm:col-start-auto sm:ml-0 sm:max-w-[16rem] sm:justify-end">
        {refs.map((ref) => {
          const resource = resources.get(ref)
          return resource ? <SourceButton key={ref} resource={resource} label={SOURCE_LABELS[resource.resourceType]} /> : null
        })}
      </div>
    </li>
  )
}

/** The note line, with the words this item is about set apart from the rest of the line. */
function Highlighted({ line, quote }: { line: string; quote: string }) {
  const words = quote.replace(/[\s.;,]+$/, '')
  const at = line.toLowerCase().indexOf(words.toLowerCase())
  if (at < 0 || words.length >= line.replace(/[\s.;,]+$/, '').length) return line
  const end = at + words.length
  return (
    <>
      <span className="font-normal text-slate-500">{line.slice(0, at)}</span>
      {line.slice(at, end)}
      <span className="font-normal text-slate-500">{line.slice(end)}</span>
    </>
  )
}

const DOTS: Record<Tone, string> = {
  rose: 'bg-rose-500',
  amber: 'bg-amber-500',
  violet: 'bg-violet-500',
  blue: 'bg-blue-500',
  slate: 'bg-slate-400',
  teal: 'bg-teal-500',
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)
