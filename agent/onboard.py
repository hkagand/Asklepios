"""Patient onboarding from the national record service (simulated): consent, review, then import.

1. The clinician enters the patient's national id, name and birth date; the service texts the patient a code.
2. With the code, the agent reads the patient's International Patient Summary (IPS) and lists every item for review,
   checked against our chart when the patient is already in it:
     new        not in our chart
     duplicate  already in our chart (not imported again)
     differs    in our chart, but not the same (another dose; "no known allergies" against recorded allergies)
     ask        to confirm with the patient first: every medicine (a prescription is not proof it is taken), and
                a diagnosis recorded long ago that is still listed as active
3. Only what the clinician accepts is written to the chart, in one transaction, with a Provenance naming the source,
   the consent and the clinician. Medicines are written as MedicationStatements, what the patient says they take,
   never as orders. Nothing in the chart is changed or overwritten.

All matching is plain code. The service token stays on the server.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from .loops import doses, ordered_doses
from .marks import Practitioner
from .meds import drug_words
from .record import Record, code_of, day_text, moment, ref_of, text_of
from .surgery import family_of
from .tools import fold

NATIONAL_ID = "urn:demo:asklepios:national-id"
MRN_SYSTEM = "urn:demo:asklepios:mrn"
SERVICE = "National record (simulated)"
SOURCE_URL = "https://national-record.demo/fhir"
IMPORT_TAG = {"system": "urn:demo:asklepios", "code": "national-import", "display": "Imported from the national record (simulated)"}
ORGANIZATION = {"reference": "Organization/org-demo-hospital", "display": "Demo General Hospital"}
SECTIONS = {
    "AllergyIntolerance": "allergies",
    "MedicationRequest": "medications",
    "Condition": "problems",
    "Procedure": "procedures",
    "Observation": "results",
}
NO_KNOWN_ALLERGY = "716186003"
# A diagnosis recorded this long ago and still listed as active is confirmed with the patient before import.
STALE_DIAGNOSIS = timedelta(days=10 * 365)
# A prescription not renewed for this long may no longer be taken.
STALE_PRESCRIPTION = timedelta(days=365)
STATUSES = ("new", "duplicate", "differs", "ask")


class NationalError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class NationalClient:
    """The simulated national record service (national/app.py)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, path: str, **options: object) -> dict:
        try:
            response = await self._client.request(method, f"{self.base_url}{path}", **options)
        except httpx.HTTPError as error:
            raise NationalError(502, f"The national record service is not reachable at {self.base_url}. Start it with: python -m national") from error
        if response.is_error:
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise NationalError(response.status_code, str(detail))
        return response.json()

    async def request_consent(self, national_id: str, name: str, birth_date: str, requester: str) -> dict:
        body = {"nationalId": national_id, "name": name, "birthDate": birth_date, "requester": requester}
        return await self._send("POST", "/consent-requests", json=body)

    async def confirm(self, request_id: str, code: str) -> dict:
        return await self._send("POST", f"/consent-requests/{request_id}/confirm", json={"code": code})

    async def reset(self) -> dict:
        """Forgets every consent request, token, message and log entry (the demo reset)."""
        return await self._send("POST", "/demo/reset")

    async def summary(self, national_id: str, token: str) -> dict:
        return await self._send(
            "GET", "/fhir/Patient/$summary", params={"identifier": f"{NATIONAL_ID}|{national_id}"},
            headers={"Authorization": f"Bearer {token}"},
        )


# ------------------------------------------------------------------- review

@dataclass
class Item:
    key: str  # the resource in the national summary, e.g. "AllergyIntolerance/nr-alg-p-3001-001"
    section: str
    label: str
    detail: str
    when: str | None
    status: str
    reason: str
    chart: list[str] = field(default_factory=list)  # what in our chart it matches
    critical: bool = False
    stale: bool = False

    def as_json(self) -> dict:
        return {
            "key": self.key, "section": self.section, "label": self.label, "detail": self.detail, "when": self.when,
            "status": self.status, "reason": self.reason, "chart": self.chart, "critical": self.critical, "stale": self.stale,
        }


def resources_of(bundle: dict) -> list[dict]:
    return [entry["resource"] for entry in bundle.get("entry", [])]


def patient_of(bundle: dict) -> dict:
    return next(resource for resource in resources_of(bundle) if resource["resourceType"] == "Patient")


def national_id_of(patient: dict) -> str | None:
    return next((item["value"] for item in patient.get("identifier", []) if item.get("system") == NATIONAL_ID), None)


def facility_of(resource: dict) -> str | None:
    """Where the national record says it was done, prescribed or measured."""
    if location := resource.get("location", {}).get("display"):
        return location
    for performer in resource.get("performer", []):
        if display := performer.get("display"):
            return display.removesuffix(" laboratory")
    for note in resource.get("note", []):
        if found := re.match(r"Recorded at (.+)", note.get("text", "")):
            return found[1]
    return None


def _day(value: str | None) -> date | None:
    when = moment(value) if value else None
    return when.date() if when else None


def _at(facility: str | None) -> str:
    return f" at {facility}" if facility else ""


def allergy_item(resource: dict, record: Record | None) -> Item:
    name = text_of(resource.get("code")) or "Allergy"
    none_known = code_of(resource.get("code")) == NO_KNOWN_ALLERGY or "no known" in fold(name)
    reactions = [text_of(item) for reaction in resource.get("reaction", []) for item in reaction.get("manifestation", [])]
    recorded = _day(resource.get("recordedDate"))
    detail = "; ".join(filter(None, [
        ", ".join(reactions),
        f"criticality {resource['criticality']}" if resource.get("criticality") else "",
        f"recorded {day_text(recorded)}{_at(facility_of(resource))}" if recorded else "",
    ]))
    item = Item(ref_of(resource), "allergies", name, detail, recorded.isoformat() if recorded else None, "new",
                "Not in our chart.", critical=resource.get("criticality") == "high")
    if record is None:
        if item.critical:
            item.reason = "Not in our chart. High criticality: check with the patient."
        return item
    chart_none = [ref_of(allergy) for allergy in record.allergies if code_of(allergy.get("code")) == NO_KNOWN_ALLERGY]
    chart_known = [allergy for allergy in record.allergies if code_of(allergy.get("code")) != NO_KNOWN_ALLERGY]
    if none_known:
        if chart_known:
            names = ", ".join(text_of(allergy.get("code")) for allergy in chart_known)
            item.status, item.reason, item.chart = "differs", f"Our chart lists {names}.", [ref_of(allergy) for allergy in chart_known]
        elif chart_none:
            item.status, item.reason, item.chart = "duplicate", "Our chart also records no known allergies.", chart_none
        return item
    same = [ref_of(allergy) for allergy in chart_known if fold(text_of(allergy.get("code"))) == fold(name)]
    if same:
        item.status, item.reason, item.chart = "duplicate", "Already in our chart.", same
    elif chart_none:
        item.status, item.reason, item.chart = "differs", "Our chart records no known allergies.", chart_none
    return item


def condition_item(resource: dict, record: Record | None, today: date) -> Item:
    coding = (resource.get("code", {}).get("coding") or [{}])[0]
    onset = _day(resource.get("onsetDateTime") or resource.get("recordedDate"))
    detail = "; ".join(filter(None, [
        f"ICD-10 {coding['code']}" if coding.get("code") else "",
        f"since {day_text(onset)}" if onset else "",
        (facility_of(resource) and f"recorded at {facility_of(resource)}") or "",
    ]))
    item = Item(ref_of(resource), "problems", text_of(resource.get("code")) or "Problem", detail,
                onset.isoformat() if onset else None, "new", "Not in our chart.")
    if record is not None:
        same = [ref_of(condition) for condition in record.conditions if code_of(condition.get("code")) == coding.get("code")]
        if same:
            item.status, item.reason, item.chart = "duplicate", "Already in our chart.", same
            return item
    active = code_of(resource.get("clinicalStatus")) in (None, "active")
    if active and onset and today - onset > STALE_DIAGNOSIS:
        item.status, item.stale = "ask", True
        item.reason = f"Recorded in {onset.year} and still listed as active: confirm it is current."
    return item


def medication_item(resource: dict, record: Record | None, today: date) -> Item:
    name = text_of(resource.get("medicationCodeableConcept")) or "Medication"
    dosage = ((resource.get("dosageInstruction") or [{}])[0].get("text") or "").strip()
    prescribed = _day(resource.get("authoredOn"))
    detail = "; ".join(filter(None, [dosage, f"last prescribed {day_text(prescribed)}{_at(facility_of(resource))}" if prescribed else ""]))
    item = Item(ref_of(resource), "medications", name, detail, prescribed.isoformat() if prescribed else None, "ask",
                "A prescription does not show the patient takes it: ask.")
    if prescribed and today - prescribed > STALE_PRESCRIPTION:
        item.stale = True
        item.reason = f"Not prescribed since {day_text(prescribed)}, though still listed as active: ask whether it is taken."
    if record is None:
        return item
    words = drug_words(name)
    current = [
        medication for medication in record.medications
        if medication.get("status") == "active" and words & drug_words(text_of(medication.get("medicationCodeableConcept")))
    ]
    if current:
        ours = ordered_doses(current[0])
        theirs = doses(dosage) or doses(name)
        item.chart = [ref_of(medication) for medication in current]
        if ours == theirs:
            item.status, item.reason = "duplicate", "Our chart has an active order at the same dose."
        else:
            item.status = "differs"
            item.reason = f"Our chart has an active order at {', '.join(ours) or 'another dose'}; the national record says {', '.join(theirs) or dosage}."
    return item


def procedure_item(resource: dict, record: Record | None, history: dict | None) -> Item:
    name = text_of(resource.get("code")) or "Procedure"
    performed = _day(resource.get("performedDateTime"))
    year = performed.year if performed else int(resource["performedString"][:4]) if (resource.get("performedString") or "")[:4].isdigit() else None
    when = day_text(performed) if performed else resource.get("performedString") or "date not recorded"
    reported = resource.get("asserter", {}).get("reference", "").startswith("Patient/")
    detail = "; ".join(filter(None, [
        when,
        ", ".join(text_of(site) for site in resource.get("bodySite", [])),
        f"done at {facility_of(resource)}" if facility_of(resource) else "",
        "reported by the patient" if reported else "",
        "implant: " + ", ".join(device.get("manipulated", {}).get("display", "") for device in resource.get("focalDevice", [])) if resource.get("focalDevice") else "",
    ]))
    item = Item(ref_of(resource), "procedures", name, detail, performed.isoformat() if performed else str(year) if year else None,
                "new", "Not in our chart.")
    if record is None or history is None:
        return item
    family = family_of(name)
    for operation in history["operations"]:
        if family_of(operation["name"]) != family or (year and operation["year"] and abs(operation["year"] - year) > 1):
            continue
        item.chart = [source["ref"] for source in operation["sources"]]
        if operation["onlyInNotes"]:
            item.reason = f"Our chart mentions it only in notes; this adds a dated record{_at(facility_of(resource))}."
        else:
            item.status, item.reason = "duplicate", f"Already in our chart ({operation['name']}, {operation['when']})."
        break
    return item


def result_item(resource: dict, record: Record | None) -> Item:
    loinc = code_of(resource.get("code"))
    quantity = resource.get("valueQuantity", {})
    measured = _day(resource.get("effectiveDateTime"))
    value = quantity.get("value")
    reading = f"{value:g} {quantity.get('unit', '')}".strip() if isinstance(value, (int, float)) else ""
    detail = "; ".join(filter(None, [reading, f"{day_text(measured)}{_at(facility_of(resource))}" if measured else ""]))
    item = Item(ref_of(resource), "results", text_of(resource.get("code")) or "Result", detail,
                measured.isoformat() if measured else None, "new", "Not in our chart.")
    if record is not None and measured and isinstance(value, (int, float)):
        for series in record.series:
            if series.code != loinc:
                continue
            same = [point.ref for point in series.points if point.when.date() == measured and abs(point.value - value) < 1e-9]
            if same:
                item.status, item.reason, item.chart = "duplicate", "The same result is in our chart.", same
    return item


def review_items(bundle: dict, record: Record | None, history: dict | None, today: date) -> list[Item]:
    """Every item of the national summary, checked against our chart (record and surgical history) if the patient
    is in it."""
    items = []
    for resource in resources_of(bundle):
        kind = resource["resourceType"]
        if kind == "AllergyIntolerance":
            items.append(allergy_item(resource, record))
        elif kind == "Condition":
            items.append(condition_item(resource, record, today))
        elif kind == "MedicationRequest":
            items.append(medication_item(resource, record, today))
        elif kind == "Procedure":
            items.append(procedure_item(resource, record, history))
        elif kind == "Observation":
            items.append(result_item(resource, record))
    return items


# ------------------------------------------------------------------- import

@dataclass(frozen=True)
class Decision:
    key: str
    import_it: bool
    taking: str | None = None  # medicines: "yes", "no" or "different"
    dose: str | None = None  # medicines taken at another dose, as the patient says it
    current: bool | None = None  # problems: False imports the diagnosis as resolved; required when it is to be asked


class ImportRefused(Exception):
    pass


def new_patient_id(national_id: str) -> str:
    """Our id for a patient onboarded from the national record: "p-" and the last four digits, as the cohort's."""
    return f"p-{int(national_id[-4:])}"


def _repoint(value: object, old: str, new: dict) -> object:
    """Every reference to the national Patient points to ours instead."""
    if isinstance(value, list):
        return [_repoint(item, old, new) for item in value]
    if isinstance(value, dict):
        if value.get("reference") == old:
            return {**new}
        return {key: _repoint(item, old, new) for key, item in value.items()}
    return value


def _meta(source: dict) -> dict:
    meta: dict = {"tag": [IMPORT_TAG], "source": SOURCE_URL}
    if security := source.get("meta", {}).get("security"):
        meta["security"] = security
    return meta


def statement(resource: dict, decision: Decision, patient: dict, asserted: str, item: Item) -> dict:
    """What the patient says about a medicine on the national record, as a MedicationStatement."""
    dosage = ((resource.get("dosageInstruction") or [{}])[0].get("text") or "").strip()
    status = {"yes": "active", "different": "active", "no": "stopped"}[decision.taking or ""]
    said = {
        "yes": "Patient confirms taking it as listed.",
        "different": f"Patient reports taking {decision.dose}." if decision.dose else "Patient reports taking a different dose.",
        "no": "Patient reports no longer taking it.",
    }[decision.taking or ""]
    result = {
        "resourceType": "MedicationStatement",
        "id": resource["id"].replace("nr-med-", "nr-ms-", 1),
        "meta": _meta(resource),
        "status": status,
        "medicationCodeableConcept": resource.get("medicationCodeableConcept"),
        "subject": patient,
        "dateAsserted": asserted,
        "informationSource": patient,
        "dosage": [{"text": decision.dose if decision.taking == "different" and decision.dose else dosage}],
        "note": [{"text": f"National record: {item.label}, {item.detail}."}, {"text": said}],
    }
    if resource.get("reasonCode"):
        result["reasonCode"] = resource["reasonCode"]
    return result


def import_transaction(
    bundle: dict,
    items: list[Item],
    decisions: list[Decision],
    *,
    patient_id: str,
    existing: bool,
    practitioner: Practitioner,
    consent: str,
    onboarding: str,
    now: datetime | None = None,
) -> dict:
    """A FHIR transaction writing what the clinician accepted, the Patient if new, and one Provenance for all of it.
    Ids come from the national record, so importing the same item again updates it rather than duplicating it."""
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    by_key = {item.key: item for item in items}
    resources = {ref_of(resource): resource for resource in resources_of(bundle)}
    national_patient = patient_of(bundle)
    ours = {"reference": f"Patient/{patient_id}", "display": (national_patient.get("name") or [{}])[0].get("text", "")}

    written: list[dict] = []
    for decision in decisions:
        item = by_key.get(decision.key)
        if item is None:
            raise ImportRefused(f"{decision.key} is not in this patient's national summary.")
        if not decision.import_it:
            continue
        if item.status == "duplicate":
            raise ImportRefused(f"{item.label} is already in the chart; it is not imported again.")
        source = _repoint(copy.deepcopy(resources[decision.key]), ref_of(national_patient), ours)
        if item.section == "medications":
            if decision.taking not in ("yes", "no", "different"):
                raise ImportRefused(f"Ask the patient about {item.label} before importing it.")
            written.append(statement(source, decision, ours, stamp, item))
            continue
        if item.section == "problems" and item.status == "ask" and decision.current is None:
            raise ImportRefused(f"Confirm with the patient whether {item.label} is current.")
        if item.section == "allergies" and item.status == "differs" and code_of(source.get("code")) == NO_KNOWN_ALLERGY:
            raise ImportRefused("The chart records allergies; \"no known allergies\" from the national record is not imported over them.")
        resource = source | {"meta": _meta(source)}
        if item.section == "problems" and decision.current is False:
            resource["clinicalStatus"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "resolved"}]}
            resource.setdefault("note", []).append({"text": "Imported as resolved: the patient says it is no longer current."})
        written.append(resource)

    entries = []
    if not existing:
        patient = {
            "resourceType": "Patient",
            "id": patient_id,
            "meta": _meta(national_patient),
            "identifier": [
                {"use": "usual", "system": MRN_SYSTEM, "value": patient_id.upper()},
                {"system": NATIONAL_ID, "value": national_id_of(national_patient)},
            ],
            "active": True,
            "name": national_patient.get("name"),
            "gender": national_patient.get("gender"),
            "birthDate": national_patient.get("birthDate"),
            "telecom": national_patient.get("telecom", []),
            "managingOrganization": ORGANIZATION,
        }
        entries.append(patient)
    entries += written
    if not entries:
        raise ImportRefused("Nothing was selected to import.")
    provenance = {
        "resourceType": "Provenance",
        "id": f"prov-onboard-{onboarding}",
        "meta": {"tag": [IMPORT_TAG], **({"security": national_patient["meta"]["security"]} if national_patient.get("meta", {}).get("security") else {})},
        "target": [{"reference": f"{resource['resourceType']}/{resource['id']}"} for resource in entries],
        "recorded": stamp,
        "policy": [f"urn:demo:asklepios:consent:{consent}"],
        "activity": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation", "code": "CREATE", "display": "create"}]},
        "agent": [
            {
                "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "verifier"}]},
                "who": practitioner.reference,
            },
            {
                "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "informant"}]},
                "who": {"display": SERVICE},
            },
        ],
        "entity": [{
            "role": "source",
            "what": {"identifier": {"system": "urn:demo:asklepios:national-record", "value": bundle.get("id", "")}, "display": f"{SERVICE}: patient summary of {bundle.get('timestamp', '')[:10]}"},
        }],
    }
    entries.append(provenance)
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"fullUrl": f"{resource['resourceType']}/{resource['id']}", "resource": resource,
             "request": {"method": "PUT", "url": f"{resource['resourceType']}/{resource['id']}"}}
            for resource in entries
        ],
    }
