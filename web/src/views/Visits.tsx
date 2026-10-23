import { SourceButton } from '../components/source.tsx'
import { Badge, Card, DocumentText, Empty } from '../components/ui.tsx'
import { attachmentText, text } from '../fhir.ts'
import { formatDate, formatTime, toTime } from '../format.ts'
import { timeline, vitalsAt, visitClinician, visitTitle, type Chart, type VisitItem } from '../model.ts'
import { select } from '../route.ts'

const DAY_MS = 86_400_000

export function Visits({ chart, selected }: { chart: Chart; selected?: string }) {
  const id = chart.patient.id ?? ''
  const items = timeline(chart)
  if (items.length === 0) {
    return (
      <Card>
        <Empty>No visits on file.</Empty>
      </Card>
    )
  }
  const current = items.find((item) => item.key === selected) ?? items[0]
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
      <Card flush className="lg:sticky lg:top-18 lg:max-h-[calc(100vh-5.5rem)] lg:overflow-y-auto">
        <ul className="divide-y divide-slate-100">
          {items.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                onClick={() => select(id, 'visits', item.key)}
                aria-current={item.key === current.key ? 'true' : undefined}
                className={`block w-full px-4 py-2.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-teal-600 ${
                  item.key === current.key ? 'bg-teal-50' : 'hover:bg-slate-50'
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium tabular-nums text-slate-500">{formatDate(item.time)}</span>
                  {item.encounter?.class.code === 'IMP' && <Badge tone="blue">Inpatient</Badge>}
                  {!item.encounter && <Badge>No encounter</Badge>}
                </span>
                <span className="mt-0.5 block truncate text-sm font-medium text-slate-900">{visitTitle(item)}</span>
                <span className="block truncate text-xs text-slate-500">{visitClinician(item)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <VisitDetail chart={chart} item={current} />
    </div>
  )
}

function VisitDetail({ chart, item }: { chart: Chart; item: VisitItem }) {
  const { encounter } = item
  const start = encounter?.period?.start
  const end = encounter?.period?.end
  const inpatient = encounter?.class.code === 'IMP'
  const vitals = encounter?.id ? vitalsAt(chart, encounter.id) : undefined
  return (
    <div className="space-y-4">
      {encounter && (
        <Card
          title={text(encounter.type?.[0]) || 'Encounter'}
          subtitle={`${formatDate(start)}${start ? `, ${formatTime(start)}` : ''} · ${visitClinician(item)} · ${encounter.serviceType ? text(encounter.serviceType) : ''}`}
          action={<SourceButton resource={encounter} label="Encounter" />}
        >
          <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            <dt className="text-slate-500">Reason</dt>
            <dd className="text-slate-800">{text(encounter.reasonCode?.[0]) || '—'}</dd>
            {inpatient && start && end && (
              <>
                <dt className="text-slate-500">Admission</dt>
                <dd className="text-slate-800">
                  {formatDate(start)} – {formatDate(end)} ({Math.round((toTime(end) - toTime(start)) / DAY_MS)} days)
                </dd>
              </>
            )}
            {vitals && (
              <>
                <dt className="text-slate-500">Vital signs</dt>
                <dd className="tabular-nums text-slate-800">{vitals}</dd>
              </>
            )}
          </dl>
        </Card>
      )}
      {item.notes.map((note) => (
        <Card
          key={note.id}
          title={note.description}
          subtitle={`${text(note.type)} · ${formatDate(note.date)} · ${note.author?.[0]?.display ?? 'Unknown author'}`}
          action={<SourceButton resource={note} label="Note" />}
        >
          <DocumentText text={attachmentText(note.content.map((content) => content.attachment)) ?? ''} />
        </Card>
      ))}
      {item.notes.length === 0 && (
        <Card>
          <Empty>No note is linked to this encounter.</Empty>
        </Card>
      )}
    </div>
  )
}
