import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  acceptOnboarding,
  confirmConsent,
  nationalPeople,
  nationalPhone,
  requestConsent,
  type ConsentSent,
  type DemoPerson,
  type ImportDecision,
  type ImportResult,
  type OnboardingReview,
  type PhoneMessage,
  type ReviewItem,
  type ReviewSection,
  type ReviewStatus,
} from '../agent.ts'
import { useClinician } from '../components/clinician.tsx'
import { Badge, Card, type Tone } from '../components/ui.tsx'
import { search } from '../fhir.ts'
import { ageOn, formatDate, formatTime, sexLabel, todayIso } from '../format.ts'
import { patientHref } from '../route.ts'

const NATIONAL_ID = 'urn:demo:asklepios:national-id'

const STATUS: Record<ReviewStatus, { label: string; tone: Tone }> = {
  new: { label: 'New', tone: 'teal' },
  duplicate: { label: 'Already in chart', tone: 'slate' },
  differs: { label: 'Differs from chart', tone: 'amber' },
  ask: { label: 'Ask the patient', tone: 'blue' },
}
const SECTIONS: [ReviewSection, string][] = [
  ['allergies', 'Allergies'],
  ['problems', 'Problems'],
  ['medications', 'Medications'],
  ['procedures', 'Operations and procedures'],
  ['results', 'Results'],
]

type Step = 'identify' | 'consent' | 'review' | 'done'

/** A new patient's history from the national record service (simulated): consent, review, then import. */
export function Onboard() {
  const { current } = useClinician()
  const [sent, setSent] = useState<ConsentSent>()
  const [review, setReview] = useState<OnboardingReview>()
  const [result, setResult] = useState<ImportResult>()
  const step: Step = result ? 'done' : review ? 'review' : sent ? 'consent' : 'identify'
  const restart = () => {
    setSent(undefined)
    setReview(undefined)
    setResult(undefined)
  }

  return (
    <main className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <h1 className="text-[32px] font-extrabold leading-[1.1] tracking-[-0.025em] text-slate-900">New patient</h1>
          <p className="mt-1.5 max-w-2xl text-[15px] text-slate-600">
            Bring in the patient&apos;s history from the national record, with their consent. Nothing is added to the
            chart until you review it.
          </p>
        </div>
        <Badge tone="violet" title="A demo service with synthetic records; it is not e-Nabız and talks to no real system">
          National record (simulated)
        </Badge>
      </div>
      <Steps step={step} />
      {!current ? (
        <p className="mt-6 rounded-lg border-l-4 border-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Choose who is viewing (top right) first: the request and the import are made in your name.
        </p>
      ) : step === 'review' && review ? (
        <Review review={review} onDone={setResult} onRestart={restart} />
      ) : step === 'done' && review && result ? (
        <Done review={review} result={result} onRestart={restart} />
      ) : (
        <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
          {step === 'identify' ? <Identify onSent={setSent} /> : <Consent sent={sent!} onConfirmed={setReview} onRestart={restart} />}
          <Phone sentTo={sent?.sentTo} />
        </div>
      )}
    </main>
  )
}

function Steps({ step }: { step: Step }) {
  const steps: [Step, string][] = [
    ['identify', 'Identify'],
    ['consent', "Patient's consent"],
    ['review', 'Review'],
    ['done', 'Imported'],
  ]
  const at = steps.findIndex(([key]) => key === step)
  return (
    <ol className="mt-5 flex flex-wrap gap-x-6 gap-y-2 border-b border-slate-300 pb-3 text-[14px] font-semibold">
      {steps.map(([key, label], index) => (
        <li key={key} className={`flex items-center gap-2 ${index === at ? 'text-slate-900' : index < at ? 'text-slate-500' : 'text-slate-400'}`}>
          <span
            className={`grid h-6 w-6 place-items-center rounded-full border-2 font-mono text-[12px] ${
              index === at ? 'border-slate-900 bg-mark' : index < at ? 'border-slate-400 bg-sheet' : 'border-slate-300 bg-sheet'
            }`}
          >
            {index < at ? '✓' : index + 1}
          </span>
          {label}
        </li>
      ))}
    </ol>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[13px] font-semibold text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-slate-500">{hint}</span>}
    </label>
  )
}

const INPUT =
  'mt-1 w-full rounded-md border border-slate-300 bg-sheet px-3 py-2 text-[15px] text-slate-900 focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900'
const PRIMARY =
  'inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-[14px] font-bold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400'

function Identify({ onSent }: { onSent: (sent: ConsentSent) => void }) {
  const [nationalId, setNationalId] = useState('')
  const [name, setName] = useState('')
  const [birthDate, setBirthDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const ready = /^\d{11}$/.test(nationalId) && name.trim() && birthDate

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      onSent(await requestConsent(nationalId, name.trim(), birthDate))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  const fill = (person: DemoPerson) => {
    setNationalId(person.nationalId)
    setName(person.name)
    setBirthDate(person.birthDate)
    setError(undefined)
  }

  return (
    <div className="space-y-6">
      <Card title="Who is the patient?" subtitle="All three must match the national record">
        <form onSubmit={submit} className="grid gap-4 sm:max-w-md">
          <Field label="National identity number" hint="11 digits. The demo's numbers start with 0, which no real number does.">
            <input
              className={`${INPUT} font-mono tracking-wider`}
              inputMode="numeric"
              maxLength={11}
              value={nationalId}
              onChange={(event) => setNationalId(event.target.value.replace(/\D/g, ''))}
              placeholder="00000003001"
            />
          </Field>
          <Field label="Full name">
            <input className={INPUT} value={name} onChange={(event) => setName(event.target.value)} placeholder="Gülay Kaplan" />
          </Field>
          <Field label="Date of birth">
            <input className={INPUT} type="date" value={birthDate} onChange={(event) => setBirthDate(event.target.value)} />
          </Field>
          {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
          <div>
            <button type="submit" className={PRIMARY} disabled={!ready || busy}>
              {busy ? 'Sending…' : 'Send consent code to the patient'}
            </button>
            <p className="mt-2 text-[12.5px] text-slate-500">
              The patient receives a one-time code by SMS. Knowing the number alone is not enough to read the record.
            </p>
          </div>
        </form>
      </Card>
      <DemoPeople chosen={nationalId} onChoose={fill} />
    </div>
  )
}

const COUNTED: [ReviewSection, string, string][] = [
  ['allergies', 'allergy', 'allergies'],
  ['problems', 'problem', 'problems'],
  ['medications', 'medicine', 'medicines'],
  ['procedures', 'operation', 'operations'],
  ['results', 'result', 'results'],
]

/** The synthetic people the simulated service has records for, with whether each is already in our chart. */
function DemoPeople({ chosen, onChoose }: { chosen: string; onChoose: (person: DemoPerson) => void }) {
  const [people, setPeople] = useState<DemoPerson[]>()
  const [charts, setCharts] = useState<Record<string, string>>({})
  const [error, setError] = useState<string>()
  useEffect(() => {
    const controller = new AbortController()
    nationalPeople(controller.signal).then(
      async (found) => {
        setPeople(found)
        const ids = await Promise.all(
          found.map(async (person) => {
            const patients = await search<fhir4.Patient>('Patient', { identifier: `${NATIONAL_ID}|${person.nationalId}` }, controller.signal)
            return [person.nationalId, patients[0]?.id ?? ''] as const
          }),
        )
        setCharts(Object.fromEntries(ids.filter(([, id]) => id)))
      },
      (failure: unknown) => !controller.signal.aborted && setError(failure instanceof Error ? failure.message : String(failure)),
    )
    return () => controller.abort()
  }, [])

  return (
    <Card
      title="Demo people"
      subtitle="Synthetic records in the simulated national service. A real service offers no such list."
      action={<Badge tone="violet">Demo only</Badge>}
      flush
    >
      {error ? (
        <p className="px-4 py-3 text-sm text-rose-800">{error}</p>
      ) : !people ? (
        <p className="px-4 py-3 text-sm text-slate-500">Loading…</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {people.map((person) => {
            const chart = charts[person.nationalId]
            const age = ageOn(person.birthDate, todayIso())
            return (
              <li key={person.nationalId} className={`flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 ${chosen === person.nationalId ? 'bg-mark/30' : ''}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-[15px] font-semibold text-slate-900">{person.name}</span>
                    {chart ? (
                      <a href={patientHref(chart)} className="text-[12.5px] font-semibold text-teal-700 hover:underline">
                        In the chart as {chart.toUpperCase()}
                      </a>
                    ) : (
                      <Badge tone="teal">Not yet a patient here</Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-[13px] text-slate-600">
                    <span className="font-mono">{person.nationalId}</span> · born {formatDate(person.birthDate)}
                    {age !== undefined && ` (${age})`} · {sexLabel(person.gender)}
                  </p>
                  <p className="mt-0.5 text-[12.5px] text-slate-500">
                    {COUNTED.filter(([section]) => person.counts[section])
                      .map(([section, one, many]) => `${person.counts[section]} ${person.counts[section] === 1 ? one : many}`)
                      .join(' · ')}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onChoose(person)}
                  className="rounded-md border border-slate-300 bg-sheet px-3 py-1.5 text-[13px] font-semibold text-slate-700 hover:border-slate-900"
                >
                  Fill in
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function Consent({ sent, onConfirmed, onRestart }: { sent: ConsentSent; onConfirmed: (review: OnboardingReview) => void; onRestart: () => void }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      onConfirmed(await confirmConsent(sent.requestId, code))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Ask the patient for the code" subtitle={`Sent by SMS to ${sent.sentTo} · expires at ${formatTime(sent.expiresAt)}`}>
      <form onSubmit={submit} className="grid gap-4 sm:max-w-md">
        <Field label="Code from the patient's phone">
          <input
            className={`${INPUT} font-mono text-[22px] tracking-[0.4em]`}
            inputMode="numeric"
            maxLength={6}
            autoFocus
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
            placeholder="••••••"
          />
        </Field>
        {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className={PRIMARY} disabled={code.length !== 6 || busy}>
            {busy ? 'Reading the national record…' : 'Confirm and read the record'}
          </button>
          <button type="button" onClick={onRestart} className="text-[14px] font-semibold text-slate-500 hover:text-slate-900">
            Start again
          </button>
        </div>
        <p className="text-[12.5px] text-slate-500">
          The code shows the patient agrees. Access lasts four hours, for this patient only.
        </p>
      </form>
    </Card>
  )
}

/** The patient's phone, simulated: the SMS the national record service sent. */
function Phone({ sentTo }: { sentTo?: string }) {
  const [messages, setMessages] = useState<PhoneMessage[]>([])
  const [error, setError] = useState<string>()
  useEffect(() => {
    if (!sentTo) return
    const controller = new AbortController()
    const read = () =>
      nationalPhone(controller.signal).then(
        (found) => {
          setMessages(found.filter((message) => message.to === sentTo))
          setError(undefined)
        },
        (failure: unknown) => !controller.signal.aborted && setError(failure instanceof Error ? failure.message : String(failure)),
      )
    void read()
    const timer = window.setInterval(read, 2000)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [sentTo])

  return (
    <aside aria-label="Patient's phone (simulated)" className="mx-auto w-full max-w-[20rem]">
      <div className="rounded-[2rem] border-[6px] border-slate-900 bg-slate-900 p-1.5 shadow-lg">
        <div className="min-h-[22rem] rounded-[1.4rem] bg-paper px-3 pb-4 pt-3">
          <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
            <span>{sentTo ?? 'Patient’s phone'}</span>
            <span>Messages</span>
          </div>
          {!sentTo ? (
            <p className="mt-16 px-4 text-center text-[13px] text-slate-400">The consent code will arrive here.</p>
          ) : error ? (
            <p className="mt-6 text-[12.5px] text-rose-700">{error}</p>
          ) : messages.length === 0 ? (
            <p className="mt-16 text-center text-[13px] text-slate-400">Waiting for the message…</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {messages.slice(0, 3).map((message) => (
                <li key={message.time + message.text} className="rounded-2xl rounded-tl-sm bg-sheet px-3 py-2 text-[13px] leading-snug text-slate-800 shadow-sm">
                  <Highlighted text={message.text} />
                  <span className="mt-1 block text-right text-[10.5px] text-slate-400">{formatTime(message.time)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <p className="mt-2 text-center text-[12px] text-slate-500">Simulated phone · no real SMS is sent</p>
    </aside>
  )
}

function Highlighted({ text }: { text: string }) {
  const match = /Code: (\d{6})/.exec(text)
  if (!match) return <>{text}</>
  return (
    <>
      {text.slice(0, match.index)}Code: <span className="mark font-mono text-[15px] font-bold tracking-wider">{match[1]}</span>
      {text.slice(match.index + match[0].length)}
    </>
  )
}

// ---------------------------------------------------------------- review

type Choice = Omit<ImportDecision, 'key'>

/** What happens to an item unless the clinician says otherwise: new items are imported, the rest wait. */
function initial(item: ReviewItem): Choice {
  return { import: item.status === 'new' }
}

/** Items still waiting for the patient's answer before they can be imported. */
const unanswered = (item: ReviewItem, choice: Choice) =>
  choice.import &&
  ((item.section === 'medications' && !choice.taking) ||
    (item.section === 'medications' && choice.taking === 'different' && !choice.dose?.trim()) ||
    (item.section === 'problems' && item.status === 'ask' && choice.current === undefined))

function Review({ review, onDone, onRestart }: { review: OnboardingReview; onDone: (result: ImportResult) => void; onRestart: () => void }) {
  const [choices, setChoices] = useState<Record<string, Choice>>(() =>
    Object.fromEntries(review.items.map((item) => [item.key, initial(item)])),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const set = (key: string, choice: Choice) => setChoices((all) => ({ ...all, [key]: choice }))
  const selected = review.items.filter((item) => choices[item.key].import)
  const waiting = review.items.filter((item) => unanswered(item, choices[item.key]))
  const toAsk = review.items.filter((item) => item.status === 'ask' && !choices[item.key].import && !choices[item.key].taking && choices[item.key].current === undefined)
  const counts = useMemo(
    () => Object.fromEntries((Object.keys(STATUS) as ReviewStatus[]).map((status) => [status, review.items.filter((item) => item.status === status).length])),
    [review.items],
  ) as Record<ReviewStatus, number>
  const { patient } = review

  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const decisions = review.items.map((item) => ({ key: item.key, ...choices[item.key] }))
      onDone(await acceptOnboarding(review.onboarding, decisions))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-6 space-y-4">
      <header className="overflow-hidden rounded-lg bg-slate-900 text-white">
        <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3 px-5 py-4">
          <div>
            <h2 className="text-[24px] font-extrabold tracking-[-0.02em]">{patient.name}</h2>
            <p className="mt-1 text-[14px] text-slate-300">
              {sexLabel(patient.gender)} · born {formatDate(patient.birthDate)} · national id{' '}
              <span className="font-mono text-white">{patient.nationalId}</span>
            </p>
          </div>
          <div className="border-l-2 border-mark pl-4 text-[14px]">
            {patient.existing ? (
              <>
                <p className="font-semibold text-mark">Already a patient here</p>
                <a href={patientHref(patient.id)} className="font-semibold underline decoration-mark underline-offset-2">
                  {patient.id.toUpperCase()}: open chart
                </a>
              </>
            ) : (
              <>
                <p className="font-semibold text-mark">New patient</p>
                <p>Will be registered as {patient.id.toUpperCase()}</p>
              </>
            )}
          </div>
        </div>
        <p className="bg-slate-800 px-5 py-1.5 text-[13px] text-slate-300">
          {review.source.service} · summary of {formatDate(review.source.summaryDate)} · access until {formatTime(review.expiresAt)}
        </p>
      </header>

      <p className="text-[14px] text-slate-700">
        {review.items.length} items:{' '}
        {[
          [counts.new, 'new'],
          [counts.ask, 'to ask the patient about'],
          [counts.differs, 'that differ from the chart'],
          [counts.duplicate, 'already in the chart'],
        ]
          .filter(([count]) => count)
          .map(([count, label]) => `${count} ${label}`)
          .join(', ')}
        . Medicines are recorded as what the patient says they take, never as orders.
      </p>

      {SECTIONS.map(([section, title]) => {
        const items = review.items.filter((item) => item.section === section)
        if (items.length === 0) return null
        return section === 'results' ? (
          <Results key={section} items={items} choices={choices} onChange={set} />
        ) : (
          <Card key={section} title={title} subtitle={`${items.length} from the national record`} flush>
            <ul className="divide-y divide-slate-100">
              {items.map((item) => (
                <Row key={item.key} item={item} choice={choices[item.key]} onChange={(choice) => set(item.key, choice)} />
              ))}
            </ul>
          </Card>
        )
      })}

      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-300 bg-paper/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-lg sm:border">
        <button type="button" className={PRIMARY} disabled={busy || selected.length === 0 || waiting.length > 0} onClick={submit}>
          {busy ? 'Importing…' : `Import ${selected.length} item${selected.length === 1 ? '' : 's'}${patient.existing ? '' : ' and register the patient'}`}
        </button>
        <span className="text-[13px] text-slate-600">
          {waiting.length > 0
            ? `${waiting.length} selected item${waiting.length === 1 ? ' needs' : 's need'} the patient's answer.`
            : toAsk.length > 0
              ? `${toAsk.length} item${toAsk.length === 1 ? '' : 's'} not asked about will not be imported.`
              : 'Each import is recorded with its source, the consent and your name.'}
        </span>
        <button type="button" onClick={onRestart} className="ml-auto text-[14px] font-semibold text-slate-500 hover:text-slate-900">
          Cancel
        </button>
        {error && <p className="w-full rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
      </div>
    </div>
  )
}

function Row({ item, choice, onChange }: { item: ReviewItem; choice: Choice; onChange: (choice: Choice) => void }) {
  const status = STATUS[item.status]
  const duplicate = item.status === 'duplicate'
  return (
    <li className={`grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 px-4 py-3 ${duplicate ? 'bg-slate-50/60' : ''}`}>
      <input
        type="checkbox"
        aria-label={`Import ${item.label}`}
        className="mt-1 h-4 w-4 accent-slate-900"
        disabled={duplicate}
        checked={choice.import}
        onChange={(event) => onChange(event.target.checked ? { ...choice, import: true } : { import: false })}
      />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={`text-[15px] font-semibold ${duplicate ? 'text-slate-500' : 'text-slate-900'}`}>{item.label}</span>
          <Badge tone={status.tone}>{status.label}</Badge>
          {item.critical && <Badge tone="rose">High criticality</Badge>}
          {item.stale && <Badge tone="amber">{item.section === 'medications' ? 'Not renewed' : 'Old entry'}</Badge>}
        </div>
        {item.detail && <p className="mt-0.5 text-[13px] text-slate-600">{item.detail}</p>}
        <p className={`mt-0.5 text-[12.5px] ${item.status === 'new' || duplicate ? 'text-slate-500' : 'font-semibold text-slate-700'}`}>{item.reason}</p>
        {!duplicate && item.section === 'medications' && <Taking choice={choice} onChange={onChange} />}
        {item.section === 'problems' && item.status === 'ask' && <Current choice={choice} onChange={onChange} />}
      </div>
    </li>
  )
}

function Option({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1 text-[13px] font-semibold ${
        active ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-sheet text-slate-700 hover:border-slate-900'
      }`}
    >
      {children}
    </button>
  )
}

/** What the patient says about a medicine; any answer imports it as a statement of what they take. */
function Taking({ choice, onChange }: { choice: Choice; onChange: (choice: Choice) => void }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[12.5px] font-semibold text-slate-500">Patient says:</span>
      <Option active={choice.taking === 'yes'} onClick={() => onChange({ import: true, taking: 'yes' })}>
        Taking as listed
      </Option>
      <Option active={choice.taking === 'different'} onClick={() => onChange({ import: true, taking: 'different', dose: choice.dose })}>
        Different dose
      </Option>
      <Option active={choice.taking === 'no'} onClick={() => onChange({ import: true, taking: 'no' })}>
        Not taking
      </Option>
      {choice.taking === 'different' && (
        <input
          className="ml-1 w-48 rounded-md border border-slate-300 bg-sheet px-2 py-1 text-[13px] focus:border-slate-900 focus:outline-none"
          placeholder="e.g. 10 mg once daily"
          value={choice.dose ?? ''}
          autoFocus
          onChange={(event) => onChange({ ...choice, dose: event.target.value })}
        />
      )}
    </div>
  )
}

function Current({ choice, onChange }: { choice: Choice; onChange: (choice: Choice) => void }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[12.5px] font-semibold text-slate-500">Patient says:</span>
      <Option active={choice.current === true} onClick={() => onChange({ import: true, current: true })}>
        Still current
      </Option>
      <Option active={choice.current === false} onClick={() => onChange({ import: true, current: false })}>
        No longer current
      </Option>
    </div>
  )
}

function Results({
  items,
  choices,
  onChange,
}: {
  items: ReviewItem[]
  choices: Record<string, Choice>
  onChange: (key: string, choice: Choice) => void
}) {
  const importable = items.filter((item) => item.status !== 'duplicate')
  const all = importable.every((item) => choices[item.key].import)
  return (
    <Card
      title="Results"
      subtitle={`${items.length} from the national record`}
      action={
        importable.length > 0 && (
          <button
            type="button"
            className="text-[13px] font-semibold text-teal-700 hover:underline"
            onClick={() => importable.forEach((item) => onChange(item.key, { import: !all }))}
          >
            {all ? 'Select none' : 'Select all'}
          </button>
        )
      }
      flush
    >
      <ul className="divide-y divide-slate-100">
        {items.map((item) => (
          <li key={item.key} className="flex items-center gap-3 px-4 py-2">
            <input
              type="checkbox"
              aria-label={`Import ${item.label}`}
              className="h-4 w-4 accent-slate-900"
              disabled={item.status === 'duplicate'}
              checked={choices[item.key].import}
              onChange={(event) => onChange(item.key, { import: event.target.checked })}
            />
            <span className="min-w-0 flex-1 text-[14px]">
              <span className="font-semibold text-slate-900">{item.label}</span>{' '}
              <span className="text-slate-600">{item.detail}</span>
            </span>
            {item.status !== 'new' && <Badge tone={STATUS[item.status].tone}>{STATUS[item.status].label}</Badge>}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Done({ review, result, onRestart }: { review: OnboardingReview; result: ImportResult; onRestart: () => void }) {
  const items = result.written.filter((reference) => !reference.startsWith('Patient/')).length
  return (
    <Card className="mt-6" title={`${review.patient.name} is ${review.patient.existing ? 'updated' : 'registered'}`}>
      <p className="text-[15px] text-slate-700">
        {items} item{items === 1 ? '' : 's'} imported into {result.patient.toUpperCase()} from the
        national record, each marked with its source. One provenance record names the consent and you.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <a href={patientHref(result.patient)} className={PRIMARY}>
          Open the chart
        </a>
        <button type="button" onClick={onRestart} className="text-[14px] font-semibold text-slate-500 hover:text-slate-900">
          Onboard another patient
        </button>
        <span className="font-mono text-[12px] text-slate-400">{result.provenance}</span>
      </div>
    </Card>
  )
}
