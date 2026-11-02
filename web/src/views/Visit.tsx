import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  addJotting,
  cancelVisit,
  deleteJotting,
  draftNote,
  editJotting,
  makeConsiderations,
  rateConsideration,
  signNote,
  tickAgenda,
  visitConsiderations,
  type AgendaItem,
  type AgendaKind,
  type Consideration,
  type ConsiderationKind,
  type ConsiderationsState,
  type Jotting,
  type NoteDraft,
  type NoteSection,
  type Visit,
} from '../agent.ts'
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
const SECTIONS: Record<NoteSection, { letter: string; label: string }> = {
  subjective: { letter: 'S', label: 'Subjective: what the patient reports' },
  objective: { letter: 'O', label: 'Objective: findings, measurements, results' },
  assessment: { letter: 'A', label: 'Assessment: your impression' },
  plan: { letter: 'P', label: 'Plan: what will be done' },
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
  if (visit?.status === 'signed') return <Signed visit={visit} />
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
  // Jottings sent but not yet back from review; each answer replaces the visit only if it is newer.
  const [pending, setPending] = useState<string[]>([])
  const latest = useRef(visit.version)
  const apply = (next: Visit) => {
    if (next.version >= latest.current) {
      latest.current = next.version
      onChange(next)
    }
  }
  const run = async (action: () => Promise<Visit>) => {
    setError(undefined)
    try {
      apply(await action())
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }
  const add = async (text: string) => {
    setPending((items) => [...items, text])
    await run(() => addJotting(visit.id, text))
    setPending((items) => {
      const at = items.indexOf(text)
      return items.filter((_, index) => index !== at)
    })
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
        <div className="space-y-4">
          <Agenda chart={chart} visit={visit} onTick={(item, done) => run(() => tickAgenda(visit.id, item.id, done))} />
          <Considerations chart={chart} visit={visit} />
        </div>
        <Jottings
          chart={chart}
          visit={visit}
          pending={pending}
          onAdd={add}
          onEdit={(jotting, text) => run(() => editJotting(visit.id, jotting.id, text))}
          onDelete={(jotting) => run(() => deleteJotting(visit.id, jotting.id))}
        />
      </div>
      <NoteCard visit={visit} pending={pending.length > 0} run={run} />
    </div>
  )
}

const ORDER: NoteSection[] = ['subjective', 'objective', 'assessment', 'plan']
const TITLES: Record<NoteSection, string> = { subjective: 'Subjective', objective: 'Objective', assessment: 'Assessment', plan: 'Plan' }

/** A section's text for editing: the plan as "- " lines, the rest as one paragraph (as the agent writes the note). */
function textsOf(draft: NoteDraft): Record<NoteSection, string> {
  return Object.fromEntries(
    ORDER.map((section) => [
      section,
      section === 'plan'
        ? draft.sections.plan.map((item) => `- ${item.text}`).join('\n')
        : draft.sections[section].map((item) => item.text).join(' '),
    ]),
  ) as Record<NoteSection, string>
}

/** The note: drafted from the jottings, every line traced to its sources and checked; edited and signed by the clinician. */
function NoteCard({ visit, pending, run }: { visit: Visit; pending: boolean; run: (action: () => Promise<Visit>) => Promise<void> }) {
  const draft = visit.draft
  const [texts, setTexts] = useState<Record<NoteSection, string>>()
  const [shownDraft, setShownDraft] = useState<string>()
  const [busy, setBusy] = useState<'drafting' | 'signing'>()
  if (draft && draft.created !== shownDraft) {
    setShownDraft(draft.created)
    setTexts(textsOf(draft))
  }
  // Names for what a drafted line cites: jottings by id, record items by the label their link chip shows.
  const labels = new Map<string, string>(
    visit.jottings.flatMap((jotting) => (jotting.review?.links ?? []).map((link) => [link.ref, link.label] as [string, string])),
  )
  const flagged = draft ? ORDER.flatMap((section) => draft.sections[section]).filter((item) => item.issues.length > 0).length : 0
  // Allergy and dose alerts from the jottings, repeated where the note is signed.
  const alerts = visit.jottings.flatMap((jotting) => (jotting.review?.alerts ?? []).map((alert) => [jotting.id, alert.text] as [string, string]))
  const changed =
    !!draft && (draft.jottings.length !== visit.jottings.length || draft.jottings.some((id, index) => visit.jottings[index]?.id !== id))
  const act = async (kind: 'drafting' | 'signing', action: () => Promise<Visit>) => {
    setBusy(kind)
    await run(action)
    setBusy(undefined)
  }
  const sign = () => {
    if (!texts || !window.confirm(`Sign this note as ${visit.practitionerName}? It is added to the chart and the visit is closed.`)) return
    void act('signing', () => signNote(visit.id, texts))
  }

  return (
    <Card
      title="Visit note"
      subtitle={
        draft
          ? `Drafted at ${formatTime(draft.created)} from ${draft.jottings.length} jottings · edit as needed, then sign`
          : 'Drafted from your jottings only; every line shows what it came from'
      }
      action={
        draft && (
          <button
            type="button"
            onClick={() => void act('drafting', () => draftNote(visit.id))}
            disabled={!!busy || pending}
            className="text-[13px] font-semibold text-teal-700 hover:underline disabled:text-slate-400"
          >
            {busy === 'drafting' ? 'Drafting…' : 'Draft again'}
          </button>
        )
      }
    >
      {!draft || !texts ? (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={PRIMARY}
            disabled={visit.jottings.length === 0 || !!busy || pending}
            onClick={() => void act('drafting', () => draftNote(visit.id))}
          >
            {busy === 'drafting'
              ? 'Drafting the note…'
              : `Draft the note from ${visit.jottings.length} jotting${visit.jottings.length === 1 ? '' : 's'}`}
          </button>
          {pending && <span className="text-[13px] text-slate-500">Waiting for the last jotting to be read…</span>}
        </div>
      ) : (
        <div className="space-y-4">
          {(flagged > 0 || draft.unused.length > 0 || changed) && (
            <div className="rounded-md border-l-4 border-amber-500 bg-amber-50 px-3 py-2 text-[13.5px] text-amber-900">
              {changed && <p className="font-semibold">The jottings changed after this draft: draft again to include them.</p>}
              {flagged > 0 && (
                <p>
                  {flagged} drafted line{flagged === 1 ? '' : 's'} to check: marked below.
                </p>
              )}
              {draft.unused.length > 0 && <p>Not in the draft: {draft.unused.join(', ')}. Add them by hand or draft again.</p>}
            </div>
          )}
          {ORDER.map((section) => (
            <div key={section}>
              <label className="block">
                <span className="text-[12.5px] font-bold uppercase tracking-wide text-slate-600">{TITLES[section]}</span>
                <textarea
                  value={texts[section]}
                  rows={Math.max(2, texts[section].split('\n').length + (section === 'plan' ? 0 : Math.ceil(texts[section].length / 110)))}
                  onChange={(event) => setTexts({ ...texts, [section]: event.target.value })}
                  placeholder={section === 'plan' ? 'One action per line, starting with "- "' : 'Nothing recorded'}
                  className="mt-1 w-full rounded-md border border-slate-300 bg-sheet px-3 py-2 text-[14.5px] leading-relaxed text-slate-900 focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
                />
              </label>
              {draft.sections[section].length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {draft.sections[section].map((item, index) => (
                    <li key={index} className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-slate-500">
                      <span className="max-w-[40ch] truncate" title={item.text}>
                        {item.text}
                      </span>
                      <span aria-hidden>←</span>
                      {item.sources.map((source) => (
                        <span key={source} className="rounded-sm bg-mark-soft px-1 font-semibold text-slate-700">
                          {source.startsWith('J') ? source : (labels.get(source) ?? source)}
                        </span>
                      ))}
                      {item.issues.map((issue) => (
                        <span key={issue} className="rounded-sm bg-amber-100 px-1 font-semibold text-amber-900">
                          ⚠ {issue}
                        </span>
                      ))}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {alerts.length > 0 && (
            <div className="rounded-md border-l-4 border-rose-500 bg-rose-50 px-3 py-2 text-[13.5px] text-rose-900">
              <p className="font-semibold">Raised during this visit, check before signing:</p>
              <ul className="mt-0.5 list-disc pl-5">
                {alerts.map(([id, text]) => (
                  <li key={id + text}>
                    {text} <span className="font-mono text-[12px] text-rose-700">({id})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-3">
            <button type="button" className={PRIMARY} disabled={!!busy || pending} onClick={sign}>
              {busy === 'signing' ? 'Signing…' : `Sign note as ${visit.practitionerName}`}
            </button>
            <span className="text-[12.5px] text-slate-500">
              Saved to the chart with you as author; a provenance record says Asklepios drafted it from your jottings.
            </span>
          </div>
        </div>
      )}
    </Card>
  )
}

function Signed({ visit }: { visit: Visit }) {
  // The patient page reads the chart again once the visit closes, so the note is there without reloading the page.
  return (
    <Card title="Note signed">
      <p className="text-[15px] text-slate-700">
        The visit note is in the chart, signed by {visit.practitionerName}, and the visit is closed. Its plan is tracked in open loops
        from now on.
      </p>
      <a href={patientHref(visit.patient, 'visits', visit.id)} className={`${PRIMARY} mt-4`}>
        Open the note
      </a>
    </Card>
  )
}

/** Opens a record item in the source drawer, reading it from the server if the chart in memory lacks it. */
function useOpenRef(chart: Chart) {
  const resources = useMemo(() => resourceIndex(chart), [chart])
  const open = useSource()
  return async (reference: string) => {
    const [type, id] = reference.split('/')
    open(resources.get(reference) ?? (await read<Resource>(type as Resource['resourceType'], id)))
  }
}

function Agenda({ chart, visit, onTick }: { chart: Chart; visit: Visit; onTick: (item: AgendaItem, done: boolean) => void }) {
  const openRef = useOpenRef(chart)
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
                {item.doneBy && item.doneBy !== 'clinician' && (
                  <span className="font-mono text-[11px] text-slate-500" title="Ticked from this jotting">
                    ✓ {item.doneBy}
                  </span>
                )}
              </div>
              <p className={`mt-1 text-[14px] leading-snug ${item.done ? 'text-slate-400 line-through decoration-slate-300' : 'text-slate-900'}`}>{item.text}</p>
              {item.detail && !item.done && <p className="mt-0.5 text-[12.5px] text-slate-500">{item.detail}</p>}
              {item.refs.length > 0 && !item.done && (
                <button type="button" onClick={() => void openRef(item.refs[0])} className="mt-1 text-[12px] font-semibold text-teal-700 hover:underline">
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

const CONSIDERATION: Record<ConsiderationKind, { label: string; tone: Tone }> = {
  cause: { label: 'Possible cause', tone: 'violet' },
  check: { label: 'Worth checking', tone: 'blue' },
  caution: { label: 'Caution', tone: 'amber' },
}

/** Suggestions from the second, clinical model (agent/considerations.py), shown only when one is configured. They
 * are for the clinician to weigh: never added to the note, and the code alerts on the jottings stay the safety net. */
function Considerations({ chart, visit }: { chart: Chart; visit: Visit }) {
  const [state, setState] = useState<ConsiderationsState>()
  const [error, setError] = useState<string>()
  const [asking, setAsking] = useState(false)
  const openRef = useOpenRef(chart)
  // Read again whenever the visit changes (a jotting added, edited or deleted), then every second and a half while a
  // run works on the jottings in the background.
  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    const read = async () => {
      try {
        const next = await visitConsiderations(visit.id, controller.signal)
        setState(next)
        setError(undefined)
        if (next.running) timer = window.setTimeout(read, 1500)
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure))
      }
    }
    void read()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [visit.id, visit.version])

  const act = async (action: () => Promise<ConsiderationsState>) => {
    setError(undefined)
    try {
      setState(await action())
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }
  const askAgain = async () => {
    setAsking(true)
    await act(() => makeConsiderations(visit.id))
    setAsking(false)
  }

  if (!state?.enabled) return null
  const result = state.considerations
  const items = result?.status === 'done' ? (result.items ?? []) : []
  const dropped = result?.dropped ?? []
  const working = state.running || asking
  return (
    <Card
      title="Clinical considerations"
      subtitle={`From ${state.model}, a second model. Suggestions to weigh, not checked facts; never added to the note.`}
      action={<Badge tone="violet">Experimental</Badge>}
      flush
    >
      {working && (
        <p className="flex items-center gap-1.5 border-b border-slate-100 px-4 py-2 text-[12px] text-slate-500">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700 motion-reduce:animate-none" />
          Reading the jottings as they stand…
        </p>
      )}
      {!working && result && !state.current && visit.jottings.length > 0 && (
        <p className="border-b border-slate-100 px-4 py-2 text-[12px] text-amber-800">Made from earlier jottings.</p>
      )}
      {error && <p className="px-4 py-2 text-[12.5px] text-rose-800">{error}</p>}
      {visit.jottings.length === 0 ? (
        <p className="px-4 py-3 text-[13.5px] text-slate-500">Considerations appear here after the first jottings.</p>
      ) : result?.status === 'failed' ? (
        <p className="px-4 py-3 text-[13px] text-slate-600">The clinical model did not answer usably: {result.error}</p>
      ) : result && items.length === 0 && !working ? (
        <p className="px-4 py-3 text-[13.5px] text-slate-500">Nothing to raise from the jottings so far.</p>
      ) : (
        <ul className={`divide-y divide-slate-100 ${working ? 'opacity-60' : ''}`}>
          {items.map((item, index) => (
            <ConsiderationRow
              key={`${index}-${item.text}`}
              item={item}
              onOpen={openRef}
              onRate={(useful) => act(() => rateConsideration(visit.id, index, item.text, useful))}
            />
          ))}
        </ul>
      )}
      {visit.jottings.length > 0 && (
        <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 px-4 py-2 text-[12px] text-slate-500">
          <button type="button" onClick={askAgain} disabled={working} className="font-semibold text-teal-700 hover:underline disabled:text-slate-400 disabled:no-underline">
            Ask again
          </button>
          {result?.seconds !== undefined && <span>{result.seconds} s</span>}
          {dropped.length > 0 && (
            <details className="w-full">
              <summary className="cursor-pointer select-none">
                {dropped.length} dropped by the checks
              </summary>
              <ul className="mt-1 space-y-1">
                {dropped.map((item) => (
                  <li key={item.text}>
                    <span className="text-slate-600">{item.text}</span> <span className="font-semibold">({item.reason})</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </footer>
      )}
    </Card>
  )
}

function ConsiderationRow({
  item,
  onOpen,
  onRate,
}: {
  item: Consideration
  onOpen: (reference: string) => Promise<void>
  onRate: (useful: boolean) => Promise<void>
}) {
  const kind = CONSIDERATION[item.kind]
  return (
    <li className="px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={kind.tone}>{kind.label}</Badge>
        {item.alerted && (
          <span className="text-[11.5px] font-semibold text-slate-500" title="A record item it cites already raised an alert on a jotting">
            also an alert above
          </span>
        )}
      </div>
      <p className="mt-1 text-[14px] leading-snug text-slate-900">{item.text}</p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {item.basis.map((source) =>
          source.ref ? (
            <button
              key={source.id}
              type="button"
              title={source.ref}
              onClick={() => void onOpen(source.ref!)}
              className="inline-flex max-w-full items-center rounded-sm bg-mark-soft px-1.5 text-[11.5px] font-semibold leading-[19px] text-slate-800 hover:bg-mark"
            >
              <span className="truncate">{source.label}</span>
            </button>
          ) : (
            <span
              key={source.id}
              title={source.label}
              className="inline-flex items-center rounded-sm border border-slate-300 px-1.5 font-mono text-[11px] leading-[17px] text-slate-600"
            >
              {source.id}
            </span>
          ),
        )}
      </div>
      <div className="mt-1.5 flex gap-3 text-[12px] font-semibold">
        {(['useful', 'not-useful'] as const).map((verdict) => (
          <button
            key={verdict}
            type="button"
            aria-pressed={item.feedback === verdict}
            onClick={() => void onRate(verdict === 'useful')}
            className={item.feedback === verdict ? 'text-slate-900 underline decoration-mark decoration-2 underline-offset-2' : 'text-slate-400 hover:text-slate-700'}
          >
            {verdict === 'useful' ? 'Useful' : 'Not useful'}
          </button>
        ))}
      </div>
    </li>
  )
}

function Jottings({
  chart,
  visit,
  pending,
  onAdd,
  onEdit,
  onDelete,
}: {
  chart: Chart
  visit: Visit
  pending: string[]
  onAdd: (text: string) => Promise<void>
  onEdit: (jotting: Jotting, text: string) => Promise<void>
  onDelete: (jotting: Jotting) => Promise<void>
}) {
  const [text, setText] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const openRef = useOpenRef(chart)
  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (!text.trim()) return
    // The box clears at once: the next line can be typed while this one is reviewed.
    void onAdd(text.trim())
    setText('')
    input.current?.focus()
  }
  const keys = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }
  const empty = visit.jottings.length === 0 && pending.length === 0
  return (
    <Card title="Jottings" subtitle="Short lines as the patient talks. The note is drafted from these, so nothing else gets in." flush>
      {empty ? (
        <p className="px-4 py-4 text-[14px] text-slate-500">
          Nothing yet. For example: <span className="italic">“RUQ pain for 3 days, worse after fatty meals”</span>,{' '}
          <span className="italic">“no fever”</span>, <span className="italic">“BP 130/80”</span>,{' '}
          <span className="italic">“plan: refer to general surgery”</span>.
        </p>
      ) : (
        <ol className="divide-y divide-slate-100">
          {visit.jottings.map((jotting) => (
            <JottingRow
              key={jotting.id}
              jotting={jotting}
              onOpen={openRef}
              onEdit={(value) => onEdit(jotting, value)}
              onDelete={() => onDelete(jotting)}
            />
          ))}
          {pending
            .filter((line) => !visit.jottings.some((jotting) => jotting.text === line))
            .map((line, index) => (
              <li key={`pending-${index}`} className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-x-3 px-4 py-2.5">
                <span className="pt-0.5 font-mono text-[12px] text-slate-300">…</span>
                <div>
                  <p className="text-[14.5px] leading-snug text-slate-900">{line}</p>
                  <Reviewing />
                </div>
              </li>
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
        <button type="submit" disabled={!text.trim()} className={PRIMARY}>
          Add
        </button>
      </form>
    </Card>
  )
}

function Reviewing() {
  return (
    <p className="mt-1 flex items-center gap-1.5 text-[12px] text-slate-400">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700 motion-reduce:animate-none" />
      Asklepios is reading it…
    </p>
  )
}

function JottingRow({
  jotting,
  onOpen,
  onEdit,
  onDelete,
}: {
  jotting: Jotting
  onOpen: (reference: string) => Promise<void>
  onEdit: (text: string) => Promise<void>
  onDelete: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(jotting.text)
  const review = jotting.review
  const section = review?.section ? SECTIONS[review.section] : undefined
  return (
    <li className="group grid grid-cols-[3.25rem_minmax(0,1fr)_auto] items-start gap-x-3 px-4 py-2.5">
      <span className="flex flex-col items-start gap-1 pt-0.5">
        <span className="font-mono text-[12px] text-slate-400" title={jotting.id}>
          {formatTime(jotting.time)}
        </span>
        {section && (
          <span
            title={section.label}
            className="grid h-5 w-5 place-items-center rounded-sm bg-slate-900 font-mono text-[11px] font-bold text-white"
          >
            {section.letter}
          </span>
        )}
      </span>
      <div className="min-w-0">
        {editing ? (
          <form
            className="flex gap-2"
            onSubmit={async (event) => {
              event.preventDefault()
              setEditing(false)
              if (value.trim() && value.trim() !== jotting.text) await onEdit(value.trim())
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
        {review?.status === 'pending' && <Reviewing />}
        {review?.alerts?.map((alert) => (
          <p
            key={alert.text}
            className={`mt-1.5 flex items-start gap-2 rounded-md px-2.5 py-1.5 text-[13px] font-semibold ${
              alert.kind === 'allergy' ? 'bg-rose-50 text-rose-800' : 'bg-amber-50 text-amber-900'
            }`}
          >
            <span aria-hidden>{alert.kind === 'allergy' ? '⚠' : '≠'}</span>
            <span className="min-w-0 flex-1">{alert.text}</span>
            {alert.refs[0] && (
              <button type="button" onClick={() => void onOpen(alert.refs[0])} className="shrink-0 text-[12px] font-semibold underline">
                Source
              </button>
            )}
          </p>
        ))}
        {(review?.links?.length ?? 0) > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {review!.links!.map((link) => (
              <button
                key={link.ref}
                type="button"
                title={link.ref}
                onClick={() => void onOpen(link.ref)}
                className="inline-flex max-w-full items-center rounded-sm bg-mark-soft px-1.5 text-[11.5px] font-semibold leading-[19px] text-slate-800 hover:bg-mark"
              >
                <span className="truncate">{link.label}</span>
              </button>
            ))}
          </div>
        )}
        {(review?.gaps?.length ?? 0) > 0 && (
          <p className="mt-1.5 text-[12.5px] text-slate-500">
            <span className="font-semibold text-slate-600">Not recorded yet:</span> {review!.gaps!.join(' · ')}
          </p>
        )}
        {review?.status === 'failed' && <p className="mt-1 text-[12px] text-slate-400">Asklepios could not read this jotting; it is kept as written.</p>}
      </div>
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
