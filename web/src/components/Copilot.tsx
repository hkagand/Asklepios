import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { agentHealth, ask, patientBrief, type AgentEvent, type Answer, type Block, type PreparedBrief, type Step } from '../agent.ts'
import { formatDate, formatTime } from '../format.ts'
import { read, type Resource } from '../fhir.ts'
import { epicrisisFacts, isEpicrisis, resourceIndex, type Chart } from '../model.ts'
import { useAsync } from '../useAsync.ts'
import { useSource } from './source.tsx'
import { Badge } from './ui.tsx'

const STARTERS = [
  'Brief me for today’s visit',
  'What changed since the last visit?',
  'What is pending or overdue?',
  'Summarise the treatment history',
]

interface Turn {
  id: number
  question: string
  steps: Step[]
  answer?: Answer
  error?: string
  running: boolean
}

/** Chat about the open patient. Every answer comes from the agent service with verified citations. */
export function Copilot({ chart, onClose }: { chart: Chart; onClose: () => void }) {
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const controller = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const health = useAsync(agentHealth, [])
  const prepared = useAsync((signal) => patientBrief(chart.patient.id ?? '', signal), [chart.patient.id])
  const resources = useMemo(() => resourceIndex(chart), [chart])
  const running = turns.at(-1)?.running ?? false
  const firstName = chart.patient.name?.[0]?.given?.[0] ?? 'this patient'

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [turns])
  useEffect(() => () => controller.current?.abort(), [])

  const update = (id: number, change: (turn: Turn) => Turn) =>
    setTurns((list) => list.map((turn) => (turn.id === id ? change(turn) : turn)))

  async function send(question: string) {
    const text = question.trim()
    if (!text || running) return
    const id = Date.now()
    const abort = new AbortController()
    controller.current = abort
    setDraft('')
    setTurns((list) => [...list, { id, question: text, steps: [], running: true }])
    try {
      await ask(chart.patient.id ?? '', sessionId, text, (event) => update(id, (turn) => apply(turn, event)), abort.signal)
      update(id, (turn) => (turn.running ? { ...turn, running: false, error: 'The agent stopped without an answer.' } : turn))
    } catch (error) {
      const message = abort.signal.aborted ? 'Stopped.' : error instanceof Error ? error.message : String(error)
      update(id, (turn) => ({ ...turn, running: false, error: message }))
    }
  }

  function restart() {
    controller.current?.abort()
    setTurns([])
    setSessionId(crypto.randomUUID())
  }

  return (
    <div className="flex h-full flex-col bg-sheet">
      <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-slate-900 text-mark">
            <SparkIcon />
          </span>
          <div className="min-w-0">
            <p className="text-[15px] font-extrabold tracking-[-0.01em] text-slate-900">ASKlepios</p>
            <p className="truncate text-xs text-slate-500">
              Reads only {firstName}’s record{health.status === 'ready' && ` · ${health.data.model}`}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {turns.length > 0 && (
            <button type="button" onClick={restart} className="rounded-md px-2 py-1 text-xs text-slate-600 hover:bg-slate-100">
              New chat
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close ASKlepios"
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <path d="m4 4 8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </header>

      <div ref={scroller} className="flex-1 space-y-6 overflow-y-auto px-4 py-4">
        {prepared.status === 'ready' && prepared.data.brief && (
          <PreparedBriefView brief={prepared.data.brief} resources={resources} />
        )}
        {health.status === 'error' && (
          <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800 ring-1 ring-rose-200">{health.error.message}</p>
        )}
        {turns.length === 0 ? (
          <Intro firstName={firstName} onPick={(question) => void send(question)} />
        ) : (
          turns.map((turn) => <TurnView key={turn.id} turn={turn} resources={resources} />)
        )}
      </div>

      <form
        className="border-t border-slate-200 p-3"
        onSubmit={(event) => {
          event.preventDefault()
          void send(draft)
        }}
      >
        <div className="flex items-end gap-2 rounded-md border border-slate-300 bg-sheet py-1.5 pl-3 pr-1.5 focus-within:border-slate-900 focus-within:ring-1 focus-within:ring-slate-900">
          <textarea
            value={draft}
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send(draft)
              }
            }}
            placeholder={`Ask about ${firstName}’s record…`}
            className="field-sizing-content max-h-40 min-h-8 flex-1 resize-none bg-transparent py-1 text-sm text-slate-900 outline-none placeholder:text-slate-400"
          />
          {running ? (
            <button
              type="button"
              onClick={() => controller.current?.abort()}
              className="rounded-md bg-slate-100 px-3 py-1.5 text-[14px] font-semibold text-slate-700 hover:bg-slate-200"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim()}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-[14px] font-bold text-white hover:bg-slate-800 disabled:bg-slate-200 disabled:text-slate-400"
            >
              Ask
            </button>
          )}
        </div>
        <p className="mt-2 text-[11px] leading-snug text-slate-400">
          Answers use only this record and can be incomplete or wrong. Check the cited sources before acting on them.
        </p>
      </form>
    </div>
  )
}

/** The brief prepared before the clinic (agent/briefs.py), shown above the conversation. */
function PreparedBriefView({ brief, resources }: { brief: NonNullable<PreparedBrief['brief']>; resources: Map<string, Resource> }) {
  const [open, setOpen] = useState(true)
  return (
    <section className="rounded-md border-l-[3px] border-mark bg-paper p-3">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-baseline justify-between gap-2 text-left">
        <span className="text-[13px] font-bold text-slate-900">Prepared brief</span>
        <span className="text-[11px] text-slate-500">
          {formatDate(brief.preparedAt)} {formatTime(brief.preparedAt)} {open ? '▴' : '▾'}
        </span>
      </button>
      {!brief.current && (
        <p className="mt-1.5 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800 ring-1 ring-amber-200">
          The chart has changed since this brief was prepared. Prepare it again from My day, or ask below.
        </p>
      )}
      {open && (
        <div className="mt-2">
          <AnswerView answer={brief.answer} resources={resources} rows={false} />
        </div>
      )}
    </section>
  )
}

function apply(turn: Turn, event: AgentEvent): Turn {
  if (event.type === 'step') return { ...turn, steps: [...turn.steps, event.step] }
  if (event.type === 'answer') return { ...turn, answer: event.answer, running: false }
  return { ...turn, error: event.message, running: false }
}

function Intro({ firstName, onPick }: { firstName: string; onPick: (question: string) => void }) {
  return (
    <div>
      <p className="text-sm leading-relaxed text-slate-700">
        Ask about {firstName}’s history, results, treatments and anything still pending. Every statement links to the
        part of the record it came from.
      </p>
      <p className="mt-5 text-[12.5px] font-semibold text-slate-500">Try asking</p>
      <div className="mt-2 flex flex-col items-start gap-2">
        {STARTERS.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onPick(question)}
            className="rounded-md border border-slate-300 bg-sheet px-3 py-1.5 text-left text-[13.5px] font-semibold text-slate-800 hover:border-slate-900 hover:bg-mark-soft"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  )
}

function TurnView({ turn, resources }: { turn: Turn; resources: Map<string, Resource> }) {
  return (
    <section>
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-lg rounded-br-sm bg-slate-900 px-3.5 py-2 text-[14px] text-white">
          {turn.question}
        </p>
      </div>
      <div className="mt-3">
        {turn.running && <Progress steps={turn.steps} />}
        {turn.answer && <AnswerView answer={turn.answer} resources={resources} />}
        {turn.error && (
          <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800 ring-1 ring-rose-200">{turn.error}</p>
        )}
      </div>
    </section>
  )
}

function Progress({ steps }: { steps: Step[] }) {
  return (
    <ul className="space-y-1.5 text-xs text-slate-500">
      {steps.map((step, index) => (
        <li key={index} className="flex items-start gap-2">
          <CheckIcon />
          <span>{step.label}</span>
        </li>
      ))}
      <li className="flex items-center gap-2">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
        {steps.length === 0 ? 'Reading the chart…' : 'Working…'}
      </li>
    </ul>
  )
}

/** `rows` false draws every bullet plainly, as the prepared brief does: a briefing is read whole, not opened row by row. */
function AnswerView({ answer, resources, rows = true }: { answer: Answer; resources: Map<string, Resource>; rows?: boolean }) {
  const [showHidden, setShowHidden] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const hidden = answer.blocks.filter((block) => block.status === 'unsupported').length
  const shown = (block: Block) => showHidden || block.status !== 'unsupported'
  const sources = Object.keys(answer.sources).length
  return (
    <div>
      <div className="space-y-2 text-[14px] leading-relaxed text-slate-800">
        {group(answer.blocks).map((item, index) =>
          Array.isArray(item) ? (
            <BulletList key={index} entries={item} rows={rows} shown={shown} answer={answer} resources={resources} />
          ) : !shown(item) ? null : item.kind === 'heading' ? (
            <p key={index} className="pt-1.5 text-[13px] font-bold text-slate-900">
              <BlockContent block={item} answer={answer} resources={resources} />
            </p>
          ) : (
            <p key={index}>
              <BlockContent block={item} answer={answer} resources={resources} />
            </p>
          ),
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
        <button type="button" onClick={() => setShowSteps(!showSteps)} className="hover:text-slate-600">
          {sources > 0 && `${sources} ${sources === 1 ? 'source' : 'sources'} · `}
          {answer.steps.length === 0
            ? 'Answered from the chart index'
            : `${answer.steps.length} ${answer.steps.length === 1 ? 'lookup' : 'lookups'}`}{' '}
          ·{' '}
          {(answer.elapsedMs / 1000).toFixed(1)} s {answer.steps.length > 0 && (showSteps ? '▴' : '▾')}
        </button>
        {hidden > 0 && (
          <button type="button" onClick={() => setShowHidden(!showHidden)} className="text-rose-600 hover:text-rose-800">
            {showHidden ? 'Hide' : 'Show'} {hidden} unverified {hidden === 1 ? 'statement' : 'statements'}
          </button>
        )}
      </div>
      {showSteps && (
        <ul className="mt-1.5 space-y-1 text-xs text-slate-500">
          {answer.steps.map((step, index) => (
            <li key={index} className="flex items-start gap-2">
              <CheckIcon />
              <span>{step.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** A bullet of an answer; a bullet written as a row has the indented bullets under it as its details. */
interface Entry {
  block: Block
  details: Block[]
}

/** Consecutive bullets become one list, and in it the indented bullets under a row become that row's details. */
function group(blocks: Block[]): (Block | Entry[])[] {
  const items: (Block | Entry[])[] = []
  for (const block of blocks) {
    const last = items.at(-1)
    if (block.kind !== 'bullet') items.push(block)
    else if (!Array.isArray(last)) items.push([{ block, details: [] }])
    else if (block.level > 0 && last.at(-1)?.block.row) last.at(-1)!.details.push(block)
    else last.push({ block, details: [] })
  }
  return items
}

function BulletList({
  entries,
  rows,
  shown,
  answer,
  resources,
}: {
  entries: Entry[]
  rows: boolean
  shown: (block: Block) => boolean
  answer: Answer
  resources: Map<string, Resource>
}) {
  const isRow = (entry: Entry) => rows && entry.block.row !== undefined && shown(entry.block)
  const dated = entries.some((entry) => isRow(entry) && entry.block.row?.when)
  // Folding is for long answers: one or two rows are the answer itself and start open.
  const folded = entries.filter(isRow).length >= 3
  const items = entries.flatMap((entry, index): ReactNode[] => {
    if (isRow(entry)) {
      return [<Row key={index} entry={entry} dated={dated} folded={folded} shown={shown} answer={answer} resources={resources} />]
    }
    // A plain bullet; or, for a row that is hidden as unverified, the details under it.
    return [entry.block, ...entry.details].filter(shown).map((block, position) => (
      <li
        key={`${index}-${position}`}
        className={`relative pl-4 before:absolute before:top-[0.65em] before:h-1 before:w-1 before:rounded-full before:bg-slate-400 ${
          block.level > 0 ? 'ml-4 before:left-0.5' : 'before:left-1'
        }`}
      >
        <BlockContent block={block} answer={answer} resources={resources} />
      </li>
    ))
  })
  return items.length > 0 ? <ul className="space-y-1.5">{items}</ul> : null
}

/** One fact of an answer. Folded, it is one line: its date, its title and the start of the fact. Open, it shows the
 *  fact in full with its sources, and the details under it. */
function Row({
  entry,
  dated,
  folded,
  shown,
  answer,
  resources,
}: {
  entry: Entry
  dated: boolean
  folded: boolean
  shown: (block: Block) => boolean
  answer: Answer
  resources: Map<string, Resource>
}) {
  // A row with lines under it starts open: such lines are usually a list the row introduces, and a folded row
  // would give no hint of it.
  const [open, setOpen] = useState(!folded || entry.details.length > 0)
  const { block } = entry
  const row = block.row!
  const details = entry.details.filter(shown)
  const blocks = [block, ...details]
  // The row's text starts with its date and title; what the row shows after the title starts at `skip`.
  const words = block.segments
    .filter((segment) => segment.text !== undefined)
    .map((segment, index) => (index === 0 ? (segment.text ?? '').slice(row.skip) : (segment.text ?? '')))
    .join('')
    .trim()
  const cited = (list: Block[]) => [...new Set(list.flatMap((item) => item.segments.flatMap((segment) => segment.cite ?? [])))]
  // The fact as an opened row shows it: the block from where the fact starts, each source beside what it supports.
  const first = block.segments.findIndex((segment) => segment.text !== undefined)
  const fact: Block = {
    ...block,
    segments: block.segments
      .map((segment, index) => (index === first ? { text: (segment.text ?? '').slice(row.fact) } : segment))
      .filter((segment) => segment.cite || segment.text?.trim()),
  }
  // A flag on the row or on a detail under it shows while the row is folded.
  const status = (['unsupported', 'check', 'unsourced'] as const).find((value) => blocks.some((item) => item.status === value))
  const marker = status && MARKERS[status]
  const complications = cited(blocks).flatMap((ref) => {
    const resource = resources.get(ref)
    return resource?.resourceType === 'DocumentReference' && isEpicrisis(resource) ? epicrisisFacts(resource).complications : []
  })
  const struck = block.status === 'unsupported' ? 'text-rose-800 line-through decoration-rose-300' : ''
  return (
    <li className="border-t border-slate-100 first:border-t-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={`grid w-full items-baseline gap-x-2 rounded-sm py-1 text-left hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-teal-600 ${
          dated ? 'grid-cols-[4.6rem_minmax(0,1fr)_auto_auto]' : 'grid-cols-[minmax(0,1fr)_auto_auto]'
        }`}
      >
        {dated && <span className={`text-xs tabular-nums text-slate-500 ${open ? '' : 'truncate'}`}>{row.when}</span>}
        {/* Folded: the title and as much of the fact as fits on one line. Open: the title; the fact is below, whole. */}
        <span className={`block ${open ? 'break-words' : 'truncate'} ${struck}`}>
          <strong className="font-semibold text-slate-900">{row.title}</strong>
          {!open && words && (
            <>
              {' '}
              <Inline text={words} />
            </>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {complications.length > 0 && (
            <Badge tone="rose" title={[...new Set(complications)].join('; ')}>
              Complication
            </Badge>
          )}
          {marker && (
            <span
              title={blocks.filter((item) => item.status === status).flatMap((item) => item.issues).join('\n')}
              className={`inline-block cursor-help rounded px-1 text-[10px] font-semibold leading-4 ${marker.className}`}
            >
              {marker.label}
            </span>
          )}
        </span>
        <span aria-hidden className="w-3 text-center text-slate-400">
          {open ? '⌄' : '›'}
        </span>
      </button>
      {open && (fact.segments.length > 0 || details.length > 0) && (
        <div className={`mb-1.5 space-y-1 rounded-r border-l-2 border-slate-300 bg-slate-50 py-1.5 pl-2.5 pr-2 text-[13px] ${dated ? 'ml-[5.1rem]' : 'ml-1'}`}>
          {fact.segments.length > 0 && (
            <p className="break-words">
              <BlockContent block={fact} answer={answer} resources={resources} />
            </p>
          )}
          {details.map((detail, index) => (
            <p key={index}>
              <BlockContent block={detail} answer={answer} resources={resources} />
            </p>
          ))}
        </div>
      )}
    </li>
  )
}

const MARKERS: Partial<Record<Block['status'], { label: string; className: string }>> = {
  check: { label: 'check', className: 'bg-amber-100 text-amber-800' },
  unsourced: { label: 'no source', className: 'bg-slate-100 text-slate-500' },
  unsupported: { label: 'unverified', className: 'bg-rose-100 text-rose-700' },
}

function BlockContent({ block, answer, resources }: { block: Block; answer: Answer; resources: Map<string, Resource> }) {
  const marker = MARKERS[block.status]
  return (
    <span className={block.status === 'unsupported' ? 'text-rose-800 line-through decoration-rose-300' : undefined}>
      {block.segments.map((segment, index) =>
        segment.cite ? (
          segment.cite.map((ref) => (
            <Citation key={`${index}-${ref}`} reference={ref} label={answer.sources[ref]?.label} resource={resources.get(ref)} />
          ))
        ) : (
          <Inline key={index} text={segment.text ?? ''} />
        ),
      )}
      {marker && (
        <span
          title={block.issues.join('\n')}
          className={`ml-1.5 inline-block cursor-help rounded px-1 align-[1px] text-[10px] font-semibold leading-4 ${marker.className}`}
        >
          {marker.label}
        </span>
      )}
    </span>
  )
}

const TYPE_DOTS: Record<string, string> = {
  Observation: 'bg-blue-500',
  DiagnosticReport: 'bg-violet-500',
  DocumentReference: 'bg-teal-500',
  Encounter: 'bg-teal-500',
  MedicationRequest: 'bg-amber-500',
  ServiceRequest: 'bg-slate-400',
  Condition: 'bg-rose-400',
  Procedure: 'bg-slate-700',
}

function Citation({ reference, label, resource }: { reference: string; label?: string; resource?: Resource }) {
  const open = useSource()
  const [type, id] = reference.split('/')
  return (
    <button
      type="button"
      title={`${label ?? reference}\n${reference}`}
      onClick={async () => open(resource ?? (await read<Resource>(type as Resource['resourceType'], id)))}
      className="mx-0.5 inline-flex max-w-[15rem] items-center gap-1 rounded-sm bg-mark-soft px-1.5 align-[1px] text-[11.5px] font-semibold leading-[19px] text-slate-800 hover:bg-mark hover:text-slate-900"
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${TYPE_DOTS[type] ?? 'bg-slate-400'}`} />
      <span className="truncate">{label ?? reference}</span>
    </button>
  )
}

/** Bold, italics and code spans: the only markdown the answers use inside a line. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|(?<![\w*])\*[^*\s][^*]*\*(?!\w))/g)
  return parts.map((part, index): ReactNode => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={index} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) return <code key={index}>{part.slice(1, -1)}</code>
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>
    return part
  })
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" className="mt-px h-3.5 w-3.5 shrink-0 text-teal-600" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="m3.5 8.5 3 3 6-7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function SparkIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="currentColor" aria-hidden>
      <path d="M8 1.5c.3 2.9 1.6 4.2 4.5 4.5-2.9.3-4.2 1.6-4.5 4.5-.3-2.9-1.6-4.2-4.5-4.5 2.9-.3 4.2-1.6 4.5-4.5Z" />
      <path d="M12.5 9.5c.15 1.45.8 2.1 2.25 2.25-1.45.15-2.1.8-2.25 2.25-.15-1.45-.8-2.1-2.25-2.25 1.45-.15 2.1-.8 2.25-2.25Z" />
    </svg>
  )
}
