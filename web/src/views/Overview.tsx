import { useState } from 'react'
import { SourceButton } from '../components/source.tsx'
import { Badge, Card, Empty, FlagMark, valueTone, type Tone } from '../components/ui.tsx'
import { code, refId, text } from '../fhir.ts'
import { daysBetween, formatDate, formatNumber, signed, todayIso, toTime } from '../format.ts'
import {
  changesSince,
  isActive,
  lastVisit,
  openOrders,
  percentChange,
  reportTime,
  timeline,
  visitClinician,
  visitTitle,
  type Change,
  type Chart,
} from '../model.ts'
import { patientHref } from '../route.ts'

export function Overview({ chart }: { chart: Chart }) {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="space-y-4">
        <SinceLastVisit chart={chart} />
        <OpenOrders chart={chart} />
        <RecentVisits chart={chart} />
      </div>
      <div className="space-y-4">
        <Problems chart={chart} />
        <Medications chart={chart} />
        <Allergies chart={chart} />
      </div>
    </div>
  )
}

const DAY_MS = 86_400_000

function SinceLastVisit({ chart }: { chart: Chart }) {
  const [showAll, setShowAll] = useState(false)
  const id = chart.patient.id ?? ''
  const visit = lastVisit(chart)
  const since = visit ? toTime(visit.period?.end ?? visit.period?.start) : Number.NEGATIVE_INFINITY

  const changes = changesSince(chart, since)
    .map((change) => ({ change, percent: change.baseline && percentChange(change.baseline.value, change.latest.value) }))
    .sort(
      (a, b) =>
        Number(Boolean(b.change.latest.flag)) - Number(Boolean(a.change.latest.flag)) ||
        Math.abs(b.percent ?? 0) - Math.abs(a.percent ?? 0),
    )
  const notable = changes.filter(({ change, percent }) => change.latest.flag || Math.abs(percent ?? 0) >= 10)
  const shown = showAll ? changes : notable
  const drawn = [...new Set(changes.map(({ change }) => formatDate(change.latest.time)))]
  const reports = chart.reports.filter((report) => reportTime(report) > since)
  const notes = chart.notes.filter((note) => toTime(note.date) > since && refId(note.context?.encounter?.[0]) !== visit?.id)
  const nothingNew = changes.length === 0 && reports.length === 0 && notes.length === 0

  return (
    <Card
      title="Since last visit"
      subtitle={
        visit
          ? `${formatDate(visit.period?.start)} · ${visit.participant?.[0]?.individual?.display} · ${text(visit.type?.[0])}`
          : 'No earlier visits on file'
      }
      action={visit && <SourceButton resource={visit} />}
      flush
    >
      {nothingNew && (
        <div className="px-4 py-3">
          <Empty>No new results, reports or notes.</Empty>
        </div>
      )}
      {changes.length > 0 && (
        <div className="pb-1">
          <div className="flex items-center justify-between gap-3 px-4 pt-3">
            <p className="text-xs font-medium text-slate-500">
              {changes.length} new lab results · drawn {drawn.join(', ')}
              {!showAll && ` · showing ${notable.length} out of range or changed by 10% or more`}
            </p>
            {notable.length < changes.length && (
              <button
                type="button"
                onClick={() => setShowAll(!showAll)}
                className="shrink-0 text-xs font-medium text-teal-700 hover:underline"
              >
                {showAll ? 'Show notable only' : `Show all ${changes.length}`}
              </button>
            )}
          </div>
          {shown.length > 0 ? (
            <table className="mt-1 w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-1.5 font-medium">Test</th>
                  <th className="px-3 py-1.5 text-right font-medium">Now</th>
                  <th className="px-3 py-1.5 text-right font-medium">Before</th>
                  <th className="px-3 py-1.5 text-right font-medium">Change</th>
                  <th className="px-3 py-1.5 font-medium">Reference</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {shown.map(({ change, percent }) => (
                  <ChangeRow key={change.series.key} id={id} change={change} percent={percent} />
                ))}
              </tbody>
            </table>
          ) : (
            <p className="px-4 py-2 text-sm text-slate-500">All new results are within range and stable.</p>
          )}
        </div>
      )}
      {reports.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-3">
          <p className="text-xs font-medium text-slate-500">New reports</p>
          <ul className="mt-1 space-y-1.5">
            {reports.map((report) => (
              <li key={report.id} className="text-sm">
                <a href={patientHref(id, 'reports', report.id)} className="font-medium text-slate-900 hover:text-teal-700">
                  {text(report.code)}
                </a>
                <span className="text-slate-500"> · {formatDate(report.effectiveDateTime)}</span>
                <p className="text-slate-600">{report.conclusion}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
      {notes.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-3">
          <p className="text-xs font-medium text-slate-500">New notes</p>
          <ul className="mt-1 space-y-1">
            {notes.map((note) => (
              <li key={note.id} className="text-sm">
                <a href={patientHref(id, 'visits', refId(note.context?.encounter?.[0]) ?? note.id)} className="font-medium text-slate-900 hover:text-teal-700">
                  {note.description}
                </a>
                <span className="text-slate-500">
                  {' '}
                  · {formatDate(note.date)} · {note.author?.[0]?.display}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

function ChangeRow({ id, change, percent }: { id: string; change: Change; percent?: number }) {
  const { series, latest, baseline } = change
  return (
    <tr className="border-t border-slate-100">
      <td className="px-4 py-2">
        <a href={patientHref(id, 'labs', series.key)} className="font-medium text-slate-800 hover:text-teal-700">
          {series.name}
        </a>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
        <span className={`font-semibold ${valueTone(latest.flag)}`}>{formatNumber(latest.value, series.decimals)}</span>{' '}
        <span className="text-xs text-slate-500">{series.unit}</span>
        <FlagMark flag={latest.flag} />
        <span className="block text-[11px] text-slate-400">{formatDate(latest.time)}</span>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-600">
        {baseline ? (
          <>
            {formatNumber(baseline.value, series.decimals)}
            <FlagMark flag={baseline.flag} />
            <span className="block text-[11px] text-slate-400">{formatDate(baseline.time)}</span>
          </>
        ) : (
          <span className="text-xs text-slate-400">first result</span>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-800">
        {baseline ? (
          <>
            {signed(latest.value - baseline.value, series.decimals)}
            {percent !== undefined && <span className="text-slate-500"> ({signed(percent, 0)}%)</span>}
            <span className="block text-[11px] text-slate-400">
              over {Math.round((latest.time - baseline.time) / DAY_MS)} days
            </span>
          </>
        ) : (
          '—'
        )}
      </td>
      <td className="px-3 py-2 text-xs text-slate-500">{series.range}</td>
      <td className="pr-3 text-right">
        <SourceButton resource={latest.observation} />
      </td>
    </tr>
  )
}

function dueStatus(due: string, today: string): [Tone, string] {
  const days = daysBetween(today, due)
  if (days < 0) return ['rose', `Overdue ${-days} d`]
  if (days === 0) return ['amber', 'Due today']
  return ['slate', `Due in ${days} d`]
}

function OpenOrders({ chart }: { chart: Chart }) {
  const today = todayIso()
  const orders = openOrders(chart)
  return (
    <Card title="Open orders" subtitle="Requested tests, imaging and referrals with no result yet" flush>
      {orders.length === 0 ? (
        <div className="px-4 py-3">
          <Empty>No open orders.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {orders.map((order) => {
            const due = (order.occurrenceDateTime ?? today).slice(0, 10)
            const [tone, label] = dueStatus(due, today)
            return (
              <li key={order.id} className="flex items-start gap-3 px-4 py-2.5">
                <div className="w-24 shrink-0 pt-0.5">
                  <Badge tone={tone}>{label}</Badge>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-900">
                    {text(order.code)}{' '}
                    {order.priority === 'urgent' && <Badge tone="amber">Urgent</Badge>}
                  </p>
                  <p className="text-xs text-slate-500">
                    {text(order.category?.[0])} · ordered {formatDate(order.authoredOn)} by {order.requester?.display} · due{' '}
                    {formatDate(due)}
                  </p>
                  {order.reasonCode?.[0] && <p className="text-xs text-slate-500">{text(order.reasonCode[0])}</p>}
                </div>
                <SourceButton resource={order} />
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function RecentVisits({ chart }: { chart: Chart }) {
  const id = chart.patient.id ?? ''
  const items = timeline(chart).slice(0, 5)
  return (
    <Card
      title="Recent visits & notes"
      action={
        <a href={patientHref(id, 'visits')} className="text-xs font-medium text-teal-700 hover:underline">
          All visits
        </a>
      }
      flush
    >
      {items.length === 0 ? (
        <div className="px-4 py-3">
          <Empty>No visits on file.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((item) => (
            <li key={item.key}>
              <a href={patientHref(id, 'visits', item.key)} className="flex items-start gap-4 px-4 py-2.5 hover:bg-slate-50">
                <span className="w-24 shrink-0 text-sm tabular-nums text-slate-500">{formatDate(item.time)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-slate-900">{visitTitle(item)}</span>
                  <span className="block truncate text-xs text-slate-500">
                    {visitClinician(item)}
                    {item.encounter?.reasonCode?.[0] && ` · ${text(item.encounter.reasonCode[0])}`}
                  </span>
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Problems({ chart }: { chart: Chart }) {
  const active = chart.conditions.filter(isActive)
  return (
    <Card title="Problem list" subtitle={`${active.length} active`} flush>
      {active.length === 0 ? (
        <div className="px-4 py-3">
          <Empty>No active problems recorded.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {active.map((condition) => (
            <li key={condition.id} className="flex items-start gap-2 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-900">{text(condition.code)}</p>
                {condition.stage?.[0]?.summary && <p className="text-xs text-slate-700">{text(condition.stage[0].summary)}</p>}
                {condition.note?.[0]?.text && <p className="text-xs text-slate-500">{condition.note[0].text}</p>}
                <p className="mt-0.5 text-[11px] text-slate-400">
                  ICD-10 {code(condition.code)} · since {formatDate(condition.onsetDateTime)}
                </p>
              </div>
              <SourceButton resource={condition} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

const periodOf = (medication: fhir4.MedicationRequest) => medication.dosageInstruction?.[0]?.timing?.repeat?.boundsPeriod

function Medications({ chart }: { chart: Chart }) {
  const today = todayIso()
  const active = chart.medications.filter((medication) => medication.status === 'active')
  const held = chart.medications.filter((medication) => medication.status === 'on-hold')
  const stopped = chart.medications.filter((medication) => {
    const end = periodOf(medication)?.end
    return medication.status === 'stopped' && end !== undefined && daysBetween(end, today) <= 90
  })
  return (
    <Card title="Medications" subtitle={`${active.length} active${held.length ? ` · ${held.length} on hold` : ''}`} flush>
      <ul className="divide-y divide-slate-100">
        {active.map((medication) => (
          <MedicationItem key={medication.id} medication={medication} />
        ))}
        {held.map((medication) => (
          <MedicationItem key={medication.id} medication={medication} held />
        ))}
      </ul>
      {active.length + held.length === 0 && (
        <div className="px-4 py-3">
          <Empty>No current medications.</Empty>
        </div>
      )}
      {stopped.length > 0 && (
        <details className="border-t border-slate-100 px-4 py-2.5">
          <summary className="cursor-pointer text-xs font-medium text-slate-500">
            Stopped or changed in the last 90 days ({stopped.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {stopped.map((medication) => (
              <li key={medication.id} className="flex items-start gap-2">
                <div className="min-w-0 flex-1 text-xs">
                  <p className="text-slate-700 line-through decoration-slate-300">{text(medication.medicationCodeableConcept)}</p>
                  <p className="text-slate-500">
                    {formatDate(periodOf(medication)?.end)} · {text(medication.statusReason)}
                  </p>
                </div>
                <SourceButton resource={medication} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  )
}

function MedicationItem({ medication, held = false }: { medication: fhir4.MedicationRequest; held?: boolean }) {
  return (
    <li className="flex items-start gap-2 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-900">
          {text(medication.medicationCodeableConcept)} {held && <Badge tone="amber">On hold</Badge>}
        </p>
        <p className="text-xs text-slate-600">{medication.dosageInstruction?.[0]?.text}</p>
        <p className="mt-0.5 text-[11px] text-slate-400">
          {held ? text(medication.statusReason) : `Since ${formatDate(periodOf(medication)?.start)} · ${medication.requester?.display}`}
        </p>
      </div>
      <SourceButton resource={medication} />
    </li>
  )
}

function Allergies({ chart }: { chart: Chart }) {
  return (
    <Card title="Allergies" flush>
      {chart.allergies.length === 0 ? (
        <div className="px-4 py-3">
          <Empty>No allergy information recorded.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {chart.allergies.map((allergy) => {
            const reaction = allergy.reaction?.[0]
            return (
              <li key={allergy.id} className="flex items-start gap-2 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-medium ${allergy.criticality === 'high' ? 'text-rose-700' : 'text-slate-900'}`}>
                    {text(allergy.code)}
                  </p>
                  {reaction && (
                    <p className="text-xs text-slate-500">
                      {reaction.manifestation.map((manifestation) => text(manifestation)).join(', ')}
                      {reaction.severity && ` · ${reaction.severity}`}
                    </p>
                  )}
                </div>
                <SourceButton resource={allergy} />
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
