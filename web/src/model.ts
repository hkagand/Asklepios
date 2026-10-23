import { code, read, refId, search, text } from './fhir.ts'
import { isoDay, todayIso, toTime } from './format.ts'

export type Flag = 'H' | 'L'

export interface Point {
  time: number
  value: number
  flag?: Flag
  observation: fhir4.Observation
}

/** All results for one test (or vital sign), oldest first. */
export interface Series {
  key: string
  name: string
  unit: string
  group: string
  decimals: number
  low?: number
  high?: number
  range?: string
  points: Point[]
}

export interface Chart {
  patient: fhir4.Patient
  conditions: fhir4.Condition[]
  medications: fhir4.MedicationRequest[]
  allergies: fhir4.AllergyIntolerance[]
  encounters: fhir4.Encounter[]
  notes: fhir4.DocumentReference[]
  labReports: fhir4.DiagnosticReport[]
  reports: fhir4.DiagnosticReport[]
  orders: fhir4.ServiceRequest[]
  appointments: fhir4.Appointment[]
  observations: Map<string, fhir4.Observation>
  labs: Series[]
  vitals: Series[]
}

const LAB_GROUPS: [string, string[]][] = [
  ['Haematology', ['718-7', '4544-3', '787-2', '6690-2', '751-8', '777-3']],
  ['Iron studies', ['2276-4']],
  ['Kidney & electrolytes', ['2160-0', '98979-8', '3094-0', '2951-2', '2823-3', '2075-0', '2028-9', '17861-6', '19123-9', '9318-7']],
  ['Liver', ['1742-6', '1920-8', '6768-6', '1975-2', '1751-7']],
  ['Diabetes & lipids', ['4548-4', '2345-7', '2093-3', '13457-7', '2085-9', '2571-8']],
  ['Thyroid', ['3016-3', '3024-7', '8099-4']],
  ['Cardiac', ['33762-6']],
  ['Tumour markers', ['2039-6']],
]
const VITAL_SIGNS = ['8480-6', '8462-4', '8867-4', '29463-7', '39156-5']
const GROUPS = [...LAB_GROUPS.map(([group]) => group), 'Other', 'Vital signs']
const LAB_PLACE = new Map(LAB_GROUPS.flatMap(([group, codes]) => codes.map((loinc, index) => [loinc, { group, index }] as const)))

const newestFirst =
  <T>(time: (item: T) => number) =>
  (a: T, b: T) =>
    time(b) - time(a)

export const encounterStart = (encounter: fhir4.Encounter): number => toTime(encounter.period?.start)
export const reportTime = (report: fhir4.DiagnosticReport): number => toTime(report.effectiveDateTime ?? report.issued)

export async function loadChart(id: string, signal: AbortSignal): Promise<Chart> {
  const byPatient = { patient: id }
  const [patient, conditions, medications, allergies, observations, diagnosticReports, notes, encounters, orders, appointments] =
    await Promise.all([
      read<fhir4.Patient>('Patient', id, signal),
      search<fhir4.Condition>('Condition', byPatient, signal),
      search<fhir4.MedicationRequest>('MedicationRequest', byPatient, signal),
      search<fhir4.AllergyIntolerance>('AllergyIntolerance', byPatient, signal),
      search<fhir4.Observation>('Observation', byPatient, signal),
      search<fhir4.DiagnosticReport>('DiagnosticReport', byPatient, signal),
      search<fhir4.DocumentReference>('DocumentReference', byPatient, signal),
      search<fhir4.Encounter>('Encounter', byPatient, signal),
      search<fhir4.ServiceRequest>('ServiceRequest', byPatient, signal),
      search<fhir4.Appointment>('Appointment', byPatient, signal),
    ])
  const isLab = (report: fhir4.DiagnosticReport) => report.category?.some((category) => code(category) === 'LAB') ?? false
  const labs = new Map<string, Series>()
  const vitals = new Map<string, Series>()
  for (const observation of observations) {
    const category = code(observation.category?.[0])
    if (category === 'laboratory') {
      const group = LAB_PLACE.get(code(observation.code) ?? '')?.group ?? 'Other'
      addPoint(labs, observation, observation.code, observation.valueQuantity, group)
    } else if (category === 'vital-signs') {
      for (const part of observation.component ?? [observation]) {
        if (VITAL_SIGNS.includes(code(part.code) ?? '')) {
          addPoint(vitals, observation, part.code, part.valueQuantity, 'Vital signs')
        }
      }
    }
  }
  return {
    patient,
    conditions: sortConditions(conditions),
    medications: medications.sort(newestFirst((medication) => toTime(medication.authoredOn))),
    allergies,
    encounters: encounters.sort(newestFirst(encounterStart)),
    notes: notes.sort(newestFirst((note) => toTime(note.date))),
    labReports: diagnosticReports.filter(isLab).sort(newestFirst(reportTime)),
    reports: diagnosticReports.filter((report) => !isLab(report)).sort(newestFirst(reportTime)),
    orders,
    appointments: appointments.sort((a, b) => toTime(a.start) - toTime(b.start)),
    observations: new Map(observations.map((observation) => [observation.id ?? '', observation])),
    labs: finish(labs),
    vitals: finish(vitals),
  }
}

function addPoint(
  target: Map<string, Series>,
  observation: fhir4.Observation,
  concept: fhir4.CodeableConcept,
  quantity: fhir4.Quantity | undefined,
  group: string,
): void {
  const key = code(concept)
  const value = quantity?.value
  const time = toTime(observation.effectiveDateTime)
  if (!key || value === undefined || Number.isNaN(time)) return
  let series = target.get(key)
  if (!series) {
    const range = observation.referenceRange?.[0]
    series = {
      key,
      name: text(concept),
      unit: quantity?.unit ?? '',
      group,
      decimals: 0,
      low: range?.low?.value,
      high: range?.high?.value,
      range: range?.text,
      points: [],
    }
    target.set(key, series)
  }
  series.points.push({ time, value, flag: flagOf(observation), observation })
}

function finish(series: Map<string, Series>): Series[] {
  const list = [...series.values()]
  for (const item of list) {
    item.points.sort((a, b) => a.time - b.time)
    item.decimals = Math.min(3, Math.max(...item.points.map((point) => decimalsOf(point.value))))
  }
  return list.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name))
}

function rank(series: Series): number {
  const position = series.group === 'Vital signs' ? VITAL_SIGNS.indexOf(series.key) : (LAB_PLACE.get(series.key)?.index ?? 99)
  return GROUPS.indexOf(series.group) * 100 + position
}

function decimalsOf(value: number): number {
  return (String(value).split('.')[1] ?? '').length
}

export function flagOf(observation: fhir4.Observation): Flag | undefined {
  const interpretation = code(observation.interpretation?.[0])
  if (interpretation === 'H' || interpretation === 'HH') return 'H'
  if (interpretation === 'L' || interpretation === 'LL') return 'L'
  return undefined
}

/** Staged diagnoses (cancers) first, then the most recent onset. */
function sortConditions(conditions: fhir4.Condition[]): fhir4.Condition[] {
  const staged = (condition: fhir4.Condition) => (condition.stage?.length ? 1 : 0)
  return conditions.sort(
    (a, b) => staged(b) - staged(a) || (b.onsetDateTime ?? '').localeCompare(a.onsetDateTime ?? ''),
  )
}

export const isActive = (condition: fhir4.Condition): boolean => code(condition.clinicalStatus) === 'active'

// ------------------------------------------------------------ derived views

export interface Change {
  series: Series
  latest: Point
  baseline?: Point
}

export function lastVisit(chart: Chart, now = Date.now()): fhir4.Encounter | undefined {
  return chart.encounters.find((encounter) => encounterStart(encounter) < now)
}

/** Tests resulted after `since`: the newest value against the last one before it. */
export function changesSince(chart: Chart, since: number): Change[] {
  return chart.labs.flatMap((series) => {
    const latest = series.points.at(-1)
    if (!latest || latest.time <= since) return []
    return [{ series, latest, baseline: series.points.filter((point) => point.time <= since).at(-1) }]
  })
}

export function percentChange(from: number, to: number): number | undefined {
  return from === 0 ? undefined : ((to - from) / Math.abs(from)) * 100
}

export function openOrders(chart: Chart): fhir4.ServiceRequest[] {
  return chart.orders
    .filter((order) => order.status === 'active')
    .sort((a, b) => (a.occurrenceDateTime ?? '').localeCompare(b.occurrenceDateTime ?? ''))
}

export function nextAppointment(appointments: fhir4.Appointment[], today = todayIso()): fhir4.Appointment | undefined {
  return appointments.find((appointment) => appointment.status === 'booked' && appointment.start && isoDay(appointment.start) >= today)
}

export function participant(appointment: fhir4.Appointment, type: 'Patient' | 'Practitioner'): fhir4.Reference | undefined {
  return appointment.participant.find((item) => item.actor?.reference?.startsWith(`${type}/`))?.actor
}

export const isLabOrder = (order: fhir4.ServiceRequest): boolean => code(order.category?.[0]) === '108252007'

/** One row of the visit history: an encounter with its notes, or a note written outside any encounter. */
export interface VisitItem {
  key: string
  time: number
  encounter?: fhir4.Encounter
  notes: fhir4.DocumentReference[]
}

export function timeline(chart: Chart, now = Date.now()): VisitItem[] {
  const items: VisitItem[] = chart.encounters
    .filter((encounter) => encounterStart(encounter) < now)
    .map((encounter) => ({ key: encounter.id ?? '', time: encounterStart(encounter), encounter, notes: [] }))
  const byEncounter = new Map(items.map((item) => [item.key, item]))
  for (const note of chart.notes) {
    const visit = byEncounter.get(refId(note.context?.encounter?.[0]) ?? '')
    if (visit) visit.notes.push(note)
    else items.push({ key: note.id ?? '', time: toTime(note.date), notes: [note] })
  }
  return items.sort((a, b) => b.time - a.time)
}

export function visitTitle(item: VisitItem): string {
  return item.notes[0]?.description || text(item.encounter?.type?.[0]) || 'Visit'
}

export function visitClinician(item: VisitItem): string | undefined {
  return item.encounter?.participant?.[0]?.individual?.display ?? item.notes[0]?.author?.[0]?.display
}

const VITAL_LABELS: Record<string, (value: string) => string> = {
  '8867-4': (value) => `HR ${value}/min`,
  '29463-7': (value) => `weight ${value} kg`,
  '39156-5': (value) => `BMI ${value}`,
}

export function vitalsAt(chart: Chart, encounterId: string): string | undefined {
  const values = new Map<string, string>()
  for (const series of chart.vitals) {
    const point = series.points.find((item) => refId(item.observation.encounter) === encounterId)
    if (point) values.set(series.key, point.value.toFixed(series.decimals))
  }
  if (values.size === 0) return undefined
  const parts = values.has('8480-6') ? [`BP ${values.get('8480-6')}/${values.get('8462-4')} mmHg`] : []
  for (const [key, label] of Object.entries(VITAL_LABELS)) {
    const value = values.get(key)
    if (value) parts.push(label(value))
  }
  return parts.join(' · ')
}

// ----------------------------------------------------------------- worklist

export interface WorklistEntry {
  patient: fhir4.Patient
  appointment?: fhir4.Appointment
  problems: string[]
  open: number
  overdue: number
}

export async function loadWorklist(signal: AbortSignal): Promise<WorklistEntry[]> {
  const today = todayIso()
  const [patients, appointments, conditions, orders] = await Promise.all([
    search<fhir4.Patient>('Patient', {}, signal),
    search<fhir4.Appointment>('Appointment', { date: `ge${today}`, status: 'booked' }, signal),
    search<fhir4.Condition>('Condition', { 'clinical-status': 'active' }, signal),
    search<fhir4.ServiceRequest>('ServiceRequest', { status: 'active' }, signal),
  ])
  const next = new Map<string, fhir4.Appointment>()
  for (const appointment of appointments.sort((a, b) => toTime(a.start) - toTime(b.start))) {
    const id = refId(participant(appointment, 'Patient'))
    if (id && !next.has(id)) next.set(id, appointment)
  }
  const problems = groupBySubject(sortConditions(conditions))
  const open = groupBySubject(orders)
  const startOf = (entry: WorklistEntry) => toTime(entry.appointment?.start) || Number.MAX_SAFE_INTEGER
  return patients
    .map((patient) => {
      const id = patient.id ?? ''
      const patientOrders = open.get(id) ?? []
      return {
        patient,
        appointment: next.get(id),
        problems: (problems.get(id) ?? []).map((condition) => text(condition.code)),
        open: patientOrders.length,
        overdue: patientOrders.filter((order) => (order.occurrenceDateTime ?? today) < today).length,
      }
    })
    .sort((a, b) => startOf(a) - startOf(b))
}

function groupBySubject<T extends { subject: fhir4.Reference }>(items: T[]): Map<string, T[]> {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const id = refId(item.subject)
    if (id) groups.set(id, [...(groups.get(id) ?? []), item])
  }
  return groups
}
