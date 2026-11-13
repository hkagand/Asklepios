"""Checks epicrisis reports (hospital discharge reports) and that they leave the existing cohort alone: python -m evals --epicrisis

The existing 21 charts are fingerprinted (evals/cohort-fingerprint.json, written from the generator at the gold anchor).
Resources added for epicrisis reports carry TAG and are left out of the fingerprint, so adding them must not change
what the 21 patients had before. Patients that are not among the file's keys are not compared.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from .run import ROOT

FINGERPRINT = Path(__file__).parent / "cohort-fingerprint.json"
TAG = {"system": "urn:demo:asklepios", "code": "epicrisis"}


def tagged(resource: dict) -> bool:
    return any(tag.get("system") == TAG["system"] and tag.get("code") == TAG["code"] for tag in resource.get("meta", {}).get("tag", []))


def fingerprint(charts: list) -> dict[str, str]:
    """Patient id -> sha256 of the chart's untagged resources as JSON with sorted keys."""
    return {
        chart.pid: hashlib.sha256(
            json.dumps([resource for resource in chart.resources if not tagged(resource)], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        for chart in charts
    }


def build_charts(anchor: date, seed: int) -> list:
    sys.path.insert(0, str(ROOT / "synthetic"))
    from cohort import build_cohort

    return build_cohort(anchor, seed)


def check_untouched(anchor: date, seed: int) -> list[str]:
    """Problems when an existing chart's untagged resources differ from the recorded fingerprint."""
    recorded = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    now = fingerprint(build_charts(anchor, seed))
    problems = [f"{pid}: its resources differ from {FINGERPRINT.name}" for pid, digest in recorded.items() if pid in now and now[pid] != digest]
    problems += [f"{pid}: no longer generated" for pid in recorded if pid not in now]
    return problems


HEADINGS = (
    "EPICRISIS REPORT", "ADMISSION AND DISCHARGE", "COMPLAINT AND HISTORY", "PAST AND FAMILY HISTORY",
    "EXAMINATION ON ADMISSION", "HOSPITAL COURSE", "ADMISSION DIAGNOSES", "DISCHARGE DIAGNOSES",
    "COMPLICATIONS DURING ADMISSION", "DISCHARGE PRESCRIPTION", "DISCHARGE RECOMMENDATIONS AND FOLLOW-UP",
    "CONDITION AT DISCHARGE",
)
PROCEDURE_HEADINGS = (
    "DATE OF PROCEDURE", "PRE-PROCEDURE DIAGNOSIS", "POST-PROCEDURE DIAGNOSIS", "PROCEDURE PERFORMED", "TEAM",
    "ANAESTHESIA", "WOUND CLASS", "OPERATION NOTE", "ESTIMATED BLOOD LOSS", "DRAINS", "COMPLICATIONS",
    "PATHOLOGY SPECIMEN",
)


def _heading_problems(label: str, text: str, expected: tuple[str, ...]) -> list[str]:
    """Each expected heading is a line of its own, exactly once, in the given order."""
    lines = text.split("\n")
    problems, last = [], -1
    for heading in expected:
        found = [index for index, line in enumerate(lines) if line == heading]
        if len(found) != 1:
            problems.append(f"{label}: {heading} appears {len(found)} times")
        elif found[0] < last:
            problems.append(f"{label}: {heading} is out of order")
        else:
            last = found[0]
    return problems


def check_format() -> list[str]:
    """Problems when the report builder in synthetic/epicrisis.py breaks the report contract."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    import base64

    from catalog import Clinician
    from chart import PatientChart
    from epicrisis import Admission, ProcedureReport, add

    chart = PatientChart(
        number=9001, given="Test", family="Patient", gender="female", birth_date=date(1980, 1, 1), city="Ankara",
        gp=Clinician("ext-test", "Test", "Doctor", "Family Medicine"),
    )
    medical = Admission(
        title="Community-acquired pneumonia", admitted=date(2026, 3, 2), discharged=date(2026, 3, 8), service="Internal Medicine",
        doctor="Dr. Elif Aydin", complaint="Cough and fever.", past_history="None.", examination="Crackles on the right.",
        course="Treated with antibiotics.", admission_diagnoses=(("J18.9", "Pneumonia, unspecified"),),
        discharge_diagnoses=(("J18.9", "Pneumonia, unspecified"),), prescription=(), recommendations="Review in two weeks.",
        outcome="Recovered",
    )

    def procedure(operation: bool) -> ProcedureReport:
        return ProcedureReport(
            performed=date(2026, 5, 4), name="Laparoscopic appendicectomy" if operation else "Colonoscopy", operation=operation,
            pre_diagnosis="Acute appendicitis", post_diagnosis="Acute appendicitis", team="Dr. A, Dr. B", anaesthesia="General",
            wound_class="Clean-contaminated", note="Uneventful.", body_site="Abdomen",
        )

    from dataclasses import replace

    surgical = replace(medical, title="Appendicitis", admitted=date(2026, 5, 3), discharged=date(2026, 5, 6), procedure=procedure(True))
    diagnostic = replace(medical, title="Anaemia", admitted=date(2026, 6, 1), discharged=date(2026, 6, 2), procedure=procedure(False))

    problems: list[str] = []
    first, second = add(chart, medical), add(chart, surgical)
    procedures = [resource for resource in chart.resources if resource["resourceType"] == "Procedure"]
    third = add(chart, diagnostic)

    def text(document: dict) -> str:
        return base64.b64decode(document["content"][0]["attachment"]["data"]).decode("utf-8")

    for label, document in (("medical", first), ("operation", second), ("diagnostic", third)):
        if not document["id"].startswith("epi-p-9001-"):
            problems.append(f"{label}: id {document['id']} does not start with epi-p-9001-")
        if not tagged(document):
            problems.append(f"{label}: the report is not tagged")
        period = document["context"]["period"]
        if period["start"] > period["end"]:
            problems.append(f"{label}: period starts after it ends")
    problems += _heading_problems("medical", text(first), HEADINGS)
    for heading in ("OPERATION REPORT", "PROCEDURE REPORT") + PROCEDURE_HEADINGS[:1]:
        if heading in text(first).split("\n"):
            problems.append(f"medical: has {heading}")
    problems += _heading_problems("operation", text(second), HEADINGS + ("OPERATION REPORT",) + PROCEDURE_HEADINGS)
    problems += _heading_problems("diagnostic", text(third), HEADINGS + ("PROCEDURE REPORT",) + PROCEDURE_HEADINGS)
    if "PROCEDURE REPORT" in text(second).split("\n") or "OPERATION REPORT" in text(third).split("\n"):
        problems.append("a report carries the wrong procedure heading")
    if len(procedures) != 1:
        problems.append(f"expected one Procedure after the operation, found {len(procedures)}")
    elif not tagged(procedures[0]):
        problems.append("the Procedure is not tagged")
    else:
        related = [item.get("reference") for item in second.get("context", {}).get("related", [])]
        if related != [f"Procedure/{procedures[0]['id']}"]:
            problems.append(f"context.related is {related}, not the Procedure")
    if len([resource for resource in chart.resources if resource["resourceType"] == "Procedure"]) != 1:
        problems.append("the diagnostic procedure added a Procedure")
    if any(tag.get("code") == "epicrisis" for tag in (chart.resources[0].get("meta", {}).get("tag", []))):
        problems.append("the Patient was tagged")
    return problems


async def run_epicrisis(settings, records, anchor: date, seed: int, out: Path) -> int:
    checks = {"untouched": check_untouched(anchor, seed), "format": check_format()}
    for name, problems in checks.items():
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
    return 1 if any(checks.values()) else 0
