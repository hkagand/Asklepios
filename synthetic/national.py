"""Synthetic national health records: what a national record service (simulated) holds for a few patients.

Each record is an International Patient Summary (IPS): a document Bundle whose Composition lists allergies,
medications, problems, procedures and results gathered from every integrated facility, ours included. None of it is
loaded into HAPI. The mock service in national/ serves it once the patient consents, and onboarding imports what a
clinician accepts. National ids start with 0, which no real Turkish identity number does.

Each record holds something worth catching at onboarding:
  p-3001 (new)       a penicillin allergy, a statin not prescribed for two years that still reads as active, and a
                     childhood asthma diagnosis still listed as active
  p-3002 (new)       ramipril 5 mg, which the patient may report differently
  p-2042 (in chart)  a caesarean section recorded at another hospital, which our chart has only in notes, next to
                     operations our chart already has
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from catalog import Clinician
from chart import NATIONAL_ID, ORGANIZATION_NAME, SYNTHETIC_META, PatientChart, at, instant, workday
from cohort import AMLODIPINE, APPENDICECTOMY, ATORVASTATIN, METFORMIN, RAMIPRIL

LOINC = "http://loinc.org"
SERVICE = "National record service (simulated)"
BASE_URL = "https://national-record.demo/fhir"
STATE = "Demo State Hospital"
UNIVERSITY = "Demo University Hospital"

# Section codes and titles from the IPS implementation guide; the resource type each section lists.
SECTIONS = (
    ("AllergyIntolerance", "48765-2", "Allergies and adverse reactions"),
    ("MedicationRequest", "10160-0", "Medication summary"),
    ("Condition", "11450-4", "Problem list"),
    ("Procedure", "47519-4", "History of procedures"),
    ("Observation", "30954-2", "Results"),
)

# Clinicians at other facilities: they appear by name only, with no Practitioner resource.
ARI = Clinician("ext-ari", "Sibel", "Arı", "Internal Medicine")
TUNA = Clinician("ext-tuna", "Kemal", "Tuna", "Family Medicine")
ER = Clinician("ext-er", "Okan", "Er", "General Surgery")
SEN = Clinician("ext-sen", "Leyla", "Şen", "Obstetrics and Gynaecology")
ACAR = Clinician("ext-acar", "Deniz", "Acar", "Orthopaedics")


class Person:
    def __init__(self, chart: PatientChart, national_id: str, phone: str) -> None:
        self.chart = chart
        self.national_id = national_id
        self.phone = phone


def _at(resource: dict, facility: str) -> None:
    """Where something was done or prescribed, by name: the national record names facilities, not our resources."""
    kind = resource["resourceType"]
    if kind == "Procedure":
        resource["location"] = {"display": facility}
    elif kind == "Observation":
        resource["performer"] = [{"display": f"{facility} laboratory"}]
    else:
        resource.setdefault("note", []).append({"text": f"Recorded at {facility}"})


def gulay_kaplan(anchor: date) -> Person:
    c = PatientChart(
        number=3001, given="Gülay", family="Kaplan", gender="female", birth_date=date(anchor.year - 58, 3, 14),
        city="Eskişehir", gp=ARI,
    )

    def ago(days: int) -> date:
        return workday(anchor - timedelta(days=days), forward=False)

    for condition in (
        c.condition("I10", "Essential (primary) hypertension", onset=ago(round(8 * 365.25)), clinician=ARI),
        c.condition("E11.9", "Type 2 diabetes mellitus without complications", onset=ago(round(5 * 365.25)), clinician=ARI),
        # Diagnosed in childhood and never closed: no inhaler or visit for it in decades.
        c.condition("J45.9", "Asthma, unspecified", onset=date(c.birth_date.year + 11, 5, 2)),
    ):
        _at(condition, STATE)
    c.allergy("Penicillin", "Urticaria and lip swelling", recorded=date(2004, 11, 8), criticality="high", severity="moderate")
    _at(c.resources[-1], STATE)
    for medication in (
        c.start_med("Amlodipine 5 mg tablet", "5 mg orally once daily", start=ago(60), prescriber=ARI, atc=AMLODIPINE, reason="Essential hypertension"),
        c.start_med("Metformin 1000 mg tablet", "1000 mg orally twice daily with meals", start=ago(35), prescriber=ARI, atc=METFORMIN, reason="Type 2 diabetes mellitus"),
        # Last prescribed more than two years ago; the record still shows it as active.
        c.start_med("Atorvastatin 20 mg tablet", "20 mg orally once daily at night", start=ago(760), prescriber=ARI, atc=ATORVASTATIN, reason="Dyslipidaemia"),
    ):
        _at(medication, STATE)
    surgery = c.procedure(
        "Laparoscopic cholecystectomy", performed=date(2016, 4, 12), body_site="Gallbladder",
        snomed=("45595009", "Laparoscopic cholecystectomy"), performer=ER, outcome="Uncomplicated",
    )
    _at(surgery, UNIVERSITY)
    for days, a1c in ((540, 7.9), (360, 7.4), (40, 7.1)):
        c.result("a1c", {"a1c": a1c}, collected=at(ago(days), 8, 40), requester=ARI)
    c.result("bmp", {"cr": 0.82, "k": 4.4, "na": 139}, collected=at(ago(40), 8, 40), requester=ARI)
    c.result("lipid", {"chol": 212, "ldl": 128, "hdl": 52, "tg": 160}, collected=at(ago(40), 8, 40), requester=ARI)
    for resource in c.resources:
        if resource["resourceType"] == "Observation":
            _at(resource, STATE)
    return Person(c, "00000003001", "+90 500 000 30 01")


def murat_ozdemir(anchor: date) -> Person:
    c = PatientChart(
        number=3002, given="Murat", family="Özdemir", gender="male", birth_date=date(anchor.year - 44, 7, 2),
        city="Bursa", gp=TUNA,
    )

    def ago(days: int) -> date:
        return workday(anchor - timedelta(days=days), forward=False)

    _at(c.condition("I10", "Essential (primary) hypertension", onset=ago(730), clinician=TUNA), STATE)
    c.no_known_allergies(ago(730))
    _at(
        c.start_med("Ramipril 5 mg tablet", "5 mg orally once daily", start=ago(180), prescriber=TUNA, atc=RAMIPRIL, reason="Essential hypertension"),
        STATE,
    )
    knee = c.procedure(
        "Right knee arthroscopy with partial meniscectomy", performed=date(2019, 9, 23), body_site="Right knee",
        performer=ACAR, outcome="Uncomplicated",
    )
    _at(knee, UNIVERSITY)
    c.result("bmp", {"cr": 0.95, "k": 4.6, "na": 140}, collected=at(ago(170), 9, 5), requester=TUNA)
    c.result("bmp", {"cr": 1.02, "k": 4.9, "na": 139}, collected=at(ago(20), 9, 5), requester=TUNA)
    for resource in c.resources:
        if resource["resourceType"] == "Observation":
            _at(resource, STATE)
    return Person(c, "00000003002", "+90 500 000 30 02")


def nermin_aktas(anchor: date) -> Person:
    """Already in our chart as p-2042: the national record repeats what was done here and adds what was not."""
    c = PatientChart(
        number=2042, given="Nermin", family="Aktaş", gender="female", birth_date=date(anchor.year - 52, 9, 3),
        city="Ankara", gp=ARI,
    )
    c.no_known_allergies(date(2015, 6, 10))
    appendix = c.procedure(
        "Open appendicectomy", performed="1996", body_site="Appendix", snomed=APPENDICECTOMY,
        note="Reported by the patient",
    )
    appendix["asserter"] = c.ref
    caesarean = c.procedure(
        "Lower segment caesarean section", performed=date(2008, 5, 19), body_site="Uterus", performer=SEN,
        outcome="Live birth, uncomplicated",
    )
    _at(caesarean, STATE)
    hernia = c.procedure(
        "Open umbilical hernia repair with mesh", performed=workday(date(2015, 6, 10), forward=True), body_site="Umbilicus",
        outcome="Uncomplicated", device="Polypropylene mesh 6 × 6 cm, onlay",
    )
    _at(hernia, ORGANIZATION_NAME)
    c.result("cbc", {"hgb": 12.9, "hct": 39.1, "mcv": 86, "wbc": 6.8, "plt": 241}, collected=at(date(2024, 3, 11), 9, 0), requester=SEN)
    for resource in c.resources:
        if resource["resourceType"] == "Observation":
            _at(resource, STATE)
    return Person(c, "00000002042", "+90 500 000 20 42")


PEOPLE = (gulay_kaplan, murat_ozdemir, nermin_aktas)


# ------------------------------------------------------------------- the IPS document

def _rewrite(value: object, ids: dict[str, str]) -> object:
    """References to resources in the document point to their new ids; references to anything else keep only their
    display, since the national record names other facilities and clinicians but does not hold them."""
    if isinstance(value, list):
        return [item for item in (_rewrite(item, ids) for item in value) if item is not None]
    if not isinstance(value, dict):
        return value
    if "reference" in value and isinstance(value["reference"], str):
        if value["reference"] in ids:
            return {**value, "reference": ids[value["reference"]]}
        return {"display": value["display"]} if value.get("display") else None
    return {key: rewritten for key, item in value.items() if (rewritten := _rewrite(item, ids)) is not None}


def summary(person: Person, anchor: date) -> dict:
    """The person's International Patient Summary as a FHIR document Bundle."""
    chart = person.chart
    kept = [resource for resource in chart.resources if resource["resourceType"] in {"Patient", *(kind for kind, _, _ in SECTIONS)}]
    ids = {f"{resource['resourceType']}/{resource['id']}": f"{resource['resourceType']}/nr-{resource['id']}" for resource in kept}
    resources = [_rewrite(resource, ids) | {"id": f"nr-{resource['id']}"} for resource in kept]
    patient = resources[0]
    patient["identifier"] = [{"system": NATIONAL_ID, "value": person.national_id}]
    patient["telecom"] = [{"system": "phone", "value": person.phone, "use": "mobile"}]
    for field in ("generalPractitioner", "managingOrganization"):
        patient.pop(field, None)
    for resource in resources[1:]:
        # Our builder ties results to orders and reports; the summary keeps the results alone.
        resource.pop("basedOn", None)
        resource.pop("encounter", None)

    timestamp = instant(at(anchor, 7, 0))
    sections = []
    for kind, code, title in SECTIONS:
        entries = [{"reference": f"{item['resourceType']}/{item['id']}"} for item in resources if item["resourceType"] == kind]
        section: dict = {"title": title, "code": {"coding": [{"system": LOINC, "code": code}]}}
        if entries:
            section["entry"] = entries
        else:
            section["emptyReason"] = {"text": "No information recorded"}
        sections.append(section)
    composition = {
        "resourceType": "Composition",
        "id": f"nr-ips-{person.national_id}",
        "meta": SYNTHETIC_META,
        "status": "final",
        "type": {"coding": [{"system": LOINC, "code": "60591-5", "display": "Patient summary Document"}]},
        "subject": {"reference": f"Patient/{patient['id']}", "display": chart.name},
        "date": timestamp,
        "author": [{"display": SERVICE}],
        "title": f"Patient summary: {chart.name}",
        "section": sections,
    }
    entries = [composition, patient, *resources[1:]]
    digest = hashlib.sha256(f"{person.national_id}:{anchor.isoformat()}".encode()).hexdigest()[:12]
    return {
        "resourceType": "Bundle",
        "id": f"ips-{person.national_id}-{digest}",
        "meta": SYNTHETIC_META,
        "identifier": {"system": "urn:demo:asklepios:national-record", "value": person.national_id},
        "type": "document",
        "timestamp": timestamp,
        "entry": [{"fullUrl": f"{BASE_URL}/{item['resourceType']}/{item['id']}", "resource": item} for item in entries],
    }


def national_records(anchor: date) -> list[dict]:
    return [summary(make(anchor), anchor) for make in PEOPLE]
