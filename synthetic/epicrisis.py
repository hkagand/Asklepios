"""Epicrisis reports: the hospital discharge report, written as text by plain code.

An Admission describes one stay (and, optionally, the procedure done during it). `add` writes it into a chart as a
DocumentReference whose text attachment is laid out in headed blocks, the same way the notes are; an operation also gets a
Procedure record. Everything added carries the `epicrisis` tag so the rest of the chart can be shown to be unchanged.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from chart import SYNTHETIC_META, LOINC, PatientChart, _b64, at, day_text, instant

TAG = {"system": "urn:demo:asklepios", "code": "epicrisis"}
REPORT_TYPE = ("18842-5", "Epicrisis report")

# Story and variant of the charts closed to new operations: their notes state their surgical history.
CLOSED = {
    ("diabetes_hypertension", 4), ("hypothyroidism", 0), ("diabetes_hypertension", 2), ("chronic_kidney_disease", 1),
    ("colorectal_cancer", 0), ("gallstone_disease", 0),
}

# Every ICD-10 code the background catalogue (epicrisis_catalogue.py) writes: the acute, resolved diagnoses of its
# episodes, their complications and working diagnoses, and the conditions an operation cured (a deviated septum, the
# osteoarthritis of a replaced knee). A background report gives no other code unless the chart's problem list has it.
CODES = {
    "A02.0": "Salmonella enteritis",
    "A04.7": "Enterocolitis due to Clostridioides difficile",
    "A08.1": "Acute gastroenteropathy due to norovirus",
    "A09.9": "Gastroenteritis and colitis of unspecified origin",
    "B35.3": "Tinea pedis",
    "B96.2": "Escherichia coli as the cause of disease",
    "B98.0": "Helicobacter pylori as the cause of disease",
    "E86": "Volume depletion (dehydration)",
    "E87.1": "Hyponatraemia",
    "E87.6": "Hypokalaemia",
    "F05.9": "Delirium, unspecified",
    "G56.0": "Carpal tunnel syndrome",
    "H81.2": "Vestibular neuronitis",
    "I80.8": "Phlebitis of other sites",
    "J12.8": "Other viral pneumonia",
    "J18.1": "Lobar pneumonia, unspecified organism",
    "J18.9": "Pneumonia, unspecified organism",
    "J22": "Unspecified acute lower respiratory infection",
    "J34.2": "Deviated nasal septum",
    "K26.0": "Acute duodenal ulcer with haemorrhage",
    "K35.8": "Acute appendicitis, other and unspecified",
    "K40.9": "Unilateral inguinal hernia, without obstruction or gangrene",
    "K56.0": "Paralytic ileus",
    "K59.0": "Constipation",
    "K63.5": "Polyp of colon",
    "K80.5": "Calculus of bile duct without cholangitis or cholecystitis",
    "K92.1": "Melaena",
    "L03.1": "Cellulitis of other parts of limb",
    "M17.1": "Other primary gonarthrosis",
    "N10": "Acute pyelonephritis",
    "N17.9": "Acute kidney failure, unspecified",
    "N20.1": "Calculus of ureter",
    "N23": "Unspecified renal colic",
    "N39.0": "Urinary tract infection, site not specified",
    "O72.1": "Other immediate postpartum haemorrhage",
    "O80": "Single spontaneous delivery",
    "R07.4": "Chest pain, unspecified",
    "R10.3": "Pain localised to other parts of lower abdomen",
    "R19.5": "Other faecal abnormalities",
    "R33": "Retention of urine",
    "R42": "Dizziness and giddiness",
    "R55": "Syncope and collapse",
    "R73.9": "Hyperglycaemia, unspecified",
    "S00.0": "Superficial injury of scalp",
    "S06.0": "Concussion",
    "S22.4": "Multiple fractures of ribs",
    "S42.2": "Fracture of upper end of humerus",
    "S52.5": "Fracture of lower end of radius",
    "S82.6": "Fracture of lateral malleolus",
    "T81.0": "Haemorrhage and haematoma complicating a procedure",
    "T81.4": "Infection following a procedure",
    "U07.1": "COVID-19, virus identified",
    "Z37.0": "Single live birth",
}
EPISODE_CODES: frozenset[str] = frozenset(CODES)


@dataclass(frozen=True)
class ProcedureReport:
    performed: date
    name: str  # "Laparoscopic appendicectomy"
    operation: bool  # False for a diagnostic procedure: no Procedure record
    pre_diagnosis: str
    post_diagnosis: str
    team: str
    anaesthesia: str
    wound_class: str
    note: str
    blood_loss: str = "Minimal"
    drains: str = "None"
    complications: str = "None"
    specimen: str = "None"
    body_site: str = ""
    device: str | None = None


@dataclass(frozen=True)
class Admission:
    title: str  # "Community-acquired pneumonia"
    admitted: date
    discharged: date
    service: str
    doctor: str  # display name, e.g. "Dr. Elif Aydın"
    complaint: str
    past_history: str
    examination: str
    course: str
    admission_diagnoses: tuple[tuple[str, str], ...]  # (ICD-10 code, text)
    discharge_diagnoses: tuple[tuple[str, str], ...]
    prescription: tuple[str, ...]
    recommendations: str
    outcome: str  # "Recovered", "Improved", ...
    complications: str = "None"  # during the admission, outside any procedure
    procedure: ProcedureReport | None = None


def _meta() -> dict:
    """A new meta for each resource: the synthetic security label plus the epicrisis tag. The shared one is never changed."""
    return {"security": list(SYNTHETIC_META["security"]), "tag": [dict(TAG)]}


def _block(heading: str, content: str | list[str]) -> str:
    text = "\n".join(line for line in content if line) if isinstance(content, list) else content
    return f"{heading}\n{text.strip() or 'None'}"


def _diagnoses(items: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"({code}) {text}" for code, text in items]


def text_of(admission: Admission, chart: PatientChart, number: str) -> str:
    patient = f"{chart.name} · MRN {chart.mrn} · {chart.age_on(admission.discharged)} y, {chart.gender}"
    blocks = [
        _block(
            "EPICRISIS REPORT",
            [
                patient,
                f"Report no. {number} · approved {day_text(admission.discharged)} · {admission.service} · {admission.doctor}",
            ],
        ),
        _block("ADMISSION AND DISCHARGE", f"{day_text(admission.admitted)} to {day_text(admission.discharged)}"),
        _block("COMPLAINT AND HISTORY", admission.complaint),
        _block("PAST AND FAMILY HISTORY", admission.past_history),
        _block("EXAMINATION ON ADMISSION", admission.examination),
        _block("HOSPITAL COURSE", admission.course),
        _block("ADMISSION DIAGNOSES", _diagnoses(admission.admission_diagnoses)),
        _block("DISCHARGE DIAGNOSES", _diagnoses(admission.discharge_diagnoses)),
        _block("COMPLICATIONS DURING ADMISSION", admission.complications),
        _block("DISCHARGE PRESCRIPTION", list(admission.prescription)),
        _block("DISCHARGE RECOMMENDATIONS AND FOLLOW-UP", admission.recommendations),
        _block("CONDITION AT DISCHARGE", admission.outcome),
    ]
    procedure = admission.procedure
    if procedure:
        blocks += [
            _block("OPERATION REPORT" if procedure.operation else "PROCEDURE REPORT", patient),
            _block("DATE OF PROCEDURE", day_text(procedure.performed)),
            _block("PRE-PROCEDURE DIAGNOSIS", procedure.pre_diagnosis),
            _block("POST-PROCEDURE DIAGNOSIS", procedure.post_diagnosis),
            _block("PROCEDURE PERFORMED", procedure.name),
            _block("TEAM", procedure.team),
            _block("ANAESTHESIA", procedure.anaesthesia),
            _block("WOUND CLASS", procedure.wound_class),
            _block("OPERATION NOTE", procedure.note),
            _block("ESTIMATED BLOOD LOSS", procedure.blood_loss),
            _block("DRAINS", procedure.drains),
            _block("COMPLICATIONS", procedure.complications),
            _block("PATHOLOGY SPECIMEN", procedure.specimen),
        ]
    return "\n\n".join(blocks) + "\n"


def add(chart: PatientChart, admission: Admission, existing: dict | None = None) -> dict:
    """Write the report into the chart (and the Procedure, for an operation); returns the DocumentReference.
    `existing` is a Procedure the chart already holds for the report's procedure: the report refers to it and adds none."""
    related = existing
    procedure = admission.procedure
    if procedure and procedure.operation and existing is None:
        record = chart.procedure(
            procedure.name,
            performed=procedure.performed,
            body_site=procedure.body_site,
            device=procedure.device,
        )
        record["meta"] = _meta()
        related = record

    document = chart._base("DocumentReference", "epi")
    sequence = document["id"].rsplit("-", 1)[1]
    number = f"ER-{chart.pid.removeprefix('p-')}-{sequence}"
    text = text_of(admission, chart, number)
    when = at(admission.discharged, 16)
    document |= {
        "meta": _meta(),
        "status": "current",
        "docStatus": "final",
        "type": {"coding": [{"system": LOINC, "code": REPORT_TYPE[0], "display": REPORT_TYPE[1]}], "text": REPORT_TYPE[1]},
        "category": [
            {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                        "code": "clinical-note",
                        "display": "Clinical Note",
                    }
                ]
            }
        ],
        "subject": chart.ref,
        "date": instant(when),
        "author": [{"display": admission.doctor}],
        "description": f"Epicrisis: {admission.title}",
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain; charset=utf-8",
                    "language": "en",
                    "data": _b64(text),
                    "title": f"Epicrisis: {admission.title}",
                    "creation": instant(when),
                }
            }
        ],
        "context": {"period": {"start": admission.admitted.isoformat(), "end": admission.discharged.isoformat()}},
    }
    if related:
        document["context"]["related"] = [{"reference": f"Procedure/{related['id']}"}]
    chart._add(document)
    return document


# Background reports start no earlier than this before the anchor (inside the ten years a report may go back) and end
# this long before the chart's first note, so the story's notes follow them in time and never have to mention them.
EARLIEST = timedelta(days=3640)
BEFORE_FIRST_NOTE = timedelta(days=120)


def add_background(chart: PatientChart, story: str, variant: int, anchor: date, seed: int) -> list[dict]:
    """Add five to ten epicrisis reports of earlier admissions to an existing patient's chart; returns the
    DocumentReferences. `story` is the story function's name. Random numbers come from the patient's own generator, so
    the story's resources and every other chart are unchanged."""
    from epicrisis_catalogue import Ctx, Patient, ercp, knee_replacement, plan

    rng = random.Random(f"epicrisis:{chart.pid}:{seed}")
    patient = Patient.of(chart, story, variant, (story, variant) in CLOSED)
    low = anchor - EARLIEST
    notes = sorted(
        date.fromisoformat(item["date"][:10]) for item in chart.resources
        if item["resourceType"] == "DocumentReference" and date.fromisoformat(item["date"][:10]) >= low
    )
    high = (notes[0] if notes else anchor) - BEFORE_FIRST_NOTE

    # Events the story already holds that get their report: (admission day, builder, the Procedure on the chart).
    fixed = []
    for procedure in (item for item in chart.resources if item["resourceType"] == "Procedure"):
        text = procedure["code"]["text"]
        performed = procedure.get("performedDateTime")
        if (story, variant) == ("diabetes_hypertension", 2) and "knee replacement" in text.lower() and performed:
            fixed.append((date.fromisoformat(performed[:10]) - timedelta(days=1), knee_replacement, procedure))
        elif story == "gallstone_disease" and text.startswith("ERCP") and performed:
            fixed.append((date.fromisoformat(performed[:10]), ercp, procedure))

    planned = [(day, episode.build, None, flag) for episode, day, flag in plan(patient, rng, low, high, [day for day, _, _ in fixed])]
    planned += [(day, build, procedure, False) for day, build, procedure in fixed]
    documents, earlier = [], []
    for day, build, procedure, complicated in sorted(planned, key=lambda item: item[0]):
        context = Ctx(patient, rng, day, complicated, list(earlier))
        admission = build(context, procedure) if procedure else build(context)
        documents.append(add(chart, admission, existing=procedure))
        if admission.procedure and admission.procedure.operation and procedure is None:
            name = admission.procedure.name
            earlier.append((admission.procedure.performed, name[:1].lower() + name[1:]))
    return documents
