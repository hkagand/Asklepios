"""The conversation loop: the model calls read-only tools until it can answer, then the answer is verified."""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field

from . import epicrisis, tools
from .audit import AuditLog
from .citations import Evidence, verify
from .fhir import FhirClient
from .llm import LlmClient, LlmError
from .loops import index_section as loops_section
from .loops import open_loops
from .meds import MedicationReader, reconcile
from .meds import index_section as medication_section
from .plans import PlanExtractor
from .record import Record, patient_name, today_text
from .surgery import SurgeryReader, surgical_history
from .surgery import index_section as surgery_section

SYSTEM_PROMPT = """\
You are ASKlepios. You answer a physician's questions about one patient's medical record at Demo General \
Hospital. The physician has this patient's chart open, usually just before or during a visit.

Sources
- Use only this patient's record: the chart index below and what your tools return. Never fill gaps with general \
medical knowledge, typical disease courses or assumptions, and never guess what a missing or pending result might show.
- The index has one line per problem, medication, open order, visit, note and report, plus the latest lab values. \
For notes it has only the title and for reports only the conclusion. Before you describe or compare what notes or \
reports say beyond that, read all of them with read_documents (up to 4 per call). Never say what a document does or \
does not contain unless you have read it.
- Tools: read_documents for full notes and reports, lab_series for trends with computed changes, medication_history \
for drug changes and their reasons, order_history for what was ordered and whether it was done, search_record to \
find where something is mentioned, read_epicrisis for the full epicrisis reports of earlier hospital admissions.
- OPEN LOOPS lists what each clinician's latest note planned and whether the record shows it was done. Report those \
statuses as given. "No record to confirm it" means the record cannot show it either way, not that it was missed.
- MEDICATION RECONCILIATION lists where the notes and the medication orders disagree. For any question about a \
medicine or its dose, including its current dose, first look for that medicine in MEDICATION RECONCILIATION, then give \
the order and also every reconciliation line about that medicine. Orders show what was \
prescribed, not what the patient takes: what the patient takes is known only from what a note says, as of its date.
- SURGICAL HISTORY lists earlier operations merged from procedure records, notes and reports. For any question about \
previous operations, answer from it and cite its ids. Give the approach, body region, implants and complications as \
listed, and say when an operation is only in notes, was done elsewhere, or its sources give different years. If it \
lists none, say what was searched and that operations done elsewhere may not be recorded; never say the patient has \
never had surgery.
- If asked whether the patient is fit or suitable for an operation, or which surgical approach to use: say that this \
is the surgeon's decision, then list every operation in SURGICAL HISTORY with its date, approach, body region, \
implants and complications, citing each. Do not assess fitness from results or vital signs, and do not say whether \
anything rules the operation in or out.
- EPICRISIS REPORTS lists the reports written at the end of each hospital admission: the discharge summary and, when \
there was one, the operation or procedure report. Its lines are only summaries: the hospital course, findings, \
biopsies, anaesthesia, the details and outcome of complications and the discharge advice are only in the full reports. \
So for any question about the patient's past (earlier admissions, operations, procedures, findings, complications, \
anaesthesia, "has he ever ...", "anything I should know about ..."), first call read_epicrisis, even when the summary \
lines, notes or problem list seem to answer it; read_documents and search_record do not replace it. Which operations \
the patient has had is answered from SURGICAL HISTORY. Skip the call only \
when the section already gives the reports in full. Use every report that bears on the question, including the \
biopsies and other procedures that led to an operation, and cite each one you use. For each, give its date, what was \
done and found, and any complication with its treatment and outcome, including medicines stopped or started. If none does, say how many reports you read, the period they cover, and that \
none of them mentions it. If the section says none are on file, say that no epicrisis reports are on file. Do not \
read them for questions about current results, medicines or orders.
- Lines that start "From the national record (simulated)" were imported from records kept elsewhere, before the \
patient's first visit here: whenever you use one, say it comes from the national record, with the facility and date \
the line gives.
- If the record does not answer the question, say so plainly, e.g. "No echocardiogram is on file."
- For an open order write "no result on file". Do not say that the test was or was not drawn, performed or \
scheduled unless the record says so.

Citations
- End every bullet and every factual sentence with the ids that support it in square brackets, e.g. \
[Observation/obs-123] or [DiagnosticReport/dr-4, DocumentReference/doc-9]. Copy every id exactly as written, never \
shortened and never as a range. Cite only ids that appear in the index or in tool results. Leave out any statement \
you cannot cite.
- Copy numbers, units and dates exactly as given. Do not calculate differences, sums or percentages yourself: quote \
the values, or use the changes reported by the index and lab_series.

Style
- Lead with the direct answer, then short "-" bullets. No tables. Write dates like "15 Oct 2026".
- Do not recommend treatments, doses, tests or diagnoses, and do not predict what will happen. You may point out what \
is abnormal, changed, pending, overdue or documented as planned.
- If asked whether to do something (start, restart, stop, increase, order), do not answer yes or no: say that the \
decision is the physician's, then report what the record documents that bears on it.
- For a pre-visit briefing, read the most recent visit note first, then give at most 10 bullets under these bold \
labels: Reason for visit, Background, Since last visit, Pending or overdue.
- Reply in the language of the physician's question, even though the record may be in another language. Keep drug \
and test names as the record writes them.

Today is {today}.

CHART INDEX
{index}
"""

# Left to itself the model often answers in the record's language, or the one used earlier in the conversation, so
# each question carries a reminder naming the language when it can be told.
TURKISH_LETTERS = set("çğıöşüÇĞİÖŞÜ")
TURKISH_WORDS = set(
    "ne neden niye nedir nasıl hangi kaç mi mı mu mü ve ile bir bu son en var yok için hasta hastanın zaman zamandı "
    "oldu değişti kesildi sonuç sonuçları özet özetle önceki sonra önce kadar göre neler durumu tedavi ilaç rapor "
    "raporu raporları tahlil bana anlat".split()
)
ENGLISH_WORDS = set(
    "the a an what why how when which who is are was were did does do has have had and or of to in on for with since "
    "last me my his her their this that there changed between brief summarise summarize show list any pending "
    "overdue visit today result results she he him it its be can could should would will let lets please tell give "
    "about from at by after before raise increase decrease lower reduce start stop restart dose taking take".split()
)


def language_of(question: str, names: Iterable[str] = ()) -> str | None:
    """"Turkish" or "English" when the question is clearly in one of them. Turkish letters count only in words that
    are not names: a capitalised word, or a word of `names` (the patient's), says nothing about the language, so "Raise
    Hülya Güneş's ramipril dose" stays English. What follows an apostrophe is a suffix ("Güneş'in", "mg'a", "let's"),
    not a word."""
    skip = {word.lower() for name in names for word in re.findall(r"[^\W\d_]+", name)}
    tokens = re.findall(r"(?<!['’])\b[^\W\d_]+", question)
    raw = [word for word in tokens if word.lower() not in skip]
    words = [word.lower() for word in raw]
    letters = any(letter in TURKISH_LETTERS for word in raw if not word[0].isupper() for letter in word)
    turkish = sum(word in TURKISH_WORDS for word in words) + 2 * letters
    english = sum(word in ENGLISH_WORDS for word in words)
    if turkish != english:
        return "Turkish" if turkish > english else "English"
    return None


def reminder(question: str, names: Iterable[str] = ()) -> str:
    language = language_of(question, names)
    reply = f"Answer in {language}" if language else "Reply in the language of the question above"
    return f"\n\n({reply}. Copy cited ids exactly.)"


@dataclass
class Session:
    id: str
    record: Record
    evidence: Evidence
    messages: list[dict]
    specs: list[dict]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    used: float = field(default_factory=time.monotonic)

    @property
    def patient_id(self) -> str:
        return self.record.id


async def sections(record: Record, plans: PlanExtractor, medicines: MedicationReader, surgery: SurgeryReader) -> str:
    """The index sections computed from the notes: open loops, medication reconciliation, surgical history."""
    loops, unread = await open_loops(record, plans)
    picture = await reconcile(record, medicines, loops)
    history = await surgical_history(record, surgery)
    return f"{loops_section(loops, unread)}\n\n{medication_section(picture)}\n\n{surgery_section(history)}"


def start_session(session_id: str, record: Record, extra: str | None = None, *, epicrisis_in_prompt: bool = False) -> Session:
    """The chart index gets the EPICRISIS REPORTS section, then `extra`: the sections computed from the notes
    (sections()). With `epicrisis_in_prompt` that section gives the reports in full and read_epicrisis is not offered."""
    reports = epicrisis.index_section(record, full=epicrisis_in_prompt)
    index = record.index() + f"\n\n{reports}" + (f"\n\n{extra}" if extra else "")
    evidence = Evidence()
    for line in index.splitlines():
        evidence.add(line)
    if epicrisis_in_prompt:
        # A report's facts are on its own lines, not on the line with its id: add each report whole.
        for block in epicrisis.read_all(record)[1:]:
            evidence.add(block)
    prompt = SYSTEM_PROMPT.format(today=today_text(record.today), index=index)
    specs = [spec for spec in tools.SPECS if not (epicrisis_in_prompt and spec["function"]["name"] == "read_epicrisis")]
    return Session(session_id, record, evidence, [{"role": "system", "content": prompt}], specs)


class Sessions:
    """Conversations in memory. A session is tied to one patient and reads the chart once, when it starts."""

    def __init__(
        self,
        fhir: FhirClient,
        plans: PlanExtractor,
        medicines: MedicationReader,
        surgery: SurgeryReader,
        *,
        idle_seconds: float = 2 * 3600,
        limit: int = 200,
    ) -> None:
        self._fhir = fhir
        self._plans = plans
        self._medicines = medicines
        self._surgery = surgery
        self._idle_seconds = idle_seconds
        self._limit = limit
        self._items: dict[str, Session] = {}

    async def get(self, session_id: str, patient_id: str) -> Session:
        session = self._items.get(session_id)
        if session is None or session.patient_id != patient_id:
            patient, found = await self._fhir.patient_chart(patient_id)
            record = Record(patient, found)
            session = self._items[session_id] = start_session(session_id, record, await sections(record, self._plans, self._medicines, self._surgery))
            self._prune()
        session.used = time.monotonic()
        return session

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._idle_seconds
        for key, session in list(self._items.items()):
            if session.used < cutoff:
                del self._items[key]
        for key in sorted(self._items, key=lambda key: self._items[key].used)[: max(0, len(self._items) - self._limit)]:
            del self._items[key]


def pre_reads(session: Session, question: str) -> bool:
    """Whether the epicrisis reports are read in code before the model's first step: the question is about the
    patient's past, the patient has reports, and the session offers read_epicrisis (not when they are in the prompt).
    Left to itself, the model often answers such questions from the index lines without reading the reports."""
    offered = any(spec["function"]["name"] == "read_epicrisis" for spec in session.specs)
    return offered and epicrisis.about_the_past(question) and bool(epicrisis.reports(session.record))


async def run_turn(
    session: Session, question: str, *, llm: LlmClient, audit: AuditLog, max_steps: int, user: str | None = None
) -> AsyncIterator[tuple[str, dict]]:
    """Yields ("step", ...) for each tool call, then ("answer", ...). Raises LlmError if no answer comes back."""
    started = time.monotonic()

    def log(event: str, **fields: object) -> None:
        audit.write(session=session.id, patient=session.patient_id, event=event, user=user, **fields)

    def run_call(call: dict, **extra: object) -> dict:
        """Runs one tool call already in the conversation, adds its result and evidence, and logs it."""
        name, arguments = call["function"]["name"], call["function"]["arguments"]
        result = tools.run(session.record, name, arguments)
        for block in result.blocks:
            session.evidence.add(block)
        session.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result.text})
        step = {"tool": name, "label": result.label}
        steps.append(step)
        log("tool", name=name, arguments=arguments, label=result.label, characters=len(result.text), **extra)
        return step

    log("question", text=question)
    # A turn that does not finish is taken back out, so the next question starts from a clean history.
    checkpoint = len(session.messages)
    answered = False
    session.messages.append({"role": "user", "content": question + reminder(question, [patient_name(session.record.patient)])})
    steps: list[dict] = []
    usage: Counter[str] = Counter()
    try:
        if pre_reads(session, question):
            # Read as if the model had called the tool; "by" tells the audit it was code.
            call = {"id": f"pre-read-{checkpoint}", "type": "function", "function": {"name": "read_epicrisis", "arguments": "{}"}}
            session.messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            yield "step", run_call(call, by="code")
        for step in range(max_steps):
            last = step == max_steps - 1
            try:
                message, used = await llm.chat(session.messages, tools=session.specs, tool_choice="none" if last else "auto")
            except LlmError as error:
                log("error", message=str(error))
                raise
            usage.update({key: value for key, value in used.items() if isinstance(value, int)})
            calls = message.get("tool_calls") or []
            if calls and not last:
                calls = [
                    {
                        "id": call.get("id") or f"call-{step}-{number}",
                        "type": "function",
                        "function": {
                            "name": call.get("function", {}).get("name", ""),
                            "arguments": call.get("function", {}).get("arguments") or "{}",
                        },
                    }
                    for number, call in enumerate(calls)
                ]
                session.messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
                for call in calls:
                    yield "step", run_call(call)
                continue
            text = (message.get("content") or "").strip()
            if not text:
                continue
            session.messages.append({"role": "assistant", "content": text})
            record = session.record
            answer = verify(
                text,
                evidence=session.evidence,
                resolve=record.resolve,
                label=record.label,
                context=f"{question} {today_text(record.today)}",
            )
            answer |= {"steps": steps, "elapsedMs": round((time.monotonic() - started) * 1000), "model": llm.model}
            log(
                "answer",
                text=text,
                statuses=dict(Counter(block["status"] for block in answer["blocks"])),
                sources=sorted(answer["sources"]),
                elapsed_ms=answer["elapsedMs"],
                usage=dict(usage),
            )
            answered = True
            yield "answer", answer
            return
        log("error", message=f"no answer after {max_steps} model calls")
        raise LlmError(f"The assistant did not reach an answer within {max_steps} steps. Try a narrower question.")
    finally:
        if not answered:
            del session.messages[checkpoint:]
