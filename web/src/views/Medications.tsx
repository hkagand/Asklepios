import { useMemo, useState } from 'react'
import { patientMedications, type MedicationDrug, type MedicationFinding, type MedicationPicture } from '../agent.ts'
import { SourceButton } from '../components/source.tsx'
import { Badge, Card, Empty, Loading, type Tone } from '../components/ui.tsx'
import type { Resource } from '../fhir.ts'
import { formatDate, formatMonthYear } from '../format.ts'
import { resourceIndex, type Chart } from '../model.ts'
import { useAsync } from '../useAsync.ts'

const FINDINGS: Record<MedicationFinding['kind'], { label: string; tone: Tone }> = {
  dose_differs: { label: 'Dose differs', tone: 'rose' },
  stopped_in_note: { label: 'Stopped per note', tone: 'rose' },
  not_ordered: { label: 'No order', tone: 'rose' },
  plan: { label: 'Plan not followed', tone: 'rose' },
  not_mentioned: { label: 'Not in recent notes', tone: 'slate' },
}

const ORDER_STATUS: Record<string, { label: string; tone: Tone; bar: string }> = {
  active: { label: 'Active order', tone: 'teal', bar: 'bg-teal-500' },
  'on-hold': { label: 'On hold', tone: 'amber', bar: 'bg-amber-400' },
  stopped: { label: 'Stopped', tone: 'slate', bar: 'bg-slate-300' },
  completed: { label: 'Completed', tone: 'slate', bar: 'bg-slate-300' },
}

const statusOf = (status: string) => ORDER_STATUS[status] ?? { label: status, tone: 'slate' as Tone, bar: 'bg-slate-300' }

/** Medication orders reconciled with what the notes say, and each drug's orders over time. */
export function Medications({ chart }: { chart: Chart }) {
  const id = chart.patient.id ?? ''
  const state = useAsync((signal) => patientMedications(id, signal), [id])
  const resources = useMemo(() => resourceIndex(chart), [chart])
  if (state.status === 'loading') return <Loading label="Comparing the medication orders with the notes…" />
  if (state.status === 'error') {
    return (
      <Card title="Medications">
        <p className="text-sm text-slate-600">Medication reconciliation needs the agent service: {state.error.message}</p>
      </Card>
    )
  }
  const picture = state.data
  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-900 ring-1 ring-amber-200">{picture.uncertainty}</p>
      <Discrepancies picture={picture} resources={resources} />
      <Reconciliation picture={picture} resources={resources} />
      <Timeline picture={picture} />
      {picture.adherence.length > 0 && (
        <Card title="What the notes say about adherence">
          <ul className="space-y-1.5 text-sm">
            {picture.adherence.map((item, index) => (
              <li key={index} className="flex items-start justify-between gap-3">
                <span>
                  “{item.quote}” <span className="text-xs text-slate-500">· {formatDate(item.date)}{item.author && ` · ${item.author}`}</span>
                </span>
                <Source refs={[item.note]} resources={resources} />
              </li>
            ))}
          </ul>
        </Card>
      )}
      {picture.unread.length > 0 && <p className="text-xs text-amber-700">{picture.unread.length} note(s) could not be read.</p>}
    </div>
  )
}

function Discrepancies({ picture, resources }: { picture: MedicationPicture; resources: Map<string, Resource> }) {
  const items = [
    ...picture.drugs.flatMap((drug) => drug.findings.filter((finding) => finding.kind !== 'not_mentioned').map((finding) => ({ name: drug.name, finding }))),
    ...picture.unlisted.map((item) => ({ name: item.drug, finding: item.finding })),
  ]
  return (
    <Card title="Discrepancies" subtitle="Where the notes and the medication orders disagree" flush>
      {items.length === 0 ? (
        <div className="px-4 py-3">
          <Empty>The latest notes agree with the medication orders.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map(({ name, finding }, index) => (
            <li key={index} className="grid grid-cols-[7.5rem_minmax(0,1fr)_auto] items-start gap-3 px-4 py-2.5">
              <Badge tone={FINDINGS[finding.kind].tone}>{FINDINGS[finding.kind].label}</Badge>
              <p className="text-sm text-slate-800">
                <span className="font-medium text-slate-900">{name}</span>: {finding.text}
              </p>
              <Source refs={finding.refs} resources={resources} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Reconciliation({ picture, resources }: { picture: MedicationPicture; resources: Map<string, Resource> }) {
  const [showPast, setShowPast] = useState(false)
  const current = picture.drugs.filter((drug) => drug.status === 'active' || drug.status === 'on-hold')
  const past = picture.drugs.filter((drug) => !current.includes(drug))
  const rows = showPast ? [...current, ...past] : current
  return (
    <Card
      title="Orders and notes"
      subtitle="Each drug's current order next to what the latest notes say"
      action={
        past.length > 0 && (
          <button type="button" onClick={() => setShowPast(!showPast)} className="text-xs font-medium text-teal-700 hover:underline">
            {showPast ? 'Hide' : 'Show'} {past.length} stopped
          </button>
        )
      }
      flush
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="text-left text-[11px] text-slate-400">
              <th className="px-4 py-2 font-medium">Drug</th>
              <th className="px-3 py-2 font-medium">Order list</th>
              <th className="px-3 py-2 font-medium">Latest notes</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {rows.map((drug) => (
              <DrugRow key={drug.name} drug={drug} resources={resources} />
            ))}
            {picture.unlisted.map((item, index) => (
              <tr key={`unlisted-${index}`} className="border-t border-slate-100 align-top">
                <td className="px-4 py-2.5 font-medium capitalize text-slate-900">{item.drug}</td>
                <td className="px-3 py-2.5">
                  <Badge tone="rose">No order</Badge>
                </td>
                <td className="px-3 py-2.5 text-slate-700">
                  “{item.quote}”<span className="block text-xs text-slate-500">{formatDate(item.date)} · {item.status}{item.byPatient && ' · by the patient'}</span>
                </td>
                <td className="pr-3 pt-2">
                  <Source refs={[item.note]} resources={resources} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function DrugRow({ drug, resources }: { drug: MedicationDrug; resources: Map<string, Resource> }) {
  const order = drug.orders.at(-1)
  const status = statusOf(drug.status)
  const latest = drug.notes.at(-1)
  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="px-4 py-2.5">
        <span className="font-medium text-slate-900">{drug.name}</span>
        <span className="mt-1 flex flex-wrap gap-1">
          {drug.findings.map((finding, index) => (
            <Badge key={index} tone={FINDINGS[finding.kind].tone} title={finding.text}>
              {FINDINGS[finding.kind].label}
            </Badge>
          ))}
        </span>
      </td>
      <td className="px-3 py-2.5 text-slate-700">
        <Badge tone={status.tone}>{status.label}</Badge> {drug.dose}
        {order && (
          <span className="block text-xs text-slate-500">
            {order.start && `since ${formatDate(order.start)}`}
            {order.end && ` to ${formatDate(order.end)}`}
            {order.statusReason && ` · ${order.statusReason}`}
            {order.reason && ` · for ${order.reason}`}
          </span>
        )}
      </td>
      <td className="px-3 py-2.5 text-slate-700">
        {latest ? (
          <>
            “{latest.quote}”
            <span className="block text-xs text-slate-500">
              {formatDate(latest.date)} · {latest.status}
              {latest.byPatient && ' · by the patient'}
            </span>
          </>
        ) : (
          <span className="text-xs text-slate-400">Not mentioned in the latest notes</span>
        )}
      </td>
      <td className="pr-3 pt-2">
        <Source refs={[...(order ? [order.ref] : []), ...(latest ? [latest.note] : [])]} resources={resources} />
      </td>
    </tr>
  )
}

const DAY_MS = 86_400_000

/** One row per drug: its orders as bars (teal active, amber on hold, grey stopped) and notes that name it as ticks. */
function Timeline({ picture }: { picture: MedicationPicture }) {
  const [showPast, setShowPast] = useState(false)
  const drugs = picture.drugs.filter((drug) => showPast || drug.status === 'active' || drug.status === 'on-hold')
  const end = Date.parse(picture.today)
  const starts = picture.drugs.flatMap((drug) => drug.orders.map((order) => Date.parse(order.start ?? picture.today)))
  // At most three years back, so long-standing drugs do not squeeze recent changes.
  const start = Math.max(Math.min(...starts, end - 365 * DAY_MS), end - 3 * 365 * DAY_MS)
  const at = (day: string | null) => Math.min(100, Math.max(0, ((Date.parse(day ?? picture.today) - start) / (end - start)) * 100))
  const ticks: number[] = []
  for (let month = new Date(start); month.getTime() <= end; month.setMonth(month.getMonth() + 3)) ticks.push(month.getTime())
  return (
    <Card
      title="Timeline"
      subtitle="Orders over time; ticks mark notes that name the drug"
      action={
        <button type="button" onClick={() => setShowPast(!showPast)} className="text-xs font-medium text-teal-700 hover:underline">
          {showPast ? 'Current drugs only' : 'Include stopped drugs'}
        </button>
      }
    >
      <div className="space-y-2">
        {drugs.map((drug) => (
          <div key={drug.name} className="grid grid-cols-[8rem_minmax(0,1fr)] items-center gap-3">
            <span className="truncate text-xs font-medium text-slate-700" title={drug.name}>
              {drug.name}
            </span>
            <div className="relative h-6 rounded bg-slate-50">
              {drug.orders.map((order) => {
                const left = at(order.start)
                const width = Math.max(0.8, at(order.end ?? picture.today) - left)
                return (
                  <span
                    key={order.ref}
                    title={`${order.name}: ${order.dose}\n${formatDate(order.start ?? undefined)} – ${order.end ? formatDate(order.end) : 'now'} · ${order.status}${order.statusReason ? ` (${order.statusReason})` : ''}`}
                    className={`absolute top-1 h-4 overflow-hidden whitespace-nowrap rounded-sm px-1 text-[10px] leading-4 text-white ${statusOf(order.status).bar}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  >
                    {order.dose.split(' orally')[0].split(' IV')[0]}
                  </span>
                )
              })}
              {drug.mentionedIn.map((mention) =>
                Date.parse(mention.date) >= start ? (
                  <span
                    key={mention.note}
                    title={`${mention.title} · ${formatDate(mention.date)}`}
                    className="absolute -bottom-0.5 h-2 w-0.5 rounded bg-slate-700"
                    style={{ left: `${at(mention.date)}%` }}
                  />
                ) : null,
              )}
            </div>
          </div>
        ))}
        <div className="grid grid-cols-[8rem_minmax(0,1fr)] gap-3">
          <span />
          <div className="relative h-4 text-[10px] text-slate-400">
            {ticks.map((tick) => (
              <span key={tick} className="absolute -translate-x-1/2" style={{ left: `${((tick - start) / (end - start)) * 100}%` }}>
                {formatMonthYear(tick)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </Card>
  )
}

function Source({ refs, resources }: { refs: string[]; resources: Map<string, Resource> }) {
  return (
    <span className="flex shrink-0 flex-wrap justify-end gap-0.5">
      {[...new Set(refs)].map((ref) => {
        const resource = resources.get(ref)
        return resource ? <SourceButton key={ref} resource={resource} label={LABELS[resource.resourceType]} /> : null
      })}
    </span>
  )
}

const LABELS: Record<string, string> = { DocumentReference: 'Note', MedicationRequest: 'Order' }
