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


def check_background_chart(chart, anchor: date, closed: set[str]) -> list[str]:
    """Problems with one existing chart's background reports."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from epicrisis import EPISODE_CODES

    pid, problems = chart.pid, []
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
    if pid == "p-1009" and not any(
        item.admitted.year == 2019 and "knee replacement" in (item.procedure or "").lower() for item in found.values()
    ):
        problems.append(f"{pid}: no 2019 report of the knee replacement")
    if pid == "p-1011" and any("hysterectomy" in item.text.lower() for item in found.values()):
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

    others = sorted({item["resourceType"] for item in resources if tagged(item)} - {"DocumentReference", "Procedure"})
    if others:
        problems.append(f"{pid}: tagged {', '.join(others)}")
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
        again = build_charts(anchor, seed)
        if json.dumps([chart.resources for chart in charts], sort_keys=True) != json.dumps([chart.resources for chart in again], sort_keys=True):
            problems.append(f"{anchor}: two builds differ")
        for pid, imported in imported_charts(anchor).items():
            if any(tagged(resource) for resource in imported):
                problems.append(f"{anchor}: {pid} holds a tagged resource")
    return problems


# The showcase patients (synthetic/showcase.py) that must be in the cohort, each with pairs of phrases that some one of
# their reports must both contain (case-insensitive), and the long-term medicine each has an active order for.
REQUIRED = {
    "p-2043": [("fine-needle aspiration", "thyroid"), ("total thyroidectomy", "hypocalc"), ("total thyroidectomy", "vocal cord"),
               ("radioiodine", ""), ("fine-needle aspiration", "lymph node"), ("cholecystectomy", ""), ("wrist", "plate"), ("pneumonia", "")],
    "p-2044": [("stent", "haematoma"), ("stent", "elective"), ("duodenal ulcer", "transfus"), ("clopidogrel", "stopped"),
               ("inguinal hernia", "aspirin"), ("angiograph", "patent"), ("pneumonia", "")],
}
ACTIVE_MEDICINE = {"p-2043": "levothyroxine", "p-2044": "aspirin"}


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
        "fields": check_fields(record),
        "tool": check_tool(record),
        "limit": check_limit(record),
        "unreadable": check_unreadable(record),
        "surgery text": check_surgery_text(record, documents),
        "none on file": check_none_on_file(imported_records(anchor)["p-3001"]),
    }
    for name, problems in checks.items():
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
    return 1 if any(checks.values()) else 0
