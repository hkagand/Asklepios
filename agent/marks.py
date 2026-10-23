"""Marks a clinician leaves on the record: "I reviewed this result" and "I told the patient".

These are the only resources Asklepios writes. A review is a FHIR Task (completed, focus = the result or order, owner =
the practitioner); telling the patient is a FHIR Communication (sender = the practitioner, recipient = the patient,
about = the results). Both carry the Asklepios tag, so they can be told apart from anything else on the server, and a
mark made by mistake is withdrawn by setting its status to entered-in-error rather than deleting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from .record import TZ, Record, moment

TAG = {"system": "urn:demo:asklepios", "code": "asklepios", "display": "Written by Asklepios"}
REVIEW = {"system": "urn:demo:asklepios:task", "code": "review-result", "display": "Result reviewed"}
MODES = "http://terminology.hl7.org/CodeSystem/v3-ParticipationMode"
MEDIUMS = {
    "in_person": ("FACE", "face-to-face"),
    "phone": ("PHONE", "telephone"),
    "video": ("VIDEOCONF", "videoconferencing"),
    "letter": ("MAILWRIT", "mail"),
    "portal": ("ONLINEWRIT", "online written"),
}
# What a review or a communication can be about.
REVIEWABLE = ("Observation", "DiagnosticReport", "ServiceRequest", "DocumentReference")


@dataclass(frozen=True)
class Practitioner:
    id: str
    name: str

    @property
    def reference(self) -> dict:
        return {"reference": f"Practitioner/{self.id}", "display": self.name}


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta(record: Record) -> dict:
    """The Asklepios tag, plus the patient's security labels (HTEST for the synthetic cohort)."""
    meta: dict = {"tag": [TAG]}
    if security := record.patient.get("meta", {}).get("security"):
        meta["security"] = security
    return meta


def review_task(record: Record, focus: str, by: Practitioner, note: str | None) -> dict:
    stamp = now_text()
    task = {
        "resourceType": "Task",
        "meta": _meta(record),
        "status": "completed",
        "intent": "order",
        "code": {"coding": [REVIEW], "text": "Result reviewed"},
        "focus": {"reference": focus, "display": record.label(focus)},
        "for": {"reference": f"Patient/{record.id}"},
        "authoredOn": stamp,
        "lastModified": stamp,
        "executionPeriod": {"end": stamp},
        "requester": by.reference,
        "owner": by.reference,
    }
    if note:
        task["note"] = [{"text": note, "authorReference": by.reference, "time": stamp}]
    return task


def communication(record: Record, about: list[str], by: Practitioner, medium: str, sent: date | None, note: str | None) -> dict:
    code, display = MEDIUMS[medium]
    patient = {"reference": f"Patient/{record.id}"}
    message = {
        "resourceType": "Communication",
        "meta": _meta(record),
        "status": "completed",
        "subject": patient,
        "recipient": [patient],
        "sender": by.reference,
        "about": [{"reference": ref, "display": record.label(ref)} for ref in about],
        "sent": datetime.combine(sent, datetime.now(TZ).timetz()).isoformat(timespec="seconds") if sent else now_text(),
        "medium": [{"coding": [{"system": MODES, "code": code, "display": display}], "text": display}],
    }
    if note:
        message["payload"] = [{"contentString": note}]
    return message


def ours(resource: dict) -> bool:
    return any(tag.get("code") == TAG["code"] for tag in resource.get("meta", {}).get("tag", []))


def is_review(resource: dict) -> bool:
    return resource.get("resourceType") == "Task" and any(
        coding.get("code") == REVIEW["code"] for coding in resource.get("code", {}).get("coding", [])
    )


@dataclass
class Mark:
    """One review or communication, read back from the record."""

    id: str
    kind: str  # "review" | "communication"
    about: list[str]
    by: str
    by_name: str
    at: datetime
    medium: str | None
    note: str | None

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "about": self.about,
            "by": self.by,
            "byName": self.by_name,
            "at": self.at.isoformat(),
            "medium": self.medium,
            "note": self.note,
        }


def mark_of(resource: dict) -> Mark | None:
    """The mark a resource records, or None if it is not a standing Asklepios mark."""
    if not ours(resource) or resource.get("status") != "completed":
        return None
    ref = f"{resource['resourceType']}/{resource['id']}"
    if is_review(resource):
        person = resource.get("owner", {})
        about = [resource.get("focus", {}).get("reference", "")]
        when = moment(resource.get("executionPeriod", {}).get("end") or resource.get("lastModified"))
        note = next((item.get("text") for item in resource.get("note", [])), None)
        kind, medium = "review", None
    elif resource["resourceType"] == "Communication":
        person = resource.get("sender", {})
        about = [item.get("reference", "") for item in resource.get("about", [])]
        when = moment(resource.get("sent"))
        note = next((item.get("contentString") for item in resource.get("payload", [])), None)
        kind, medium = "communication", (resource.get("medium") or [{}])[0].get("text")
    else:
        return None
    return Mark(ref, kind, about, person.get("reference", ""), person.get("display", ""), when or datetime.now(TZ), medium, note)


def marks_of(record: Record) -> list[Mark]:
    """The patient's Asklepios marks that still stand (not withdrawn), oldest first."""
    found = [mark for resource in record.resources.values() if (mark := mark_of(resource))]
    return sorted(found, key=lambda mark: mark.at)
