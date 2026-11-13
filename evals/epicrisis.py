"""Checks epicrisis reports (hospital discharge reports) and that they leave the existing cohort alone: python -m evals --epicrisis

The existing 21 charts are fingerprinted (evals/cohort-fingerprint.json, written from the generator at the gold anchor).
Resources added for epicrisis reports carry TAG and are left out of the fingerprint, so adding them must not change
what the 21 patients had before. Patients that are not among the file's keys are not compared.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from agent import tools
from agent.chat import start_session
from agent.citations import Evidence
from agent.epicrisis import index_line, index_section, read_all, reports
from agent.loops import latest_notes
from agent.record import Record, day_text

from .onboarding import imported_records
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


def scratch_admissions() -> dict:
    """The three admissions of the scratch chart: medical, operation, diagnostic procedure."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from dataclasses import replace

    from epicrisis import Admission, ProcedureReport

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
            complications="Minor port-site bleeding" if operation else "None",
        )

    surgical = replace(
        medical, title="Appendicitis", admitted=date(2026, 5, 3), discharged=date(2026, 5, 6), procedure=procedure(True),
        discharge_diagnoses=(("K35.8", "Acute appendicitis, other and unspecified"), ("I10", "Essential hypertension")),
        complications="Urinary retention, resolved",
    )
    diagnostic = replace(medical, title="Anaemia", admitted=date(2026, 6, 1), discharged=date(2026, 6, 2), procedure=procedure(False))
    return {"medical": medical, "operation": surgical, "diagnostic": diagnostic}


def scratch_chart():
    """A chart numbered 9001 holding the three scratch reports; also each report by label, and how many Procedure
    records the chart had right after the operation was added."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from catalog import Clinician
    from chart import PatientChart
    from epicrisis import add

    chart = PatientChart(
        number=9001, given="Test", family="Patient", gender="female", birth_date=date(1980, 1, 1), city="Ankara",
        gp=Clinician("ext-test", "Test", "Doctor", "Family Medicine"),
    )
    admissions = scratch_admissions()
    documents = {"medical": add(chart, admissions["medical"]), "operation": add(chart, admissions["operation"])}
    after_operation = len([resource for resource in chart.resources if resource["resourceType"] == "Procedure"])
    documents["diagnostic"] = add(chart, admissions["diagnostic"])
    return chart, documents, after_operation


def record_of(chart, today: date) -> Record:
    """The chart as the agent reads it on `today`, built the way cohort_records does."""
    patient, found = None, defaultdict(list)
    for resource in chart.resources:
        if resource["resourceType"] == "Patient":
            patient = resource
        else:
            found[resource["resourceType"]].append(resource)
    return Record(patient, dict(found), today=today)


def check_format(chart, documents: dict[str, dict], after_operation: int) -> list[str]:
    """Problems when the report builder in synthetic/epicrisis.py breaks the report contract."""
    problems: list[str] = []
    first, second, third = documents["medical"], documents["operation"], documents["diagnostic"]
    procedures = [resource for resource in chart.resources if resource["resourceType"] == "Procedure"]

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
    if after_operation != 1:
        problems.append(f"expected one Procedure after the operation, found {after_operation}")
    elif not tagged(procedures[0]):
        problems.append("the Procedure is not tagged")
    else:
        related = [item.get("reference") for item in second.get("context", {}).get("related", [])]
        if related != [f"Procedure/{procedures[0]['id']}"]:
            problems.append(f"context.related is {related}, not the Procedure")
    if len(procedures) != after_operation:
        problems.append("the diagnostic procedure added a Procedure")
    if any(tag.get("code") == "epicrisis" for tag in (chart.resources[0].get("meta", {}).get("tag", []))):
        problems.append("the Patient was tagged")
    return problems


INDEX_TITLE = "EPICRISIS REPORTS, newest first: one line per hospital admission (read_epicrisis returns all of them in full)"
NONE_ON_FILE = "No epicrisis reports are on file for this patient."


def tagged_refs(record: Record) -> list[str]:
    return [ref for ref, resource in record.resources.items() if resource["resourceType"] == "DocumentReference" and tagged(resource)]


def check_kinds(record: Record, plain_note_ref: str) -> list[str]:
    """Tagged documents are epicrisis reports; an untagged DocumentReference stays a note."""
    problems = []
    refs = tagged_refs(record)
    if len(refs) != 3:
        problems.append(f"expected 3 tagged reports, found {len(refs)}")
    problems += [f"{ref}: kind {record.document_by_ref[ref].kind!r}, expected 'epicrisis'" for ref in refs if record.document_by_ref[ref].kind != "epicrisis"]
    problems += [f"{ref}: category {record.document_by_ref[ref].category!r}" for ref in refs if record.document_by_ref[ref].category != "Epicrisis report"]
    if record.document_by_ref[plain_note_ref].kind != "note":
        problems.append(f"the plain note is kind {record.document_by_ref[plain_note_ref].kind!r}, expected 'note'")
    latest = [document.ref for document in latest_notes(record)]
    if plain_note_ref not in latest:
        problems.append("latest_notes leaves out the plain note")
    problems += [f"latest_notes includes {ref}" for ref in refs if ref in latest]
    visits = next((section for section in record.index().split("\n\n") if section.startswith("VISITS AND NOTES")), "")
    problems += [f"{ref} is listed under VISITS AND NOTES" for ref in refs if ref in visits]
    return problems


def check_fields(record: Record) -> list[str]:
    """The fields read by heading, newest first, and the index section's lines."""
    problems = []
    admissions = scratch_admissions()
    found = reports(record)
    if [report.discharged for report in found] != [admissions[label].discharged for label in ("diagnostic", "operation", "medical")]:
        problems.append(f"reports are not the three admissions newest first: {[report.discharged for report in found]}")
        return problems
    operation, report = admissions["operation"], found[1]
    if report.procedure != operation.procedure.name:
        problems.append(f"operation: procedure {report.procedure!r}, expected {operation.procedure.name!r}")
    if report.complications != (operation.complications, operation.procedure.complications):
        problems.append(f"operation: complications {report.complications!r}, expected both fields")
    expected = tuple(f"({code}) {text}" for code, text in operation.discharge_diagnoses)
    if report.diagnoses != expected:
        problems.append(f"operation: diagnoses {report.diagnoses!r}, expected {expected!r}")
    if (report.admitted, report.discharged) != (operation.admitted, operation.discharged):
        problems.append(f"operation: {report.admitted} to {report.discharged}, expected {operation.admitted} to {operation.discharged}")
    if report.service != operation.service:
        problems.append(f"operation: service {report.service!r}, expected {operation.service!r}")
    if report.outcome != operation.outcome:
        problems.append(f"operation: outcome {report.outcome!r}, expected {operation.outcome!r}")
    problems += [f"{item.ref}: not readable" for item in found if not item.readable]
    if found[0].procedure != admissions["diagnostic"].procedure.name or found[2].procedure is not None:
        problems.append(f"procedures read as {[item.procedure for item in found]}")
    if found[2].complications:
        problems.append(f"medical: complications {found[2].complications!r}, expected none")
    lines = index_section(record).split("\n")
    if lines[0] != INDEX_TITLE:
        problems.append(f"index section title is {lines[0]!r}")
    if len(lines) != 4:
        problems.append(f"index section has {len(lines) - 1} lines, expected 3")
    for line, item in zip(lines[1:], found):
        if not line.startswith("- ") or not line.endswith(f" [{item.ref}]"):
            problems.append(f"index line does not end with [{item.ref}]: {line}")
    if len(lines) > 2 and not lines[2].startswith(f"- {day_text(operation.admitted)} to {day_text(operation.discharged)}, {operation.service}: "):
        problems.append(f"operation index line: {lines[2]}")
    return problems


def check_tool(record: Record) -> list[str]:
    """read_epicrisis returns every report in full, its ids count as seen, and the prompt mode leaves the tool out."""
    problems = []
    found = reports(record)
    result = tools.run(record, "read_epicrisis", "{}")
    first, last = min(item.admitted for item in found), max(item.discharged for item in found)
    summary = f"3 epicrisis reports, admissions from {day_text(first)} to {day_text(last)}."
    if not result.blocks or result.blocks[0] != summary:
        problems.append(f"first block is {result.blocks[:1]}, expected {summary!r}")
    for item in found:
        if f"[{item.ref}]" not in result.text:
            problems.append(f"the tool does not give {item.ref}")
        if item.text.strip() not in result.text:
            problems.append(f"the tool does not give the full text of {item.ref}")
    if result.label != "Read 3 epicrisis reports":
        problems.append(f"label is {result.label!r}")
    evidence = Evidence()
    for block in result.blocks:
        evidence.add(block)
    problems += [f"Evidence has not seen {item.ref}" for item in found if not evidence.seen(item.ref)]
    names = [spec["function"]["name"] for spec in start_session("check", record).specs]
    if "read_epicrisis" not in names:
        problems.append("a session's tools do not include read_epicrisis")
    session = start_session("check", record, epicrisis_in_prompt=True)
    if "read_epicrisis" in [spec["function"]["name"] for spec in session.specs]:
        problems.append("with the reports in the prompt, the tools still include read_epicrisis")
    prompt = session.messages[0]["content"]
    problems += [f"the prompt lacks the full text of {item.ref}" for item in found if item.text.strip() not in prompt]
    return problems


def check_limit(record: Record) -> list[str]:
    """Over the limit, whole reports are dropped from the oldest end, and the result says so."""
    problems = []
    found = reports(record)
    blocks = read_all(record, limit=len(read_all(record)[1]) + 10)
    given = [block for block in blocks if block.startswith("[DocumentReference/")]
    if len(given) != 1 or not given[0].startswith(f"[{found[0].ref}]"):
        problems.append(f"expected only the newest report, got {len(given)}")
    older = found[1:]
    expected = (
        f"2 older reports were left out (admissions from {day_text(min(item.admitted for item in older))} "
        f"to {day_text(max(item.discharged for item in older))})."
    )
    if blocks[-1] != expected:
        problems.append(f"last block is {blocks[-1]!r}, expected {expected!r}")
    return problems


def check_unreadable(record: Record) -> list[str]:
    """A report whose headings cannot be read is still listed, and its text is still returned."""
    problems = []
    ref = reports(record)[1].ref
    resource = json.loads(json.dumps(record.resources[ref]))
    attachment = resource["content"][0]["attachment"]
    text = base64.b64decode(attachment["data"]).decode("utf-8")
    lowered = "\n".join(line.lower() if line.isupper() else line for line in text.split("\n"))
    attachment["data"] = base64.b64encode(lowered.encode("utf-8")).decode("ascii")
    found: dict[str, list[dict]] = defaultdict(list)
    for key, item in record.resources.items():
        if item["resourceType"] != "Patient":
            found[item["resourceType"]].append(resource if key == ref else item)
    copy = Record(record.patient, dict(found), today=record.today)
    report = next(item for item in reports(copy) if item.ref == ref)
    if report.readable:
        problems.append("a report with lower-cased headings is readable")
    line = index_line(report)
    if not line.startswith(f"{day_text(report.when)}: ") or not line.endswith(f"Fields not readable; read_epicrisis for the text [{ref}]"):
        problems.append(f"unreadable index line: {line}")
    for name, build in (("record.index()", copy.index), ("index_section()", lambda: index_section(copy))):
        try:
            build()
        except Exception as error:  # noqa: BLE001 - the check is that nothing raises
            problems.append(f"{name} raised {error!r}")
    if lowered.strip() not in "\n\n".join(read_all(copy)):
        problems.append("read_epicrisis does not return the unreadable report's text")
    return problems


def check_none_on_file(record_without: Record) -> list[str]:
    """A patient without reports: the index says none are on file, and so does the tool."""
    problems = []
    section = index_section(record_without)
    if section != f"{INDEX_TITLE}\n- none on file":
        problems.append(f"index section is {section!r}")
    blocks = tools.run(record_without, "read_epicrisis", "{}").blocks
    if blocks != [NONE_ON_FILE]:
        problems.append(f"the tool returns {blocks!r}")
    return problems


async def run_epicrisis(settings, records, anchor: date, seed: int, out: Path) -> int:
    sys.path.insert(0, str(ROOT / "synthetic"))
    from chart import at

    chart, documents, after_operation = scratch_chart()
    checks = {"untouched": check_untouched(anchor, seed), "format": check_format(chart, documents, after_operation)}
    plain = chart.note(when=at(date(2026, 7, 1), 10), author=chart.gp, title="Follow-up visit", body="Well. No new complaints.")
    record = record_of(chart, anchor)
    checks |= {
        "kinds": check_kinds(record, f"DocumentReference/{plain['id']}"),
        "fields": check_fields(record),
        "tool": check_tool(record),
        "limit": check_limit(record),
        "unreadable": check_unreadable(record),
        "none on file": check_none_on_file(imported_records(anchor)["p-3001"]),
    }
    for name, problems in checks.items():
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
    return 1 if any(checks.values()) else 0
