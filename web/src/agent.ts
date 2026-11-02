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

const putJson = <T>(url: string, body: unknown) =>
  send<T>(url, { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) })

const deleteJson = <T>(url: string) => send<T>(url, { method: 'DELETE', headers: headers() })

const patientPath = (patientId: string) => `/api/patients/${encodeURIComponent(patientId)}`

export interface AgentHealth {
  model: string
  /** The second, clinical model for visit considerations, when one is configured. */
  clinicalModel: string | null
  /** The clinic day the agent works with; `fixedToday` when AGENT_TODAY sets it. */
  today: string
  fixedToday: boolean
}

export const agentHealth = (signal: AbortSignal) => getJson<AgentHealth>('/api/health', signal)

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

// ---------------------------------------------------------------- visits (agent/visits.py)

export type AgendaKind = 'reason' | 'loop' | 'medication' | 'allergy'

/** Something the record suggests covering at this visit. */
export interface AgendaItem {
  id: string
  kind: AgendaKind
  text: string
  detail: string
  refs: string[]
  done: boolean
  doneBy: string | null
}

export type NoteSection = 'subjective' | 'objective' | 'assessment' | 'plan'

/** Live help on one jotting (agent/jottings.py): the model's reading, checked, and the code's alerts. */
export interface JottingReview {
  status: 'pending' | 'done' | 'failed'
  section?: NoteSection | null
  covers?: string[]
  links?: { ref: string; label: string }[]
  gaps?: string[]
  alerts?: { kind: 'allergy' | 'dose'; text: string; refs: string[] }[]
  error?: string
}

export interface Jotting {
  id: string
  time: string
  text: string
  by: string
  review: JottingReview | null
}

export interface Visit {
  id: string
  encounter: string
  patient: string
  practitioner: string
  practitionerName: string
  started: string
  status: 'open' | 'signed' | 'cancelled'
  appointment: string | null
  reason: string | null
  agenda: AgendaItem[]
  jottings: Jotting[]
  version: number
  draft: NoteDraft | null
  note: string | null
}

export type ConsiderationKind = 'cause' | 'check' | 'caution'

/** One suggestion from the clinical model, kept by code because it cites a jotting and only what it was shown. */
export interface Consideration {
  kind: ConsiderationKind
  text: string
  /** Jottings (`ref` null) and record items it rests on. */
  basis: { id: string; ref: string | null; label: string }[]
  /** A record item it cites already has a code alert in this visit. */
  alerted: boolean
  feedback?: 'useful' | 'not-useful'
}

/** The clinical model's latest considerations (agent/considerations.py), with the jottings they were made from. */
export interface Considerations {
  model: string
  jottings: [string, string][]
  at: string
  status: 'done' | 'failed'
  items?: Consideration[]
  dropped?: { kind: ConsiderationKind; text: string; reason: string }[]
  seconds?: number
  error?: string
}

export interface ConsiderationsState {
  enabled: boolean
  model: string | null
  /** A run is working on the jottings as they stand. */
  running: boolean
  /** The considerations were made from the jottings as they stand. */
  current: boolean
  considerations: Considerations | null
}

export interface DraftItem {
  text: string
  sources: string[]
  issues: string[]
}

/** The note drafted from the jottings and checked by code (agent/notes.py). */
export interface NoteDraft {
  sections: Record<NoteSection, DraftItem[]>
  unused: string[]
  created: string
  jottings: string[]
}

const visitPath = (visitId: string) => `/api/visits/${encodeURIComponent(visitId)}`

export async function patientVisit(patientId: string, signal: AbortSignal): Promise<Visit | null> {
  return (await getJson<{ visit: Visit | null }>(`${patientPath(patientId)}/visit`, signal)).visit
}

export const startVisit = (patientId: string) => postJson<Visit>(`${patientPath(patientId)}/visits`, {})
export const addJotting = (visitId: string, text: string) => postJson<Visit>(`${visitPath(visitId)}/jottings`, { text })
export const editJotting = (visitId: string, jottingId: string, text: string) =>
  putJson<Visit>(`${visitPath(visitId)}/jottings/${encodeURIComponent(jottingId)}`, { text })
export const deleteJotting = (visitId: string, jottingId: string) =>
  deleteJson<Visit>(`${visitPath(visitId)}/jottings/${encodeURIComponent(jottingId)}`)
export const tickAgenda = (visitId: string, itemId: string, done: boolean) =>
  postJson<Visit>(`${visitPath(visitId)}/agenda/${encodeURIComponent(itemId)}`, { done })
export const draftNote = (visitId: string) => postJson<Visit>(`${visitPath(visitId)}/draft`, {})
export const signNote = (visitId: string, sections: Record<NoteSection, string>) => postJson<Visit>(`${visitPath(visitId)}/sign`, sections)
export const cancelVisit = (visitId: string) => postJson<Visit>(`${visitPath(visitId)}/cancel`, {})
export const visitConsiderations = (visitId: string, signal: AbortSignal) =>
  getJson<ConsiderationsState>(`${visitPath(visitId)}/considerations`, signal)
export const makeConsiderations = (visitId: string) => postJson<ConsiderationsState>(`${visitPath(visitId)}/considerations`, {})
export const rateConsideration = (visitId: string, index: number, text: string, useful: boolean) =>
  postJson<ConsiderationsState>(`${visitPath(visitId)}/considerations/feedback`, { index, text, useful })

// ---------------------------------------------------------------- onboarding (agent/onboard.py)

export type ReviewStatus = 'new' | 'duplicate' | 'differs' | 'ask'
export type ReviewSection = 'allergies' | 'problems' | 'medications' | 'procedures' | 'results'

/** One item of a patient's national summary, checked against our chart. */
export interface ReviewItem {
  key: string
  section: ReviewSection
  label: string
  detail: string
  when: string | null
  status: ReviewStatus
  reason: string
  chart: string[]
  critical: boolean
  stale: boolean
}

export interface OnboardingReview {
  onboarding: string
  patient: { name: string; birthDate: string; gender: string; nationalId: string; existing: boolean; id: string }
  source: { service: string; summaryDate: string }
  expiresAt: string
  items: ReviewItem[]
  imported: string[] | null
}

export interface ConsentSent {
  requestId: string
  sentTo: string
  expiresAt: string
}

export interface ImportDecision {
  key: string
  import: boolean
  taking?: 'yes' | 'no' | 'different'
  dose?: string
  current?: boolean
}

export interface ImportResult {
  patient: string
  written: string[]
  provenance: string
}

export interface PhoneMessage {
  to: string
  patient: string
  time: string
  text: string
}

export const requestConsent = (nationalId: string, name: string, birthDate: string) =>
  postJson<ConsentSent>('/api/onboarding/consent', { nationalId, name, birthDate })

export const confirmConsent = (requestId: string, code: string) =>
  postJson<OnboardingReview>(`/api/onboarding/consent/${encodeURIComponent(requestId)}/confirm`, { code })

export const acceptOnboarding = (onboarding: string, decisions: ImportDecision[]) =>
  postJson<ImportResult>(`/api/onboarding/${encodeURIComponent(onboarding)}/accept`, { decisions })

export interface DemoPerson {
  nationalId: string
  name: string
  birthDate: string
  gender: string
  counts: Record<ReviewSection, number>
}

/** Who has a record in the simulated national service: a demo aid, which a real service would never offer. */
export async function nationalPeople(signal: AbortSignal): Promise<DemoPerson[]> {
  const response = await fetch('/national/demo/people', { signal })
  if (!response.ok) throw new Error('The national record service is not reachable. Start it with: python -m national')
  return ((await response.json()) as { people: DemoPerson[] }).people
}

/** The simulated patient's phone, straight from the national record service: it stands for the patient's device. */
export async function nationalPhone(signal: AbortSignal): Promise<PhoneMessage[]> {
  const response = await fetch('/national/demo/phone', { signal })
  if (!response.ok) throw new Error('The national record service is not reachable. Start it with: python -m national')
  return ((await response.json()) as { messages: PhoneMessage[] }).messages
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
