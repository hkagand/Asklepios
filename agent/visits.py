"""Visits: a workspace for one visit, from the agenda the record suggests to the note the clinician signs.

Starting a visit opens a FHIR Encounter (in progress) for the acting clinician. The agenda is built from the record by
plain code: the reason for the appointment, open loops to close, medicines to confirm, allergies to confirm. During the
visit the clinician writes short jottings. The working state (agenda ticks, jottings) is kept on the agent, one JSON
file per visit, until the note is signed; only the Encounter is written to FHIR before then.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .loops import OPEN, Loop
from .marks import TAG, Practitioner
from .meds import DISCREPANCIES
from .record import Record, moment, ref_of, text_of

NO_KNOWN_ALLERGY = "716186003"
ORGANIZATION = {"reference": "Organization/org-demo-hospital", "display": "Demo General Hospital"}
PRIMARY_PERFORMER = {
    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "code": "PPRF", "display": "primary performer"}]
}
# How each open loop reads on the agenda.
LOOP_AGENDA = {
    "missing": "Planned, not done",
    "dose_mismatch": "Ordered at another dose",
    "overdue": "Overdue",
    "to_review": "Result to review",
    "not_ordered": "Planned, not ordered",
    "no_trace": "Check whether it happened",
    "to_inform": "Tell the patient the result",
}


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AgendaItem:
    id: str
    kind: str  # reason, loop, medication, allergy
    text: str
    detail: str
    refs: list[str]
    done: bool = False
    done_by: str | None = None  # a jotting id, or "clinician" when ticked by hand


@dataclass
class Jotting:
    id: str
    time: str
    text: str
    by: str
    # Live help (jottings.py): section, covers, links, gaps, alerts, status ("pending", "done" or "failed").
    review: dict | None = None


@dataclass
class Visit:
    id: str  # the Encounter id
    patient: str
    practitioner: str
    practitioner_name: str
    started: str
    status: str = "open"  # open, signed, cancelled
    appointment: str | None = None
    reason: str | None = None
    agenda: list[AgendaItem] = field(default_factory=list)
    jottings: list[Jotting] = field(default_factory=list)
    version: int = 0  # raised on every save, so the panel can ignore an older answer that arrives late
    draft: dict | None = None  # the drafted note, checked (notes.py)
    note: str | None = None  # the signed note, "DocumentReference/..."

    def jot(self, text: str, by: str) -> Jotting:
        number = max((int(item.id[1:]) for item in self.jottings), default=0) + 1
        jotting = Jotting(f"J{number}", now_text(), text, by, {"status": "pending"})
        self.jottings.append(jotting)
        return jotting

    def apply_review(self, jotting_id: str, text: str, review: dict) -> None:
        """Keeps a review if the jotting still reads as it did when reviewed, and ticks the agenda items it covers."""
        jotting = next((item for item in self.jottings if item.id == jotting_id), None)
        if jotting is None or jotting.text != text:
            return
        jotting.review = review
        for item in self.agenda:
            if item.id in review.get("covers", []) and not item.done:
                item.done, item.done_by = True, jotting_id

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "encounter": f"Encounter/{self.id}",
            "patient": self.patient,
            "practitioner": self.practitioner,
            "practitionerName": self.practitioner_name,
            "started": self.started,
            "status": self.status,
            "appointment": self.appointment,
            "reason": self.reason,
            "agenda": [{**asdict(item), "doneBy": item.done_by} for item in self.agenda],
            "jottings": [asdict(item) for item in self.jottings],
            "version": self.version,
            "draft": self.draft,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: dict) -> Visit:
        return cls(
            id=data["id"], patient=data["patient"], practitioner=data["practitioner"],
            practitioner_name=data["practitionerName"], started=data["started"], status=data["status"],
            appointment=data.get("appointment"), reason=data.get("reason"),
            agenda=[AgendaItem(item["id"], item["kind"], item["text"], item["detail"], item["refs"], item["done"], item.get("doneBy"))
                    for item in data["agenda"]],
            jottings=[Jotting(**item) for item in data["jottings"]],
            version=data.get("version", 0),
            draft=data.get("draft"),
            note=data.get("note"),
        )


class VisitStore:
    """Visits on disk, one JSON file each; written after every change."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, visit_id: str) -> asyncio.Lock:
        """Held while a visit is read, changed and saved, so two quick jottings cannot overwrite each other."""
        return self._locks.setdefault(visit_id, asyncio.Lock())

    def _path(self, visit_id: str) -> Path:
        return self.folder / f"{visit_id}.json"

    def save(self, visit: Visit) -> None:
        visit.version += 1
        self._path(visit.id).write_text(json.dumps(visit.as_json(), ensure_ascii=False, indent=1), encoding="utf-8")

    def get(self, visit_id: str) -> Visit | None:
        path = self._path(visit_id)
        return Visit.from_json(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def open_for(self, patient_id: str) -> Visit | None:
        """The patient's visit in progress, if any (the newest)."""
        found = []
        for path in self.folder.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["patient"] == patient_id and data["status"] == "open":
                found.append(Visit.from_json(data))
        return max(found, key=lambda visit: visit.started, default=None)


# ------------------------------------------------------------------- agenda

def todays_appointment(record: Record) -> dict | None:
    """The patient's booked appointment today, if any."""
    return next(
        (appointment for appointment in record.upcoming() if (moment(appointment.get("start")) or datetime.min).date() == record.today),
        None,
    )


def agenda(record: Record, loops: list[Loop], picture: dict, appointment: dict | None) -> list[AgendaItem]:
    """What the record suggests covering at this visit, in order: why the patient came, what is still open, which
    medicines to confirm, and allergies. Plain code; nothing here is the model's suggestion."""
    items: list[tuple[str, str, str, list[str]]] = []
    if appointment and appointment.get("description"):
        items.append(("reason", f"Reason for visit: {appointment['description']}", "", [ref_of(appointment)]))
    for loop in loops:
        if loop.status in OPEN:
            refs = [*([loop.note.ref] if loop.note else []), *loop.evidence]
            items.append(("loop", f"{LOOP_AGENDA[loop.status]}: {loop.line}", loop.detail, list(dict.fromkeys(refs))))
    for drug in picture.get("drugs", []):
        for finding in drug["findings"]:
            # Planned changes not carried out are already open loops.
            if finding["kind"] in DISCREPANCIES and finding["kind"] != "plan":
                items.append(("medication", f"Confirm {drug['name']}", finding["text"], finding["refs"]))
    for item in picture.get("unlisted", []):
        items.append(("medication", f"Confirm {item['drug']}", item["finding"]["text"], item["finding"]["refs"]))
    for item in picture.get("reported", []):
        items.append(("medication", f"Confirm {item['drug']}", item["text"], item["refs"]))
    known = [allergy for allergy in record.allergies if (allergy.get("code", {}).get("coding") or [{}])[0].get("code") != NO_KNOWN_ALLERGY]
    if known:
        names = ", ".join(text_of(allergy.get("code")) for allergy in known)
        items.append(("allergy", f"Confirm allergies: {names}", "", [ref_of(allergy) for allergy in known]))
    elif record.allergies:
        items.append(("allergy", "Confirm there are still no known allergies", "", [ref_of(allergy) for allergy in record.allergies]))
    else:
        items.append(("allergy", "Ask about allergies: none recorded", "", []))
    return [AgendaItem(f"A{number}", kind, text, detail, refs) for number, (kind, text, detail, refs) in enumerate(items, 1)]


# ------------------------------------------------------------------- FHIR

def new_visit_id() -> str:
    return f"visit-{secrets.token_hex(6)}"


def encounter(record: Record, visit: Visit, by: Practitioner) -> dict:
    """The visit as a FHIR Encounter: in progress while the visit is open, finished or cancelled after."""
    meta: dict = {"tag": [TAG]}
    if security := record.patient.get("meta", {}).get("security"):
        meta["security"] = security
    resource = {
        "resourceType": "Encounter",
        "id": visit.id,
        "meta": meta,
        "status": {"open": "in-progress", "signed": "finished", "cancelled": "cancelled"}[visit.status],
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
        "type": [{"text": "Clinic visit"}],
        "subject": {"reference": f"Patient/{record.id}"},
        "participant": [{"type": [PRIMARY_PERFORMER], "individual": by.reference}],
        "period": {"start": visit.started},
        "serviceProvider": ORGANIZATION,
    }
    if visit.appointment:
        resource["appointment"] = [{"reference": visit.appointment}]
    if visit.reason:
        resource["reasonCode"] = [{"text": visit.reason}]
    return resource
