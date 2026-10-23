"""The conversation loop: the model calls read-only tools until it can answer, then the answer is verified."""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from . import tools
from .audit import AuditLog
from .citations import Evidence, verify
from .fhir import FhirClient
from .llm import LlmClient, LlmError
from .record import Record, today_text

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
find where something is mentioned.
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
    "overdue visit today result results".split()
)


def language_of(question: str) -> str | None:
    """"Turkish" or "English" when the question is clearly in one of them."""
    words = re.findall(r"[^\W\d_]+", question.lower())
    turkish = sum(word in TURKISH_WORDS for word in words) + 2 * any(letter in TURKISH_LETTERS for letter in question)
    english = sum(word in ENGLISH_WORDS for word in words)
    if turkish != english:
        return "Turkish" if turkish > english else "English"
    return None


def reminder(question: str) -> str:
    language = language_of(question)
    reply = f"Answer in {language}" if language else "Reply in the language of the question above"
    return f"\n\n({reply}. Copy cited ids exactly.)"


@dataclass
class Session:
    id: str
    record: Record
    evidence: Evidence
    messages: list[dict]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    used: float = field(default_factory=time.monotonic)

    @property
    def patient_id(self) -> str:
        return self.record.id


def start_session(session_id: str, record: Record) -> Session:
    index = record.index()
    evidence = Evidence()
    for line in index.splitlines():
        evidence.add(line)
    prompt = SYSTEM_PROMPT.format(today=today_text(record.today), index=index)
    return Session(session_id, record, evidence, [{"role": "system", "content": prompt}])


class Sessions:
    """Conversations in memory. A session is tied to one patient and reads the chart once, when it starts."""

    def __init__(self, fhir: FhirClient, *, idle_seconds: float = 2 * 3600, limit: int = 200) -> None:
        self._fhir = fhir
        self._idle_seconds = idle_seconds
        self._limit = limit
        self._items: dict[str, Session] = {}

    async def get(self, session_id: str, patient_id: str) -> Session:
        session = self._items.get(session_id)
        if session is None or session.patient_id != patient_id:
            patient, found = await self._fhir.patient_chart(patient_id)
            session = self._items[session_id] = start_session(session_id, Record(patient, found))
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


async def run_turn(
    session: Session, question: str, *, llm: LlmClient, audit: AuditLog, max_steps: int
) -> AsyncIterator[tuple[str, dict]]:
    """Yields ("step", ...) for each tool call, then ("answer", ...). Raises LlmError if no answer comes back."""
    started = time.monotonic()

    def log(event: str, **fields: object) -> None:
        audit.write(session=session.id, patient=session.patient_id, event=event, **fields)

    log("question", text=question)
    # A turn that does not finish is taken back out, so the next question starts from a clean history.
    checkpoint = len(session.messages)
    answered = False
    session.messages.append({"role": "user", "content": question + reminder(question)})
    steps: list[dict] = []
    usage: Counter[str] = Counter()
    try:
        for step in range(max_steps):
            last = step == max_steps - 1
            try:
                message, used = await llm.chat(session.messages, tools=tools.SPECS, tool_choice="none" if last else "auto")
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
                    name, arguments = call["function"]["name"], call["function"]["arguments"]
                    result = tools.run(session.record, name, arguments)
                    for block in result.blocks:
                        session.evidence.add(block)
                    session.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result.text})
                    steps.append({"tool": name, "label": result.label})
                    log("tool", name=name, arguments=arguments, label=result.label, characters=len(result.text))
                    yield "step", {"tool": name, "label": result.label}
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
