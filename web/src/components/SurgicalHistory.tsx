import { useMemo, useState } from 'react'
import type { Operation, SurgeryRegion, SurgeryStatement, SurgicalHistory as History } from '../agent.ts'
import { read, text, type Resource } from '../fhir.ts'
import { formatDate } from '../format.ts'
import { resourceIndex, type Chart } from '../model.ts'
import type { AsyncState } from '../useAsync.ts'
import { SourceButton, useSource } from './source.tsx'
import { Badge, Card, Empty } from './ui.tsx'

const REGIONS: [SurgeryRegion, string][] = [
  ['abdomen', 'Abdomen & pelvis'],
  ['chest', 'Chest'],
  ['head_neck', 'Head & neck'],
  ['spine_limbs', 'Spine & limbs'],
  ['other', 'Other'],
]
const REGION_NAME = Object.fromEntries(REGIONS) as Record<SurgeryRegion, string>
// "No abdominal operations recorded", "No chest operations recorded"…
const REGION_ADJECTIVE: Record<SurgeryRegion, string> = {
  abdomen: 'abdominal or pelvic',
  chest: 'chest',
  head_neck: 'head or neck',
  spine_limbs: 'spine or limb',
  other: 'other',
}
const SOURCES_SHOWN = 3
const APPROACH: Record<string, string> = {
  open: 'Open',
  laparoscopic: 'Laparoscopic',
  robotic: 'Robotic',
  endoscopic: 'Endoscopic',
  percutaneous: 'Percutaneous',
}

/** Earlier operations from the agent (Procedure records, notes and reports), or the Procedure records alone. */
export function SurgicalHistory({ chart, state }: { chart: Chart; state: AsyncState<History> }) {
  if (state.status === 'error') return <ProcedureRecords chart={chart} problem={state.error.message} />
  return (
    <Card
      title="Surgical history"
      subtitle={state.status === 'ready' ? subtitleOf(state.data) : 'Reading procedure records, notes and reports…'}
      flush
    >
      {state.status === 'loading' ? (
        <div className="flex items-center gap-2 px-4 py-3 text-sm text-slate-500">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
          Reading the record
        </div>
      ) : (
        <Operations chart={chart} history={state.data} />
      )}
    </Card>
  )
}

function subtitleOf(history: History): string {
  const count = history.operations.length
  if (count === 0) return history.noneStated.length ? 'None, as stated in a note' : 'None recorded'
  const abdominal = history.operations.filter((operation) => operation.region === 'abdomen').length
  return `${count} earlier operation${count === 1 ? '' : 's'}${abdominal ? ` · ${abdominal} abdominal or pelvic` : ''}`
}

/** The band fact: how many operations, and how many in the abdomen. */
export function operationsFact(chart: Chart, state: AsyncState<History>): string | undefined {
  if (state.status === 'loading') return undefined
  if (state.status === 'error') {
    const count = chart.procedures.length
    return count ? `${count} in procedure records` : undefined
  }
  const { operations, noneStated } = state.data
  if (operations.length === 0) return noneStated.length ? 'None (per notes)' : 'None recorded'
  const abdominal = operations.filter((operation) => operation.region === 'abdomen').length
  return `${operations.length} · ${abdominal} abdominal`
}

function Operations({ chart, history }: { chart: Chart; history: History }) {
  const [region, setRegion] = useState<SurgeryRegion | 'all'>('all')
  const resources = useMemo(() => resourceIndex(chart), [chart])
  const { operations, clues, noneStated, searched } = history
  const shown = region === 'all' ? operations : operations.filter((operation) => operation.region === region)
  const counts = Object.fromEntries(REGIONS.map(([key]) => [key, operations.filter((operation) => operation.region === key).length]))

  return (
    <>
      {operations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pt-3" role="group" aria-label="Body region">
          <RegionChip label="All" count={operations.length} active={region === 'all'} onClick={() => setRegion('all')} />
          {REGIONS.filter(([key]) => key !== 'other' || counts.other > 0).map(([key, label]) => (
            <RegionChip key={key} label={label} count={counts[key]} active={region === key} onClick={() => setRegion(key)} />
          ))}
        </div>
      )}
      {shown.length > 0 ? (
        <ul className="mt-2 divide-y divide-slate-100 border-t border-slate-100">
          {shown.map((operation) => (
            <OperationRow
              key={`${operation.name}:${operation.date}`}
              operation={operation}
              showRegion={region === 'all'}
              resources={resources}
            />
          ))}
        </ul>
      ) : (
        <div className="px-4 py-3">
          {operations.length === 0 && noneStated.length > 0 ? (
            <NoneStated statements={noneStated} resources={resources} />
          ) : (
            <Empty>
              No {region === 'all' ? '' : `${REGION_ADJECTIVE[region]} `}operations recorded.
            </Empty>
          )}
        </div>
      )}
      {clues.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-2.5">
          <p className="text-xs font-semibold text-slate-500">Signs of earlier surgery</p>
          <ul className="mt-1 space-y-1.5">
            {clues.map((clue) => (
              <li key={`${clue.ref}:${clue.quote}`} className="text-[13px] text-slate-700">
                <span className="font-semibold text-slate-900">{clue.finding}</span>
                <span className="text-slate-500"> — “{clue.quote}”</span>
                <span className="ml-1 inline-flex">
                  <SourceChip reference={clue.ref} label={clue.label} resources={resources} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <footer className="border-t border-slate-100 px-4 py-2.5 text-xs leading-relaxed text-slate-500">
        {searchedText(searched)}
        {(operations.length === 0 || region !== 'all') && ' Operations done elsewhere may not be in this record.'}
        {history.unread.length > 0 && (
          <span className="text-amber-700"> {history.unread.length} document(s) could not be read.</span>
        )}
        <span className="block">Operations are read from notes by the language model; dates, regions and merging come from code.</span>
      </footer>
    </>
  )
}

function searchedText(searched: History['searched']): string {
  const parts = [
    `${searched.procedures} procedure record${searched.procedures === 1 ? '' : 's'}`,
    `${searched.notes} note${searched.notes === 1 ? '' : 's'}`,
    `${searched.reports} report${searched.reports === 1 ? '' : 's'}`,
  ]
  // Month and year: "since Jun 2015".
  const since = searched.earliest ? ` since ${formatDate(searched.earliest).replace(/^\d+ /, '')}` : ''
  return `Searched ${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}${since}.`
}

function RegionChip({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12.5px] font-semibold ${
        active
          ? 'border-slate-900 bg-slate-900 text-white'
          : count
            ? 'border-slate-300 bg-sheet text-slate-800 hover:border-slate-900'
            : 'border-slate-200 bg-sheet text-slate-400 hover:border-slate-400'
      }`}
    >
      {label}
      <span className={`font-mono text-[11.5px] ${active ? 'text-mark' : count ? 'text-slate-500' : 'text-slate-300'}`}>{count}</span>
    </button>
  )
}

function OperationRow({
  operation,
  showRegion,
  resources,
}: {
  operation: Operation
  showRegion: boolean
  resources: Map<string, Resource>
}) {
  const [allSources, setAllSources] = useState(false)
  // The quote that says most about it, usually a past surgical history line.
  const quoted = operation.sources
    .filter((source) => source.quote)
    .sort((a, b) => (b.quote?.length ?? 0) - (a.quote?.length ?? 0))[0]
  return (
    <li className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 px-4 py-2.5">
      <div className="pt-px font-mono text-[13px] font-semibold tabular-nums text-slate-900" title={operation.when}>
        {operation.year ?? '—'}
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold leading-snug text-slate-900">{operation.name}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {operation.approach && <Badge>{APPROACH[operation.approach] ?? operation.approach}</Badge>}
          {showRegion && <span className="text-[12px] text-slate-500">{REGION_NAME[operation.region]}</span>}
          {operation.side && <span className="text-[12px] text-slate-500">· {operation.side}</span>}
          {operation.precision !== 'year' && operation.date && (
            <span className="text-[12px] text-slate-500">· {operation.when}</span>
          )}
          {operation.elsewhere && (
            <Badge tone="violet" title="A note or the patient says it was done at another hospital">
              Done elsewhere
            </Badge>
          )}
          {operation.onlyInNotes && (
            <Badge tone="amber" title="No procedure record: only notes or reports mention it">
              Only in notes
            </Badge>
          )}
        </div>
        {operation.yearsDiffer.length > 0 && (
          <p className="mt-1 text-[12.5px] font-semibold text-amber-800">
            Sources give different years: {operation.yearsDiffer.join(' and ')}
          </p>
        )}
        {operation.implants.length > 0 && (
          <p className="mt-1 text-[12.5px] font-semibold text-rose-700">Implant: {operation.implants.join('; ')}</p>
        )}
        {operation.complications.length > 0 && (
          <p className="mt-1 text-[12.5px] font-semibold text-rose-700">Complications: {operation.complications.join('; ')}</p>
        )}
        {quoted?.quote && <p className="mt-1 text-[12.5px] leading-snug text-slate-600">“{quoted.quote}”</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {(allSources ? operation.sources : operation.sources.slice(0, SOURCES_SHOWN)).map((source) => (
            <SourceChip key={`${source.ref}:${source.quote}`} reference={source.ref} label={source.label} resources={resources} />
          ))}
          {operation.sources.length > SOURCES_SHOWN && (
            <button
              type="button"
              onClick={() => setAllSources(!allSources)}
              className="text-[11.5px] font-semibold text-teal-700 hover:underline"
            >
              {allSources ? 'Fewer' : `+${operation.sources.length - SOURCES_SHOWN} more`}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

function NoneStated({ statements, resources }: { statements: SurgeryStatement[]; resources: Map<string, Resource> }) {
  return (
    <div className="space-y-1">
      {statements.map((statement) => (
        <p key={statement.ref} className="text-sm text-slate-700">
          <span className="font-semibold text-slate-900">None stated:</span> “{statement.quote}”{' '}
          <SourceChip reference={statement.ref} label={statement.label} resources={resources} />
        </p>
      ))}
    </div>
  )
}

/** A highlighted chip naming a source; opens it in the source drawer. */
function SourceChip({ reference, label, resources }: { reference: string; label: string; resources: Map<string, Resource> }) {
  const open = useSource()
  const [type, id] = reference.split('/')
  return (
    <button
      type="button"
      title={reference}
      onClick={async () => open(resources.get(reference) ?? (await read<Resource>(type as Resource['resourceType'], id)))}
      className="inline-flex max-w-full items-center rounded-sm bg-mark-soft px-1.5 text-[11.5px] font-semibold leading-[19px] text-slate-800 hover:bg-mark hover:text-slate-900"
    >
      <span className="truncate">{label}</span>
    </button>
  )
}

/** Without the agent: the Procedure records alone, which miss operations only notes mention. */
function ProcedureRecords({ chart, problem }: { chart: Chart; problem: string }) {
  const procedures = chart.procedures.filter((procedure) => procedure.status === 'completed')
  return (
    <Card title="Surgical history" subtitle="Procedure records only" flush>
      {procedures.length === 0 ? (
        <div className="px-4 py-3">
          <Empty>No procedure records.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {procedures.map((procedure) => (
            <li key={procedure.id} className="flex items-start gap-3 px-4 py-2.5">
              <span className="w-14 shrink-0 pt-px font-mono text-[13px] font-semibold tabular-nums text-slate-900">
                {(procedure.performedDateTime ?? procedure.performedString)?.slice(0, 4) ?? '—'}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-slate-900">{text(procedure.code)}</p>
                <p className="text-xs text-slate-500">
                  {procedure.bodySite?.map((site) => text(site)).join(', ')}
                  {procedure.asserter?.reference?.startsWith('Patient/') && ' · reported by the patient'}
                </p>
              </div>
              <SourceButton resource={procedure} />
            </li>
          ))}
        </ul>
      )}
      <p className="border-t border-slate-100 px-4 py-2.5 text-xs text-amber-800">
        Notes and reports were not read, so operations only they mention are missing here ({problem}).
      </p>
    </Card>
  )
}
