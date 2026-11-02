import { useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { addJotting, cancelVisit, deleteJotting, editJotting, tickAgenda, type AgendaItem, type AgendaKind, type Jotting, type Visit } from '../agent.ts'
import { useSource } from '../components/source.tsx'
import { Badge, Card, type Tone } from '../components/ui.tsx'
import { read, type Resource } from '../fhir.ts'
import { formatTime } from '../format.ts'
import { resourceIndex, type Chart } from '../model.ts'
import { patientHref } from '../route.ts'

const KINDS: Record<AgendaKind, { label: string; tone: Tone }> = {
  reason: { label: 'Reason', tone: 'teal' },
  loop: { label: 'Open loop', tone: 'amber' },
  medication: { label: 'Medicine', tone: 'blue' },
  allergy: { label: 'Allergy', tone: 'rose' },
}

/** One visit: the agenda the record suggests, and the clinician's jottings, from which the note is drafted. */
export function VisitView({
  chart,
  visit,
  onChange,
  onStart,
  starting,
}: {
  chart: Chart
  visit: Visit | null
  onChange: (visit: Visit | null) => void
  onStart: () => void
  starting: boolean
}) {
  if (!visit || visit.status !== 'open') {
    return (
      <Card title="No visit in progress">
        <p className="text-[15px] text-slate-700">
          Start a visit to see an agenda from {chart.patient.name?.[0]?.text ?? 'the patient'}&apos;s record and keep short jottings
          as you talk. Asklepios drafts the visit note from them for you to edit and sign.
        </p>
        <button type="button" onClick={onStart} disabled={starting} className={`${PRIMARY} mt-4`}>
          {starting ? 'Starting…' : 'Start visit'}
        </button>
      </Card>
    )
  }
  return <Workspace chart={chart} visit={visit} onChange={onChange} />
}

const PRIMARY =
  'inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-[14px] font-bold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400'

function Workspace({ chart, visit, onChange }: { chart: Chart; visit: Visit; onChange: (visit: Visit | null) => void }) {
  const [error, setError] = useState<string>()
  const run = async (action: () => Promise<Visit>) => {
    setError(undefined)
    try {
      onChange(await action())
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }
  const cancel = async () => {
    if (!window.confirm('Close this visit without a note? Its jottings are kept on the agent but nothing is added to the chart.')) return
    await run(() => cancelVisit(visit.id))
    window.location.hash = patientHref(visit.patient)
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border-l-4 border-mark bg-sheet px-4 py-3">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-500 opacity-60 motion-reduce:hidden" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-teal-600" />
        </span>
        <p className="text-[14.5px] text-slate-800">
          <span className="font-bold">Visit in progress</span> · started {formatTime(visit.started)} by {visit.practitionerName}
          {visit.reason && <span className="text-slate-600"> · {visit.reason}</span>}
        </p>
        <button type="button" onClick={cancel} className="ml-auto text-[13.5px] font-semibold text-slate-500 hover:text-rose-700">
          Cancel visit
        </button>
      </div>
      {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
      <div className="grid items-start gap-4 @4xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <Agenda chart={chart} visit={visit} onTick={(item, done) => run(() => tickAgenda(visit.id, item.id, done))} />
        <Jottings
          visit={visit}
          onAdd={(text) => run(() => addJotting(visit.id, text))}
          onEdit={(jotting, text) => run(() => editJotting(visit.id, jotting.id, text))}
          onDelete={(jotting) => run(() => deleteJotting(visit.id, jotting.id))}
        />
      </div>
    </div>
  )
}

function Agenda({ chart, visit, onTick }: { chart: Chart; visit: Visit; onTick: (item: AgendaItem, done: boolean) => void }) {
  const resources = useMemo(() => resourceIndex(chart), [chart])
  const open = useSource()
  const covered = visit.agenda.filter((item) => item.done).length
  return (
    <Card title="Agenda from the record" subtitle={`${covered} of ${visit.agenda.length} covered · built from the chart, not suggested by the model`} flush>
      <ul className="divide-y divide-slate-100">
        {visit.agenda.map((item) => (
          <li key={item.id} className={`grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 px-4 py-2.5 ${item.done ? 'bg-slate-50/70' : ''}`}>
            <input
              type="checkbox"
              aria-label={`Covered: ${item.text}`}
              className="mt-1 h-4 w-4 accent-slate-900"
              checked={item.done}
              onChange={(event) => onTick(item, event.target.checked)}
            />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={KINDS[item.kind].tone}>{KINDS[item.kind].label}</Badge>
                {item.doneBy && item.doneBy !== 'clinician' && <span className="font-mono text-[11px] text-slate-400">from {item.doneBy}</span>}
              </div>
              <p className={`mt-1 text-[14px] leading-snug ${item.done ? 'text-slate-400 line-through decoration-slate-300' : 'text-slate-900'}`}>{item.text}</p>
              {item.detail && !item.done && <p className="mt-0.5 text-[12.5px] text-slate-500">{item.detail}</p>}
              {item.refs.length > 0 && !item.done && (
                <button
                  type="button"
                  onClick={async () => {
                    const [type, id] = item.refs[0].split('/')
                    open(resources.get(item.refs[0]) ?? (await read<Resource>(type as Resource['resourceType'], id)))
                  }}
                  className="mt-1 text-[12px] font-semibold text-teal-700 hover:underline"
                >
                  Show source
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Jottings({
  visit,
  onAdd,
  onEdit,
  onDelete,
}: {
  visit: Visit
  onAdd: (text: string) => Promise<void>
  onEdit: (jotting: Jotting, text: string) => Promise<void>
  onDelete: (jotting: Jotting) => Promise<void>
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)
  const submit = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true)
    await onAdd(text.trim())
    setText('')
    setBusy(false)
    input.current?.focus()
  }
  const keys = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submit()
    }
  }
  return (
    <Card title="Jottings" subtitle="Short lines as the patient talks. The note is drafted from these, so nothing else gets in." flush>
      {visit.jottings.length === 0 ? (
        <p className="px-4 py-4 text-[14px] text-slate-500">
          Nothing yet. For example: <span className="italic">“RUQ pain for 3 days, worse after fatty meals”</span>,{' '}
          <span className="italic">“no fever”</span>, <span className="italic">“BP 130/80”</span>,{' '}
          <span className="italic">“plan: refer to general surgery”</span>.
        </p>
      ) : (
        <ol className="divide-y divide-slate-100">
          {visit.jottings.map((jotting) => (
            <JottingRow key={jotting.id} jotting={jotting} onEdit={(value) => onEdit(jotting, value)} onDelete={() => onDelete(jotting)} />
          ))}
        </ol>
      )}
      <form onSubmit={submit} className="flex items-end gap-2 border-t border-slate-200 bg-paper/60 px-4 py-3">
        <textarea
          ref={input}
          rows={2}
          autoFocus
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={keys}
          placeholder="Type what the patient says or what you find… (Enter to add, Shift+Enter for a new line)"
          className="min-w-0 flex-1 resize-none rounded-md border border-slate-300 bg-sheet px-3 py-2 text-[14.5px] text-slate-900 focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
        />
        <button type="submit" disabled={!text.trim() || busy} className={PRIMARY}>
          Add
        </button>
      </form>
    </Card>
  )
}

function JottingRow({ jotting, onEdit, onDelete }: { jotting: Jotting; onEdit: (text: string) => Promise<void>; onDelete: () => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(jotting.text)
  return (
    <li className="group grid grid-cols-[3.25rem_minmax(0,1fr)_auto] items-start gap-x-3 px-4 py-2.5">
      <span className="pt-0.5 font-mono text-[12px] text-slate-400" title={jotting.id}>
        {formatTime(jotting.time)}
      </span>
      {editing ? (
        <form
          className="flex gap-2"
          onSubmit={async (event) => {
            event.preventDefault()
            if (value.trim()) await onEdit(value.trim())
            setEditing(false)
          }}
        >
          <input
            autoFocus
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className="min-w-0 flex-1 rounded-md border border-slate-300 bg-sheet px-2 py-1 text-[14.5px] focus:border-slate-900 focus:outline-none"
          />
          <button type="submit" className="text-[13px] font-semibold text-teal-700">
            Save
          </button>
        </form>
      ) : (
        <p className="whitespace-pre-wrap text-[14.5px] leading-snug text-slate-900">{jotting.text}</p>
      )}
      {!editing && (
        <span className="flex gap-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <button type="button" onClick={() => setEditing(true)} className="text-[12.5px] font-semibold text-slate-500 hover:text-slate-900">
            Edit
          </button>
          <button type="button" onClick={() => void onDelete()} className="text-[12.5px] font-semibold text-slate-500 hover:text-rose-700">
            Delete
          </button>
        </span>
      )}
    </li>
  )
}
