"""Open loops: what each clinician's latest note planned, matched against what the record shows happened since.

The model has only extracted the plan items (plans.py). Everything here is plain code: due dates, matching against
orders, results, appointments, visits and medication orders, and the status of each item.

Statuses, worst first
  missing        the due date has passed and nothing was ordered, booked or resulted
  dose_mismatch  a medication was ordered as planned, but at a different dose from the one in the plan
  overdue        ordered or booked, the due date has passed and there is no result
  to_review      the result is on file but no clinician has reviewed it
  not_ordered    nothing ordered or booked yet, and the due date has not passed or none was given
  no_trace       a kind the record cannot show, such as a phone call or a meeting, and nothing was found
  to_inform      reviewed, but nothing records that the patient was told
  pending        ordered or booked and not yet due (or the result is still preliminary)
  conditional    only to be done if something happens
  done           the visit or change is on file; for a test or scan, the result was reviewed and the patient told

A test or scan is tracked through five stages: ordered (the order), performed (sample taken or scan done), resulted
(final result issued), reviewed (a clinician's review mark, marks.py) and communicated (a mark that the patient was
told). A later visit note that quotes the result by date counts for both of the last two, marked as inferred.
"""

from __future__ import annotations

import asyncio
import calendar
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from .llm import LlmError
from .marks import marks_of
from .plans import PlanExtractor, PlanItem, plain
from .record import EARLIEST, Document, Record, code_of, day_text, moment, ref_of, text_of
from .tools import fold

STATUSES = (
    "missing", "dose_mismatch", "overdue", "to_review", "not_ordered", "no_trace", "to_inform", "pending", "conditional",
    "done",
)
OPEN = ("missing", "dose_mismatch", "overdue", "to_review", "not_ordered", "no_trace", "to_inform")
FINAL = ("final", "amended", "corrected", "appended")
TRACKED = ("lab", "imaging", "procedure", "referral", "visit", "contact", "meeting", "medication", "conditional")

# Test families: the words that name them in notes and order names, and the LOINC codes of the results that show
# they were done. A comprehensive metabolic panel also covers a basic one.
LAB_TESTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "cbc": (("cbc", "fbc", "complete blood count", "full blood count", "blood count"), ("718-7", "6690-2", "777-3")),
    "bmp": (
        ("basic metabolic panel", "bmp", "electrolytes", "renal function", "kidney function", "urea and electrolytes", "potassium", "creatinine", "egfr"),
        ("2160-0", "2823-3", "2951-2"),
    ),
    "cmp": (
        (
            "comprehensive metabolic panel", "cmp", "liver function", "liver enzymes", "liver tests", "liver blood tests", "lfts", "lft",
            "alt", "ast", "alp", "alkaline phosphatase", "transaminases", "bilirubin",
        ),
        ("1742-6", "1920-8", "6768-6"),
    ),
    "a1c": (("hba1c", "a1c", "hemoglobin a1c", "glycated hemoglobin"), ("4548-4",)),
    "lipids": (("lipid panel", "lipid profile", "lipids", "cholesterol", "ldl"), ("2093-3", "13457-7", "2085-9", "2571-8")),
    "thyroid": (("thyroid function", "tsh", "free t4", "ft4"), ("3016-3", "3024-7")),
    "tpo": (("anti-tpo", "tpo antibodies", "thyroid antibodies"), ("8099-4",)),
    "uacr": (("urine albumin/creatinine ratio", "albumin/creatinine ratio", "uacr", "urine acr", "acr"), ("9318-7",)),
    "ferritin": (("ferritin", "iron studies"), ("2276-4",)),
    "ntprobnp": (("nt-probnp", "ntprobnp", "bnp"), ("33762-6",)),
    "cea": (("cea", "carcinoembryonic antigen"), ("2039-6",)),
    "magnesium": (("magnesium",), ("19123-9",)),
}
COVERS = {"cmp": {"bmp"}}
STUDIES: dict[str, tuple[str, ...]] = {
    "ct": ("ct", "computed tomography"),
    "mri": ("mri", "magnetic resonance"),
    "echo": ("echocardiogram", "echocardiography", "echo"),
    "ultrasound": ("ultrasound", "sonography"),
    "xray": ("x-ray", "xray", "radiograph"),
    "colonoscopy": ("colonoscopy",),
    "endoscopy": ("endoscopy", "gastroscopy"),
    "biopsy": ("biopsy",),
}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "ten": 10, "twelve": 12, "a": 1}
# Words notes use for a drug, besides its name on the order.
DRUG_WORDS = {
    "iron": ("ferrous", "iron"),
    "leucovorin": ("folinate", "leucovorin"),
    "folinic": ("folinate",),
    "folfox": ("oxaliplatin", "fluorouracil", "folinate"),
}
# A medication change counts as made if the order changes between these offsets from the note and the due date.
MEDICATION_WINDOW = (timedelta(days=-2), timedelta(days=14))
# A call or meeting is matched only by a visit or appointment this close to its due date.
CONTACT_WINDOW = timedelta(days=7)
ORDER_KINDS = {"108252007": "lab", "363679005": "imaging", "3457005": "referral", "103693007": "procedure"}


@dataclass
class Part:
    name: str
    status: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    # For a test or scan: ordered, performed, resulted, reviewed, communicated (see Matcher.stages), and the report a
    # review or communication mark should point at.
    stages: list[dict] = field(default_factory=list)
    target: str | None = None


@dataclass
class Loop:
    """A plan item from a note; an order still open that no current plan item covers (source "order"); or a result
    since the last visit that no plan item covers (source "result")."""

    note: Document | None
    item: PlanItem
    status: str
    due: date | None
    detail: str
    evidence: list[str]
    parts: list[Part] = field(default_factory=list)
    source: str = "plan"
    stages: list[dict] = field(default_factory=list)
    target: str | None = None

    @property
    def line(self) -> str:
        """The whole note line the quote comes from ("then stop" alone says little), or the order name."""
        if self.note is None:
            return self.item.quote
        quote = plain(self.item.quote)
        for line in self.note.text.splitlines():
            if quote in plain(line):
                return re.sub(r"^([-•*]|\d{1,2}[.)])\s+", "", line.strip())
        return self.item.quote

    def as_json(self) -> dict:
        return {
            "source": self.source,
            "stages": self.stages,
            "target": self.target,
            "note": self.note.ref if self.note else None,
            "noteDate": self.note.when.date().isoformat() if self.note else None,
            "author": self.note.author if self.note else None,
            "quote": self.item.quote,
            "line": self.line,
            "kind": self.item.kind,
            "status": self.status,
            "due": self.due.isoformat() if self.due else None,
            "detail": self.detail,
            "evidence": self.evidence,
            "parts": [part.__dict__ for part in self.parts],
        }


def says(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(fold(phrase))}(?![a-z0-9])", fold(text)))


def worst(statuses: list[str]) -> str:
    return min(statuses, key=STATUSES.index)


def latest_notes(record: Record) -> list[Document]:
    """Each clinician's most recent note: a later note by the same clinician takes over the earlier plan."""
    latest: dict[str, Document] = {}
    for document in record.documents:
        if document.kind == "note" and document.when.date() <= record.today:
            key = document.author or document.ref
            if key not in latest or document.when > latest[key].when:
                latest[key] = document
    return sorted(latest.values(), key=lambda document: document.when, reverse=True)


# ------------------------------------------------------------------------- dates

def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_end(start: date, text: str) -> date | None:
    """The end of "3 months", "6-8 weeks", "about a year" from `start`; the longer bound of a range."""
    words = fold(text).replace("–", "-")
    found = re.search(r"(\d+|[a-z]+)(?:\s*(?:-|to)\s*(\d+|[a-z]+))?\s*(day|week|month|year)s?", words)
    if not found:
        return None
    amounts = [NUMBERS.get(value, None) if not value.isdigit() else int(value) for value in found.groups()[:2] if value]
    amount = max((value for value in amounts if value), default=None)
    if amount is None:
        return None
    unit = found.group(3)
    if unit == "day":
        return start + timedelta(days=amount)
    if unit == "week":
        return start + timedelta(weeks=amount)
    return add_months(start, amount * (12 if unit == "year" else 1))


def due_date(record: Record, note: Document, item: PlanItem) -> date | None:
    written = note.when.date()
    if item.due_type == "date" and item.due_value:
        try:
            return date.fromisoformat(item.due_value[:10])
        except ValueError:
            return None
    if item.due_type == "within" and item.due_value:
        return period_end(written, item.due_value)
    if item.due_type == "before_next_visit":
        return next_visit(record, note)
    if item.due_type == "with_next_bloods":
        draws = sorted({point.when.date() for points in record.points.values() for _, point in points if point.when.date() > written})
        return draws[0] if draws else None
    return None


def next_visit(record: Record, note: Document) -> date | None:
    """The first visit or booked appointment after the note, preferring the same clinician."""
    written = note.when.date()
    visits = []
    for encounter in record.encounters:
        start = record.encounter_start(encounter)
        if start and start.date() > written:
            clinician = (encounter.get("participant") or [{}])[0].get("individual", {}).get("display", "")
            visits.append((clinician != note.author, start.date()))
    for appointment in record.appointments:
        start = moment(appointment.get("start"))
        if start and start.date() > written and appointment.get("status") in ("booked", "arrived", "fulfilled"):
            clinicians = [participant.get("actor", {}).get("display", "") for participant in appointment.get("participant", [])]
            visits.append((note.author not in clinicians, start.date()))
    return min(visits)[1] if visits else None


# ---------------------------------------------------------------------- matching

def test_families(name: str) -> list[str]:
    """Lab families a test name refers to; a word inside a longer match does not count ("creatinine" in "urine
    albumin/creatinine ratio")."""
    matched = [(key, word) for key, (words, _) in LAB_TESTS.items() for word in words if says(name, word)]
    kept = [key for key, word in matched if not any(word != other and word in other for _, other in matched)]
    return list(dict.fromkeys(kept))


def generic_bloods(name: str) -> bool:
    """"Bloods", "blood tests", "labs": a lab plan that names no test."""
    return not test_families(name) and not study_families(name) and bool(re.search(r"blood|\blabs?\b", fold(name)))


def covered_by(order_name: str) -> set[str]:
    """The test families an order covers, e.g. a comprehensive metabolic panel also covers a basic one."""
    families = set(test_families(order_name))
    return families | {covered for family in families for covered in COVERS.get(family, ())}


def study_families(name: str) -> list[str]:
    return [key for key, words in STUDIES.items() if any(says(name, word) for word in words)]


class Matcher:
    def __init__(self, record: Record) -> None:
        self.record = record
        self.today = record.today
        self.marks = marks_of(record)
        # Observation -> the report it belongs to, so a review of either counts for both.
        self.report_for: dict[str, str] = {}
        for resource in record.resources.values():
            if resource["resourceType"] == "DiagnosticReport":
                for result in resource.get("result", []):
                    self.report_for[result.get("reference", "")] = ref_of(resource)

    # ------------------------------------------------------------------ stages

    def noted(self, performed: datetime | None, issued: datetime | None) -> Document | None:
        """The first note written after the result that quotes its date ("Labs 15 Sep 2026: ..."), if any."""
        if performed is None:
            return None
        day = day_text(performed.date())
        notes = sorted((document for document in self.record.documents if document.kind == "note"), key=lambda document: document.when)
        return next(
            (note for note in notes if note.when > (issued or performed) and note.when.date() <= self.today and day in note.text),
            None,
        )

    def stages(self, report_ref: str, order_ref: str | None = None) -> tuple[str, list[dict], str]:
        """For a result on file: its status, its five stages and a one-line summary of where it stands."""
        report = self.record.resources[report_ref]
        performed = moment(report.get("effectiveDateTime"))
        issued = moment(report.get("issued")) or performed
        final = report.get("status", "final") in FINAL
        if order_ref is None:
            based = [item.get("reference") for item in report.get("basedOn", [])]
            order_ref = next((ref for ref in based if ref in self.record.resources), None)
        order = self.record.resources.get(order_ref) if order_ref else None
        related = {report_ref, *(item.get("reference") for item in report.get("result", []))} | ({order_ref} if order_ref else set())
        review = next((mark for mark in self.marks if mark.kind == "review" and related & set(mark.about)), None)
        told = next((mark for mark in self.marks if mark.kind == "communication" and related & set(mark.about)), None)
        noted = self.noted(performed, issued)
        discussed = noted if noted and noted.encounter else None

        def stage(name: str, done: bool, at: datetime | None, refs: list[str], by: str | None = None, *, inferred: bool = False, note: str | None = None) -> dict:
            return {"stage": name, "done": done, "at": at.date().isoformat() if at else None, "by": by, "refs": refs, "inferred": inferred, "note": note}

        ordered_at = moment(order.get("authoredOn")) if order else None
        steps = [
            stage("ordered", order is not None, ordered_at, [order_ref] if order else [], note=None if order else "no order on file"),
            stage("performed", performed is not None, performed, [report_ref]),
            stage("resulted", final, issued, [report_ref], note=None if final else f"result {report.get('status', 'not final')}"),
        ]
        if review:
            steps.append(stage("reviewed", True, review.at, [review.id], review.by_name, note=review.note))
        elif noted:
            steps.append(stage("reviewed", True, noted.when, [noted.ref], noted.author, inferred=True, note=f"quoted in {noted.title}"))
        else:
            steps.append(stage("reviewed", False, None, []))
        if told:
            steps.append(stage("communicated", True, told.at, [told.id], told.by_name, note=told.medium))
        elif discussed:
            steps.append(stage("communicated", True, discussed.when, [discussed.ref], discussed.author, inferred=True, note="discussed at the visit"))
        else:
            steps.append(stage("communicated", False, None, []))

        def said(step: dict, verb: str) -> str:
            when = day_text(date.fromisoformat(step["at"])) if step["at"] else ""
            if step["inferred"]:
                return f"{verb} at the visit on {when} (from the note)"
            how = f" by {step['note']}" if step["stage"] == "communicated" and step["note"] else ""
            return f"{verb}{how} by {step['by']} {when}"

        resulted = f"resulted {day_text(issued.date())}" if issued else "resulted"
        review_step, told_step = steps[3], steps[4]
        if not final:
            return "pending", steps, f"performed, result {report.get('status', 'not final')}"
        if not review_step["done"]:
            return "to_review", steps, f"{resulted}, not yet reviewed"
        if not told_step["done"]:
            return "to_inform", steps, f"{resulted}; {said(review_step, 'reviewed')}; nothing records that the patient was told"
        if review_step["inferred"] and told_step["inferred"]:
            return "done", steps, f"{resulted}; discussed at the visit on {told_step['at'] and day_text(date.fromisoformat(told_step['at']))}"
        return "done", steps, f"{resulted}; {said(review_step, 'reviewed')}; {said(told_step, 'patient told')}"

    def order_steps(self, order: dict) -> list[dict]:
        """The stages of an order with no result yet: only "ordered" is done."""
        ordered = moment(order.get("authoredOn"))
        first = {"stage": "ordered", "done": True, "at": ordered.date().isoformat() if ordered else None, "by": order.get("requester", {}).get("display"), "refs": [ref_of(order)], "inferred": False, "note": None}
        rest = [{"stage": name, "done": False, "at": None, "by": None, "refs": [], "inferred": False, "note": None} for name in ("performed", "resulted", "reviewed", "communicated")]
        return [first, *rest]

    def result_part(self, name: str, result_ref: str, order_ref: str | None = None) -> Part:
        report = self.report_for.get(result_ref, result_ref)
        status, steps, summary = self.stages(report, order_ref)
        return Part(name, status, summary, [result_ref], steps, report)

    def order_part(self, name: str, order: dict, due: date | None) -> Part:
        """An order matched to a plan item: through its result if it has one, else where the order stands."""
        results = self.record.results_for.get(ref_of(order), [])
        if results:
            return self.result_part(name, results[0], ref_of(order))
        status, detail, _ = self.order_state(order, due)
        steps = self.order_steps(order) if order_kind(order) in ("lab", "imaging", "procedure") else []
        return Part(name, status, detail, [ref_of(order)], steps)

    def new_results(self, covered: set[str]) -> list[Loop]:
        """Reports issued since the last visit that no plan item or order covers."""
        visits = [start.date() for encounter in self.record.encounters if (start := self.record.encounter_start(encounter)) and start.date() <= self.today]
        since = max(visits, default=None)
        found = []
        for ref, resource in self.record.resources.items():
            if resource["resourceType"] != "DiagnosticReport" or ref in covered:
                continue
            issued = moment(resource.get("issued") or resource.get("effectiveDateTime"))
            if issued is None or issued.date() > self.today or (since and issued.date() <= since):
                continue
            part = self.result_part(self.record.label(ref), ref)
            kind = "lab" if ref not in self.record.document_by_ref else "imaging"
            item = PlanItem(self.record.label(ref), kind, (), None, None, None, "none", None)
            found.append(Loop(None, item, part.status, None, part.detail, [ref], [], "result", part.stages, ref))
        return found

    def orders_after(self, written: date) -> list[dict]:
        return [order for order in self.record.orders if (moment(order.get("authoredOn")) or EARLIEST).date() >= written]

    def order_state(self, order: dict, due: date | None) -> tuple[str, str, date | None]:
        """Status of an order that exists, with a detail line and the due date that applies."""
        ref = ref_of(order)
        results = self.record.results_for.get(ref, [])
        ordered = day_text((moment(order.get("authoredOn")) or EARLIEST).date())
        if results or order.get("status") == "completed":
            return "done", f"ordered {ordered}" + (f", result {self.record.label(results[0])}" if results else ", completed"), due
        if order.get("status") in ("revoked", "entered-in-error"):
            return "missing", f"ordered {ordered} but {order['status']}", due
        when = moment(order.get("occurrenceDateTime"))
        due = when.date() if when else due
        if due and due < self.today:
            return "overdue", f"ordered {ordered}, due {day_text(due)}, no result on file", due
        return "pending", f"ordered {ordered}" + (f", due {day_text(due)}" if due else ""), due

    def not_found(self, what: str, due: date | None) -> tuple[str, str]:
        if due and due < self.today:
            return "missing", f"no {what} on file; was due {day_text(due)}"
        return "not_ordered", f"no {what} on file yet" + (f"; due {day_text(due)}" if due else "")

    # ------------------------------------------------------------------ by kind

    def bloods(self, written: date, due: date | None) -> list[Part]:
        """A plan for "bloods" that names no test: the lab orders placed with or after the note, else any result."""
        orders = [order for order in self.orders_after(written) if order_kind(order) == "lab"]
        if orders:
            return [self.order_part(text_of(order.get("code")), order, due) for order in orders]
        results = sorted((point.when, ref) for ref, points in self.record.points.items() for _, point in points if written < point.when.date() <= self.today)
        if results:
            return [self.result_part("bloods", results[0][1])]
        status, detail = self.not_found("lab order or result", due)
        return [Part("bloods", status, detail)]

    def lab(self, name: str, written: date, due: date | None) -> Part:
        families = test_families(name)
        if not families:
            return self.study(name, written, due, kind="test")
        codes = {code for family in families for code in LAB_TESTS[family][1]}
        results = sorted(
            (point.when, ref)
            for ref, points in self.record.points.items()
            for series, point in points
            if series.code in codes and written < point.when.date() <= self.today
        )
        if results:
            return self.result_part(name, results[0][1])
        orders = [order for order in self.orders_after(written) if set(families) & covered_by(text_of(order.get("code")))]
        if orders:
            return self.order_part(name, orders[0], due)
        status, detail = self.not_found("order or result", due)
        return Part(name, status, detail)

    def study(self, name: str, written: date, due: date | None, *, kind: str = "study") -> Part:
        """Imaging, procedures and tests outside the lab families: matched by name against orders and reports."""
        families = study_families(name)

        def same(text: str) -> bool:
            if families:
                return bool(set(families) & set(study_families(text)))
            return says(text, name) or says(name, text)

        reports = [
            document
            for document in self.record.documents
            if document.kind == "report" and written < document.when.date() <= self.today and same(document.title)
        ]
        if reports:
            return self.result_part(name, min(reports, key=lambda document: document.when).ref)
        orders = [order for order in self.orders_after(written) if same(text_of(order.get("code")))]
        if orders:
            return self.order_part(name, orders[0], due)
        status, detail = self.not_found("order or report", due)
        return Part(name, status, detail)

    def referral(self, item: PlanItem, written: date, due: date | None) -> Part:
        service = item.service or item.quote
        words = [word for word in re.findall(r"[a-z]+", fold(service)) if len(word) >= 5 and word not in ("referral", "clinic", "review")]
        orders = [
            order
            for order in self.orders_after(written)
            if any(says(text_of(order.get("code")), word) for word in words)
        ]
        if orders:
            status, detail, _ = self.order_state(orders[0], due)
            return Part(service, status, detail, [ref_of(orders[0])])
        status, detail = self.not_found("referral", due)
        return Part(service, status, detail)

    def named_clinician(self, quote: str) -> str | None:
        """A clinician the plan line names by family name ("clinic with Dr. Kerem Yalçın"), from the record's visits."""
        names = {
            reference.get("display", "")
            for reference in [
                *(participant.get("individual", {}) for encounter in self.record.encounters for participant in encounter.get("participant", [])),
                *(participant.get("actor", {}) for appointment in self.record.appointments for participant in appointment.get("participant", [])),
            ]
            if reference.get("reference", "").startswith("Practitioner/") and reference.get("display")
        }
        return next((name for name in sorted(names) if len(name.split()[-1]) >= 3 and says(quote, name.split()[-1])), None)

    def visit(self, note: Document, item: PlanItem, written: date, due: date | None) -> Part:
        clinician = self.named_clinician(item.quote) or note.author
        name = f"visit with {clinician}" if clinician else "follow-up visit"
        for encounter in sorted(self.record.encounters, key=lambda entry: self.record.encounter_start(entry) or EARLIEST):
            start = self.record.encounter_start(encounter)
            seen_by = (encounter.get("participant") or [{}])[0].get("individual", {}).get("display", "")
            if start and written < start.date() <= self.today and (not clinician or seen_by == clinician):
                return Part(name, "done", f"seen {day_text(start.date())}", [ref_of(encounter)])
        for appointment in self.record.appointments:
            start = moment(appointment.get("start"))
            clinicians = [participant.get("actor", {}).get("display", "") for participant in appointment.get("participant", [])]
            if start and start.date() > written and appointment.get("status") == "booked" and (not clinician or clinician in clinicians):
                if start.date() < self.today:
                    return Part(name, "overdue", f"booked for {day_text(start.date())}, no visit on file", [ref_of(appointment)])
                return Part(name, "pending", f"booked for {day_text(start.date())}", [ref_of(appointment)])
        status, detail = self.not_found("appointment or visit", due)
        return Part(name, status, detail)

    def untracked(self, item: PlanItem, written: date, due: date | None) -> Part:
        """Calls and meetings: found only if an appointment or visit near the due date names them."""
        service = item.service or item.quote
        words = [word for word in re.findall(r"[a-z]+", fold(service)) if len(word) >= 5]
        latest = due + CONTACT_WINDOW if due else date.max
        for appointment in self.record.appointments:
            start = moment(appointment.get("start"))
            text = " ".join([appointment.get("description", ""), *(text_of(kind) for kind in appointment.get("serviceType", []))])
            if start and written < start.date() <= latest and any(says(text, word) for word in words):
                status = "done" if start.date() < self.today else "pending"
                return Part(service, status, f"appointment {day_text(start.date())}", [ref_of(appointment)])
        return Part(service, "no_trace", f"the record has no {item.kind} entry to check this against")

    def medication(self, item: PlanItem, written: date, due: date | None) -> Part:
        drug = item.drug or item.quote
        names = {word for word in re.findall(r"[a-z]+", fold(drug)) if len(word) >= 4}
        names |= {synonym for word in names for synonym in DRUG_WORDS.get(word, ())}
        orders = [
            medication
            for medication in self.record.medications
            if any(says(text_of(medication.get("medicationCodeableConcept")), name) for name in names)
        ]
        if not orders and item.action in ("stop", "hold"):
            # A class rather than a drug ("hold maintenance chemotherapy"): the drugs held or stopped around then.
            changed = self.changed_medications(item.action, written, due)
            if changed:
                names = ", ".join(
                    re.split(r"\s+(?=[\d(])", text_of(medication.get("medicationCodeableConcept")))[0] for medication in changed
                )
                return Part(drug, "done", f"{item.action} recorded for {names}", [ref_of(medication) for medication in changed])
        if not orders:
            return Part(drug, "no_trace", f"no medication order for {drug} on file")
        # From the note (most changes are made at the visit) to a little after the due date (a planned later stop).
        low, high = written + MEDICATION_WINDOW[0], max(due or written, written) + MEDICATION_WINDOW[1]
        if item.action in ("stop", "hold"):
            for medication in self.changed_medications(item.action, written, due, orders):
                _, end = self.record.medication_period(medication)
                return Part(drug, "done", f"{medication['status'].replace('-', ' ')}" + (f" {day_text(end)}" if end else ""), [ref_of(medication)])
        else:
            started = [
                (start, medication)
                for medication in orders
                if (start := self.record.medication_period(medication)[0]) and low <= start <= high
            ]
            planned = doses(item.dose or "")
            # A new order counts if it carries the planned dose; with no dose in the plan, any new order does.
            for start, medication in started:
                if not planned or planned[0] in ordered_doses(medication):
                    return Part(drug, "done", f"ordered from {day_text(start)}", [ref_of(medication)])
            if started:
                start, medication = started[0]
                written_as = first_dosage(medication) or text_of(medication.get("medicationCodeableConcept"))
                detail = f"ordered from {day_text(start)} as {written_as}; the plan says {item.dose}"
                return Part(drug, "dose_mismatch", detail, [ref_of(medication)])
        late = self.today > high
        verb = {"stop": "stop", "hold": "hold"}.get(item.action or "", "new order")
        detail = f"no {verb} recorded for {drug}" + (f"; was due {day_text(due)}" if due else f" around {day_text(written)}")
        return Part(drug, "missing" if late else "not_ordered", detail, [ref_of(orders[0])])

    def changed_medications(self, action: str, written: date, due: date | None, among: list[dict] | None = None) -> list[dict]:
        """Medication orders stopped (or put on hold) between the note and a little after the due date. An order on
        hold has no end date, so any order on hold counts."""
        wanted = {"stop": ("stopped", "completed", "cancelled", "entered-in-error"), "hold": ("on-hold",)}[action]
        low, high = written + MEDICATION_WINDOW[0], max(due or written, written) + MEDICATION_WINDOW[1]
        changed = []
        for medication in self.record.medications if among is None else among:
            _, end = self.record.medication_period(medication)
            if medication.get("status") in wanted and ((end is None and action == "hold") or (end and low <= end <= high)):
                changed.append(medication)
        return changed

    def open_order(self, order: dict) -> Loop:
        """An active order that no current plan item covers, e.g. a referral from an earlier visit."""
        when = moment(order.get("occurrenceDateTime"))
        status, detail, due = self.order_state(order, when.date() if when else None)
        if status == "pending" and not due:
            detail += ", no due date"
        requester = order.get("requester", {}).get("display")
        item = PlanItem(text_of(order.get("code")), order_kind(order), (), None, None, None, "none", None)
        steps = self.order_steps(order) if order_kind(order) in ("lab", "imaging", "procedure") else []
        detail += f" by {requester}" if requester else ""
        return Loop(None, item, status, due, detail, [ref_of(order)], [], "order", steps)

    # ------------------------------------------------------------------- items

    def loop(self, note: Document, item: PlanItem) -> Loop | None:
        if item.kind not in TRACKED or (item.kind == "medication" and item.action in (None, "continue")):
            return None
        written = note.when.date()
        due = due_date(self.record, note, item)
        if item.kind == "conditional":
            return Loop(note, item, "conditional", due, "only if the stated condition arises", [])
        if item.kind == "lab":
            named = [name for name in item.tests if not generic_bloods(name)]
            parts = [self.lab(name, written, due) for name in named] if named else self.bloods(written, due)
        elif item.kind in ("imaging", "procedure"):
            parts = [self.study(name, written, due) for name in item.tests or (item.quote,)]
        elif item.kind == "referral":
            parts = [self.referral(item, written, due)]
        elif item.kind == "visit":
            parts = [self.visit(note, item, written, due)]
        elif item.kind == "medication":
            parts = [self.medication(item, written, due)]
        else:
            parts = [self.untracked(item, written, due)]
        parts = merge(parts)
        status = worst([part.status for part in parts])
        detail = "; ".join(f"{part.name}: {part.detail}" if len(parts) > 1 else part.detail for part in parts)
        evidence = list(dict.fromkeys(ref for part in parts for ref in part.evidence))
        if len(parts) > 1:
            return Loop(note, item, status, due, detail, evidence, parts)
        return Loop(note, item, status, due, detail, evidence, [], "plan", parts[0].stages, parts[0].target)


DOSE = re.compile(
    r"(\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)\s*(mg/m²|mg/m2|mg/kg|micrograms?|mcg|µg|ug|mg|g|units?|iu|ml)(?![a-z])",
    re.IGNORECASE,
)
DOSE_UNITS = {"mg/m2": "mg/m²", "microgram": "mcg", "micrograms": "mcg", "µg": "mcg", "ug": "mcg", "unit": "units", "iu": "units"}


def doses(text: str) -> list[str]:
    """Doses in the order written, one way: "80 mg", "49/51 mg", "75 mcg", "65 mg/m²"."""
    found = []
    for amount, unit in DOSE.findall(text):
        numbers = [f"{float(part.replace(',', '.')):g}" for part in re.split(r"\s*/\s*", amount)]
        unit = unit.lower()
        found.append(f"{'/'.join(numbers)} {DOSE_UNITS.get(unit, unit)}")
    return found


def first_dosage(medication: dict) -> str:
    return ((medication.get("dosageInstruction") or [{}])[0].get("text") or "").strip()


def ordered_doses(medication: dict) -> list[str]:
    """The doses an order's instructions give; the tablet strength in its name only when the instructions give none."""
    return doses(first_dosage(medication)) or doses(text_of(medication.get("medicationCodeableConcept")))


def order_kind(order: dict) -> str:
    return ORDER_KINDS.get(code_of((order.get("category") or [{}])[0]) or "", "procedure")


def merge(parts: list[Part]) -> list[Part]:
    """Parts that rest on the same evidence with the same outcome, e.g. "CT chest" and "CT abdomen" on one order."""
    merged: list[Part] = []
    for part in parts:
        same = next((other for other in merged if part.evidence and (other.status, other.detail, other.evidence) == (part.status, part.detail, part.evidence)), None)
        if same:
            same.name += f", {part.name}"
        else:
            merged.append(replace(part, evidence=list(part.evidence)))
    return merged


async def open_loops(record: Record, extractor: PlanExtractor) -> tuple[list[Loop], list[str]]:
    """Each clinician's latest plan checked against the record, plus open orders no plan item covers, worst first;
    and the notes whose plan could not be read."""
    notes = latest_notes(record)
    found = await asyncio.gather(*(extractor.items(note) for note in notes), return_exceptions=True)
    matcher = Matcher(record)
    loops, unread = [], []
    for note, items in zip(notes, found):
        if isinstance(items, LlmError):
            unread.append(note.ref)
            continue
        if isinstance(items, BaseException):
            raise items
        loops += [loop for item in items if (loop := matcher.loop(note, item))]
    covered = {ref for loop in loops for ref in loop.evidence}
    loops += [matcher.open_order(order) for order in record.open_orders() if ref_of(order) not in covered]
    covered |= {matcher.report_for.get(ref, ref) for ref in covered}
    covered |= {loop.target for loop in loops if loop.target} | {part.target for loop in loops for part in loop.parts if part.target}
    loops += matcher.new_results(covered)
    loops.sort(key=lambda loop: (STATUSES.index(loop.status), loop.due or date.max))
    return loops, unread


STATUS_TEXT = {
    "missing": "NOT DONE, due date passed",
    "dose_mismatch": "ORDERED AT A DIFFERENT DOSE from the plan",
    "overdue": "OVERDUE",
    "to_review": "RESULTED, NOT YET REVIEWED",
    "not_ordered": "Planned, nothing ordered yet",
    "no_trace": "Planned, no record to confirm it",
    "to_inform": "Reviewed, nothing records that the patient was told",
    "pending": "Ordered or booked",
    "conditional": "Only if needed",
    "done": "Done",
}


def loop_line(loop: Loop) -> str:
    if loop.note:
        about = f' ("{loop.item.quote}")' if loop.item.quote.rstrip(" .;,") != loop.line.rstrip(" .;,") else ""
        source = f'"{loop.line}"{about} ({loop.item.kind}), planned {day_text(loop.note.when.date())}'
        source += f" by {loop.note.author}" if loop.note.author else ""
    elif loop.source == "result":
        source = f"{loop.item.quote} (new result since the last visit)"
    else:
        source = f"{loop.item.quote} ({loop.item.kind} order not in a current plan)"
    refs = ", ".join([*([loop.note.ref] if loop.note else []), *loop.evidence])
    return f"{STATUS_TEXT[loop.status]}: {source}; {loop.detail} [{refs}]"


def index_section(loops: list[Loop], unread: list[str]) -> str:
    """The OPEN LOOPS section of the chart index: every item, worst first, so "was it done?" has dated sources too."""
    title = (
        "OPEN LOOPS: plan items from each clinician's latest note, open orders and new results, checked against the "
        "record (tests are tracked from order to result, review and telling the patient)"
    )
    lines = [loop_line(loop) for loop in loops]
    lines += [f"The plan in {ref} could not be read" for ref in unread]
    return title + "\n" + "\n".join(f"- {line}" for line in lines or ["no plan items found"])
