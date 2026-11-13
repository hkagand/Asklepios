"""Epicrisis reports (hospital discharge reports): their fields read by heading, a line each for the chart index, and
the read_epicrisis tool, which returns all of them in full.

A report's text is blocks of an upper-case heading line followed by its content; empty content is written "None".
The operation or procedure report, when there was one, follows the discharge summary in the same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .record import MONTHS, Document, Record, day_text

MAX_CHARS = 60_000

HEADINGS = (
    "EPICRISIS REPORT", "ADMISSION AND DISCHARGE", "COMPLAINT AND HISTORY", "PAST AND FAMILY HISTORY",
    "EXAMINATION ON ADMISSION", "HOSPITAL COURSE", "ADMISSION DIAGNOSES", "DISCHARGE DIAGNOSES",
    "COMPLICATIONS DURING ADMISSION", "DISCHARGE PRESCRIPTION", "DISCHARGE RECOMMENDATIONS AND FOLLOW-UP",
    "CONDITION AT DISCHARGE", "OPERATION REPORT", "PROCEDURE REPORT", "DATE OF PROCEDURE", "PRE-PROCEDURE DIAGNOSIS",
    "POST-PROCEDURE DIAGNOSIS", "PROCEDURE PERFORMED", "TEAM", "ANAESTHESIA", "WOUND CLASS", "OPERATION NOTE",
    "ESTIMATED BLOOD LOSS", "DRAINS", "COMPLICATIONS", "PATHOLOGY SPECIMEN",
)
# Without these the report's fields cannot be listed.
REQUIRED = ("EPICRISIS REPORT", "ADMISSION AND DISCHARGE", "DISCHARGE DIAGNOSES", "CONDITION AT DISCHARGE")
EMPTY = "None"

INDEX_TITLE = (
    "EPICRISIS REPORTS, newest first: one summary line per hospital admission. The course, findings, anaesthesia, "
    "complication details and discharge advice are only in the full reports: read_epicrisis returns all of them"
)
FULL_TITLE = "EPICRISIS REPORTS, in full, newest first"
NONE_ON_FILE = "No epicrisis reports are on file for this patient."


@dataclass(frozen=True)
class Epicrisis:
    ref: str
    title: str
    when: datetime  # the document's date
    admitted: date | None
    discharged: date | None
    service: str
    diagnoses: tuple[str, ...]  # discharge diagnoses, "(I10) Essential hypertension"
    procedure: str | None  # PROCEDURE PERFORMED
    complications: tuple[str, ...]  # both complication fields, without "None", each distinct one once
    outcome: str
    readable: bool  # False when the headings could not be read
    text: str

    @property
    def first_day(self) -> date:
        return self.admitted or self.when.date()

    @property
    def last_day(self) -> date:
        return self.discharged or self.when.date()


def _sections(text: str) -> dict[str, str]:
    """Heading -> its content, for every known heading that is a line of its own."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if line.strip() in HEADINGS and line.strip() not in sections:
            current = sections[line.strip()] = []
        elif current is not None:
            current.append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _day(text: str) -> date | None:
    """A day written as day_text writes it: "2 Mar 2026"."""
    parts = text.split()
    if len(parts) != 3 or not parts[0].isdigit() or parts[1] not in MONTHS or not parts[2].isdigit():
        return None
    try:
        return date(int(parts[2]), MONTHS.index(parts[1]) + 1, int(parts[0]))
    except ValueError:
        return None


def _value(content: str | None) -> str | None:
    return content if content and content != EMPTY else None


def _parse(document: Document) -> Epicrisis:
    sections = _sections(document.text)
    start, _, end = (sections.get("ADMISSION AND DISCHARGE") or "").partition(" to ")
    admitted, discharged = _day(start.strip()), _day(end.strip())
    approved = next((line for line in (sections.get("EPICRISIS REPORT") or "").splitlines() if line.startswith("Report no.")), "")
    service = " · ".join(approved.split(" · ")[2:-1])
    diagnoses = tuple(line.strip() for line in (sections.get("DISCHARGE DIAGNOSES") or "").splitlines() if _value(line.strip()))
    # A procedural complication is often written in both fields: each distinct one is listed once.
    complications = tuple(dict.fromkeys(
        " ".join(value.split())
        for heading in ("COMPLICATIONS DURING ADMISSION", "COMPLICATIONS")
        if (value := _value(sections.get(heading)))
    ))
    readable = all(heading in sections for heading in REQUIRED) and admitted is not None and discharged is not None
    return Epicrisis(
        ref=document.ref,
        title=document.title.removeprefix("Epicrisis: "),
        when=document.when,
        admitted=admitted,
        discharged=discharged,
        service=service,
        diagnoses=diagnoses,
        procedure=_value(sections.get("PROCEDURE PERFORMED")),
        complications=complications,
        outcome=_value(sections.get("CONDITION AT DISCHARGE")) or "",
        readable=readable,
        text=document.text,
    )


def reports(record: Record) -> list[Epicrisis]:
    """Every epicrisis report of the patient, newest first."""
    return [_parse(document) for document in record.documents if document.kind == "epicrisis"]


def index_line(report: Epicrisis) -> str:
    if not report.readable:
        return f"{day_text(report.when)}: {report.title}. Fields not readable; read_epicrisis for the text [{report.ref}]"
    return (
        f"{day_text(report.first_day)} to {day_text(report.last_day)}, {report.service}: {report.title}. "
        f"Discharge diagnoses: {'; '.join(report.diagnoses) or 'none'}. "
        f"Procedure: {report.procedure or 'no procedure'}. "
        f"Complications: {'; '.join(report.complications) or 'none'}. "
        f"Condition at discharge: {report.outcome or 'not recorded'} [{report.ref}]"
    )


def _span(items: list[Epicrisis]) -> str:
    return f"admissions from {day_text(min(item.first_day for item in items))} to {day_text(max(item.last_day for item in items))}"


def _block(report: Epicrisis) -> str:
    if report.readable:
        head = f"[{report.ref}] Epicrisis report: {report.title}, {day_text(report.first_day)} to {day_text(report.last_day)}, {report.service}"
    else:
        head = f"[{report.ref}] Epicrisis report: {report.title}, {day_text(report.when)}"
    return f"{head}\n{report.text.strip()}"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def read_all(record: Record, limit: int = MAX_CHARS) -> list[str]:
    """The tool's blocks: a summary, then every report in full, newest first. Over `limit` characters of reports,
    whole reports are left out from the oldest end (the newest is always given) and a last block says which."""
    found = reports(record)
    if not found:
        return [NONE_ON_FILE]
    blocks, used = [], 0
    for report in found:
        block = _block(report)
        if blocks and used + len(block) > limit:
            break
        blocks.append(block)
        used += len(block)
    summary = f"{_count(len(found), 'epicrisis report')}, {_span(found)}."
    left_out = found[len(blocks):]
    if left_out:
        were = "was" if len(left_out) == 1 else "were"
        blocks.append(f"{_count(len(left_out), 'older report')} {were} left out ({_span(left_out)}).")
    return [summary, *blocks]


# Which questions are about the patient's past, which the reports answer. Each pattern is matched against the
# lower-cased question; a word that also asks about results, medicines or orders ("previous", "last", "prior HbA1c")
# is not here. Questions about which operations the patient has had are answered from SURGICAL HISTORY, so a question
# that names an operation (OPERATIONS) is about the past only through a word of PAST_EVENTS.
PAST_EVENTS = tuple(re.compile(pattern) for pattern in (
    # English
    r"\b(admitted|admissions?|hospitali[sz](ed|ations?)|hospital stays?)\b",  # stays in hospital
    r"\bcomplications?\b",  # what went wrong
    r"\bafter (an? |the |any |his |her )?(procedure|operation|surgery)",  # events after a procedure or operation
    r"\b(an(a)?esthe\w*|intubat\w*|airway)\b",  # anaesthesia
    r"\b(need|should|must) to know\b|\bshould know\b",  # "anything I should know about ..."
    # Turkish
    r"\byat(ış\w*|tı\w*|mış\w*)",  # yatış, yattı, yatmış: admitted
    r"\bkomplikasyon\w*",  # complication
    r"\b(işlem|ameliyat)\w* sonra",  # after a procedure or operation
    r"\b(anestezi\w*|entübasyon\w*)",  # anaesthesia
    r"\bbilmem gereken\b",  # "what I need to know"
))
# Asks about the past too, unless the question names an operation.
PAST_WORDS = tuple(re.compile(pattern) for pattern in (
    r"\bprocedures?\b",  # English: a procedure
    r"\bever\b",  # English: "has he ever ..."
    r"\bişlem\w*",  # Turkish: a procedure
    r"\bgeçir(di|miş)\w*",  # Turkish: "inme geçirdi mi", had (an illness)
    r"\bdaha önce\b",  # Turkish: before, previously ("daha önceki" is left out: "the previous value")
))
# An operation, or a surgical specialty ("hepatobiliary surgery", "genel cerrahi").
OPERATIONS = re.compile(r"\b(operations?|operated|surger(y|ies)|surgical|ameliyat\w*|operasyon\w*|cerrahi\w*)")


def about_the_past(question: str) -> bool:
    """True when the question asks about the patient's past: earlier admissions, complications, anaesthesia, events
    after a procedure, "has he ever ...", "anything I should know about ...", in English or Turkish. Not for a
    question about which operations the patient has had (SURGICAL HISTORY answers those)."""
    text = question.lower()
    if any(pattern.search(text) for pattern in PAST_EVENTS):
        return True
    return not OPERATIONS.search(text) and any(pattern.search(text) for pattern in PAST_WORDS)


def index_section(record: Record, *, full: bool = False) -> str:
    """The EPICRISIS REPORTS section of the chart index: a line per report, or (`full`) every report as the tool gives it."""
    found = reports(record)
    if full:
        return FULL_TITLE + "\n" + ("\n\n".join(read_all(record)[1:]) if found else "- none on file")
    return INDEX_TITLE + "\n" + "\n".join(f"- {line}" for line in [index_line(report) for report in found] or ["none on file"])
