/** Client for the agent service (agent/app.py), reached through the dev proxy at /api. */

export type Status = 'ok' | 'check' | 'unsourced' | 'unsupported' | 'plain'

export interface Segment {
  text?: string
  cite?: string[]
}

export interface Block {
  kind: 'paragraph' | 'bullet' | 'heading'
  level: number
  segments: Segment[]
  status: Status
  issues: string[]
}

export interface Step {
  tool: string
  label: string
}

export interface Answer {
  blocks: Block[]
  sources: Record<string, { label: string }>
  steps: Step[]
  elapsedMs: number
  model: string
}

export type AgentEvent = { type: 'step'; step: Step } | { type: 'answer'; answer: Answer } | { type: 'error'; message: string }

/** Open loops (agent/loops.py), worst first. */
export type LoopStatus =
  | 'missing'
  | 'dose_mismatch'
  | 'overdue'
  | 'to_review'
  | 'not_ordered'
  | 'no_trace'
  | 'to_inform'
  | 'pending'
  | 'conditional'
  | 'done'

/** One step of a test or scan: ordered, performed, resulted, reviewed, communicated. */
export interface Stage {
  stage: 'ordered' | 'performed' | 'resulted' | 'reviewed' | 'communicated'
  done: boolean
  at: string | null
  by: string | null
  refs: string[]
  /** Taken from a later visit note that quotes the result, not from a mark. */
  inferred: boolean
  note: string | null
}

export interface LoopPart {
  name: string
  status: LoopStatus
  detail: string
  evidence: string[]
  stages: Stage[]
  /** The report a review or communication mark points at. */
  target: string | null
}

export interface Loop {
  source: 'plan' | 'order' | 'result'
  note: string | null
  noteDate: string | null
  author: string | null
  quote: string
  line: string
  kind: string
  status: LoopStatus
  due: string | null
  detail: string
  evidence: string[]
  parts: LoopPart[]
  stages: Stage[]
  target: string | null
}

export interface PatientLoops {
  patient: string
  today: string
  loops: Loop[]
  unread: string[]
}

export type LoopCounts = { statuses?: Partial<Record<LoopStatus, number>>; unread?: number; error?: string }

/** A review (FHIR Task) or a communication to the patient (FHIR Communication) left by a clinician; agent/marks.py. */
export interface Mark {
  id: string
  kind: 'review' | 'communication'
  about: string[]
  by: string
  byName: string
  at: string
  medium: string | null
  note: string | null
}

export type Medium = 'in_person' | 'phone' | 'video' | 'letter' | 'portal'

/** Medication reconciliation (agent/meds.py): orders against what the notes say. */
export interface MedicationOrder {
  ref: string
  name: string
  dose: string
  start: string | null
  end: string | null
  status: string
  statusReason: string | null
  reason: string | null
  prescriber: string | null
}

export interface MedicationMention {
  quote: string
  dose: string | null
  status: string
  byPatient: boolean
  note: string
  date: string
  author: string | null
}

export interface MedicationFinding {
  kind: 'dose_differs' | 'stopped_in_note' | 'not_ordered' | 'plan' | 'not_mentioned'
  text: string
  refs: string[]
}

export interface MedicationDrug {
  name: string
  status: string
  dose: string
  orders: MedicationOrder[]
  notes: MedicationMention[]
  mentionedIn: { note: string; date: string; title: string }[]
  findings: MedicationFinding[]
}

export interface MedicationPicture {
  patient: string
  today: string
  uncertainty: string
  drugs: MedicationDrug[]
  unlisted: (MedicationMention & { drug: string; finding: MedicationFinding })[]
  adherence: { quote: string; summary: string; note: string; date: string; author: string | null }[]
  unread: string[]
}

const NOT_RUNNING = 'The agent service is not reachable. Start it from the project folder with: python -m agent'

let acting: string | null = null

/** The practitioner named on every request to the agent (X-Practitioner); set by the clinician picker. */
export function setActingPractitioner(id: string | null): void {
  acting = id
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return acting ? { 'X-Practitioner': acting, ...extra } : extra
}

async function send<T>(url: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { ...init, signal })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error(NOT_RUNNING, { cause: error })
  }
  if (!response.ok) {
    const detail = ((await response.json().catch(() => ({}))) as { detail?: unknown }).detail
    const message = typeof detail === 'string' ? detail : undefined
    throw new Error(response.status >= 500 && !message ? NOT_RUNNING : (message ?? `The agent service answered ${response.status}.`))
  }
  return (await response.json()) as T
}

const getJson = <T>(url: string, signal: AbortSignal) => send<T>(url, { headers: headers() }, signal)

const postJson = <T>(url: string, body: unknown) =>
  send<T>(url, { method: 'POST', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) })

const patientPath = (patientId: string) => `/api/patients/${encodeURIComponent(patientId)}`

export const agentHealth = (signal: AbortSignal) => getJson<{ model: string }>('/api/health', signal)

export type BriefState = 'missing' | 'ready' | 'outdated' | 'preparing'

export interface DayPatient {
  patient: string
  name: string
  mrn: string | null
  appointment: { ref: string; start: string; description: string | null }
  loops: Partial<Record<LoopStatus, number>>
  medications: number
  brief: { state: BriefState; preparedAt: string | null }
}

/** A clinician's day (agent/app.py, briefs.py). */
export interface ClinicDay {
  clinician: { id: string; name: string }
  day: string
  today: string
  totals: { visits: number; toReview: number; followUps: number; medications: number; briefsReady: number }
  patients: DayPatient[]
}

export interface PreparedBrief {
  state: BriefState
  brief: null | { question: string; preparedAt: string; visit: string | null; current: boolean; answer: Answer }
}

const dayQuery = (day?: string) => (day ? `?${new URLSearchParams({ day })}` : '')

export const clinicDay = (clinicianId: string, day: string | undefined, signal: AbortSignal) =>
  getJson<ClinicDay>(`/api/clinicians/${encodeURIComponent(clinicianId)}/day${dayQuery(day)}`, signal)

export const prepareBriefs = (clinicianId: string, day?: string) =>
  postJson<{ day: string; started: string[] }>(`/api/clinicians/${encodeURIComponent(clinicianId)}/briefs${dayQuery(day)}`, {})

export const patientBrief = (patientId: string, signal: AbortSignal) => getJson<PreparedBrief>(`${patientPath(patientId)}/brief`, signal)

export const patientMedications = (patientId: string, signal: AbortSignal) =>
  getJson<MedicationPicture>(`${patientPath(patientId)}/medications`, signal)

export type SurgeryRegion = 'abdomen' | 'chest' | 'head_neck' | 'spine_limbs' | 'other'

export interface SurgerySource {
  ref: string
  kind: 'procedure' | 'note' | 'report'
  label: string
  quote: string | null
  date?: string
}

/** One earlier operation, merged from Procedure records, notes and reports (agent/surgery.py). */
export interface Operation {
  name: string
  date: string | null
  precision: 'day' | 'month' | 'year' | 'none'
  when: string
  year: number | null
  yearsDiffer: number[]
  approach: string | null
  side: string | null
  region: SurgeryRegion
  regionLabel: string
  complications: string[]
  implants: string[]
  doneHere: boolean
  elsewhere: boolean
  onlyInNotes: boolean
  sources: SurgerySource[]
}

export interface SurgeryStatement {
  ref: string
  label: string
  date: string
  quote: string
}

export interface SurgicalHistory {
  patient: string
  today: string
  operations: Operation[]
  clues: (SurgeryStatement & { finding: string })[]
  noneStated: SurgeryStatement[]
  regions: Record<SurgeryRegion, string>
  searched: { procedures: number; notes: number; reports: number; documentsRead: number; earliest: string | null }
  unread: string[]
}

export const patientSurgery = (patientId: string, signal: AbortSignal) =>
  getJson<SurgicalHistory>(`${patientPath(patientId)}/surgery`, signal)

export async function patientMarks(patientId: string, signal: AbortSignal): Promise<Mark[]> {
  return (await getJson<{ marks: Mark[] }>(`${patientPath(patientId)}/marks`, signal)).marks
}

export async function markReviewed(patientId: string, focus: string[], note?: string): Promise<Mark[]> {
  return (await postJson<{ marks: Mark[] }>(`${patientPath(patientId)}/reviews`, { focus, note })).marks
}

export async function markCommunicated(
  patientId: string,
  about: string[],
  medium: Medium,
  sent?: string,
  note?: string,
): Promise<Mark[]> {
  return (await postJson<{ marks: Mark[] }>(`${patientPath(patientId)}/communications`, { about, medium, sent, note })).marks
}

/** `markId` is "Task/123" or "Communication/456". */
export async function withdrawMark(patientId: string, markId: string): Promise<void> {
  await postJson(`${patientPath(patientId)}/marks/${markId}/withdraw`, {})
}

export const patientLoops = (patientId: string, signal: AbortSignal) =>
  getJson<PatientLoops>(`${patientPath(patientId)}/loops`, signal)

export async function loopSummary(patientIds: string[], signal: AbortSignal): Promise<Record<string, LoopCounts>> {
  const query = new URLSearchParams({ patients: patientIds.join(',') })
  return (await getJson<{ patients: Record<string, LoopCounts> }>(`/api/loops/summary?${query}`, signal)).patients
}

/** Asks one question in a conversation and reports progress as server-sent events arrive. */
export async function ask(
  patientId: string,
  sessionId: string,
  question: string,
  onEvent: (event: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${patientPath(patientId)}/chat`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ session_id: sessionId, question }),
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new Error(NOT_RUNNING, { cause: error })
  }
  if (!response.ok || !response.body) {
    throw new Error(response.status >= 500 ? NOT_RUNNING : `The agent service answered ${response.status} ${response.statusText}.`)
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const event = parseEvent(buffer.slice(0, end))
      buffer = buffer.slice(end + 2)
      if (event) onEvent(event)
    }
  }
}

function parseEvent(chunk: string): AgentEvent | undefined {
  let name = 'message'
  const data: string[] = []
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (data.length === 0) return undefined
  const payload: unknown = JSON.parse(data.join('\n'))
  if (name === 'step') return { type: 'step', step: payload as Step }
  if (name === 'answer') return { type: 'answer', answer: payload as Answer }
  if (name === 'error') return { type: 'error', message: (payload as { message: string }).message }
  return undefined
}
