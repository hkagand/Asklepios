"""One patient's chart as compact text the model can read and cite.

The model never sees FHIR JSON. Everything it reads is rendered here, and every
line names the resource it came from, e.g. [Observation/obs-p-2041-301], so an
answer can point back to its source.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

# Clinic time: Europe/Istanbul has been UTC+3 all year since 2016.
TZ = timezone(timedelta(hours=3))
EARLIEST = datetime(1900, 1, 1, tzinfo=TZ)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ICD10 = "http://hl7.org/fhir/sid/icd-10"

LAB_GROUPS: dict[str, tuple[str, ...]] = {
    "Haematology": ("718-7", "4544-3", "787-2", "6690-2", "751-8", "777-3"),
    "Iron studies": ("2276-4",),
    "Kidney and electrolytes": (
        "2160-0", "98979-8", "3094-0", "2951-2", "2823-3", "2075-0", "2028-9", "17861-6", "19123-9", "9318-7",
    ),
    "Liver": ("1742-6", "1920-8", "6768-6", "1975-2", "1751-7"),
    "Diabetes and lipids": ("4548-4", "2345-7", "2093-3", "13457-7", "2085-9", "2571-8"),
    "Thyroid": ("3016-3", "3024-7", "8099-4"),
    "Cardiac": ("33762-6",),
    "Tumour markers": ("2039-6",),
}
VITAL_SIGNS = ("8480-6", "8462-4", "8867-4", "29463-7", "39156-5", "8302-2")
GROUPS = (*LAB_GROUPS, "Other", "Vital signs")
PLACE = {code: (group, index) for group, codes in LAB_GROUPS.items() for index, code in enumerate(codes)}

REPORT_KINDS = {"RAD": "Imaging", "CUS": "Echocardiography", "SP": "Pathology", "GE": "Molecular pathology", "OTH": "Procedure"}
ORDER_KINDS = {"108252007": "laboratory", "363679005": "imaging", "3457005": "referral", "103693007": "procedure"}
FLAGS = {"H": "high", "HH": "critically high", "L": "low", "LL": "critically low"}


def ref_of(resource: dict) -> str:
    return f"{resource['resourceType']}/{resource['id']}"


def first(items: list | None) -> dict:
    return (items or [{}])[0]


def text_of(concept: dict | None) -> str:
    if not concept:
        return ""
    coding = first(concept.get("coding"))
    return concept.get("text") or coding.get("display") or coding.get("code") or ""


def code_of(concept: dict | None) -> str | None:
    return first((concept or {}).get("coding")).get("code")


def moment(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)).astimezone(TZ)


def day_text(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def today_text(today: date) -> str:
    return f"{WEEKDAYS[today.weekday()]} {day_text(today)}"


def decode(data: str | None) -> str:
    return base64.b64decode(data).decode("utf-8") if data else ""


def patient_name(patient: dict) -> str:
    name = first(patient.get("name"))
    return name.get("text") or " ".join([*name.get("given", []), name.get("family", "")]).strip()


def signed(value: float, decimals: int) -> str:
    magnitude = f"{abs(value):.{decimals}f}"
    if float(magnitude) == 0:
        return magnitude
    return ("-" if value < 0 else "+") + magnitude


def _decimals(value: float) -> int:
    text = repr(value)
    return min(3, len(text.split(".")[1])) if "." in text else 0


def _drops_one(full: list[str], short: list[str]) -> bool:
    """True if `short` is `full` without one of its middle parts."""
    return len(full) == len(short) + 1 and any(full[:i] + full[i + 1 :] == short for i in range(1, len(full) - 1))


@dataclass
class Point:
    when: datetime
    value: float
    flag: str | None
    ref: str


@dataclass
class Series:
    """All results for one test or vital sign, oldest first."""

    code: str
    name: str
    unit: str
    group: str
    range: str | None
    points: list[Point] = field(default_factory=list)
    decimals: int = 0

    def amount(self, value: float) -> str:
        number = f"{value:.{self.decimals}f}"
        if not self.unit:
            return number
        return f"{number}%" if self.unit == "%" else f"{number} {self.unit}"

    def reading(self, point: Point) -> str:
        flag = f" ({FLAGS[point.flag]})" if point.flag in FLAGS else ""
        return f"{self.amount(point.value)}{flag} on {day_text(point.when)} [{point.ref}]"

    def change(self, start: Point, end: Point) -> str:
        unit = " points" if self.unit == "%" else f" {self.unit}" if self.unit else ""
        text = f"change {signed(end.value - start.value, self.decimals)}{unit}"
        if start.value:
            text += f" ({signed((end.value - start.value) / abs(start.value) * 100, 0)}%)"
        return f"{text} over {(end.when.date() - start.when.date()).days} days"


@dataclass
class Document:
    """A clinical note or a narrative report (imaging, endoscopy, pathology, ...)."""

    ref: str
    kind: str
    category: str
    title: str
    when: datetime
    author: str
    text: str
    conclusion: str | None = None
    encounter: str | None = None


class Record:
    def __init__(self, patient: dict, found: dict[str, list[dict]], today: date | None = None) -> None:
        self.patient = patient
        self.id: str = patient["id"]
        self.today = today or datetime.now(TZ).date()
        self.resources: dict[str, dict] = {ref_of(patient): patient}
        for items in found.values():
            for item in items:
                self.resources[ref_of(item)] = item
        self.by_id = {resource["id"]: ref for ref, resource in self.resources.items()}

        by_onset = sorted(found.get("Condition", []), key=lambda item: item.get("onsetDateTime") or "", reverse=True)
        self.conditions = sorted(by_onset, key=lambda item: not item.get("stage"))
        self.allergies = found.get("AllergyIntolerance", [])
        self.medications = sorted(
            found.get("MedicationRequest", []), key=lambda item: self.medication_period(item)[0] or EARLIEST, reverse=True
        )
        self.encounters = sorted(found.get("Encounter", []), key=lambda item: self.encounter_start(item) or EARLIEST, reverse=True)
        self.orders = sorted(found.get("ServiceRequest", []), key=lambda item: moment(item.get("authoredOn")) or EARLIEST, reverse=True)
        self.appointments = sorted(found.get("Appointment", []), key=lambda item: moment(item.get("start")) or EARLIEST)

        reports = found.get("DiagnosticReport", [])
        self.lab_reports = [report for report in reports if self._is_lab(report)]
        documents = [self._note(note) for note in found.get("DocumentReference", [])]
        documents += [self._report(report) for report in reports if not self._is_lab(report)]
        self.documents = sorted(documents, key=lambda document: document.when, reverse=True)
        self.document_by_ref = {document.ref: document for document in self.documents}
        self.results_for: dict[str, list[str]] = defaultdict(list)
        for report in reports:
            for based_on in report.get("basedOn", []):
                self.results_for[based_on.get("reference", "")].append(ref_of(report))

        self.points: dict[str, list[tuple[Series, Point]]] = defaultdict(list)
        self.series = self._build_series(found.get("Observation", []))

    # ------------------------------------------------------------- parsing

    @staticmethod
    def _is_lab(report: dict) -> bool:
        return any(code_of(category) == "LAB" for category in report.get("category", []))

    @staticmethod
    def encounter_start(encounter: dict) -> datetime | None:
        return moment(encounter.get("period", {}).get("start"))

    @staticmethod
    def medication_period(medication: dict) -> tuple[date | None, date | None]:
        bounds = first(medication.get("dosageInstruction")).get("timing", {}).get("repeat", {}).get("boundsPeriod", {})
        start = moment(bounds.get("start") or medication.get("authoredOn"))
        end = moment(bounds.get("end"))
        return (start.date() if start else None, end.date() if end else None)

    def _note(self, note: dict) -> Document:
        attachment = first(note.get("content")).get("attachment", {})
        return Document(
            ref=ref_of(note),
            kind="note",
            category=text_of(note.get("type")) or "Note",
            title=note.get("description") or attachment.get("title") or text_of(note.get("type")) or "Note",
            when=moment(note.get("date") or attachment.get("creation")) or EARLIEST,
            author=first(note.get("author")).get("display", ""),
            text=decode(attachment.get("data")),
            encounter=first(note.get("context", {}).get("encounter")).get("reference"),
        )

    def _report(self, report: dict) -> Document:
        category = first(report.get("category"))
        return Document(
            ref=ref_of(report),
            kind="report",
            category=REPORT_KINDS.get(code_of(category) or "", text_of(category) or "Report"),
            title=text_of(report.get("code")) or "Report",
            when=moment(report.get("effectiveDateTime") or report.get("issued")) or EARLIEST,
            author=first(report.get("resultsInterpreter") or report.get("performer")).get("display", ""),
            text=decode(first(report.get("presentedForm")).get("data")) or report.get("conclusion", ""),
            conclusion=report.get("conclusion"),
        )

    def _build_series(self, observations: list[dict]) -> list[Series]:
        series: dict[str, Series] = {}
        for observation in observations:
            category = code_of(first(observation.get("category")))
            when = moment(observation.get("effectiveDateTime"))
            if when is None or category not in ("laboratory", "vital-signs"):
                continue
            ref = ref_of(observation)
            flag = code_of(first(observation.get("interpretation")))
            for part in observation.get("component") or [observation]:
                code, quantity = code_of(part.get("code")), part.get("valueQuantity") or {}
                if not code or quantity.get("value") is None or (category == "vital-signs" and code not in VITAL_SIGNS):
                    continue
                item = series.get(code)
                if item is None:
                    group = "Vital signs" if category == "vital-signs" else PLACE.get(code, ("Other", 0))[0]
                    reference = first(observation.get("referenceRange")).get("text")
                    item = series[code] = Series(code, text_of(part.get("code")), quantity.get("unit", ""), group, reference)
                point = Point(when, quantity["value"], flag, ref)
                item.points.append(point)
                self.points[ref].append((item, point))
        for item in series.values():
            item.points.sort(key=lambda point: point.when)
            item.decimals = max(_decimals(point.value) for point in item.points)

        def rank(item: Series) -> tuple[int, int, str]:
            position = VITAL_SIGNS.index(item.code) if item.group == "Vital signs" else PLACE.get(item.code, ("", 99))[1]
            return GROUPS.index(item.group), position, item.name

        return sorted(series.values(), key=rank)

    # ------------------------------------------------------------- lookups

    def resolve(self, raw: str) -> str | None:
        """Accepts 'Type/id', a bare id, or either wrapped in brackets.

        Models sometimes drop one part of a long id ("dr-p-020" for "dr-p-2041-020"). That is accepted when exactly one
        id of the same type matches.
        """
        token = raw.strip().strip("[]【】()<>\"'` ").rstrip(".,;:")
        if token in self.resources:
            return token
        kind, _, bare = token.rpartition("/")
        if found := self.by_id.get(bare):
            return found
        parts = bare.split("-")
        matches = [
            ref
            for key, ref in self.by_id.items()
            if (not kind or ref.startswith(kind + "/")) and _drops_one(key.split("-"), parts)
        ]
        return matches[0] if len(matches) == 1 else None

    def upcoming(self) -> list[dict]:
        return [
            appointment
            for appointment in self.appointments
            if appointment.get("status") == "booked" and (moment(appointment.get("start")) or EARLIEST).date() >= self.today
        ]

    def open_orders(self) -> list[dict]:
        active = [order for order in self.orders if order.get("status") == "active"]
        return sorted(active, key=lambda order: order.get("occurrenceDateTime") or "")

    # ---------------------------------------------------------- one-liners

    def patient_line(self) -> str:
        patient = self.patient
        parts = [patient_name(patient), patient.get("gender", "gender unknown")]
        if patient.get("birthDate"):
            born = date.fromisoformat(patient["birthDate"])
            years = self.today.year - born.year - ((self.today.month, self.today.day) < (born.month, born.day))
            parts.append(f"{years} years old (born {day_text(born)})")
        mrn = next(
            (
                identifier.get("value")
                for identifier in patient.get("identifier", [])
                if code_of(identifier.get("type")) == "MR"
            ),
            None,
        )
        if mrn:
            parts.append(f"MRN {mrn}")
        city = first(patient.get("address")).get("city")
        if city:
            parts.append(f"lives in {city}")
        gp = first(patient.get("generalPractitioner")).get("display")
        if gp:
            parts.append(f"GP {gp}")
        return ", ".join(parts) + f" [{ref_of(patient)}]"

    def appointment_line(self, appointment: dict) -> str:
        start = moment(appointment.get("start")) or EARLIEST
        when = f"today ({day_text(start)})" if start.date() == self.today else day_text(start)
        text = f"{when} at {start:%H:%M}"
        clinician = next(
            (
                participant["actor"].get("display")
                for participant in appointment.get("participant", [])
                if participant.get("actor", {}).get("reference", "").startswith("Practitioner/")
            ),
            None,
        )
        service = text_of(first(appointment.get("serviceType")))
        if clinician:
            text += f" with {clinician}" + (f" ({service})" if service else "")
        if appointment.get("description"):
            text += f": {appointment['description']}"
        return f"{text} [{ref_of(appointment)}]"

    def condition_line(self, condition: dict) -> str:
        concept = condition.get("code", {})
        coding = first(concept.get("coding"))
        name = text_of(concept)
        parts = [f"{name} (ICD-10 {coding['code']})" if coding.get("system") == ICD10 and coding.get("code") else name]
        onset = moment(condition.get("onsetDateTime"))
        if onset:
            parts.append(f"since {day_text(onset)}")
        stage = text_of(first(condition.get("stage")).get("summary"))
        if stage:
            parts.append(stage)
        note = first(condition.get("note")).get("text")
        if note:
            parts.append(note.rstrip("."))
        status = code_of(condition.get("clinicalStatus"))
        if status and status != "active":
            parts.append(status)
        asserter = condition.get("asserter", {}).get("display")
        if asserter:
            parts.append(f"recorded by {asserter}")
        return "; ".join(parts) + f" [{ref_of(condition)}]"

    def allergy_line(self, allergy: dict) -> str:
        parts = [text_of(allergy.get("code")) or "Allergy"]
        reactions = [text_of(item) for reaction in allergy.get("reaction", []) for item in reaction.get("manifestation", [])]
        if reactions:
            parts.append("reaction: " + ", ".join(reactions))
        severity = first(allergy.get("reaction")).get("severity")
        if severity:
            parts.append(f"severity {severity}")
        if allergy.get("criticality"):
            parts.append(f"criticality {allergy['criticality']}")
        recorded = moment(allergy.get("recordedDate"))
        if recorded:
            parts.append(f"recorded {day_text(recorded)}")
        return "; ".join(parts) + f" [{ref_of(allergy)}]"

    def medication_line(self, medication: dict) -> str:
        name = text_of(medication.get("medicationCodeableConcept")) or "Medication"
        dosage = first(medication.get("dosageInstruction")).get("text")
        parts = [f"{name}: {dosage}" if dosage else name]
        start, end = self.medication_period(medication)
        if start and end:
            parts.append(f"{day_text(start)} to {day_text(end)}")
        elif start:
            parts.append(f"since {day_text(start)}")
        reason = text_of(first(medication.get("reasonCode")))
        if reason:
            parts.append(f"for {reason}")
        prescriber = medication.get("requester", {}).get("display")
        if prescriber:
            parts.append(f"prescribed by {prescriber}")
        status = medication.get("status", "unknown")
        if status != "active":
            why = text_of(medication.get("statusReason"))
            parts.append(status.replace("-", " ") + (f": {why}" if why else ""))
        return "; ".join(parts) + f" [{ref_of(medication)}]"

    def due_text(self, due: date) -> str:
        days = (due - self.today).days
        if days < 0:
            return f"due {day_text(due)}, OVERDUE by {-days} days"
        if days == 0:
            return f"due today ({day_text(due)})"
        return f"due {day_text(due)} (in {days} days)"

    def order_line(self, order: dict) -> str:
        category = first(order.get("category"))
        kind = ORDER_KINDS.get(code_of(category) or "", text_of(category).lower() or "order")
        parts = [f"{text_of(order.get('code')) or 'Order'} ({kind})"]
        ordered = moment(order.get("authoredOn"))
        requester = order.get("requester", {}).get("display")
        if ordered:
            parts.append(f"ordered {day_text(ordered)}" + (f" by {requester}" if requester else ""))
        if order.get("priority") not in (None, "routine"):
            parts.append(f"priority {order['priority']}")
        due = moment(order.get("occurrenceDateTime"))
        status = order.get("status", "unknown")
        results = self.results_for.get(ref_of(order), [])
        if status == "active":
            parts.append(self.due_text(due.date()) if due else "no due date")
        else:
            if due:
                parts.append(f"due {day_text(due)}")
            parts.append(f"status {status}")
        reason = text_of(first(order.get("reasonCode")))
        if reason:
            parts.append(f"reason: {reason}")
        parts += [f"result: {self.label(result)} [{result}]" for result in results] or ["no result on file"]
        return "; ".join(parts) + f" [{ref_of(order)}]"

    def encounter_line(self, encounter: dict) -> str:
        start = self.encounter_start(encounter) or EARLIEST
        text = f"{day_text(start)}: {text_of(first(encounter.get('type'))) or 'Visit'}"
        end = moment(encounter.get("period", {}).get("end"))
        if encounter.get("class", {}).get("code") == "IMP" and end:
            text += f" (inpatient, {day_text(start)} to {day_text(end)})"
        clinician = first(encounter.get("participant")).get("individual", {}).get("display")
        service = text_of(encounter.get("serviceType"))
        if clinician:
            text += f" with {clinician}" + (f" ({service})" if service else "")
        reason = text_of(first(encounter.get("reasonCode")))
        if reason:
            text += f"; reason: {reason}"
        ref = ref_of(encounter)
        text += f" [{ref}]"
        for document in self.documents:
            if document.encounter == ref:
                text += f'; note "{document.title}" [{document.ref}]'
        return text

    def document_line(self, document: Document) -> str:
        if document.kind == "report":
            text = f"{day_text(document.when)}: {document.category}: {document.title}"
            if document.author:
                text += f", {document.author}"
            if document.conclusion:
                text += f". Conclusion: {document.conclusion}"
            return f"{text} [{document.ref}]"
        author = f" by {document.author}" if document.author else ""
        return f'{day_text(document.when)}: {document.category} "{document.title}"{author} [{document.ref}]'

    def latest_line(self, series: Series) -> str:
        last = series.points[-1]
        text = f"{series.name}: {series.reading(last)}"
        if len(series.points) > 1:
            previous = series.points[-2]
            text += f"; previous {series.reading(previous)}; {series.change(previous, last)}"
        if series.range:
            text += f"; reference {series.range}"
        if len(series.points) > 2:
            text += f"; {len(series.points)} results since {day_text(series.points[0].when)}"
        return text

    # ------------------------------------------------------- full renders

    def document_text(self, ref: str) -> str:
        document = self.document_by_ref[ref]
        header = f"[{document.ref}] {document.category}: {document.title}, {day_text(document.when)}"
        if document.author:
            header += f", {document.author}"
        if document.encounter:
            header += f"; visit [{document.encounter}]"
        return f"{header}\n{document.text.strip()}"

    def lab_report_text(self, report: dict) -> str:
        when = moment(report.get("effectiveDateTime") or report.get("issued")) or EARLIEST
        lines = [f"{text_of(report.get('code')) or 'Laboratory report'}, collected {day_text(when)} [{ref_of(report)}]"]
        for result in report.get("result", []):
            for series, point in self.points.get(result.get("reference", ""), []):
                lines.append(f"- {series.name}: {series.reading(point)}" + (f"; reference {series.range}" if series.range else ""))
        return "\n".join(lines)

    def describe(self, ref: str) -> str:
        resource = self.resources.get(ref)
        if resource is None:
            return f"{ref}: not in this patient's record."
        if ref in self.document_by_ref:
            return self.document_text(ref)
        render = {
            "Patient": lambda item: self.patient_line(),
            "Condition": self.condition_line,
            "AllergyIntolerance": self.allergy_line,
            "MedicationRequest": self.medication_line,
            "ServiceRequest": self.order_line,
            "Appointment": self.appointment_line,
            "Encounter": self.encounter_line,
            "DiagnosticReport": self.lab_report_text,
        }.get(resource["resourceType"])
        if render:
            return render(resource)
        readings = [f"{series.name}: {series.reading(point)}" for series, point in self.points.get(ref, [])]
        return "\n".join(readings) or f"[{ref}] has no numeric value."

    def label(self, ref: str) -> str:
        """A short name for a citation chip."""
        resource = self.resources.get(ref)
        if resource is None:
            return ref
        kind = resource["resourceType"]
        if ref in self.document_by_ref:
            document = self.document_by_ref[ref]
            return f"{document.title.split(' with ')[0]} · {day_text(document.when)}"
        if kind == "Observation":
            readings = self.points.get(ref, [])
            if not readings:
                return text_of(resource.get("code")) or "Observation"
            series, point = readings[0]
            if len(readings) > 1:
                values = "/".join(f"{reading.value:.{item.decimals}f}" for item, reading in readings)
                return f"{text_of(resource.get('code'))} {values} {series.unit} · {day_text(point.when)}"
            return f"{series.name} {series.amount(point.value)} · {day_text(point.when)}"
        if kind == "DiagnosticReport":
            when = moment(resource.get("effectiveDateTime") or resource.get("issued")) or EARLIEST
            return f"{text_of(resource.get('code'))} · {day_text(when)}"
        if kind == "MedicationRequest":
            return text_of(resource.get("medicationCodeableConcept")) or "Medication"
        if kind == "ServiceRequest":
            ordered = moment(resource.get("authoredOn")) or EARLIEST
            return f"Order: {text_of(resource.get('code')).split(' with ')[0]} · {day_text(ordered)}"
        if kind == "Encounter":
            return f"{text_of(first(resource.get('type'))) or 'Visit'} · {day_text(self.encounter_start(resource) or EARLIEST)}"
        if kind == "Condition":
            return text_of(resource.get("code")) or "Problem"
        if kind == "AllergyIntolerance":
            return text_of(resource.get("code")) or "Allergy"
        if kind == "Appointment":
            return f"Appointment · {day_text(moment(resource.get('start')) or EARLIEST)}"
        return "Patient details"

    # --------------------------------------------------------------- index

    def index(self) -> str:
        """The chart overview placed in the system prompt: one line per item, each with its id."""
        sections = [
            ("PATIENT", [self.patient_line()]),
            ("UPCOMING APPOINTMENTS", [self.appointment_line(item) for item in self.upcoming()] or ["none booked"]),
            ("PROBLEM LIST", [self.condition_line(item) for item in self.conditions] or ["none recorded"]),
            ("ALLERGIES", [self.allergy_line(item) for item in self.allergies] or ["not recorded"]),
            ("MEDICATIONS", self._medication_lines()),
            ("OPEN ORDERS (ordered, no result on file yet)", [self.order_line(item) for item in self.open_orders()] or ["none"]),
            ("VISITS AND NOTES, newest first (read_documents for a full note)", self._visit_lines()),
            (
                "REPORTS, newest first (read_documents for the full report)",
                [self.document_line(item) for item in self.documents if item.kind == "report"] or ["none"],
            ),
            ("LATEST RESULTS: newest value per test and the one before (lab_series for the full history)", self._result_lines()),
        ]
        return "\n\n".join(
            title + "\n" + "\n".join(line if line.endswith(":") else f"- {line}" for line in lines) for title, lines in sections
        )

    def _medication_lines(self) -> list[str]:
        groups: dict[str, list[str]] = {"Active:": [], "On hold:": [], "Stopped or completed, newest first:": []}
        for medication in self.medications:
            status = medication.get("status")
            key = "Active:" if status == "active" else "On hold:" if status == "on-hold" else "Stopped or completed, newest first:"
            groups[key].append(self.medication_line(medication))
        lines = [line for title, items in groups.items() if items for line in (title, *items)]
        return lines or ["none recorded"]

    def _visit_lines(self) -> list[str]:
        rows = [
            (start, self.encounter_line(encounter))
            for encounter in self.encounters
            if (start := self.encounter_start(encounter)) and start.date() <= self.today
        ]
        rows += [
            (document.when, self.document_line(document))
            for document in self.documents
            if document.kind == "note" and document.encounter not in self.resources
        ]
        rows.sort(key=lambda row: row[0], reverse=True)
        return [line for _, line in rows] or ["none"]

    def _result_lines(self) -> list[str]:
        lines: list[str] = []
        for group in GROUPS:
            members = [series for series in self.series if series.group == group]
            if members:
                lines += [f"{group}:", *(self.latest_line(series) for series in members)]
        return lines or ["no results on file"]
