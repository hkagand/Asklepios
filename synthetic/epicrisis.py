"""Epicrisis reports: the hospital discharge report, written as text by plain code.

An Admission describes one stay (and, optionally, the procedure done during it). `add` writes it into a chart as a
DocumentReference whose text attachment is laid out in headed blocks, the same way the notes are; an operation also gets a
Procedure record. Everything added carries the `epicrisis` tag so the rest of the chart can be shown to be unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chart import SYNTHETIC_META, LOINC, PatientChart, _b64, at, day_text, instant

TAG = {"system": "urn:demo:asklepios", "code": "epicrisis"}
REPORT_TYPE = ("18842-5", "Epicrisis report")


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


def add(chart: PatientChart, admission: Admission) -> dict:
    """Write the report into the chart (and the Procedure, for an operation); returns the DocumentReference."""
    related = None
    procedure = admission.procedure
    if procedure and procedure.operation:
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
