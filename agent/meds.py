"""Medication reconciliation: the order list against what the notes say, with a timeline per drug.

The record holds medication orders (MedicationRequest) and notes. It has no dispensing or administration records, so
nothing here says what the patient actually takes; that is known only where a note states it, and the panel says so.

The model reads each clinician's latest note for the medications it mentions and how (MedicationReader). Everything
else is plain code: grouping orders by drug, and the findings:

  dose_differs     a note on or after the current order gives another dose than the order
  stopped_in_note  a note says the drug was stopped or is not taken, but the order is still active
  not_ordered      a note says the patient takes a drug that no order lists (bought over the counter, from elsewhere)
  plan             from open loops: a planned change written at another dose, or a planned stop not recorded
  not_mentioned    an active order no note of the last year mentions (shown for information, not a discrepancy)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .llm import LlmError
from .loops import DRUG_WORDS, Loop, doses, first_dosage, latest_notes, ordered_doses, says
from .plans import NoteReader, plain
from .record import Document, Record, day_text, ref_of, text_of
from .tools import fold

STATUSES = ("taking", "started", "changed", "stopped", "held", "planned", "intolerance", "mentioned")
DISCREPANCIES = ("dose_differs", "stopped_in_note", "not_ordered", "plan")
UNCERTAINTY = (
    "This list shows medication orders. The record has no dispensing or administration data, so whether the patient "
    "takes a medicine is known only where a note says so."
)
# A note mentioning a dose counts against the current order only if written on or after the order started, give or
# take this much.
ORDER_SLACK = timedelta(days=2)
RECENT = timedelta(days=365)

PROMPT = """\
You list the medicines one clinical note mentions, as the note states them. Medicines only: not lab values (such as \
"Mg 1.5 mg/dL"), not procedures.

Return only JSON: {"medications": [...], "adherence": [...]}.
Each medication:
- "quote": the words of the note that mention it, copied exactly (part of one line; leave out list markers).
- "drug": the name as written, e.g. "ramipril", "sacubitril/valsartan", "FOLFOX".
- "dose": the dose as written, e.g. "10 mg", "75 micrograms", "65 mg/m²"; null if none is given.
- "status": "taking" (the patient is on it: "on ramipril 10 mg", "continue", "tolerating"), "started" (started at \
this visit), "changed" (dose changed at this visit), "stopped" (stopped by anyone, or the patient is not taking it), \
"held", "planned" (to start or change later), "intolerance" (an allergy or side effect that rules it out), or \
"mentioned" (anything else, such as past history).
- "by_patient": true when the note says the patient themself stopped, skipped, or added it (for example bought over \
the counter); otherwise false.
Each adherence statement about how the patient takes medicines in general: {"quote": "...", "summary": "<a few words>"}.
List a medicine once per way it is mentioned. Do not add medicines the note does not mention."""


@dataclass(frozen=True)
class Mention:
    quote: str
    drug: str
    dose: str | None
    status: str
    by_patient: bool


@dataclass(frozen=True)
class NoteMedicines:
    medications: tuple[Mention, ...]
    adherence: tuple[tuple[str, str], ...]  # (quote, summary)


class MedicationReader(NoteReader[NoteMedicines]):
    prompt = PROMPT
    version = 1
    what = "medicines"

    def parse(self, reply: str, note_text: str) -> NoteMedicines:
        found = re.search(r"\{.*\}", reply, re.DOTALL)
        if not found:
            raise ValueError("no JSON object in the reply")
        data = json.loads(found.group())
        if not isinstance(data, dict) or not isinstance(data.get("medications"), list):
            raise ValueError("the reply has no medications list")
        note = plain(note_text)

        def quoted(raw: dict) -> str | None:
            quote = str(raw.get("quote") or "").strip().lstrip("-•* ").strip()
            return quote if quote and plain(quote) in note else None

        mentions = []
        for raw in data["medications"]:
            if not isinstance(raw, dict) or not (quote := quoted(raw)) or not str(raw.get("drug") or "").strip():
                continue
            status = raw.get("status") if raw.get("status") in STATUSES else "mentioned"
            dose = str(raw.get("dose")).strip() if raw.get("dose") else None
            mentions.append(Mention(quote, str(raw["drug"]).strip(), dose, status, bool(raw.get("by_patient"))))
        adherence = [
            (quote, str(raw.get("summary") or "").strip())
            for raw in data.get("adherence") or []
            if isinstance(raw, dict) and (quote := quoted(raw))
        ]
        return NoteMedicines(tuple(mentions), tuple(adherence))

    def dump(self, result: NoteMedicines) -> object:
        return {"medications": [asdict(item) for item in result.medications], "adherence": [list(item) for item in result.adherence]}

    def load(self, data: object) -> NoteMedicines:
        return NoteMedicines(
            tuple(Mention(**item) for item in data["medications"]), tuple(tuple(item) for item in data["adherence"])
        )


# ----------------------------------------------------------------- reconciling

def drug_words(name: str) -> set[str]:
    """The words that can name a drug in an order: its own long words, plus regimen and common names."""
    words = {word for word in re.findall(r"[a-z]+", fold(name)) if len(word) >= 4}
    return words | {synonym for word in words for synonym in DRUG_WORDS.get(word, ())}


def order_text(medication: dict) -> str:
    concept = medication.get("medicationCodeableConcept", {})
    return " ".join([text_of(concept), *(coding.get("display", "") for coding in concept.get("coding", []))])


@dataclass
class Drug:
    name: str
    orders: list[dict]  # oldest first
    notes: list[dict] = field(default_factory=list)  # what the latest notes say
    mentioned_in: list[dict] = field(default_factory=list)  # every note naming it, for the timeline
    findings: list[dict] = field(default_factory=list)

    @property
    def current(self) -> dict:
        return self.orders[-1]


def group_orders(record: Record) -> list[Drug]:
    """Medication orders by drug (the ATC display, or the first word of the name), the newest order last."""
    groups: dict[str, list[dict]] = {}
    for medication in record.medications:
        concept = medication.get("medicationCodeableConcept", {})
        key = ((concept.get("coding") or [{}])[0].get("display") or text_of(concept).split(" ")[0]).lower()
        groups.setdefault(key, []).append(medication)
    drugs = []
    for orders in groups.values():
        orders.sort(key=lambda medication: record.medication_period(medication)[0] or date.min)
        name = re.split(r"\s+(?=[\d(])", text_of(orders[-1].get("medicationCodeableConcept")))[0]
        drugs.append(Drug(name, orders))
    return drugs


def matching(drugs: list[Drug], name: str) -> Drug | None:
    words = drug_words(name)
    return next((drug for drug in drugs if any(says(order_text(order), word) for order in drug.orders for word in words)), None)


def order_json(record: Record, medication: dict) -> dict:
    start, end = record.medication_period(medication)
    return {
        "ref": ref_of(medication),
        "name": text_of(medication.get("medicationCodeableConcept")),
        "dose": first_dosage(medication),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "status": medication.get("status"),
        "statusReason": text_of(medication.get("statusReason")) or None,
        "reason": text_of((medication.get("reasonCode") or [{}])[0]) or None,
        "prescriber": medication.get("requester", {}).get("display"),
    }


async def reconcile(record: Record, reader: MedicationReader, loops: list[Loop]) -> dict:
    """The medication picture of one patient: drugs with their orders, what notes say, and findings."""
    drugs = group_orders(record)
    notes = latest_notes(record)
    read = await asyncio.gather(*(reader.read(note) for note in notes), return_exceptions=True)
    unlisted: list[dict] = []
    adherence: list[dict] = []
    unread: list[str] = []

    for note, result in zip(notes, read):
        if isinstance(result, LlmError):
            unread.append(note.ref)
            continue
        if isinstance(result, BaseException):
            raise result
        written = note.when.date()
        place = {"note": note.ref, "date": written.isoformat(), "author": note.author}
        adherence += [{"quote": quote, "summary": summary, **place} for quote, summary in result.adherence]
        for mention in result.medications:
            said = {"quote": mention.quote, "dose": mention.dose, "status": mention.status, "byPatient": mention.by_patient, **place}
            drug = matching(drugs, mention.drug)
            if drug is None:
                if mention.status in ("taking", "started", "changed"):
                    origin = "added by the patient" if mention.by_patient else "no order on file"
                    unlisted.append({
                        "drug": mention.drug, **said,
                        "finding": {"kind": "not_ordered", "text": f"Taken according to the note ({origin}); no order lists it", "refs": [note.ref]},
                    })
                continue
            drug.notes.append(said)
            current = drug.current
            start = record.medication_period(current)[0] or date.min
            if written + ORDER_SLACK < start:
                continue  # the order changed after this note
            if mention.status == "stopped" and current.get("status") == "active":
                who = "the patient stopped it" if mention.by_patient else "it was stopped"
                drug.findings.append({
                    "kind": "stopped_in_note",
                    "text": f"The note of {day_text(written)} says {who}; the order is still active",
                    "refs": [note.ref, ref_of(current)],
                })
            noted, ordered = doses(mention.dose or ""), ordered_doses(current)
            if (
                mention.status in ("taking", "started", "changed")
                and noted and ordered and noted[0] not in ordered
                and current.get("status") in ("active", "on-hold")
            ):
                drug.findings.append({
                    "kind": "dose_differs",
                    "text": f"The note of {day_text(written)} gives {mention.dose}; the order gives {first_dosage(current) or ', '.join(ordered)}",
                    "refs": [note.ref, ref_of(current)],
                })

    # Open loops already compare planned changes with the orders written; their findings win over the note's.
    for loop in loops:
        if loop.item.kind != "medication" or loop.status not in ("missing", "dose_mismatch"):
            continue
        refs = [ref for ref in loop.evidence if ref.startswith("MedicationRequest/")]
        drug = next((drug for drug in drugs if any(ref_of(order) in refs for order in drug.orders)), None)
        if drug is None:
            continue
        drug.findings = [finding for finding in drug.findings if finding["kind"] != "dose_differs"]
        drug.findings.append({"kind": "plan", "text": f"Plan of {day_text(loop.note.when.date()) if loop.note else ''}: {loop.detail}", "refs": [*([loop.note.ref] if loop.note else []), *refs]})

    since = record.today - RECENT
    texts = [(document, fold(document.text)) for document in record.documents if document.kind == "note"]
    for drug in drugs:
        words = drug_words(drug.name) | {word for order in drug.orders for word in drug_words(order_text(order))}
        drug.mentioned_in = [
            {"note": document.ref, "date": document.when.date().isoformat(), "title": document.title}
            for document, text in texts
            if any(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) for word in words)
        ]
        recent = [item for item in drug.mentioned_in if date.fromisoformat(item["date"]) >= since]
        if drug.current.get("status") == "active" and not recent:
            last = drug.mentioned_in[-1]["date"] if drug.mentioned_in else None
            drug.findings.append({
                "kind": "not_mentioned",
                "text": "No note of the last 12 months mentions it" + (f" (last {day_text(date.fromisoformat(last))})" if last else ""),
                "refs": [ref_of(drug.current)],
            })

    rank = {"active": 0, "on-hold": 1}
    drugs.sort(key=lambda drug: (rank.get(drug.current.get("status"), 2), drug.name.lower()))
    return {
        "patient": record.id,
        "today": record.today.isoformat(),
        "uncertainty": UNCERTAINTY,
        "drugs": [
            {
                "name": drug.name,
                "status": drug.current.get("status"),
                "dose": first_dosage(drug.current),
                "orders": [order_json(record, order) for order in drug.orders],
                "notes": drug.notes,
                "mentionedIn": drug.mentioned_in,
                "findings": drug.findings,
            }
            for drug in drugs
        ],
        "unlisted": unlisted,
        "adherence": adherence,
        "unread": unread,
    }


def index_section(picture: dict) -> str:
    """The MEDICATION RECONCILIATION section of the chart index: only the findings, each with its sources."""
    lines = [
        f"{drug['name']}: {finding['text']} [{', '.join(finding['refs'])}]"
        for drug in picture["drugs"]
        for finding in drug["findings"]
        if finding["kind"] in DISCREPANCIES
    ]
    lines += [f"{item['drug']}: {item['finding']['text']} [{', '.join(item['finding']['refs'])}]" for item in picture["unlisted"]]
    lines += [f'Adherence, {day_text(date.fromisoformat(item["date"]))}: "{item["quote"]}" [{item["note"]}]' for item in picture["adherence"]]
    head = f"MEDICATION RECONCILIATION: orders against what the notes say. {picture['uncertainty']}"
    return head + "\n" + "\n".join(f"- {line}" for line in lines or ["no discrepancies found"])
