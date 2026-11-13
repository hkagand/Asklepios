"""Checks epicrisis reports (hospital discharge reports) and that they leave the existing cohort alone: python -m evals --epicrisis

The existing 21 charts are fingerprinted (evals/cohort-fingerprint.json, written from the generator at the gold anchor).
Resources added for epicrisis reports carry TAG and are left out of the fingerprint, so adding them must not change
what the 21 patients had before. Patients that are not among the file's keys are not compared.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from agent import tools
from agent.chat import start_session
from agent.citations import Evidence
from agent.epicrisis import index_line, index_section, read_all, reports
from agent.loops import latest_notes
from agent.record import Record, day_text, text_of

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
    elif not procedures[0]["id"].startswith("eproc-p-9001-"):
        problems.append(f"the Procedure's id {procedures[0]['id']} does not start with eproc-p-9001-")
    else:
        related = [item.get("reference") for item in second.get("context", {}).get("related", [])]
        if related != [f"Procedure/{procedures[0]['id']}"]:
            problems.append(f"context.related is {related}, not the Procedure")
    if len(procedures) != after_operation:
        problems.append("the diagnostic procedure added a Procedure")
    if any(tag.get("code") == "epicrisis" for tag in (chart.resources[0].get("meta", {}).get("tag", []))):
        problems.append("the Patient was tagged")
    return problems


INDEX_TITLE = (
    "EPICRISIS REPORTS, newest first: one summary line per hospital admission. The course, findings, anaesthesia, "
    "complication details and discharge advice are only in the full reports: read_epicrisis returns all of them"
)
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
    # The tag is matched on its system and code: the same code under another system is not an epicrisis report.
    resource = json.loads(json.dumps(record.resources[plain_note_ref]))
    resource.setdefault("meta", {})["tag"] = [{"system": "urn:example:other", "code": TAG["code"]}]
    found: dict[str, list[dict]] = defaultdict(list)
    for key, item in record.resources.items():
        if item["resourceType"] != "Patient":
            found[item["resourceType"]].append(resource if key == plain_note_ref else item)
    if Record(record.patient, dict(found), today=record.today).document_by_ref[plain_note_ref].kind != "note":
        problems.append("a note tagged 'epicrisis' under another system is read as an epicrisis report")
    return problems


def check_fields(record: Record, records: dict[str, Record]) -> list[str]:
    """The fields read by heading, newest first, and the index section's lines: short, with clean punctuation, also
    for the showcase patients (`records`, by patient id) and for a report without its "Report no." line."""
    problems = []
    for pid in ("p-2043", "p-2044", "p-2045"):
        for line in index_section(records[pid]).split("\n")[1:]:
            if len(line) > 600 or ".." in line or ", :" in line:
                problems.append(f"{pid}: index line of {len(line)} characters: {line[:120]!r}...")
    first = reports(record)[0]
    without = "\n".join(line for line in first.text.split("\n") if not line.startswith("Report no."))
    line = index_line(next(item for item in reports(_with_text(record, first.ref, without)) if item.ref == first.ref))
    if ", :" in line or ".." in line:
        problems.append(f"index line of a report without its Report no. line: {line!r}")
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

    # A procedural complication is written in the procedure block and again under COMPLICATIONS DURING ADMISSION: it
    # is listed once.
    same, written = operation.procedure.complications, report.text
    text = written.replace(f"COMPLICATIONS DURING ADMISSION\n{operation.complications}\n", f"COMPLICATIONS DURING ADMISSION\n{same}\n")
    if text == written:
        problems.append("operation: could not write the procedure's complication under COMPLICATIONS DURING ADMISSION")
    else:
        twice = next(item for item in reports(_with_text(record, report.ref, text)) if item.ref == report.ref)
        if twice.complications != (same,):
            problems.append(f"the same complication in both blocks reads as {twice.complications!r}, expected ({same!r},)")
        if index_line(twice).count(same) != 1:
            problems.append(f"the same complication in both blocks is listed {index_line(twice).count(same)} times in the index line")
    return problems


def _with_text(record: Record, ref: str, text: str) -> Record:
    """A copy of the record in which the document `ref` has the given text."""
    resource = json.loads(json.dumps(record.resources[ref]))
    resource["content"][0]["attachment"]["data"] = base64.b64encode(text.encode("utf-8")).decode("ascii")
    found: dict[str, list[dict]] = defaultdict(list)
    for key, item in record.resources.items():
        if item["resourceType"] != "Patient":
            found[item["resourceType"]].append(resource if key == ref else item)
    return Record(record.patient, dict(found), today=record.today)


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
    if not blocks[0].endswith("; the newest report is given below."):
        problems.append(f"first block is {blocks[0]!r}, expected it to say how many reports are given below")
    return problems


def check_unreadable(record: Record) -> list[str]:
    """A report whose headings cannot be read is still listed, and its text is still returned."""
    problems = []
    ref = reports(record)[1].ref
    text = base64.b64decode(record.resources[ref]["content"][0]["attachment"]["data"]).decode("utf-8")
    lowered = "\n".join(line.lower() if line.isupper() else line for line in text.split("\n"))
    copy = _with_text(record, ref, lowered)
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


def check_surgery_text(record: Record, documents: dict[str, dict]) -> list[str]:
    """The surgery reader is given an epicrisis report without its PROCEDURE REPORT block (a diagnostic procedure is
    not an operation), and with its OPERATION REPORT block in full."""
    from agent.surgery import text_for_reading

    problems = []
    diagnostic = record.document_by_ref[f"DocumentReference/{documents['diagnostic']['id']}"]
    given = text_for_reading(diagnostic)
    full_block = diagnostic.text.split("\nPROCEDURE REPORT\n", 1)
    if "PROCEDURE REPORT" in given.splitlines():
        problems.append("diagnostic: the reader is given the PROCEDURE REPORT heading")
    if len(full_block) != 2:
        problems.append("diagnostic: the scratch report has no PROCEDURE REPORT block")
    else:
        leaked = [line for line in full_block[1].splitlines() if line.strip() and line.strip() not in full_block[0] and line in given]
        if leaked:
            problems.append(f"diagnostic: the reader is given the procedure block's {leaked[0]!r}")
    for heading in ("EPICRISIS REPORT", "DISCHARGE DIAGNOSES", "CONDITION AT DISCHARGE"):
        if heading not in given.splitlines():
            problems.append(f"diagnostic: the reader is not given {heading}")
    operation = record.document_by_ref[f"DocumentReference/{documents['operation']['id']}"]
    given = text_for_reading(operation)
    if "OPERATION REPORT" not in given.splitlines() or "OPERATION NOTE" not in given.splitlines() or "Uneventful." not in given:
        problems.append("operation: the reader is not given the operation report with its note")

    # The PAST AND FAMILY HISTORY block repeats earlier operations: the reader reads each from its own report.
    past = "Previous operations: open appendicectomy (2001)."
    text = operation.text.replace("PAST AND FAMILY HISTORY\nNone.\n", f"PAST AND FAMILY HISTORY\n{past}\n")
    if text == operation.text:
        problems.append("operation: could not write a past operation into PAST AND FAMILY HISTORY")
    # The same, with trailing spaces after the headings and CRLF line endings.
    spaced = re.sub(r"(?m)^([A-Z][A-Z -]+)$", r"\1  ", text).replace("\n", "\r\n")
    diagnostic_spaced = re.sub(r"(?m)^([A-Z][A-Z -]+)$", r"\1  ", diagnostic.text).replace("\n", "\r\n")
    for label, written in (("operation", text), ("operation, spaced", spaced)):
        given = text_for_reading(_with_text(record, operation.ref, written).document_by_ref[operation.ref])
        lines = [line.strip() for line in given.splitlines()]
        if "PAST AND FAMILY HISTORY" in lines or past in given:
            problems.append(f"{label}: the reader is given the PAST AND FAMILY HISTORY block")
        missing = [heading for heading in HEADINGS + ("OPERATION REPORT", "OPERATION NOTE") if heading != "PAST AND FAMILY HISTORY" and heading not in lines]
        if missing or "Uneventful." not in given or "Treated with antibiotics." not in given:
            problems.append(f"{label}: the reader is not given the rest of the report (missing {missing})")
    given = text_for_reading(_with_text(record, diagnostic.ref, diagnostic_spaced).document_by_ref[diagnostic.ref])
    if "PROCEDURE REPORT" in [line.strip() for line in given.splitlines()]:
        problems.append("diagnostic, spaced: the reader is given the PROCEDURE REPORT block")
    return problems


DIAGNOSTIC_NAMES = (
    "Polyp removal", "Endoscopic polypectomy", "Colonoscopy with polypectomy", "Colonoscopy", "Gastroscopy",
    "Upper gastrointestinal endoscopy", "Fine-needle aspiration of a thyroid nodule", "Core biopsy", "Kidney biopsy",
    "Diagnostic coronary angiography", "Coronary angiography", "Cystoscopy", "Hysteroscopy with endometrial sampling",
    "Bronchoscopy", "Sigmoidoscopy", "Bone marrow biopsy", "Lumbar puncture", "Endoscopic haemostasis", "Endoscopic haemostasis with clips",
    "Gastroscopy with adrenaline injection and clips", "Endoscopic duodenal ulcer hemostasis with clipping",
    "Polypectomy of hyperplastic polyp of sigmoid colon", "Endoscopic clipping of duodenal ulcer",
)
OPERATION_NAMES = (
    "ERCP with biliary sphincterotomy and balloon stone extraction", "Coronary angiography with stent to the right coronary artery",
    "Primary percutaneous coronary intervention with a drug-eluting stent", "Excision biopsy of a breast lump",
    "Laparoscopic cholecystectomy", "Open appendicectomy", "Total thyroidectomy", "Right total knee replacement",
    "Incisional hernia repair with mesh", "Port-a-cath insertion", "Septoplasty", "Carpal tunnel release",
    "Percutaneous endoscopic gastrostomy", "Endoscopic sinus surgery", "Endoscopic carpal tunnel release",
    "Angiographic embolisation", "Endoscopic stone removal", "Endoscopic sinus surgery with polypectomy",
    "Laparoscopic sleeve gastrectomy", "Transurethral resection of the prostate", "Cystoscopy with ureteric stent insertion",
    "Hysteroscopic myomectomy",
    "Surgical haemostasis", "Return to theatre for haemostasis", "Exploration of neck wound and haemostasis",
    "Re-exploration for bleeding", "Evacuation of haematoma",
    # Operations with a diagnostic word in their name.
    "Nasal polypectomy", "Hysteroscopic polypectomy", "Transanal polypectomy", "Sentinel lymph node biopsy",
    "Cone biopsy of the cervix", "Open lung biopsy", "Cystoscopy and TURBT", "Cystoscopy with lithotripsy",
    "Hysteroscopy and D&C", "Laparoscopy and biopsy", "Gastroscopy and PEG placement",
)


def check_diagnostic_names(records: dict[str, Record]) -> list[str]:
    """is_diagnostic is true for diagnostic procedures and false for operations, including every operation that
    evals/surgery.toml expects (its full name from the patient's Procedure records, else the expectation's phrase)."""
    import tomllib

    from agent.surgery import is_diagnostic

    from .run import says

    problems = [f"{name!r} is not diagnostic" for name in DIAGNOSTIC_NAMES if not is_diagnostic(name)]
    problems += [f"{name!r} is diagnostic" for name in OPERATION_NAMES if is_diagnostic(name)]
    expected = tomllib.loads((ROOT / "evals" / "surgery.toml").read_text(encoding="utf-8"))["patient"]
    for patient in expected:
        record = records.get(patient["id"])
        for item in patient["operations"]:
            names = [text_of(procedure.get("code")) for procedure in record.procedures] if record else []
            names = [name for name in names if says(name, item["match"])] or [item["match"]]
            problems += [f"{patient['id']}: expected operation {name!r} is diagnostic" for name in names if is_diagnostic(name)]
    return problems


def _stub_operation(name: str, when: str = "this document"):
    from agent.surgery import Operation

    return Operation(quote=name, name=name, when=when, approach=None, side=None, elsewhere=False, complications=(), implants=())


def _stub_reader(document_ref: str, *operations):
    """The smallest reader surgical_history accepts: an async read(document), answering for one document only."""
    from agent.surgery import DocumentSurgery

    class Reader:
        async def read(self, document):
            return DocumentSurgery(tuple(operations) if document.ref == document_ref else (), (), None)

    return Reader()


async def check_surgery_filter(chart, documents: dict[str, dict]) -> list[str]:
    """Whatever the reader returns for a document, a diagnostic procedure does not reach the history; the real
    operation does, and the document counts as read. What was left out is returned, and said in the index section."""
    from agent.surgery import index_section as surgery_index, surgical_history

    ref = f"DocumentReference/{documents['operation']['id']}"
    reader = _stub_reader(
        ref, *(_stub_operation(name) for name in ("Laparoscopic appendicectomy", "Polyp removal", "Endoscopic polypectomy")),
    )
    # No Procedure records: only what the stub returns can appear.
    record = record_of(chart, date(2026, 11, 13))
    record.procedures = []
    history = await surgical_history(record, reader)
    names = [item["name"] for item in history["operations"]]
    problems = []
    if names != ["Laparoscopic appendicectomy"]:
        problems.append(f"the history lists {names}, expected only the appendicectomy")
    if history["searched"]["documentsRead"] < 1:
        problems.append("the document with the dropped operations does not count as searched")
    left_out = [(item.get("name"), item.get("ref")) for item in history.get("leftOut", [])]
    if left_out != [("Polyp removal", ref), ("Endoscopic polypectomy", ref)]:
        problems.append(f"the history leaves out {left_out}, expected the polyp removal and the polypectomy of {ref}")
    last = surgery_index(history).splitlines()[-1]
    if not (last.startswith("- Not counted as operations, being diagnostic procedures: ") and "polyp removal (" in last and "endoscopic polypectomy (" in last):
        problems.append(f"the index section's last line is {last!r}, expected the operations not counted")
    return problems


async def check_implants(chart, documents: dict[str, dict]) -> list[str]:
    """Drains, clips, sutures, staples, packs and catheters are not implants: of "subhepatic drain; skin clips;
    polypropylene mesh" only the mesh is listed."""
    from dataclasses import replace

    from agent.surgery import surgical_history

    operation = replace(_stub_operation("Open incisional hernia repair"), implants=("subhepatic drain", "skin clips", "polypropylene mesh"))
    record = record_of(chart, date(2026, 11, 13))
    record.procedures = []
    history = await surgical_history(record, _stub_reader(f"DocumentReference/{documents['operation']['id']}", operation))
    implants = [item["implants"] for item in history["operations"]]
    return [] if implants == [["polypropylene mesh"]] else [f"the implants listed are {implants}, expected only the mesh"]


def check_surgery_tidy() -> list[str]:
    """A statement of no operations is listed once, the newest, with its document's kind and date; the nose is head and
    neck."""
    from agent.surgery import index_section as surgery_index, region_of

    names = ("Septoplasty", "Nasal polypectomy", "Reduction of a broken nose")
    problems = [f"{name!r} is not head and neck" for name in names if region_of(name) != "head_neck"]
    statement = "No previous operations."
    history = {
        "operations": [], "clues": [], "leftOut": [],
        "noneStated": [
            {"ref": "DocumentReference/epi-1", "kind": "epicrisis", "label": "Epicrisis", "date": "2019-03-02", "quote": statement},
            {"ref": "DocumentReference/doc-1", "kind": "note", "label": "Note", "date": "2021-05-04", "quote": "No previous operations"},
            {"ref": "DocumentReference/epi-2", "kind": "epicrisis", "label": "Epicrisis", "date": "2023-07-08", "quote": statement},
            {"ref": "DocumentReference/doc-2", "kind": "note", "label": "Note", "date": "2020-01-01", "quote": "Never had surgery."},
        ],
        "searched": {"procedures": 0, "notes": 2, "reports": 0, "epicrisis": 2, "documentsRead": 4, "earliest": None},
    }
    lines = [line for line in surgery_index(history).splitlines() if "states:" in line]
    expected = [
        f'- An epicrisis report of 8 Jul 2023 states: "{statement}" [DocumentReference/epi-2]',
        '- A note of 1 Jan 2020 states: "Never had surgery." [DocumentReference/doc-2]',
    ]
    if lines != expected:
        problems.append(f"the statements of no operations are listed as {lines}, expected {expected}")
    return problems


STENT_NAMES = (
    "Stents to the right coronary artery", "Stent to the LAD", "Drug-eluting stent placement in the right coronary artery",
    "PCI to the left anterior descending artery", "Coronary stenting", "RCA stent",
    "Primary percutaneous coronary intervention with a drug-eluting stent to the right coronary artery",
)
NOT_CORONARY_STENT_NAMES = ("Biliary stent insertion", "Ureteric stent insertion", "Carotid artery stenting", "Coronary artery bypass grafting")


async def _stub_history(chart, documents: dict[str, dict], procedures: list[tuple[str, str]], mentions: list[tuple[str, str]]) -> list[dict]:
    """The operations surgical_history lists for Procedure records (name, day) and one document's reader mentions (name, when)."""
    from agent.surgery import surgical_history

    record = record_of(chart, date(2026, 11, 13))
    record.procedures = [
        {"resourceType": "Procedure", "id": f"stub-{number}", "status": "completed", "code": {"text": name}, "performedDateTime": day}
        for number, (name, day) in enumerate(procedures)
    ]
    reader = _stub_reader(f"DocumentReference/{documents['operation']['id']}", *(_stub_operation(name, when) for name, when in mentions))
    return (await surgical_history(record, reader))["operations"]


async def check_stent_family(chart, documents: dict[str, dict]) -> list[str]:
    """A name that speaks of a stent and a coronary artery is a coronary stent, however it is worded; a stent
    elsewhere is not. A reader's "Stents to the right coronary artery" joins the Procedure record of that stent."""
    from agent.surgery import family_of

    problems = [f"{name!r} is not a coronary stent" for name in STENT_NAMES if family_of(name) != "coronary stent"]
    problems += [f"{name!r} is a coronary stent" for name in NOT_CORONARY_STENT_NAMES if family_of(name) == "coronary stent"]
    operations = await _stub_history(
        chart, documents,
        [
            ("Primary percutaneous coronary intervention with a drug-eluting stent to the right coronary artery", "2018-03-02"),
            ("Percutaneous coronary intervention with a stent to the left anterior descending artery", "2019-06-11"),
        ],
        [("Stents to the right coronary artery", "2018")],
    )
    if len(operations) != 2:
        problems.append(f"the history lists {[item['name'] for item in operations]}, expected the 2019 stent and one 2018 stent")
    elif not any(len(item["sources"]) > 1 and item["year"] == 2018 for item in operations):
        problems.append("the reader's 2018 stent is not merged with the Procedure record")
    return problems


async def check_merging(chart, documents: dict[str, dict]) -> list[str]:
    """Differently worded mentions of one operation merge when one name contains the other; different operations,
    and the two sides, stay apart."""
    problems = []

    async def count(procedures: list[tuple[str, str]], mentions: list[tuple[str, str]]) -> tuple[int, list[dict]]:
        operations = await _stub_history(chart, documents, procedures, mentions)
        return len(operations), operations

    orif = "Open reduction and internal fixation of left distal radius"
    number, operations = await count([(orif + " fracture", "2024-01-27")], [(orif, "2024-01-27")])
    if number != 1 or len(operations[0]["sources"]) != 2:
        problems.append(f"(a) the reader's {orif!r} is not merged with the Procedure record: {[item['name'] for item in operations]}")
    await count([(orif + " fracture", "2024-01-27")], [("ORIF of the left distal radius with a volar plate", "2024-01-27")])
    number, _ = await count([("Open right inguinal hernia repair with mesh", "2021-05-04")], [("Open incisional hernia repair with mesh", "2021")])
    if number != 2:
        problems.append(f"(c) an inguinal and an incisional hernia repair in one year are listed as {number} operation(s)")
    number, _ = await count([("Open right inguinal hernia repair with mesh", "2021-05-04")], [("hernia repair", "2021")])
    if number != 1:
        problems.append(f"(d) a plain hernia repair is not merged with the inguinal repair of its year ({number} operations)")
    number, _ = await count([("Left knee arthroscopy", "2020-02-02")], [("Right knee arthroscopy", "2020")])
    if number != 2:
        problems.append(f"(e) a left and a right knee arthroscopy are listed as {number} operation(s)")
    return problems


# Questions about the patient's past, for which the reports are read in code before the model's first step: the gold
# category's questions (English and Turkish) and a few more.
PRE_READ = (
    "Any prior things I need to know about her thyroid?", "Did she have complications after any operation?",
    "Tiroidi ile ilgili daha önce bilmem gereken bir şey var mı?", "Anything in his earlier admissions that matters before I prescribe an anti-inflammatory?",
    "Has he ever been admitted for a stroke?", "What should the anaesthetist know from her earlier operations?",
    "Any bleeding after a procedure before?", "Has he been admitted to hospital before, and for what?",
    "Was she ever hospitalised?", "Any problems with anesthesia in the past?", "Anything I should know about his heart?",
    "Hastaneye hiç yattı mı?", "Önceki yatışlarında komplikasyon gelişti mi?", "Ameliyattan sonra komplikasyon oldu mu?",
    "Anestezi ile ilgili bir sorun yaşadı mı?", "Hiç inme geçirdi mi?",
    "What should I know about her heart?", "Any past history I should be aware of?",
    "Anything important in her past medical history?", "Kalbiyle ilgili bilmemiz gereken bir şey var mı?",
    "Hiç hastaneye yatırıldı mı?", "Has she been in hospital before?", "Any previous biopsies?",
    # A capital İ lower-cases to "i" and a combining dot: both spellings must fire.
    "İşlemden sonra kanama oldu mu?", "işlemden sonra kanama oldu mu?",
    "Any history of bleeding?", "Did he have a transfusion?", "What did the colonoscopy find?", "Was she in hospital last year?",
)
# Questions about current results, medicines, orders or the visit, and about which operations the patient has had
# (answered from SURGICAL HISTORY: the gold questions of category surgery among them): left to the model.
NO_PRE_READ = (
    "What was her last TSH?", "What changed since the last visit?", "What is her current levothyroxine dose?",
    "Brief me for today's visit", "What was the previous HbA1c?",
    "Son TSH değeri neydi?", "Son vizitten beri ne değişti?", "Şu anki levotiroksin dozu nedir?",
    "Bugünkü vizit için hastayı özetle", "Önceki HbA1c değeri neydi?",
    "Has she had previous abdominal surgery?", "Daha önce karın ameliyatı geçirdi mi?", "When was his gallbladder removed?",
    "Has he had any abdominal operations?", "Has he had any operations before?", "When did she have her hysterectomy?",
    "What did hepatobiliary surgery say about resection?", "Has she had any operations?", "Has he ever had surgery?",
    "Daha önce ameliyat oldu mu?", "Genel cerrahi ne dedi?",
    # A procedure that is ordered or due, "ever" or "daha önce" with a result or a medicine, complications or the
    # airway without the past, an operation, a procedure or anaesthesia.
    "Is the procedure ordered yet?", "When is her procedure scheduled?", "Has her potassium ever been high?",
    "Has the eGFR ever been below 30?", "Has she ever taken metformin?", "Daha önce HbA1c kaç idi?",
    "Daha önce hangi ilaçları kullandı?", "Any diabetic complications?", "Any airway disease?",
    # The present, the family's history, and a current report are not the patient's past admissions.
    "Is she in hospital now?", "Family history of diabetes?", "What does the echo show?",
)


def check_pre_read(record: Record, record_without: Record) -> list[str]:
    """The rule that reads the reports in code fires for questions about the past and not for current results,
    medicines, orders or briefings; never for a patient without reports, nor when the reports are in the prompt."""
    from agent.chat import pre_reads

    session, without = start_session("check", record), start_session("check", record_without)
    in_prompt = start_session("check", record, epicrisis_in_prompt=True)
    problems = [f"not pre-read: {question!r}" for question in PRE_READ if not pre_reads(session, question)]
    problems += [f"pre-read: {question!r}" for question in NO_PRE_READ if pre_reads(session, question)]
    problems += [f"pre-read without reports: {question!r}" for question in PRE_READ if pre_reads(without, question)]
    problems += [f"pre-read with the reports in the prompt: {question!r}" for question in PRE_READ if pre_reads(in_prompt, question)]
    # A conversation that already holds a read_epicrisis result is not given the reports again.
    read = start_session("check", record)
    call = {"id": "call-0", "type": "function", "function": {"name": "read_epicrisis", "arguments": "{}"}}
    read.messages += [
        {"role": "user", "content": PRE_READ[0]},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "call-0", "content": tools.run(record, "read_epicrisis", "{}").text},
        {"role": "assistant", "content": "Answered."},
    ]
    problems += [f"pre-read again after a read_epicrisis result: {question!r}" for question in PRE_READ if pre_reads(read, question)]
    return problems


async def check_read_once(record: Record) -> list[str]:
    """Through run_turn with a stub in place of the model: a past question pre-reads the reports once, and a second
    past question in the same conversation adds no further read_epicrisis result."""
    import tempfile

    from agent.audit import AuditLog
    from agent.chat import run_turn

    class Model:
        model = "stub"

        async def chat(self, messages: list[dict], *, tools: list[dict], tool_choice: str, **_: object) -> tuple[dict, dict]:
            return {"role": "assistant", "content": "Nothing more to add."}, {}

    def results(session) -> int:
        ids = {
            call["id"] for message in session.messages if message["role"] == "assistant"
            for call in message.get("tool_calls") or [] if call["function"]["name"] == "read_epicrisis"
        }
        return sum(message["role"] == "tool" and message["tool_call_id"] in ids for message in session.messages)

    problems = []
    session = start_session("check", record)
    with tempfile.TemporaryDirectory() as folder:
        audit = AuditLog(Path(folder) / "audit.jsonl")
        for number, question in enumerate(("Has he been admitted to hospital before, and for what?", "Any problems with anesthesia in the past?"), 1):
            async for _ in run_turn(session, question, llm=Model(), audit=audit, max_steps=2):
                pass
            if (found := results(session)) != 1:
                problems.append(f"after question {number}, {found} read_epicrisis results in the session, expected 1")
    return problems


MICROGRAMS = ("125 μg", "125 µg", "125 ug")  # Greek mu (U+03BC), micro sign (U+00B5), plain letters


def check_units() -> list[str]:
    """The citation verifier reads micrograms the same however the mu is written, and an unknown unit never raises."""
    from agent.citations import facts_in, verify

    problems = []
    texts = [f"Levothyroxine {amount} daily." for amount in MICROGRAMS] + ["Dose 125 zorkg daily, 125 Μg."]
    facts = {}
    for text in texts:
        try:
            facts[text] = facts_in(text)
        except Exception as error:  # noqa: BLE001 - the check is that nothing raises
            problems.append(f"facts_in({text!r}) raised {error!r}")
    found = {tuple(facts[text]) for text in texts[:3] if text in facts}
    if len(found) != 1:
        problems.append(f"the three microgram forms give different facts: {sorted(found)}")
    ref = "MedicationRequest/med-1"
    for source in MICROGRAMS:
        for written in MICROGRAMS:
            try:
                evidence = Evidence()
                evidence.add(f"{ref} Levothyroxine {source} daily")
                blocks = verify(f"- Levothyroxine {written} daily [{ref}]", evidence=evidence, resolve=lambda token: token, label=str, context="")["blocks"]
            except Exception as error:  # noqa: BLE001 - the check is that nothing raises
                problems.append(f"verify({written!r}) raised {error!r}")
                continue
            if [block["status"] for block in blocks] != ["ok"]:
                problems.append(f"{written!r} against a source with {source!r}: {[(block['status'], block.get('issues')) for block in blocks]}")
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


# The anchors the background reports are checked at: the gold anchor, the next working days, and a leap day.
BACKGROUND_ANCHORS = (date(2026, 10, 24), date(2026, 10, 26), date(2028, 2, 29))
# Patients closed to new operations, with the story and variant each one is at every anchor (seed 2041).
CLOSED_PATIENTS = {
    "p-1003": ("diabetes_hypertension", 4), "p-1014": ("hypothyroidism", 0), "p-1009": ("diabetes_hypertension", 2),
    "p-1011": ("chronic_kidney_disease", 1), "p-2041": ("colorectal_cancer", 0), "p-2042": ("gallstone_disease", 0),
}
NOT_IN_HERO = re.compile(r"\bPET\b|echocardiogra|ejection fraction", re.IGNORECASE)
# Codes the catalogue gives only to a complication of the admission or its procedure.
COMPLICATION_CODES = {
    "A04.7", "E87.1", "E87.6", "F05.9", "I80.8", "J22", "K56.0", "K59.0", "N17.9", "O72.1", "R33", "R55", "R73.9",
    "T81.0", "T81.4",
}
STOP_WORDS = {"a", "an", "and", "or", "of", "the", "with", "without", "to", "due", "in", "on", "for", "not", "other", "unspecified"}


def _section(text: str, heading: str) -> list[str]:
    """The content lines under a heading of an epicrisis report."""
    from agent.epicrisis import HEADINGS as REPORT_HEADINGS

    lines, inside = [], False
    for line in text.splitlines():
        if line.strip() in REPORT_HEADINGS:
            inside = line.strip() == heading
        elif inside and line.strip():
            lines.append(line.strip())
    return lines


def _medicine_name(order: dict) -> str:
    """"Sodium bicarbonate 500 mg tablet" -> "sodium bicarbonate"; "Fluorouracil IV" -> "fluorouracil"."""
    text = re.sub(r"\(.*?\)", "", order["medicationCodeableConcept"]["text"])
    name = re.split(r"\d", text)[0].strip().lower()
    return name.removesuffix(" iv").strip()


def _order_period(order: dict) -> tuple[date, date | None]:
    bounds = order["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]
    return date.fromisoformat(bounds["start"]), date.fromisoformat(bounds["end"]) if "end" in bounds else None


def _long_term(order: dict) -> bool:
    start, end = _order_period(order)
    return end is None or (end - start).days > 90


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower())) - STOP_WORDS


def _procedure_problems(pid: str, docs: list[dict], found: dict, tagged_procedures: set[str]) -> list[str]:
    """A procedure report has no tagged Procedure; each tagged Procedure is cited by exactly one operation report."""
    problems = []
    for doc in docs:
        ref = f"DocumentReference/{doc['id']}"
        text = found[ref].text
        related = [item["reference"].split("/", 1)[1] for item in doc.get("context", {}).get("related", [])]
        if "PROCEDURE REPORT" in text.splitlines() and any(key in tagged_procedures for key in related):
            problems.append(f"{pid}: {ref} is a procedure report with a tagged Procedure")
    for key in tagged_procedures:
        citing = [
            doc for doc in docs
            if f"Procedure/{key}" in [item["reference"] for item in doc.get("context", {}).get("related", [])]
            and "OPERATION REPORT" in found[f"DocumentReference/{doc['id']}"].text.splitlines()
        ]
        if len(citing) != 1:
            problems.append(f"{pid}: Procedure/{key} is referenced by {len(citing)} operation reports")
    return problems


def _prescription_problems(pid: str, resources: list[dict], found: dict) -> list[str]:
    """A long-term medicine in a discharge prescription has an order active on the discharge day."""
    problems = []
    orders = [item for item in resources if item["resourceType"] == "MedicationRequest" and _long_term(item)]
    names = {_medicine_name(item) for item in orders}
    for ref, item in found.items():
        for line in _section(item.text, "DISCHARGE PRESCRIPTION"):
            for name in names:
                if name in line.lower() and not any(
                    _medicine_name(order) == name and _order_period(order)[0] <= item.discharged
                    and (_order_period(order)[1] is None or item.discharged <= _order_period(order)[1])
                    for order in orders
                ):
                    problems.append(f"{pid}: {ref} prescribes {name} with no order active on {item.discharged}")
    return problems


def check_background_chart(chart, anchor: date, closed: set[str], story: tuple[str, int] | None = None) -> list[str]:
    """Problems with one existing chart's background reports. `story` is the chart's story and variant (by default the
    one it has with seed 2041, where that matters)."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from epicrisis import EPISODE_CODES

    pid, problems = chart.pid, []
    story = story or CLOSED_PATIENTS.get(pid)
    resources = chart.resources
    docs = [item for item in resources if item["resourceType"] == "DocumentReference" and tagged(item)]
    procedures = {item["id"]: item for item in resources if item["resourceType"] == "Procedure"}
    tagged_procedures = {key for key, item in procedures.items() if tagged(item)}
    found = {item.ref: item for item in reports(record_of(chart, anchor))}
    if not 5 <= len(docs) <= 10:
        return [f"{pid}: {len(docs)} reports"]
    problems += [f"{pid}: {ref} not readable" for ref, item in found.items() if not item.readable]
    if problems:
        return problems
    earliest = date.fromordinal(anchor.toordinal() - 3653)
    for item in found.values():
        if not earliest <= item.admitted <= item.discharged < anchor:
            problems.append(f"{pid}: {item.ref} from {item.admitted} to {item.discharged}")
    if not any(item.complications for item in found.values()):
        problems.append(f"{pid}: no report with a complication")
    conditions = [item for item in resources if item["resourceType"] == "Condition"]
    condition_words = set().union(
        *(_words(item["code"].get("text", "") + " " + item["code"]["coding"][0]["display"]) for item in conditions)
    )
    if not any(not (_words(item.title) & condition_words) for item in found.values()):
        problems.append(f"{pid}: every report's title shares a word with the chart's conditions")

    problems += _procedure_problems(pid, docs, found, tagged_procedures)

    if pid in closed and tagged_procedures:
        problems.append(f"{pid}: closed to new operations but has {len(tagged_procedures)} new Procedure records")
    if story == ("diabetes_hypertension", 2) and not any(
        item.admitted.year == 2019 and "knee replacement" in (item.procedure or "").lower() for item in found.values()
    ):
        problems.append(f"{pid}: no 2019 report of the knee replacement")
    if story == ("chronic_kidney_disease", 1) and any("hysterectomy" in item.text.lower() for item in found.values()):
        problems.append(f"{pid}: a report mentions the hysterectomy")
    if pid == "p-2041":
        problems += [f"{pid}: {ref} mentions {NOT_IN_HERO.search(item.text)[0]}" for ref, item in found.items() if NOT_IN_HERO.search(item.text)]

    summaries = [
        item for item in resources
        if item["resourceType"] == "DocumentReference" and not tagged(item) and item["type"]["coding"][0]["code"] == "18842-5"
    ]
    for summary in summaries:
        period = summary.get("context", {}).get("period") or {"start": summary["date"], "end": summary["date"]}
        start, end = date.fromisoformat(period["start"][:10]), date.fromisoformat(period["end"][:10])
        problems += [
            f"{pid}: {ref} overlaps the admission of the discharge summary of {start}"
            for ref, item in found.items() if item.admitted <= end and start <= item.discharged
        ]

    problems += _prescription_problems(pid, resources, found)

    codes = {coding["code"] for item in conditions for coding in item["code"]["coding"]}
    born = date.fromisoformat(resources[0]["birthDate"])
    for ref, item in found.items():
        given = [re.match(r"\((\S+)\)", line) for line in item.diagnoses]
        problems += [f"{pid}: {ref} has a diagnosis line without a code: {line}" for line, hit in zip(item.diagnoses, given) if not hit]
        given_codes = {hit[1] for hit in given if hit}
        problems += [f"{pid}: {ref} gives {code}, not in the chart or EPISODE_CODES" for code in sorted(given_codes - codes - EPISODE_CODES)]
        if any(code.startswith(("O", "Z37")) for code in given_codes):
            age = item.admitted.year - born.year - ((item.admitted.month, item.admitted.day) < (born.month, born.day))
            if resources[0]["gender"] != "female" or not 18 <= age <= 45:
                problems.append(f"{pid}: {ref} is a childbirth for a {resources[0]['gender']} patient aged {age}")

    for ref, item in found.items():
        during = " ".join(_section(item.text, "COMPLICATIONS DURING ADMISSION"))
        procedure = " ".join(_section(item.text, "COMPLICATIONS"))
        admitted_codes = {hit[1] for line in _section(item.text, "ADMISSION DIAGNOSES") if (hit := re.match(r"\((\S+)\)", line))}
        complication_codes = {hit[1] for line in item.diagnoses if (hit := re.match(r"\((\S+)\)", line))} & COMPLICATION_CODES
        if during == "None" and ((procedure and procedure != "None") or complication_codes - admitted_codes):
            problems.append(f"{pid}: {ref} has a complication but says None under COMPLICATIONS DURING ADMISSION")
        if item.title == "Observation after a head injury":
            complaint = " ".join(_section(item.text, "COMPLAINT AND HISTORY"))
            examination = " ".join(_section(item.text, "EXAMINATION ON ADMISSION"))
            if "collision" in complaint and "fall" in complaint.replace("collision", ""):
                problems.append(f"{pid}: {ref} speaks of a fall after a car collision")
            if "back of the head" in complaint and "occipital" not in examination:
                problems.append(f"{pid}: {ref} struck the back of the head but the swelling is elsewhere")

    # Clarithromycin raises statin and calcium-channel blocker levels: not given while either is ordered.
    for ref, item in found.items():
        given = item.text.lower().count("clarithromycin") - item.text.lower().count("clarithromycin avoided")
        interacting = sorted({
            _medicine_name(order) for order in resources
            if order["resourceType"] == "MedicationRequest" and _interacts_with_clarithromycin(_medicine_name(order))
            and _order_period(order)[0] <= item.discharged and (_order_period(order)[1] is None or item.admitted < _order_period(order)[1])
        })
        if given and interacting:
            problems.append(f"{pid}: {ref} gives clarithromycin with {', '.join(interacting)} ordered")
        isolation = re.search(r"Isolate at home until ([^.(,]+)", item.text)
        if isolation and not ((until := _day_of(isolation[1])) and until > item.discharged):
            problems.append(f"{pid}: {ref} advises isolation until {isolation[1].strip()!r}, not a day after discharge on {item.discharged}")

    others = sorted({item["resourceType"] for item in resources if tagged(item)} - {"DocumentReference", "Procedure"})
    if others:
        problems.append(f"{pid}: tagged {', '.join(others)}")
    return problems


def _interacts_with_clarithromycin(name: str) -> bool:
    """A statin or a calcium-channel blocker."""
    return name.endswith("statin") or name.endswith("dipine") or name in ("diltiazem", "verapamil")


def _day_of(text: str) -> date | None:
    """A day written as day_text writes it ("2 Mar 2026"), or None."""
    from agent.record import MONTHS

    parts = text.split()
    if len(parts) != 3 or not parts[0].isdigit() or parts[1] not in MONTHS or not parts[2].isdigit():
        return None
    return date(int(parts[2]), MONTHS.index(parts[1]) + 1, int(parts[0]))


# The gold anchor, where the cohort-wide variety of the background reports is checked.
GOLD_ANCHOR = date(2026, 10, 23)
HEAD_INJURY = "Observation after a head injury"
MOST_HEAD_INJURIES = 8  # charts with a head-injury report, at most
MOST_SAME_COURSE = 2  # patients whose reports share one HOSPITAL COURSE text, at most


def _variety_problems(charts: list, anchor: date) -> list[str]:
    """Across the background charts: head injury in at most MOST_HEAD_INJURIES charts, and no HOSPITAL COURSE text in
    the reports of more than MOST_SAME_COURSE patients."""
    problems = []
    found = {chart.pid: reports(record_of(chart, anchor)) for chart in charts}
    head = [pid for pid, items in found.items() if any(item.title == HEAD_INJURY for item in items)]
    if len(head) > MOST_HEAD_INJURIES:
        problems.append(f"head injury is in {len(head)} charts, more than {MOST_HEAD_INJURIES}")
    courses: dict[str, set[str]] = defaultdict(set)
    titles: dict[str, str] = {}
    for pid, items in found.items():
        for item in items:
            course = " ".join(_section(item.text, "HOSPITAL COURSE"))
            courses[course].add(pid)
            titles[course] = item.title
    problems += [
        f"the hospital course of {titles[course]!r} is the same in {len(pids)} patients ({', '.join(sorted(pids))})"
        for course, pids in courses.items() if len(pids) > MOST_SAME_COURSE
    ]
    return problems


def check_background(anchors: list[date], seed: int) -> list[str]:
    """The existing 21 charts' background reports, at each anchor; none for the imported patients; deterministic."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from epicrisis import CLOSED
    from national import imported_charts
    from showcase import SHOWCASE

    problems = []
    if set(CLOSED) != set(CLOSED_PATIENTS.values()):
        problems.append(f"CLOSED is {sorted(CLOSED)}, expected {sorted(CLOSED_PATIENTS.values())}")
    for anchor in anchors:
        charts = build_charts(anchor, seed)
        problems += [
            f"{anchor}: {problem}"
            for chart in charts if chart.pid not in SHOWCASE
            for problem in check_background_chart(chart, anchor, set(CLOSED_PATIENTS))
        ]
        if anchor == GOLD_ANCHOR:
            problems += [f"{anchor}: {problem}" for problem in _variety_problems([chart for chart in charts if chart.pid not in SHOWCASE], anchor)]
        again = build_charts(anchor, seed)
        if json.dumps([chart.resources for chart in charts], sort_keys=True) != json.dumps([chart.resources for chart in again], sort_keys=True):
            problems.append(f"{anchor}: two builds differ")
        for pid, imported in imported_charts(anchor).items():
            if any(tagged(resource) for resource in imported):
                problems.append(f"{anchor}: {pid} holds a tagged resource")
    return problems + _seed_problems(GOLD_ANCHOR)


SWEEP_SEEDS = range(1, 41)
CHECKED_SEEDS = (17, 77, 91)  # seeds that once crashed the generator: every per-chart check runs on them


def _charts_with_stories(anchor: date, seed: int) -> tuple[list, dict[str, tuple[str, int]]]:
    """The cohort, and the story and variant of each chart that got background reports: which patient tells which
    story depends on the seed."""
    import cohort

    stories: dict[str, tuple[str, int]] = {}
    add_background = cohort.add_background

    def recording(chart, story, variant, *args):
        stories[chart.pid] = (story, variant)
        return add_background(chart, story, variant, *args)

    cohort.add_background = recording
    try:
        return build_charts(anchor, seed), stories
    finally:
        cohort.add_background = add_background


def _seed_problems(anchor: date) -> list[str]:
    """The cohort builds for every seed of the sweep with 5 to 10 reports for each existing patient, and passes the
    per-chart checks for CHECKED_SEEDS."""
    from epicrisis import CLOSED
    from showcase import SHOWCASE

    problems = []
    for seed in sorted(set(SWEEP_SEEDS) | set(CHECKED_SEEDS)):
        try:
            charts, stories = _charts_with_stories(anchor, seed)
        except Exception as error:  # noqa: BLE001 - any crash is the finding
            problems.append(f"seed {seed}: the build raises {type(error).__name__}: {error!r}")
            continue
        charts = [chart for chart in charts if chart.pid not in SHOWCASE]
        if len(charts) != 21:
            problems.append(f"seed {seed}: {len(charts)} existing patients")
        for chart in charts:
            count = sum(1 for item in chart.resources if item["resourceType"] == "DocumentReference" and tagged(item))
            if not 5 <= count <= 10:
                problems.append(f"seed {seed}: {chart.pid} has {count} reports")
        if seed in CHECKED_SEEDS:
            closed = {pid for pid, story in stories.items() if story in CLOSED}
            problems += [
                f"seed {seed}: {problem}"
                for chart in charts for problem in check_background_chart(chart, anchor, closed, stories[chart.pid])
            ]
    return problems


# The showcase patients (synthetic/showcase.py) that must be in the cohort, each with pairs of phrases that some one of
# their reports must both contain (case-insensitive), and the long-term medicine each has an active order for.
REQUIRED = {
    "p-2043": [("fine-needle aspiration", "thyroid"), ("total thyroidectomy", "hypocalc"), ("total thyroidectomy", "vocal cord"),
               ("radioiodine", ""), ("fine-needle aspiration", "lymph node"), ("cholecystectomy", ""), ("wrist", "plate"), ("pneumonia", "")],
    "p-2044": [("stent", "haematoma"), ("stent", "elective"), ("duodenal ulcer", "transfus"), ("clopidogrel", "stopped"),
               ("inguinal hernia", "aspirin"), ("angiograph", "patent"), ("pneumonia", "")],
    "p-2045": [("cholecystectomy", "converted"), ("cormack", "videolaryngoscope"), ("wound infection", ""), ("incisional hernia", "mesh"),
               ("deep vein thrombosis", "three months"), ("knee replacement", "spinal"), ("polyp", "bleed"), ("renal colic", "")],
}
ACTIVE_MEDICINE = {"p-2043": "levothyroxine", "p-2044": "aspirin", "p-2045": "amlodipine"}
# The planned admissions of the showcase patients, by the name of their timeline function and its fields: each is
# admitted, and has its procedure, on a working day.
PLANNED = {
    "p-2043": ("thyroid_timeline", ("aspiration", "surgery", "radioiodine", "node")),
    "p-2044": ("coronary_timeline", ("stent", "hernia")),
    "p-2045": ("surgery_timeline", ("hernia", "colonoscopy", "knee")),
}


def _planned_problems(pid: str, found: dict, anchor: date) -> list[str]:
    import showcase

    problems = []
    name, fields = PLANNED.get(pid, ("", ()))
    timeline = getattr(showcase, name)(anchor) if name else None
    for field_name in fields:
        day = getattr(timeline, field_name)
        matching = [item for item in found.values() if item.admitted == day]
        if len(matching) != 1:
            problems.append(f"{pid}: {len(matching)} reports of the planned {field_name} admission on {day}")
            continue
        days = [("admitted", day)] + [("procedure", _day_of(line)) for line in _section(matching[0].text, "DATE OF PROCEDURE")]
        problems += [
            f"{pid}: the planned {field_name}: {what} on {when:%A} {when}" for what, when in days if when and when.weekday() >= 5
        ]
    return problems


def _overlaps(first: dict, second: dict) -> bool:
    return first["start"] < second["end"] and second["start"] < first["end"]


def _clinicians(appointment: dict) -> set[str]:
    return {actor["actor"]["reference"] for actor in appointment["participant"] if actor["actor"]["reference"].startswith("Practitioner/")}


def check_showcase(charts: dict, records: dict[str, Record], anchor: date) -> list[str]:
    """The showcase patients' reports, problem lists, orders, notes and next appointment, at one anchor. `charts` and
    `records` are keyed by patient id."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from national import imported_charts
    from showcase import SHOWCASE

    problems = [f"{pid} is not in the cohort" for pid in REQUIRED if pid not in charts]
    booked = [item for chart in charts.values() for item in chart.resources if item["resourceType"] == "Appointment"]
    booked += [item for resources in imported_charts(anchor).values() for item in resources if item["resourceType"] == "Appointment"]
    earliest = date.fromordinal(anchor.toordinal() - 3653)
    for pid in (pid for pid in SHOWCASE if pid in charts):
        resources, record = charts[pid].resources, records[pid]
        docs = [item for item in resources if item["resourceType"] == "DocumentReference" and tagged(item)]
        found = {item.ref: item for item in reports(record)}
        if not 8 <= len(found) <= 10:
            problems.append(f"{pid}: {len(found)} reports")
        if unreadable := [ref for ref, item in found.items() if not item.readable]:
            problems.append(f"{pid}: not readable: {', '.join(unreadable)}")
            continue
        problems += [
            f"{pid}: {ref} from {item.admitted} to {item.discharged}"
            for ref, item in found.items() if not earliest <= item.admitted <= item.discharged < anchor
        ]
        for first, second in REQUIRED.get(pid, []):
            if not any(first in item.text.lower() and second in item.text.lower() for item in found.values()):
                problems.append(f"{pid}: no report holds both {first!r} and {second!r}")
        problems += _prescription_problems(pid, resources, found)
        problems += _planned_problems(pid, found, anchor)
        # A report's author does not refer the patient on to themself as the family doctor.
        for ref, item in found.items():
            approved = next((line for line in _section(item.text, "EPICRISIS REPORT") if line.startswith("Report no.")), "")
            author = approved.split(" · ")[-1]
            if author and f"family doctor ({author.lower()})" in " ".join(_section(item.text, "DISCHARGE RECOMMENDATIONS AND FOLLOW-UP")).lower():
                problems.append(f"{pid}: {ref} refers the patient to its own author, {author}, as the family doctor")
        # An echocardiogram's findings belong to a report on the chart (the heart-failure patients have them).
        if not any(item["resourceType"] == "DiagnosticReport" and "echocardiogra" in item["code"].get("text", "").lower() for item in resources):
            problems += [f"{pid}: {ref} mentions an echocardiogram the chart has no report of" for ref, item in found.items() if "echocardiogra" in item.text.lower()]
        tagged_procedures = {item["id"] for item in resources if item["resourceType"] == "Procedure" and tagged(item)}
        problems += _procedure_problems(pid, docs, found, tagged_procedures)
        operations = [item for item in found.values() if "OPERATION REPORT" in item.text.splitlines()]
        if len(operations) != len(tagged_procedures):
            problems.append(f"{pid}: {len(operations)} operation reports, {len(tagged_procedures)} tagged Procedure records")

        if not any(item["resourceType"] == "Condition" for item in resources):
            problems.append(f"{pid}: no conditions")
        medicine = ACTIVE_MEDICINE.get(pid)
        if medicine and not any(
            item["resourceType"] == "MedicationRequest" and item["status"] == "active" and _medicine_name(item).startswith(medicine)
            and _order_period(item)[0] <= anchor and _order_period(item)[1] is None
            for item in resources
        ):
            problems.append(f"{pid}: no active {medicine} order")
        notes = [item for item in resources if item["resourceType"] == "DocumentReference" and not tagged(item)]
        if len(notes) < 2:
            problems.append(f"{pid}: {len(notes)} notes")

        appointments = [item for item in resources if item["resourceType"] == "Appointment"]
        upcoming = [item for item in appointments if item["start"][:10] >= anchor.isoformat()]
        if len(upcoming) != 1 or len(appointments) != 1:
            problems.append(f"{pid}: {len(appointments)} appointments, {len(upcoming)} on or after {anchor}")
        for appointment in upcoming:
            clash = [
                item["id"] for item in booked
                if item is not appointment and _clinicians(item) & _clinicians(appointment) and _overlaps(item, appointment)
            ]
            if clash:
                problems.append(f"{pid}: the appointment at {appointment['start']} collides with {', '.join(clash)}")

        problems += [f"{pid}: latest_notes includes {document.ref}" for document in latest_notes(record) if document.ref in found]
        others = sorted({item["resourceType"] for item in resources if tagged(item)} - {"DocumentReference", "Procedure"})
        if others:
            problems.append(f"{pid}: tagged {', '.join(others)}")
    return problems


async def run_epicrisis(settings, records, anchor: date, seed: int, out: Path) -> int:
    sys.path.insert(0, str(ROOT / "synthetic"))
    from chart import at

    chart, documents, after_operation = scratch_chart()
    showcase = []
    for day in (anchor, *BACKGROUND_ANCHORS):
        charts = {item.pid: item for item in build_charts(day, seed)}
        found = check_showcase(charts, {pid: record_of(item, day) for pid, item in charts.items()}, day)
        showcase += [f"{day}: {problem}" for problem in found]
    checks = {
        "untouched": check_untouched(anchor, seed),
        "background": check_background([anchor, *BACKGROUND_ANCHORS], seed),
        "showcase": showcase,
        "format": check_format(chart, documents, after_operation),
    }
    plain = chart.note(when=at(date(2026, 7, 1), 10), author=chart.gp, title="Follow-up visit", body="Well. No new complaints.")
    record = record_of(chart, anchor)
    checks |= {
        "kinds": check_kinds(record, f"DocumentReference/{plain['id']}"),
        "fields": check_fields(record, records),
        "tool": check_tool(record),
        "limit": check_limit(record),
        "unreadable": check_unreadable(record),
        "surgery text": check_surgery_text(record, documents),
        "diagnostic names": check_diagnostic_names(records),
        "surgery filter": await check_surgery_filter(chart, documents),
        "implants": await check_implants(chart, documents),
        "surgery tidy": check_surgery_tidy(),
        "stent family": await check_stent_family(chart, documents),
        "merging": await check_merging(chart, documents),
        "none on file": check_none_on_file(imported_records(anchor)["p-3001"]),
        "pre-read": check_pre_read(record, imported_records(anchor)["p-3001"]),
        "read once": await check_read_once(record),
        "units": check_units(),
    }
    for name, problems in checks.items():
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
    return 1 if any(checks.values()) else 0
