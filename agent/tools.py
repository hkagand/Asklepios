"""Read-only tools the model can call. Each one sees only the open patient's record."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .record import ORDER_KINDS, Record, Series, code_of, day_text, moment, text_of

MAX_DOCUMENTS = 4
MAX_SEARCH_DOCUMENTS = 6
MAX_SEARCH_LINES = 3


@dataclass
class ToolResult:
    blocks: list[str]
    label: str

    @property
    def text(self) -> str:
        return "\n\n".join(self.blocks)


def _optional_day(description: str) -> dict:
    return {"type": "string", "description": f"{description}, YYYY-MM-DD (optional)"}


SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_documents",
            "description": (
                "Read the full text of clinical notes and narrative reports (imaging, endoscopy, pathology, molecular, "
                "echocardiography) by id: findings, assessments and plans. Also accepts any other id from the index "
                "(lab report, order, medication, visit, problem) and returns its details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"Up to {MAX_DOCUMENTS} ids, e.g. [\"DocumentReference/doc-1\", \"DiagnosticReport/dr-2\"]",
                    }
                },
                "required": ["ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_record",
            "description": (
                "Find where something is mentioned: keyword search over the full text of every note and report and "
                "over the problem, medication, allergy and order lists. Returns matching passages with ids and dates, "
                "best matches first. Use short keywords such as \"neuropathy\", \"tumour board\", \"rash\"."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "One or a few keywords"},
                    "date_from": _optional_day("Only documents on or after this day"),
                    "date_to": _optional_day("Only documents on or before this day"),
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lab_series",
            "description": (
                "Every result over time for a lab test or vital sign, oldest first, with flags and reference range, plus "
                "computed changes: latest against previous, first against latest, lowest and highest. Accepts names, "
                "abbreviations or LOINC codes (\"haemoglobin\", \"Hb\", \"CEA\", \"eGFR\", \"weight\", \"blood pressure\") "
                "or a group (\"blood count\", \"liver\", \"kidney\", \"lipids\", \"thyroid\", \"vital signs\")."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "test": {"type": "string", "description": "Test name, abbreviation, LOINC code or group"},
                    "date_from": _optional_day("Only results on or after this day"),
                    "date_to": _optional_day("Only results on or before this day"),
                },
                "required": ["test"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "medication_history",
            "description": (
                "Medication orders over time, grouped by drug: start and stop dates, doses and dose changes, holds, "
                "what each drug was for, and the documented reason for every stop, hold or change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Optional filter by drug name or indication, e.g. \"oxaliplatin\" or \"hypertension\"",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "order_history",
            "description": (
                "Orders and referrals (laboratory, imaging, procedures, referrals): when each was ordered and due, its "
                "status, how many days an open order is overdue, and the report that fulfilled it. Use it for questions "
                "like \"was the CT done?\" or \"what is still outstanding?\". Without a query, completed laboratory "
                "orders are only counted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional keywords, e.g. \"CT\" or \"colonoscopy\""},
                    "status": {"type": "string", "enum": ["open", "completed", "all"], "description": "Default: all"},
                },
            },
        },
    },
]


def run(record: Record, name: str, arguments: str) -> ToolResult:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return ToolResult([f"Error: the arguments for {name} were not valid JSON: {arguments}"], f"Could not run {name}")
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolResult([f"Error: there is no tool called {name}. Available: {', '.join(HANDLERS)}."], f"Unknown tool {name}")
    if not isinstance(parsed, dict):
        return ToolResult([f"Error: the arguments for {name} must be a JSON object."], f"Could not run {name}")
    return handler(record, parsed)


# ------------------------------------------------------------------ text matching

STOPWORDS = {
    "a", "about", "after", "all", "an", "and", "any", "are", "at", "be", "been", "before", "by", "did", "do", "does",
    "ever", "for", "from", "had", "has", "have", "he", "her", "him", "his", "how", "in", "is", "it", "its", "of", "on",
    "or", "patient", "record", "she", "since", "that", "the", "their", "there", "this", "to", "was", "were", "what",
    "when", "where", "which", "who", "why", "with",
}


def fold(text: str) -> str:
    """Lower case without accents, with British spellings mapped to American (anaemia, tumour, oedema)."""
    plain = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "I"))
    plain = "".join(character for character in plain if not unicodedata.combining(character)).lower()
    for british, american in (("ae", "e"), ("oe", "e"), ("our", "or")):
        plain = plain.replace(british, american)
    return plain


def _stem(word: str) -> str:
    if len(word) >= 5:
        for suffix in ("ies", "es", "is", "ing", "ed", "s", "y"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                return word[: -len(suffix)]
    return word


def terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", fold(query))
    kept = [word for word in words if word not in STOPWORDS] or words
    return list(dict.fromkeys(_stem(word) for word in kept))


def _matcher(query: str) -> Callable[[str], set[int]]:
    patterns = [re.compile(r"\b" + re.escape(term)) for term in terms(query)]
    return lambda text: {index for index, pattern in enumerate(patterns) if pattern.search(fold(text))}


def _day(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _period_text(start: date | None, end: date | None) -> str:
    if start and end:
        return f" between {day_text(start)} and {day_text(end)}"
    if start:
        return f" since {day_text(start)}"
    if end:
        return f" up to {day_text(end)}"
    return ""


# ------------------------------------------------------------------------- tools

def read_documents(record: Record, arguments: dict) -> ToolResult:
    ids = arguments.get("ids") or arguments.get("id") or []
    wanted = [ids] if isinstance(ids, str) else [str(item) for item in ids]
    if not wanted:
        return ToolResult(["Error: give at least one id."], "Could not read documents")
    blocks, labels = [], []
    for raw in wanted[:MAX_DOCUMENTS]:
        ref = record.resolve(raw)
        if ref is None:
            blocks.append(f"{raw}: not found in this patient's record.")
            continue
        blocks.append(record.describe(ref))
        labels.append(record.label(ref))
    if len(wanted) > MAX_DOCUMENTS:
        blocks.append(f"Only the first {MAX_DOCUMENTS} ids were read; ask again for the rest.")
    return ToolResult(blocks, "Read " + "; ".join(labels) if labels else "Looked for documents that are not on file")


def search_record(record: Record, arguments: dict) -> ToolResult:
    query = str(arguments.get("query") or "").strip()
    start, end = _day(arguments.get("date_from")), _day(arguments.get("date_to"))
    label = f"Searched the record for “{query}”"
    if not query:
        return ToolResult(["Error: give a query."], label)
    match = _matcher(query)
    period = _period_text(start, end)

    hits = []
    for document in record.documents:
        day = document.when.date()
        if (start and day < start) or (end and day > end):
            continue
        lines = [line.strip() for line in document.text.splitlines() if line.strip()]
        scored = [(len(found), position, line) for position, line in enumerate(lines) if (found := match(line))]
        covered = set().union(match(document.title), *(match(line) for _, _, line in scored))
        if covered:
            hits.append((len(covered), document, scored))
    hits.sort(key=lambda hit: (hit[0], hit[1].when), reverse=True)

    blocks = []
    for _, document, scored in hits[:MAX_SEARCH_DOCUMENTS]:
        best = sorted(sorted(scored, key=lambda item: -item[0])[:MAX_SEARCH_LINES], key=lambda item: item[1])
        author = f", {document.author}" if document.author else ""
        lines = [f"[{document.ref}] {document.category}: {document.title}, {day_text(document.when)}{author}"]
        lines += [f"  …{line[:300]}{'…' if len(line) > 300 else ''}" for _, _, line in best]
        if len(scored) > len(best):
            lines.append(f"  ({len(scored) - len(best)} more matching lines; read_documents for the full text)")
        blocks.append("\n".join(lines))

    entries = []
    lists = (
        ("Problem", record.conditions, record.condition_line),
        ("Medication", record.medications, record.medication_line),
        ("Allergy", record.allergies, record.allergy_line),
        ("Order", record.orders, record.order_line),
    )
    for prefix, items, render in lists:
        for item in items:
            if (start or end) and not _within(item, start, end):
                continue
            line = render(item)
            if match(line.rsplit(" [", 1)[0]):
                entries.append(f"- {prefix}: {line}")
    if entries:
        blocks.append("List entries:\n" + "\n".join(entries[:8]))

    if not blocks:
        return ToolResult([f"No note, report or list entry mentions “{query}”{period}."], label)
    summary = f"Search “{query}”{period}: {len(hits)} notes or reports and {len(entries)} list entries match."
    if len(hits) > MAX_SEARCH_DOCUMENTS:
        summary += f" Showing the best {MAX_SEARCH_DOCUMENTS} documents."
    return ToolResult([summary, *blocks], label)


def _within(item: dict, start: date | None, end: date | None) -> bool:
    when = moment(item.get("onsetDateTime") or item.get("authoredOn") or item.get("recordedDate"))
    if when is None:
        return False
    day = when.date()
    return not ((start and day < start) or (end and day > end))


ALIASES: dict[str, tuple[str, ...]] = {
    "718-7": ("hb", "hgb", "hemoglobin", "blood count", "cbc", "fbc"),
    "4544-3": ("hct", "hematocrit", "pcv", "blood count", "cbc", "fbc"),
    "787-2": ("mcv", "blood count", "cbc", "fbc"),
    "6690-2": ("wbc", "white cells", "white blood cells", "leukocytes", "leucocytes", "blood count", "cbc", "fbc"),
    "751-8": ("anc", "neutrophils", "blood count", "cbc", "fbc"),
    "777-3": ("plt", "platelets", "blood count", "cbc", "fbc"),
    "2951-2": ("na", "sodium", "electrolytes"),
    "2823-3": ("k", "potassium", "electrolytes"),
    "2075-0": ("cl", "chloride", "electrolytes"),
    "2028-9": ("bicarbonate", "hco3", "co2", "electrolytes"),
    "3094-0": ("bun", "urea", "kidney", "renal"),
    "2160-0": ("cr", "creat", "creatinine", "kidney", "renal"),
    "98979-8": ("egfr", "gfr", "kidney", "renal"),
    "9318-7": ("uacr", "acr", "albuminuria", "microalbumin", "urine albumin"),
    "2345-7": ("glucose", "blood sugar", "fasting glucose", "glu"),
    "17861-6": ("ca", "calcium"),
    "19123-9": ("mg", "magnesium"),
    "1751-7": ("alb", "albumin", "liver"),
    "1742-6": ("alt", "sgpt", "liver", "transaminases"),
    "1920-8": ("ast", "sgot", "liver", "transaminases"),
    "6768-6": ("alp", "alkaline phosphatase", "liver"),
    "1975-2": ("bilirubin", "tbil", "liver"),
    "4548-4": ("a1c", "hba1c", "glycated hemoglobin", "glycosylated hemoglobin"),
    "2093-3": ("cholesterol", "total cholesterol", "lipids", "lipid panel"),
    "2085-9": ("hdl", "lipids", "lipid panel"),
    "13457-7": ("ldl", "lipids", "lipid panel"),
    "2571-8": ("tg", "triglycerides", "lipids", "lipid panel"),
    "3016-3": ("tsh", "thyroid"),
    "3024-7": ("ft4", "free t4", "thyroid"),
    "8099-4": ("tpo", "anti-tpo", "thyroid antibodies"),
    "2276-4": ("ferritin", "iron"),
    "33762-6": ("bnp", "nt-probnp", "ntprobnp", "natriuretic peptide"),
    "2039-6": ("cea", "carcinoembryonic antigen", "tumor marker", "tumor markers"),
    "8480-6": ("sbp", "systolic", "blood pressure", "bp", "vitals", "vital signs"),
    "8462-4": ("dbp", "diastolic", "blood pressure", "bp", "vitals", "vital signs"),
    "8867-4": ("hr", "pulse", "heart rate", "vitals", "vital signs"),
    "29463-7": ("weight", "body weight", "vitals", "vital signs"),
    "39156-5": ("bmi", "body mass index", "vitals", "vital signs"),
    "8302-2": ("height",),
}


def find_series(record: Record, test: str) -> list[Series]:
    query = fold(test).strip()
    best, chosen = 0, []
    for series in record.series:
        names = {fold(series.name), series.code, fold(series.group), *ALIASES.get(series.code, ())}
        if query in names:
            score = 3
        elif any(len(name) > 1 and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", query) for name in names):
            score = 2
        elif len(query) >= 3 and query in fold(series.name):
            score = 1
        else:
            continue
        if score > best:
            best, chosen = score, [series]
        elif score == best:
            chosen.append(series)
    return chosen


def lab_series(record: Record, arguments: dict) -> ToolResult:
    test = str(arguments.get("test") or "").strip()
    start, end = _day(arguments.get("date_from")), _day(arguments.get("date_to"))
    found = find_series(record, test) if test else []
    if not found:
        available = ", ".join(series.name for series in record.series)
        return ToolResult([f"No results for “{test}”. Tests on file: {available or 'none'}."], f"Looked for “{test}” results")
    blocks = [_series_text(series, start, end) for series in found]
    return ToolResult(blocks, "Looked up " + ", ".join(series.name for series in found))


def _series_text(series: Series, start: date | None, end: date | None) -> str:
    points = [
        point
        for point in series.points
        if not ((start and point.when.date() < start) or (end and point.when.date() > end))
    ]
    period = _period_text(start, end)
    head = f"{series.name} (LOINC {series.code}), {series.unit or 'no unit'}"
    if series.range:
        head += f", reference {series.range}"
    if not points:
        span = f"{day_text(series.points[0].when)} to {day_text(series.points[-1].when)}"
        return f"{head}: no results{period}. Results on file run from {span}."
    lines = [f"{head}: {len(points)} results{period}, {day_text(points[0].when)} to {day_text(points[-1].when)}"]
    lines += [f"- {series.reading(point)}" for point in points]
    if len(points) > 1:
        last, previous, first_point = points[-1], points[-2], points[0]
        lines.append(f"Latest against previous: {series.change(previous, last)}.")
        if len(points) > 2:
            lines.append(f"First against latest: {series.change(first_point, last)}.")
        lowest = min(points, key=lambda point: point.value)
        highest = max(points, key=lambda point: point.value)
        lines.append(
            f"Lowest {series.amount(lowest.value)} on {day_text(lowest.when)}; "
            f"highest {series.amount(highest.value)} on {day_text(highest.when)}."
        )
    return "\n".join(lines)


def medication_history(record: Record, arguments: dict) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    medications = record.medications
    note = ""
    if name:
        match = _matcher(name)
        scored = [(len(match(_medication_terms(item))), item) for item in medications]
        best = max((score for score, _ in scored), default=0)
        if best:
            medications = [item for score, item in scored if score == best]
        else:
            note = f"No medication matches “{name}”; showing the full medication history."
    groups: dict[str, list[dict]] = {}
    for medication in sorted(medications, key=lambda item: record.medication_period(item)[0] or date.min):
        concept = medication.get("medicationCodeableConcept", {})
        coding = (concept.get("coding") or [{}])[0]
        key = coding.get("display") or text_of(concept).split(" ")[0]
        groups.setdefault(key.capitalize(), []).append(medication)
    ordered = sorted(groups.items(), key=lambda group: max(record.medication_period(item)[0] or date.min for item in group[1]), reverse=True)
    blocks = [note] if note else []
    blocks += [f"{drug}:\n" + "\n".join(f"- {record.medication_line(item)}" for item in items) for drug, items in ordered]
    if not ordered:
        blocks = ["No medications are recorded."]
    return ToolResult(blocks, f"Checked the {name} medication history" if name and not note else "Checked the medication history")


def _medication_terms(medication: dict) -> str:
    concept = medication.get("medicationCodeableConcept", {})
    coding = (concept.get("coding") or [{}])[0]
    reason = text_of((medication.get("reasonCode") or [{}])[0])
    return " ".join([text_of(concept), coding.get("display", ""), reason, text_of(medication.get("statusReason"))])


def order_history(record: Record, arguments: dict) -> ToolResult:
    query = str(arguments.get("query") or "").strip()
    status = str(arguments.get("status") or "all").lower()
    orders = record.orders
    if status == "open":
        orders = [order for order in orders if order.get("status") == "active"]
    elif status == "completed":
        orders = [order for order in orders if order.get("status") != "active"]
    hidden = 0
    if query:
        match = _matcher(query)
        orders = [order for order in orders if match(f"{text_of(order.get('code'))} {_order_kind(order)} {_reason(order)}")]
    else:
        routine = [order for order in orders if _routine_lab(record, order)]
        hidden = len(routine)
        orders = [order for order in orders if order not in routine]
    open_orders = [order for order in orders if order.get("status") == "active"]
    closed = [order for order in orders if order.get("status") != "active"]
    blocks = []
    if open_orders:
        blocks.append("Open (no result on file):\n" + "\n".join(f"- {record.order_line(order)}" for order in open_orders))
    if closed:
        blocks.append("Completed or closed, newest first:\n" + "\n".join(f"- {record.order_line(order)}" for order in closed))
    if hidden:
        blocks.append(f"Plus {hidden} completed laboratory orders (use lab_series for their results).")
    if not blocks:
        blocks = [f"No orders match “{query}”." if query else "No orders are recorded."]
    return ToolResult(blocks, f"Checked orders for “{query}”" if query else "Checked orders and referrals")


def _routine_lab(record: Record, order: dict) -> bool:
    """A completed lab order whose results are plain values rather than a narrative report."""
    if order.get("status") == "active" or _order_kind(order) != "laboratory":
        return False
    return not any(ref in record.document_by_ref for ref in record.results_for.get(f"ServiceRequest/{order['id']}", []))


def _order_kind(order: dict) -> str:
    category = (order.get("category") or [{}])[0]
    return ORDER_KINDS.get(code_of(category) or "", text_of(category).lower())


def _reason(order: dict) -> str:
    return text_of((order.get("reasonCode") or [{}])[0])


HANDLERS: dict[str, Callable[[Record, dict], ToolResult]] = {
    "read_documents": read_documents,
    "search_record": search_record,
    "lab_series": lab_series,
    "medication_history": medication_history,
    "order_history": order_history,
}
