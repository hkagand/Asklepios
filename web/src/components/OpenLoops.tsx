import { useMemo, useState, type ReactNode } from 'react'
import {
  markCommunicated,
  markReviewed,
  patientLoops,
  withdrawMark,
  type Loop,
  type LoopPart,
  type LoopStatus,
  type Medium,
  type Stage,
} from '../agent.ts'
import type { Resource } from '../fhir.ts'
import { formatDate, formatDayMonth, todayIso } from '../format.ts'
import { resourceIndex, type Chart } from '../model.ts'
import { useAsync } from '../useAsync.ts'
import { useClinician } from './clinician.tsx'
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
  to_review: { label: 'To review', tone: 'amber', hint: 'The result is on file but no clinician has reviewed it.' },
  not_ordered: { label: 'Not ordered', tone: 'amber', hint: 'Planned, but nothing is ordered or booked yet.' },
  no_trace: { label: 'No record', tone: 'violet', hint: 'A call, meeting or step the record has no entry for. Check it another way.' },
  to_inform: { label: 'Tell patient', tone: 'blue', hint: 'Reviewed, but nothing records that the patient was told.' },
  pending: { label: 'In progress', tone: 'slate', hint: 'Ordered or booked and not yet due.' },
  conditional: { label: 'If needed', tone: 'slate', hint: 'Only to be done if the stated condition arises.' },
  done: { label: 'Done', tone: 'teal', hint: 'Done; for a test, reviewed and the patient told.' },
}

const SECTIONS: { title: string; statuses: LoopStatus[] }[] = [
  { title: 'Needs action', statuses: ['missing', 'dose_mismatch', 'overdue', 'not_ordered'] },
  { title: 'Results to review or tell the patient', statuses: ['to_review', 'to_inform'] },
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

const STAGE_LABELS: Record<Stage['stage'], string> = {
  ordered: 'Ordered',
  performed: 'Performed',
  resulted: 'Resulted',
  reviewed: 'Reviewed',
  communicated: 'Patient told',
}

const MEDIUMS: [Medium, string][] = [
  ['in_person', 'In person'],
  ['phone', 'Phone'],
  ['video', 'Video'],
  ['letter', 'Letter'],
  ['portal', 'Patient portal'],
]

/** Each clinician's latest plan, open orders and new results, checked against the record by the agent service.
 * Shows `fallback` (the plain open orders) when the service cannot be reached. */
export function OpenLoops({ chart, fallback }: { chart: Chart; fallback: ReactNode }) {
  const id = chart.patient.id ?? ''
  const [version, setVersion] = useState(0)
  const state = useAsync((signal) => patientLoops(id, signal), [id, version])
  const resources = useMemo(() => resourceIndex(chart), [chart])
  const [showClosed, setShowClosed] = useState(false)
  const [loops, setLoops] = useState<Loop[] | undefined>()
  if (state.status === 'ready' && state.data.loops !== loops) setLoops(state.data.loops)

  if (state.status === 'error') {
    return (
      <div>
        {fallback}
        <p className="mt-1.5 px-1 text-xs text-slate-500">Open loops are not available: {state.error.message}</p>
      </div>
    )
  }
  // Keep showing the last list while a refresh after a mark is loading.
  const shown = loops ?? []
  const closed = shown.filter((loop) => CLOSED.includes(loop.status))
  const unread = state.status === 'ready' ? state.data.unread.length : 0
  const refresh = () => setVersion((value) => value + 1)
  return (
    <Card
      title="Open loops"
      subtitle="Plans in each clinician's latest note, open orders and new results, checked against the record"
      flush
    >
      {loops === undefined && (
        <div className="flex items-center gap-2 px-4 py-3 text-sm text-slate-500">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-teal-700" />
          Checking the plans against the record…
        </div>
      )}
      {loops !== undefined && shown.length === closed.length && (
        <div className="px-4 py-3">
          <Empty>Nothing outstanding.</Empty>
        </div>
      )}
      {SECTIONS.map(({ title, statuses }) => {
        const items = shown.filter((loop) => statuses.includes(loop.status))
        return items.length === 0 ? null : (
          <section key={title} className="border-b border-slate-100 last:border-b-0">
            <h3 className="px-4 pt-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{title}</h3>
            <ul className="divide-y divide-slate-100">
              {items.map((loop) => (
                <LoopRow key={loopKey(loop)} patientId={id} loop={loop} resources={resources} onChange={refresh} />
              ))}
            </ul>
          </section>
        )
      })}
      {loops !== undefined && (
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
          {closed.map((loop) => (
            <LoopRow key={loopKey(loop)} patientId={id} loop={loop} resources={resources} onChange={refresh} />
          ))}
        </ul>
      )}
    </Card>
  )
}

const loopKey = (loop: Loop) => `${loop.source}:${loop.note ?? ''}:${loop.quote}:${loop.evidence.join(',')}`

/** The parts of an item, or the item itself when it has one. */
const pieces = (loop: Loop): (Loop | LoopPart)[] => (loop.parts.length > 0 ? loop.parts : [loop])

const targetsOf = (loop: Loop, status: LoopStatus) =>
  pieces(loop)
    .filter((piece) => piece.status === status && piece.target)
    .map((piece) => piece.target as string)

function LoopRow({
  patientId,
  loop,
  resources,
  onChange,
}: {
  patientId: string
  loop: Loop
  resources: Map<string, Resource>
  onChange: () => void
}) {
  const status = LOOP_STATUS[loop.status]
  const refs = [...(loop.note ? [loop.note] : []), ...loop.evidence]
  const planned = loop.noteDate
    ? `Planned ${formatDate(loop.noteDate)}${loop.author ? ` by ${loop.author}` : ''}`
    : loop.source === 'result'
      ? 'New result since the last visit'
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
          <ul className="mt-1 space-y-1">
            {loop.parts.map((part, index) => (
              <li key={index} className="text-xs text-slate-600">
                <span className="flex items-baseline gap-1.5">
                  <span className={`h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full ${DOTS[LOOP_STATUS[part.status].tone]}`} />
                  <span>
                    <span className="font-medium text-slate-700">{part.name}</span>: {part.detail}
                  </span>
                </span>
                {part.stages.length > 0 && <Stages stages={part.stages} compact />}
              </li>
            ))}
          </ul>
        ) : (
          <>
            <p className="mt-0.5 text-xs text-slate-600">{capitalise(loop.detail)}</p>
            {loop.stages.length > 0 && <Stages stages={loop.stages} />}
          </>
        )}
        <Actions patientId={patientId} loop={loop} onChange={onChange} />
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

/** Ordered → performed → resulted → reviewed → patient told, with dates; inferred steps in italics. */
function Stages({ stages, compact = false }: { stages: Stage[]; compact?: boolean }) {
  return (
    <ol className={`flex flex-wrap items-center gap-x-1 gap-y-1 ${compact ? 'mt-0.5 pl-3' : 'mt-1.5'}`}>
      {stages.map((stage, index) => {
        const title = [
          STAGE_LABELS[stage.stage],
          stage.at && formatDate(stage.at),
          stage.by && `by ${stage.by}`,
          stage.note,
          stage.inferred && 'inferred from a later visit note that quotes the result',
        ]
          .filter(Boolean)
          .join(' · ')
        return (
          <li key={stage.stage} className="flex items-center gap-1">
            {index > 0 && <span className="text-[10px] text-slate-300">→</span>}
            <span
              title={title}
              className={`inline-flex items-center gap-1 rounded px-1.5 py-px text-[11px] ${
                stage.done ? 'bg-teal-50 text-teal-800' : 'bg-slate-50 text-slate-400 ring-1 ring-inset ring-slate-200'
              } ${stage.inferred ? 'italic' : ''}`}
            >
              <span aria-hidden>{stage.done ? '✓' : '○'}</span>
              {STAGE_LABELS[stage.stage]}
              {stage.done && stage.at && !compact && <span className="text-teal-700/70">{formatDayMonth(stage.at)}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

/** Mark the item's results reviewed, record that the patient was told, or undo one's own mark. */
function Actions({ patientId, loop, onChange }: { patientId: string; loop: Loop; onChange: () => void }) {
  const { current } = useClinician()
  const [telling, setTelling] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const toReview = targetsOf(loop, 'to_review')
  const toInform = targetsOf(loop, 'to_inform')
  // One communication can cover several results, so the same mark may appear on more than one part.
  const mine = [
    ...new Set(
      pieces(loop)
        .flatMap((piece) => piece.stages)
        .filter((stage) => stage.done && !stage.inferred && current && stage.by === current.name)
        .flatMap((stage) => stage.refs.filter((ref) => ref.startsWith('Task/') || ref.startsWith('Communication/'))),
    ),
  ]
  if (toReview.length === 0 && toInform.length === 0 && mine.length === 0) return null

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(undefined)
    try {
      await action()
      setTelling(false)
      onChange()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem))
    } finally {
      setBusy(false)
    }
  }

  if (!current) {
    return <p className="mt-1.5 text-xs text-slate-500">Choose who is viewing (top right) to mark results reviewed.</p>
  }
  return (
    <div className="mt-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {toReview.length > 0 && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => markReviewed(patientId, toReview))}
            className="rounded-md bg-teal-700 px-2 py-1 text-xs font-medium text-white hover:bg-teal-800 disabled:opacity-50"
          >
            Mark reviewed
          </button>
        )}
        {toInform.length > 0 && !telling && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setTelling(true)}
            className="rounded-md border border-teal-300 px-2 py-1 text-xs font-medium text-teal-800 hover:bg-teal-50 disabled:opacity-50"
          >
            Patient told…
          </button>
        )}
        {mine.length > 0 && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(async () => Promise.all(mine.map((mark) => withdrawMark(patientId, mark))))}
            title="Withdraws your review and communication marks on this item (kept as entered-in-error)"
            className="text-xs text-slate-500 hover:text-rose-700 hover:underline disabled:opacity-50"
          >
            Undo my marks
          </button>
        )}
      </div>
      {telling && (
        <TellForm busy={busy} onCancel={() => setTelling(false)} onSave={(medium, sent, note) => void run(() => markCommunicated(patientId, toInform, medium, sent, note))} />
      )}
      {error && <p className="mt-1 text-xs text-rose-700">{error}</p>}
    </div>
  )
}

function TellForm({
  busy,
  onCancel,
  onSave,
}: {
  busy: boolean
  onCancel: () => void
  onSave: (medium: Medium, sent: string, note?: string) => void
}) {
  const today = todayIso()
  const [medium, setMedium] = useState<Medium>('in_person')
  const [sent, setSent] = useState(today)
  const [note, setNote] = useState('')
  const field = 'rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-800 focus:border-teal-600 focus:outline-none'
  return (
    <form
      className="mt-1.5 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200"
      onSubmit={(event) => {
        event.preventDefault()
        onSave(medium, sent, note.trim() || undefined)
      }}
    >
      <select value={medium} onChange={(event) => setMedium(event.target.value as Medium)} className={field} aria-label="How">
        {MEDIUMS.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <input type="date" value={sent} max={today} onChange={(event) => setSent(event.target.value)} className={field} aria-label="When" />
      <input
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Note (optional)"
        maxLength={1000}
        className={`${field} min-w-0 flex-1`}
      />
      <button type="submit" disabled={busy || !sent} className="rounded-md bg-teal-700 px-2 py-1 text-xs font-medium text-white hover:bg-teal-800 disabled:opacity-50">
        Save
      </button>
      <button type="button" onClick={onCancel} className="text-xs text-slate-500 hover:underline">
        Cancel
      </button>
    </form>
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

/** Counts of a patient's open loops as badges, worst first; "None" when nothing is open or pending. */
export function LoopBadges({ statuses }: { statuses: Partial<Record<LoopStatus, number>> }) {
  const late = (statuses.missing ?? 0) + (statuses.overdue ?? 0)
  const badges: [number, Tone, string, string][] = [
    [late, 'rose', `${late} late`, 'Overdue, or due and never ordered'],
    [statuses.dose_mismatch ?? 0, 'rose', `${statuses.dose_mismatch} other dose`, LOOP_STATUS.dose_mismatch.hint],
    [statuses.to_review ?? 0, 'amber', `${statuses.to_review} to review`, LOOP_STATUS.to_review.hint],
    [statuses.not_ordered ?? 0, 'amber', `${statuses.not_ordered} to order`, LOOP_STATUS.not_ordered.hint],
    [statuses.no_trace ?? 0, 'violet', `${statuses.no_trace} unconfirmed`, LOOP_STATUS.no_trace.hint],
    [statuses.to_inform ?? 0, 'blue', `${statuses.to_inform} to tell`, LOOP_STATUS.to_inform.hint],
    [statuses.pending ?? 0, 'slate', `${statuses.pending} pending`, LOOP_STATUS.pending.hint],
  ]
  const shown = badges.filter(([count]) => count > 0)
  if (shown.length === 0) return <span className="text-xs text-slate-400">None</span>
  return shown.map(([, tone, label, hint]) => (
    <Badge key={label} tone={tone} title={hint}>
      {label}
    </Badge>
  ))
}
