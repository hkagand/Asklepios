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


# Words a sentence does not end after ("Dr. Kerem Yalçın").
ABBREVIATIONS = ("dr", "mr", "mrs", "ms", "prof", "st", "vs", "e.g", "i.e", "approx", "no")


def first_sentence(text: str) -> str:
    """The text up to the end of its first sentence, or an earlier semicolon or colon that starts the details,
    without the stop: "Transient hypocalcaemia from day 1: corrected calcium ..." -> "Transient hypocalcaemia from
    day 1"."""
    for found in re.finditer(r"[.!?](?=\s+[A-Z(])|[;:](?=\s)", text):
        word = re.split(r"\s", text[: found.start()])[-1].lower()
        if word not in ABBREVIATIONS:
            return _clean(text[: found.start()])
    return _clean(text)


def _clean(text: str) -> str:
    """On one line, without a stop at the end, so a line can add its own."""
    return " ".join(text.split()).rstrip(" .;:,")


LINE_LIMIT = 600  # characters of an index line, past which its diagnoses are given by name only
# A pointer to another heading of the report: "(see COMPLICATIONS DURING ADMISSION)".
POINTER = re.compile(r"\s*\(see [A-Z][A-Z -]+\)")


def index_line(report: Epicrisis) -> str:
    """One line per report: its dates, service, title, the first sentence of each discharge diagnosis, the procedure,
    the first sentence of each distinct complication, and the condition at discharge. The rest is in the full report."""
    if not report.readable:
        return f"{day_text(report.when)}: {_clean(report.title)}. Fields not readable; read_epicrisis for the text [{report.ref}]"
    service = f", {report.service}" if report.service else ""
    # A complication that points to COMPLICATIONS DURING ADMISSION repeats that field's.
    heads = [first_sentence(item) for item in report.complications]
    own = [head for head in heads if "(see COMPLICATIONS DURING ADMISSION)" not in head] or heads
    complications = "; ".join(dict.fromkeys(POINTER.sub("", head) for head in own)) or "none"

    def line(diagnoses: list[str]) -> str:
        return (
            f"{day_text(report.first_day)} to {day_text(report.last_day)}{service}: {_clean(report.title)}. "
            f"Discharge diagnoses: {'; '.join(diagnoses) or 'none'}. "
            f"Procedure: {_clean(report.procedure or '') or 'no procedure'}. "
            f"Complications: {complications}. "
            f"Condition at discharge: {_clean(report.outcome) or 'not recorded'} [{report.ref}]"
        )

    # A long line names each diagnosis without its qualifiers ("Duodenal ulcer with haemorrhage, posterior bulb, ..."),
    # and if still too long, without a closing remark in brackets too.
    named = [first_sentence(item).split(", ")[0] for item in report.diagnoses]
    for diagnoses in ([first_sentence(item) for item in report.diagnoses], named):
        if len(text := line(diagnoses)) <= LINE_LIMIT:
            return text
    return line([re.sub(r"(?<=\S)\s*\([^()]*\)$", "", item) for item in named])


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
        given = "the newest report is" if len(blocks) == 1 else f"the newest {len(blocks)} reports are"
        summary = f"{summary[:-1]}; {given} given below."
        were = "was" if len(left_out) == 1 else "were"
        blocks.append(f"{_count(len(left_out), 'older report')} {were} left out ({_span(left_out)}).")
    return [summary, *blocks]


# Which questions are about the patient's past, which the reports answer. Each pattern is matched against the question
# as lower() leaves it after "İ" is made "i", so a Turkish "ı" may also be written "i" (from a capital "I"): patterns
# match both. A word that also asks about results, medicines or orders ("previous", "last", "prior HbA1c") is not here.
# Questions about which operations the patient has had are answered from SURGICAL HISTORY, so a question that names an
# operation (OPERATIONS) is about the past only through PAST_EVENTS.

# The past, an operation, a procedure or anaesthesia: what ties a general word ("complications", "a biopsy") to the past.
PAST_CONTEXT = (
    r"(\b(previous\w*|prior|earlier|past|before|ever|history|after|operations?|operated|surger(y|ies)|surgical|procedures?"
    r"|an(a)?esthe\w*|admi(tted|ssions?)|hospital\w*)\b|\b(önce\w*|geçmiş\w*|sonra\w*|ameliyat\w*|operasyon\w*|işlem\w*"
    r"|anestezi\w*|yat[ıi]\w*|geçir\w*|h[ıi]ç)\b)"
)
PAST_EVENTS = tuple(re.compile(pattern) for pattern in (
    # English
    r"\b(admitted|admissions?|hospitali[sz](ed|ations?)|hospital stays?)\b",  # stays in hospital
    # "has she been in hospital before", "was she in hospital last year"; not "is she in hospital now?"
    r"^(?!(is|are)\b)(?!.*\b(now|currently|today)\b).*\bin (the |a )?hospital\b",
    r"(?<!family )\bhistory of\b",  # "any history of bleeding?"; not the family's
    r"\btransfus\w*",  # a transfusion
    # What a diagnostic procedure found: "what did the colonoscopy find?"
    r"\b(colonoscop|sigmoidoscop|gastroscop|endoscop|bronchoscop|cystoscop|biops|angiogra|aspiration)\w*\b.*\b(find|found|show|showed|shown)\b",
    r"\bafter (an? |the |any |his |her )?(procedure|operation|surgery)",  # events after a procedure or operation
    r"\b(an(a)?esthe\w*|intubat\w*|difficult airway)\b",  # anaesthesia
    r"\b(need|should|must)( i| we)? (to )?know\b",  # "anything I should know about ...", "what should I know"
    r"\b(should|need to|must) be aware of\b",  # "anything I should be aware of"
    r"\bpast (medical )?history\b",
    # Turkish
    r"\byat([ıi]ş\w*|t[ıi]\w*|m[ıi]ş\w*|[ıi]r\w*)",  # yatış, yattı, yatmış, yatırıldı: admitted
    r"\b(işlem|ameliyat)\w* sonra",  # after a procedure or operation
    r"\b(anestezi\w*|entübasyon\w*)",  # anaesthesia
    r"\bbilme(m|miz) gereken\b",  # "what I (we) need to know"
    # Complications, the airway, a procedure or a biopsy, each with the past, an operation, a procedure or
    # anaesthesia somewhere in the question: not "any diabetic complications?", "when is her procedure scheduled?".
    rf"\b(complications?|airway|procedures?|biops\w*|komplikasyon\w*|biyopsi\w*)\b(?=.*{PAST_CONTEXT})",
    rf"{PAST_CONTEXT}.*\b(complications?|airway|procedures?|biops\w*|komplikasyon\w*|biyopsi\w*)",
))
# Asks about the past too, unless the question names an operation, a result or a medicine ("has her potassium ever
# been high?", "daha önce hangi ilaçları kullandı?": the chart's results and medicines answer those).
PAST_WORDS = tuple(re.compile(pattern) for pattern in (
    r"\bever\b",  # English: "has he ever ..."
    r"\bgeçir(di|miş)\w*",  # Turkish: "inme geçirdi mi", had (an illness)
    r"\bdaha önce\b",  # Turkish: before, previously ("daha önceki" is left out: "the previous value")
))
# An operation, or a surgical specialty ("hepatobiliary surgery", "genel cerrahi").
OPERATIONS = re.compile(r"\b(operations?|operated|surger(y|ies)|surgical|ameliyat\w*|operasyon\w*|cerrahi\w*)")
# A result or a medicine.
RESULTS_OR_MEDICINES = re.compile(
    r"\b(results?|values?|levels?|tests?|labs?|readings?|high|low|elevated|raised|above|below|normal|abnormal|hba1c|a1c"
    r"|tsh|e?gfr|potassium|sodium|creatinine|glucose|sugar|cholesterol|ldl|hdl|ha?emoglobin|inr|ferritin|blood pressure"
    r"|take|takes|taken|taking|took|medicines?|medications?|drugs?|doses?|dosage|prescribed|prescriptions?|pills?|tablets?)\b"
    r"|\b(sonuç\w*|değer\w*|düzey\w*|seviye\w*|yüksek\w*|düşük\w*|kaç|potasyum\w*|sodyum\w*|kreatinin\w*|glukoz\w*"
    r"|şeker\w*|kolesterol\w*|hemoglobin\w*|[ıi]laç\w*|kullan\w*|doz\w*|reçete\w*)"
)


def about_the_past(question: str) -> bool:
    """True when the question asks about the patient's past: earlier admissions, complications, anaesthesia, events
    after a procedure, "has he ever ...", "anything I should know about ...", in English or Turkish. Not for a
    question about which operations the patient has had (SURGICAL HISTORY answers those), nor about results, medicines
    or orders."""
    text = question.replace("İ", "i").lower()
    if any(pattern.search(text) for pattern in PAST_EVENTS):
        return True
    if OPERATIONS.search(text) or RESULTS_OR_MEDICINES.search(text):
        return False
    return any(pattern.search(text) for pattern in PAST_WORDS)


def index_section(record: Record, *, full: bool = False) -> str:
    """The EPICRISIS REPORTS section of the chart index: a line per report, or (`full`) every report as the tool gives it."""
    found = reports(record)
    if full:
        return FULL_TITLE + "\n" + ("\n\n".join(read_all(record)[1:]) if found else "- none on file")
    return INDEX_TITLE + "\n" + "\n".join(f"- {line}" for line in [index_line(report) for report in found] or ["none on file"])
