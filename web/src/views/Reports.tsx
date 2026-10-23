import { SourceButton } from '../components/source.tsx'
import { Badge, Card, DocumentText, Empty, type Tone } from '../components/ui.tsx'
import { attachmentText, code, text } from '../fhir.ts'
import { daysBetween, formatDate, todayIso } from '../format.ts'
import { isLabOrder, openOrders, type Chart } from '../model.ts'
import { select } from '../route.ts'

const CATEGORIES: Record<string, [string, Tone]> = {
  RAD: ['Imaging', 'blue'],
  CUS: ['Echo', 'teal'],
  SP: ['Pathology', 'violet'],
  GE: ['Molecular', 'violet'],
}

function category(report: fhir4.DiagnosticReport): [string, Tone] {
  const concept = report.category?.[0]
  return CATEGORIES[code(concept) ?? ''] ?? [text(concept) || 'Report', 'slate']
}

export function Reports({ chart, selected }: { chart: Chart; selected?: string }) {
  const id = chart.patient.id ?? ''
  const today = todayIso()
  const awaiting = openOrders(chart).filter((order) => !isLabOrder(order))
  const current = chart.reports.find((report) => report.id === selected) ?? chart.reports[0]
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
      <div className="space-y-4">
        {awaiting.length > 0 && (
          <Card title="Awaiting" subtitle="Requested, with no report on file" flush>
            <ul className="divide-y divide-slate-100">
              {awaiting.map((order) => {
                const due = (order.occurrenceDateTime ?? today).slice(0, 10)
                const late = daysBetween(due, today)
                return (
                  <li key={order.id} className="flex items-start gap-2 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-900">{text(order.code)}</p>
                      <p className="text-xs text-slate-500">
                        Ordered {formatDate(order.authoredOn)} by {order.requester?.display}
                      </p>
                      <p className="mt-1">
                        {late > 0 ? (
                          <Badge tone="rose">
                            Overdue {late} d · due {formatDate(due)}
                          </Badge>
                        ) : (
                          <Badge>Due {formatDate(due)}</Badge>
                        )}
                      </p>
                    </div>
                    <SourceButton resource={order} />
                  </li>
                )
              })}
            </ul>
          </Card>
        )}
        <Card title="Reports" subtitle={`${chart.reports.length} on file`} flush>
          {chart.reports.length === 0 ? (
            <div className="px-4 py-3">
              <Empty>No imaging, pathology or other reports.</Empty>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {chart.reports.map((report) => {
                const [label, tone] = category(report)
                return (
                  <li key={report.id}>
                    <button
                      type="button"
                      onClick={() => select(id, 'reports', report.id ?? '')}
                      aria-current={report.id === current?.id ? 'true' : undefined}
                      className={`block w-full px-4 py-2.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-teal-600 ${
                        report.id === current?.id ? 'bg-teal-50' : 'hover:bg-slate-50'
                      }`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium tabular-nums text-slate-500">{formatDate(report.effectiveDateTime)}</span>
                        <Badge tone={tone}>{label}</Badge>
                      </span>
                      <span className="mt-0.5 block text-sm font-medium text-slate-900">{text(report.code)}</span>
                      <span className="block truncate text-xs text-slate-500">{report.resultsInterpreter?.[0]?.display}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      </div>
      {current && <ReportDetail report={current} />}
    </div>
  )
}

function ReportDetail({ report }: { report: fhir4.DiagnosticReport }) {
  const body = attachmentText(report.presentedForm)
  const interpreter = report.resultsInterpreter?.[0]?.display ?? report.performer?.[0]?.display
  return (
    <Card
      title={text(report.code)}
      subtitle={`Performed ${formatDate(report.effectiveDateTime)} · reported ${formatDate(report.issued)}${interpreter ? ` · ${interpreter}` : ''}`}
      action={<SourceButton resource={report} label="Report" />}
    >
      {report.conclusion && (
        <div className="mb-4 rounded-lg bg-amber-50 px-3 py-2 ring-1 ring-amber-100">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-800">Conclusion</p>
          <p className="mt-0.5 text-sm text-slate-900">{report.conclusion}</p>
        </div>
      )}
      {body ? <DocumentText text={body} /> : <Empty>No report text attached.</Empty>}
    </Card>
  )
}
