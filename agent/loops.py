"""Open loops: what each clinician's latest note planned, matched against what the record shows happened since.

The model has only extracted the plan items (plans.py). Everything here is plain code: due dates, matching against
orders, results, appointments, visits and medication orders, and the status of each item.

Statuses, worst first
  missing      the due date has passed and nothing was ordered, booked or resulted
  overdue      ordered or booked, the due date has passed and there is no result
  not_ordered  nothing ordered or booked yet, and the due date has not passed or none was given
  no_trace     a kind the record cannot show, such as a phone call or a meeting, and nothing was found
  pending      ordered or booked and not yet due
  conditional  only to be done if something happens
  done         the result, visit or change is on file
"""

from __future__ import annotations

import asyncio
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .llm import LlmError
from .plans import PlanExtractor, PlanItem, plain
from .record import EARLIEST, Document, Record, code_of, day_text, moment, ref_of, text_of
from .tools import fold

STATUSES = ("missing", "overdue", "not_ordered", "no_trace", "pending", "conditional", "done")
OPEN = ("missing", "overdue", "not_ordered", "no_trace")
TRACKED = ("lab", "imaging", "procedure", "referral", "visit", "contact", "meeting", "medication", "conditional")

# Test families: the words that name them in notes and order names, and the LOINC codes of the results that show
# they were done. A comprehensive metabolic panel also covers a basic one.
LAB_TESTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "cbc": (("cbc", "fbc", "complete blood count", "full blood count", "blood count"), ("718-7", "6690-2", "777-3")),
    "bmp": (
        ("basic metabolic panel", "bmp", "electrolytes", "renal function", "kidney function", "urea and electrolytes", "potassium", "creatinine", "egfr"),
        ("2160-0", "2823-3", "2951-2"),
    ),
    "cmp": (("comprehensive metabolic panel", "cmp", "liver function", "liver enzymes", "lfts", "lft"), ("1742-6", "1920-8", "6768-6")),
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
DRUG_WORDS = {"iron": ("ferrous", "iron"), "leucovorin": ("folinate", "leucovorin"), "folinic": ("folinate",)}
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


@dataclass
class Loop:
    """A plan item from a note, or (note None) an order still open that no current plan item covers."""

    note: Document | None
    item: PlanItem
    status: str
    due: date | None
    detail: str
    evidence: list[str]
    parts: list[Part] = field(default_factory=list)

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
            "source": "plan" if self.note else "order",
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
            parts = []
            for order in orders:
                status, detail, _ = self.order_state(order, due)
                parts.append(Part(text_of(order.get("code")), status, detail, [ref_of(order)]))
            return parts
        results = sorted((point.when, ref) for ref, points in self.record.points.items() for _, point in points if written < point.when.date() <= self.today)
        if results:
            return [Part("bloods", "done", f"resulted {day_text(results[0][0].date())}", [results[0][1]])]
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
            when, ref = results[0]
            return Part(name, "done", f"resulted {day_text(when.date())}", [ref])
        orders = [order for order in self.orders_after(written) if set(families) & covered_by(text_of(order.get("code")))]
        if orders:
            status, detail, _ = self.order_state(orders[0], due)
            return Part(name, status, detail, [ref_of(orders[0])])
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
            report = min(reports, key=lambda document: document.when)
            return Part(name, "done", f"reported {day_text(report.when.date())}", [report.ref])
        orders = [order for order in self.orders_after(written) if same(text_of(order.get("code")))]
        if orders:
            status, detail, _ = self.order_state(orders[0], due)
            return Part(name, status, detail, [ref_of(orders[0])])
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

    def visit(self, note: Document, written: date, due: date | None) -> Part:
        name = f"visit with {note.author}" if note.author else "follow-up visit"
        for encounter in sorted(self.record.encounters, key=lambda item: self.record.encounter_start(item) or EARLIEST):
            start = self.record.encounter_start(encounter)
            clinician = (encounter.get("participant") or [{}])[0].get("individual", {}).get("display", "")
            if start and written < start.date() <= self.today and (not note.author or clinician == note.author):
                return Part(name, "done", f"seen {day_text(start.date())}", [ref_of(encounter)])
        for appointment in self.record.appointments:
            start = moment(appointment.get("start"))
            clinicians = [participant.get("actor", {}).get("display", "") for participant in appointment.get("participant", [])]
            if start and start.date() > written and appointment.get("status") == "booked" and (not note.author or note.author in clinicians):
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
                names = ", ".join(text_of(medication.get("medicationCodeableConcept")).split(" ")[0] for medication in changed)
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
            for medication in orders:
                start, _ = self.record.medication_period(medication)
                if start and low <= start <= high:
                    return Part(drug, "done", f"ordered from {day_text(start)}", [ref_of(medication)])
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
        return Loop(None, item, status, due, detail + (f" by {requester}" if requester else ""), [ref_of(order)])

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
            parts = [self.visit(note, written, due)]
        elif item.kind == "medication":
            parts = [self.medication(item, written, due)]
        else:
            parts = [self.untracked(item, written, due)]
        parts = merge(parts)
        status = worst([part.status for part in parts])
        detail = "; ".join(f"{part.name}: {part.detail}" if len(parts) > 1 else part.detail for part in parts)
        evidence = list(dict.fromkeys(ref for part in parts for ref in part.evidence))
        return Loop(note, item, status, due, detail, evidence, parts if len(parts) > 1 else [])


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
            merged.append(Part(part.name, part.status, part.detail, list(part.evidence)))
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
    loops.sort(key=lambda loop: (STATUSES.index(loop.status), loop.due or date.max))
    return loops, unread


STATUS_TEXT = {
    "missing": "NOT DONE, due date passed",
    "overdue": "OVERDUE",
    "not_ordered": "Planned, nothing ordered yet",
    "no_trace": "Planned, no record to confirm it",
    "pending": "Ordered or booked",
    "conditional": "Only if needed",
    "done": "Done",
}


def loop_line(loop: Loop) -> str:
    if loop.note:
        about = f' ("{loop.item.quote}")' if loop.item.quote != loop.line else ""
        source = f'"{loop.line}"{about} ({loop.item.kind}), planned {day_text(loop.note.when.date())}'
        source += f" by {loop.note.author}" if loop.note.author else ""
    else:
        source = f"{loop.item.quote} ({loop.item.kind} order not in a current plan)"
    refs = ", ".join([*([loop.note.ref] if loop.note else []), *loop.evidence])
    return f"{STATUS_TEXT[loop.status]}: {source}; {loop.detail} [{refs}]"


def index_section(loops: list[Loop], unread: list[str]) -> str:
    """The OPEN LOOPS section of the chart index: every item, worst first, so "was it done?" has dated sources too."""
    title = "OPEN LOOPS: plan items from each clinician's latest note, checked against the record"
    lines = [loop_line(loop) for loop in loops]
    lines += [f"The plan in {ref} could not be read" for ref in unread]
    return title + "\n" + "\n".join(f"- {line}" for line in lines or ["no plan items found"])
