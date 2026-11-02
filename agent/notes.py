"""Visit notes: drafted from the clinician's jottings, checked by code, then edited and signed by the clinician.

The model writes Subjective, Objective, Assessment and Plan from the jottings only. Every item it writes cites the
jottings (J1, J2, ...) and record items it comes from. Code then checks the draft:
  no source        an item cites nothing, or an id it was not given
  not in sources   a number in an item appears in none of the sources it cites
  unused           a jotting no item cites
Flagged items stay visible for the clinician; nothing is dropped silently. The clinician edits the text and signs.
Signing writes the note as a DocumentReference in the usual note format (its plan as "- " lines, so open loops can
track it), marks the Encounter finished, and adds a Provenance: the clinician is the author, Asklepios assembled it
from their jottings.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timezone

from .llm import LlmClient, LlmError
from .marks import TAG, Practitioner
from .record import Record, day_text, first, moment, patient_name
from .visits import Visit
from .visits import encounter as visit_encounter

SECTIONS = ("subjective", "objective", "assessment", "plan")
LOINC = "http://loinc.org"
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
DOCUMENT_CATEGORY = {
    "coding": [{"system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category", "code": "clinical-note", "display": "Clinical Note"}]
}

PROMPT = """\
You write a clinic visit note from the clinician's jottings. You get the jottings (each starts with its id, e.g. J3), \
the visit agenda with what was covered, and record items the jottings refer to (each starts with its id).

Return only JSON: {"subjective": [...], "objective": [...], "assessment": [...], "plan": [...]}, each a list of \
{"text": "...", "sources": ["J1", ...]}.
- Use only what the jottings state. Do not add symptoms, findings, impressions, results, doses or plans the jottings \
do not state. You may name a value of a record item a jotting refers to (e.g. the HbA1c it discusses), citing its id.
- Every item cites the ids it comes from: the jottings, and any record item whose value it gives.
- Every jotting appears in the note at least once.
- Subjective: what the patient reports. Objective: findings, measurements, results. Assessment: only impressions the \
clinician wrote. Plan: one action per item, as the clinician wrote it.
- Short clinical sentences in the third person ("Reports occasional loose stools on metformin."). [] for an empty \
section."""


def _sources(record: Record, visit: Visit) -> dict[str, str]:
    """What the draft may cite: the jottings, and the record items the jottings were linked to."""
    sources = {jotting.id: jotting.text for jotting in visit.jottings}
    for jotting in visit.jottings:
        for link in (jotting.review or {}).get("links", []):
            ref = link["ref"] if isinstance(link, dict) else link
            if ref in record.resources and ref not in sources:
                sources[ref] = record.describe(ref)[:400]
    return sources


def numbers_in(text: str) -> set[str]:
    """The numbers in a text, normalised (8,0 and 8.0 read as 8)."""
    return {number.replace(",", ".").rstrip("0").rstrip(".") if "." in number.replace(",", ".") else number for number in NUMBER.findall(text)}


def verify(sections: dict[str, list[dict]], sources: dict[str, str], jottings: list[str]) -> tuple[dict[str, list[dict]], list[str]]:
    """Each item with the issues found; and the jottings no item cites."""
    checked: dict[str, list[dict]] = {}
    cited: set[str] = set()
    for section in SECTIONS:
        checked[section] = []
        for item in sections.get(section, []):
            known = [source for source in item["sources"] if source in sources]
            issues = []
            if not known:
                issues.append("no source")
            if unknown := [source for source in item["sources"] if source not in sources]:
                issues.append(f"cites unknown {', '.join(unknown)}")
            grounding = " ".join(sources[source] for source in known)
            if missing := sorted(numbers_in(item["text"]) - numbers_in(grounding)):
                issues.append(f"{', '.join(missing)} not in its sources")
            cited |= set(known)
            checked[section].append({"text": item["text"], "sources": known, "issues": issues})
    return checked, [jotting for jotting in jottings if jotting not in cited]


def _parse(reply: str) -> dict[str, list[dict]]:
    found = re.search(r"\{.*\}", reply, re.DOTALL)
    data = json.loads(found.group()) if found else None
    if not isinstance(data, dict):
        raise ValueError("no JSON object")
    sections = {}
    for section in SECTIONS:
        items = data.get(section) or []
        sections[section] = [
            {"text": str(item.get("text", "")).strip(), "sources": [str(source) for source in item.get("sources") or []]}
            for item in items
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
    return sections


async def draft(llm: LlmClient, record: Record, visit: Visit) -> dict:
    """The drafted note, checked: {"sections": {...}, "unused": [...], "created": ...}."""
    sources = _sources(record, visit)
    jottings = "\n".join(f"{jotting.id}: {jotting.text}" for jotting in visit.jottings)
    agenda = "\n".join(f"{item.id} ({'covered' if item.done else 'not covered'}): {item.text}" for item in visit.agenda) or "(none)"
    linked = "\n".join(f"{ref}: {text}" for ref, text in sources.items() if not ref.startswith("J")) or "(none)"
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"JOTTINGS\n{jottings}\n\nAGENDA\n{agenda}\n\nRECORD ITEMS\n{linked}"},
    ]
    problem = ""
    for _ in range(2):
        message, _ = await llm.chat(messages, tools=[], tool_choice="none")
        try:
            sections = _parse(message.get("content") or "")
            break
        except (ValueError, json.JSONDecodeError) as error:
            problem = str(error)
    else:
        raise LlmError(f"The draft note was not usable ({problem}).")
    checked, unused = verify(sections, sources, [jotting.id for jotting in visit.jottings])
    return {"sections": checked, "unused": unused, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def section_text(section: str, items: list[dict]) -> str:
    """A section's text for editing: the plan as "- " lines, the rest as one paragraph."""
    if section == "plan":
        return "\n".join(f"- {item['text']}" for item in items)
    return " ".join(item["text"] for item in items)


# ------------------------------------------------------------------- signing

def note_text(record: Record, author: str, specialty: str, when: datetime, sections: dict[str, str]) -> str:
    """The note in the format the chart uses: a header, then upper-case section headings."""
    patient = record.patient
    born = date.fromisoformat(patient["birthDate"]) if patient.get("birthDate") else None
    age = ""
    if born:
        today = when.date()
        age = f"{today.year - born.year - ((today.month, today.day) < (born.month, born.day))} y, {patient.get('gender', '')}"
    mrn = next((item.get("value") for item in patient.get("identifier", []) if item.get("system", "").endswith(":mrn")), record.id.upper())
    title = f"{specialty} visit note" if specialty else "Clinic visit note"
    lines = [title.upper(), f"{patient_name(patient)} · MRN {mrn}" + (f" · {age}" if age else ""), f"{day_text(when)} · {author}" + (f", {specialty}" if specialty else ""), ""]
    for section in SECTIONS:
        body = sections.get(section, "").strip()
        if not body:
            continue
        if section == "plan":
            body = "\n".join(line if line.lstrip().startswith(("-", "•")) else f"- {line.strip()}" for line in body.splitlines() if line.strip())
        lines += [section.upper(), body, ""]
    return "\n".join(lines).strip() + "\n"


def sign_transaction(record: Record, visit: Visit, by: Practitioner, specialty: str, sections: dict[str, str], now: datetime | None = None) -> tuple[dict, str]:
    """The DocumentReference, the finished Encounter and a Provenance, as one FHIR transaction; and the note's ref."""
    stamp = now or datetime.now(timezone.utc)
    when = stamp.isoformat(timespec="seconds")
    text = note_text(record, by.name, specialty, stamp.astimezone(moment(visit.started).tzinfo) if moment(visit.started) else stamp, sections)
    title = text.splitlines()[0].capitalize()
    meta: dict = {"tag": [TAG]}
    if security := record.patient.get("meta", {}).get("security"):
        meta["security"] = security
    note_id = f"note-{visit.id}"
    document = {
        "resourceType": "DocumentReference",
        "id": note_id,
        "meta": meta,
        "status": "current",
        "docStatus": "final",
        "type": {"coding": [{"system": LOINC, "code": "11506-3", "display": "Progress note"}], "text": "Progress note"},
        "category": [DOCUMENT_CATEGORY],
        "subject": {"reference": f"Patient/{record.id}"},
        "date": when,
        "author": [by.reference],
        "authenticator": by.reference,
        "description": title,
        "content": [{"attachment": {
            "contentType": "text/plain; charset=utf-8", "language": "en", "title": title, "creation": when,
            "data": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        }}],
        "context": {"encounter": [{"reference": f"Encounter/{visit.id}"}], "period": {"start": visit.started, "end": when}},
    }
    visit.status = "signed"
    encounter = visit_encounter(record, visit, by)
    encounter["period"]["end"] = when
    provenance = {
        "resourceType": "Provenance",
        "id": f"prov-{visit.id}",
        "meta": meta,
        "target": [{"reference": f"DocumentReference/{note_id}"}],
        "recorded": when,
        "activity": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation", "code": "CREATE"}]},
        "agent": [
            {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "author"}]}, "who": by.reference},
            {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "assembler"}]},
             "who": {"display": "Asklepios: drafted from the clinician's jottings, edited and signed by the clinician"}},
        ],
        "entity": [{"role": "source", "what": {"display": f"Visit jottings ({len(visit.jottings)}) of {day_text(stamp.date())}"}}],
    }
    entries = [document, encounter, provenance]
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"fullUrl": f"{item['resourceType']}/{item['id']}", "resource": item, "request": {"method": "PUT", "url": f"{item['resourceType']}/{item['id']}"}} for item in entries],
    }
    return bundle, f"DocumentReference/{note_id}"


def specialty_of(practitioner: dict) -> str:
    return (first(practitioner.get("qualification")).get("code") or {}).get("text", "")
