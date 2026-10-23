import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { agentHealth, ask, type AgentEvent, type Answer, type Block, type Step } from '../agent.ts'
import { read, type Resource } from '../fhir.ts'
import type { Chart } from '../model.ts'
import { useAsync } from '../useAsync.ts'
import { useSource } from './source.tsx'

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
    <div className="flex h-full flex-col bg-white">
      <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-teal-700 text-white">
            <SparkIcon />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900">ASKlepios</p>
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
        <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white py-1.5 pl-3 pr-1.5 focus-within:border-teal-600 focus-within:ring-1 focus-within:ring-teal-600">
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
              className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-200"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim()}
              className="rounded-lg bg-teal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:bg-slate-200 disabled:text-slate-400"
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

function apply(turn: Turn, event: AgentEvent): Turn {
  if (event.type === 'step') return { ...turn, steps: [...turn.steps, event.step] }
  if (event.type === 'answer') return { ...turn, answer: event.answer, running: false }
  return { ...turn, error: event.message, running: false }
}

function resourceIndex(chart: Chart): Map<string, Resource> {
  const all: Resource[] = [
    chart.patient,
    ...chart.conditions,
    ...chart.medications,
    ...chart.allergies,
    ...chart.encounters,
    ...chart.notes,
    ...chart.labReports,
    ...chart.reports,
    ...chart.orders,
    ...chart.appointments,
    ...chart.observations.values(),
  ]
  return new Map(all.map((resource) => [`${resource.resourceType}/${resource.id}`, resource]))
}

function Intro({ firstName, onPick }: { firstName: string; onPick: (question: string) => void }) {
  return (
    <div>
      <p className="text-sm leading-relaxed text-slate-700">
        Ask about {firstName}’s history, results, treatments and anything still pending. Every statement links to the
        part of the record it came from.
      </p>
      <p className="mt-5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Try</p>
      <div className="mt-2 flex flex-col items-start gap-2">
        {STARTERS.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onPick(question)}
            className="rounded-full border border-teal-200 bg-teal-50 px-3 py-1.5 text-left text-[13px] text-teal-900 hover:border-teal-300 hover:bg-teal-100"
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
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-teal-700 px-3.5 py-2 text-sm text-white">
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
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-teal-700" />
        {steps.length === 0 ? 'Reading the chart…' : 'Working…'}
      </li>
    </ul>
  )
}

function AnswerView({ answer, resources }: { answer: Answer; resources: Map<string, Resource> }) {
  const [showHidden, setShowHidden] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const hidden = answer.blocks.filter((block) => block.status === 'unsupported').length
  const blocks = answer.blocks.filter((block) => showHidden || block.status !== 'unsupported')
  return (
    <div>
      <div className="space-y-2 text-[13.5px] leading-relaxed text-slate-800">
        {group(blocks).map((item, index) =>
          Array.isArray(item) ? (
            <ul key={index} className="space-y-1.5">
              {item.map((block, position) => (
                <li
                  key={position}
                  className={`relative pl-4 before:absolute before:top-[0.65em] before:h-1 before:w-1 before:rounded-full before:bg-slate-400 ${
                    block.level > 0 ? 'ml-4 before:left-0.5' : 'before:left-1'
                  }`}
                >
                  <BlockContent block={block} answer={answer} resources={resources} />
                </li>
              ))}
            </ul>
          ) : item.kind === 'heading' ? (
            <p key={index} className="pt-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
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

/** Consecutive bullets become one list. */
function group(blocks: Block[]): (Block | Block[])[] {
  const items: (Block | Block[])[] = []
  for (const block of blocks) {
    const last = items.at(-1)
    if (block.kind === 'bullet' && Array.isArray(last)) last.push(block)
    else items.push(block.kind === 'bullet' ? [block] : block)
  }
  return items
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
}

function Citation({ reference, label, resource }: { reference: string; label?: string; resource?: Resource }) {
  const open = useSource()
  const [type, id] = reference.split('/')
  return (
    <button
      type="button"
      title={`${label ?? reference}\n${reference}`}
      onClick={async () => open(resource ?? (await read<Resource>(type as Resource['resourceType'], id)))}
      className="mx-0.5 inline-flex max-w-[15rem] items-center gap-1 rounded border border-slate-200 bg-slate-50 px-1.5 align-[1px] text-[11px] leading-[18px] text-slate-600 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800"
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
