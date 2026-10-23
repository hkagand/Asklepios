"""Splits the model's answer into statements with citations, and checks them.

A citation only counts if the model was shown that id in this conversation (in
the chart index or a tool result). Numbers, percentages and dates in a cited
statement must appear in the text that came with the cited ids; anything else is
flagged for the reader.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

TYPES = (
    "Patient",
    "Observation",
    "DiagnosticReport",
    "DocumentReference",
    "Condition",
    "MedicationRequest",
    "ServiceRequest",
    "Encounter",
    "AllergyIntolerance",
    "Appointment",
)
REF = re.compile(r"\b(?:%s)/[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,62}[A-Za-z0-9])?" % "|".join(TYPES))
BRACKETS = re.compile(r"\s*(?:\[([^\[\]\n]{1,400})\]|【([^【】\n]{1,400})】|\(([^()\n]{1,400})\))")
FILLER = {"", "and", "&", "see", "also", "e.g.", "ref", "refs", "source", "sources"}
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%|%\s?(\d+(?:\.\d+)?)")
UNITS = {
    unit.lower(): unit
    for unit in "mm cm kg mg mcg µg mL g/dL mg/dL g/L mg/L mmol/L µmol/L ng/mL ng/dL pg/mL U/L IU/L mmHg mg/kg mg/m² fL bpm".split()
} | {"mg/m2": "mg/m²", "umol/l": "µmol/L", "ug": "µg"}
QUANTITY = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s?(%s)(?![\w/])" % "|".join(map(re.escape, sorted(UNITS, key=len, reverse=True))),
    re.IGNORECASE,
)
TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
MONTHS = {
    "Jan": ("January", "Ocak", "Oca"),
    "Feb": ("February", "Şubat", "Şub"),
    "Mar": ("March", "Mart"),
    "Apr": ("April", "Nisan", "Nis"),
    "May": ("Mayıs",),
    "Jun": ("June", "Haziran", "Haz"),
    "Jul": ("July", "Temmuz", "Tem"),
    "Aug": ("August", "Ağustos", "Ağu"),
    "Sep": ("Sept", "September", "Eylül", "Eyl"),
    "Oct": ("October", "Ekim", "Eki"),
    "Nov": ("November", "Kasım", "Kas"),
    "Dec": ("December", "Aralık", "Ara"),
}
MONTH_NAMES = {name: short for short, names in MONTHS.items() for name in (short, *names)}
_MONTH = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
# "7 Jul 2026", "July 7, 2026", "Jul 2026" and "7 Jul".
DATE = re.compile(
    rf"\b(?:(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH})\b\.?"
    rf"|(?P<month2>{_MONTH})\b\.?\s+(?P<day2>\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"|(?P<month3>{_MONTH})\b\.?)"
    rf"(?:,?\s+(?P<year>\d{{4}})\b)?"
)
# A line that is only a bold label, e.g. "**Since last visit**:" — a heading, not a statement.
LABEL = re.compile(r"\*\*([^*]{1,80})\*\*\s*[:\-–—]?\s*")

# Models often write non-breaking hyphens, minus signs and narrow spaces.
PLAIN = str.maketrans(
    {**dict.fromkeys("\u2010\u2011\u2012\u2212", "-"), **dict.fromkeys("\u00a0\u2007\u2009\u202f", " ")}
)


def facts_in(text: str) -> list[str]:
    """Dates, times, percentages, measurements and other numbers in the text, written one way.

    For example "7 Jul 2026", "10:30", "26%", "13 mm" and "9.8".
    """
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text.translate(PLAIN))
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    facts: list[str] = []

    def take(fact: str) -> str:
        facts.append(fact)
        return " "

    def date(match: re.Match) -> str:
        day, year = match["day"] or match["day2"], match["year"]
        if not (day or year):
            return match.group()
        month = MONTH_NAMES[match["month"] or match["month2"] or match["month3"]]
        return take(" ".join(part for part in (day and str(int(day)), month, year) if part))

    text = DATE.sub(date, text)
    text = TIME.sub(lambda match: take(f"{int(match[1])}:{match[2]}"), text)
    text = PERCENT.sub(lambda match: take(_number(match[1] or match[2]) + "%"), text)
    text = QUANTITY.sub(lambda match: take(f"{_number(match[1])} {UNITS[match[2].lower()]}"), text)
    facts += [_number(number) for number in NUMBER.findall(text)]
    return list(dict.fromkeys(facts))


def _number(text: str) -> str:
    return f"{float(text):f}".rstrip("0").rstrip(".")


def _implied(facts: list[str]) -> set[str]:
    """What a source supports: "7 Jul 2026" also backs "Jul 2026", "7 Jul" and "2026"; "26%" and "26 mm" back "26"."""
    implied = set(facts)
    for fact in facts:
        parts = fact.split()
        if fact.endswith("%"):
            implied.add(fact[:-1])
        elif len(parts) == 3:
            implied |= {" ".join(parts[1:]), " ".join(parts[:2]), parts[2]}
        elif len(parts) == 2 and parts[1].isdigit():
            implied.add(parts[1])
        elif len(parts) == 2 and parts[1].lower() in UNITS:
            implied.add(parts[0])
    return implied


def _checkable(facts: list[str]) -> list[str]:
    """Single-digit counts ("2 cycles", "grade 1") are too common to check; dates, percentages and measurements are."""
    return [fact for fact in facts if not fact.isdigit() or int(fact) >= 10]


class Evidence:
    """Every id the model has been shown in this conversation, with the facts shown alongside it."""

    def __init__(self) -> None:
        self._facts: dict[str, set[str]] = defaultdict(set)
        self.everything: set[str] = set()

    def add(self, block: str) -> None:
        refs = set(REF.findall(block))
        facts = _implied(facts_in(REF.sub("", block)))
        self.everything |= facts
        for ref in refs:
            self._facts[ref] |= facts

    def seen(self, ref: str) -> bool:
        return ref in self._facts

    def facts(self, refs: list[str]) -> set[str]:
        return set().union(*(self._facts[ref] for ref in refs if ref in self._facts))


@dataclass
class Block:
    kind: str
    level: int
    text: str


def split_blocks(text: str) -> list[Block]:
    """Paragraphs, bullets and headings of a markdown answer."""
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", 0, " ".join(paragraph)))
            paragraph.clear()

    for line in text.translate(PLAIN).splitlines():
        stripped = line.strip()
        if not stripped or re.fullmatch(r"[-*_]{3,}", stripped):
            flush()
            continue
        indent = len(line) - len(line.lstrip())
        if heading := re.match(r"#{1,6}\s+(.*)", stripped):
            flush()
            blocks.append(Block("heading", 0, heading.group(1).strip("*")))
        elif bullet := re.match(r"(?:[-*•+]|\d{1,2}[.)])\s+(.*)", stripped):
            flush()
            if label := LABEL.fullmatch(bullet.group(1)):
                blocks.append(Block("heading", 0, label.group(1)))
            else:
                blocks.append(Block("bullet", 1 if indent >= 2 else 0, bullet.group(1)))
        elif label := LABEL.fullmatch(stripped):
            flush()
            blocks.append(Block("heading", 0, label.group(1)))
        elif stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
                flush()
                blocks.append(Block("bullet", 0, " · ".join(cell for cell in cells if cell)))
        else:
            paragraph.append(stripped)
    flush()
    return blocks


def segments(text: str, resolve: Callable[[str], str | None]) -> list[dict]:
    """Text pieces and citation groups, e.g. [{"text": "Hb 9.8 g/dL"}, {"cite": ["Observation/obs-1"]}]."""
    pieces: list[dict] = []
    position = 0
    for match in BRACKETS.finditer(text):
        refs = _citation(next(group for group in match.groups() if group is not None), resolve)
        if refs is None:
            continue
        pieces.append({"text": text[position : match.start()]})
        pieces.append({"cite": refs})
        position = match.end()
    pieces.append({"text": text[position:]})

    result: list[dict] = []
    for piece in pieces:
        if "cite" in piece:
            result.append(piece)
            continue
        position = 0
        for match in REF.finditer(piece["text"]):
            result += [{"text": piece["text"][position : match.start()]}, {"cite": [resolve(match.group()) or match.group()]}]
            position = match.end()
        result.append({"text": piece["text"][position:]})
    return [piece for piece in result if piece.get("cite") or piece.get("text")]


def _citation(body: str, resolve: Callable[[str], str | None]) -> list[str] | None:
    """The ids in a bracket, or None if the bracket holds ordinary text."""
    refs = []
    for token in re.split(r"[,;\s]+", body.strip()):
        token = token.strip(".:'\"`*")
        if token.lower() in FILLER:
            continue
        if expanded := _range(token, resolve):
            refs += expanded
        elif REF.fullmatch(token):
            refs.append(resolve(token) or token)
        elif resolved := resolve(token):
            refs.append(resolved)
        else:
            return None
    return refs or None


def _range(token: str, resolve: Callable[[str], str | None]) -> list[str] | None:
    """Shorthand such as "MedicationRequest/med-4-004-006" for med-4-004, med-4-005 and med-4-006."""
    match = re.fullmatch(r"(.+-)(\d+)-(\d+)", token)
    if not match or resolve(token):
        return None
    prefix, first, last = match.groups()
    if len(first) != len(last) or not 0 < int(last) - int(first) <= 10:
        return None
    refs = []
    for number in range(int(first), int(last) + 1):
        ref = resolve(f"{prefix}{number:0{len(first)}d}")
        if ref is None:
            return None
        refs.append(ref)
    return refs


def verify(text: str, *, evidence: Evidence, resolve: Callable[[str], str | None], label: Callable[[str], str], context: str) -> dict:
    """The answer as blocks for the chat panel, each with a verification status.

    ok          every number and date is in what the assistant read, normally in the cited sources; an uncited
                summary counts when its numbers and dates are in sources cited elsewhere in the answer
    check       cited, but some numbers or dates appear nowhere in what the assistant read, or some ids were never shown
    unsourced   a bullet, or a sentence with numbers, that cites nothing
    unsupported every cited id is one the model was never shown; hidden by default
    plain       framing text with nothing to check
    """
    allowed = _implied(facts_in(context))
    parsed = []
    for block in split_blocks(text):
        parts = segments(block.text, resolve)
        cited = list(dict.fromkeys(ref for part in parts for ref in part.get("cite", [])))
        parsed.append((block, parts, [ref for ref in cited if evidence.seen(ref)], [ref for ref in cited if not evidence.seen(ref)]))
    backing = evidence.facts([ref for *_, known, _ in parsed for ref in known])

    blocks, sources = [], {}
    for block, parts, known, unknown in parsed:
        issues = []
        if unknown and known:
            parts = [
                {"cite": [ref for ref in part["cite"] if ref in known]} if "cite" in part else part
                for part in parts
                if "text" in part or any(ref in known for ref in part["cite"])
            ]
            issues.append("Removed citations to records the assistant had not opened: " + ", ".join(unknown))
        claims = [fact for fact in _checkable(facts_in(" ".join(part.get("text", "") for part in parts))) if fact not in allowed]
        if block.kind == "heading":
            status = "plain"
        elif unknown and not known:
            status = "unsupported"
            issues.append("Cites records the assistant had not opened: " + ", ".join(unknown))
        elif known:
            missing = [fact for fact in claims if fact not in evidence.facts(known)]
            unseen = [fact for fact in missing if fact not in evidence.everything]
            elsewhere = [fact for fact in missing if fact in evidence.everything]
            if unseen:
                issues.append("Not found in anything the assistant read: " + ", ".join(unseen))
            status = "check" if issues else "ok"
            if elsewhere:
                issues.append("From other parts of the record than the cited sources: " + ", ".join(elsewhere))
        elif claims and all(fact in backing for fact in claims):
            status = "ok"
            issues.append("Backed by sources cited elsewhere in this answer")
        elif not claims and block.text.rstrip("*").endswith(":"):
            status = "plain"
        elif claims or block.kind == "bullet":
            status = "unsourced"
            issues.append("No source cited")
        else:
            status = "plain"
        for ref in known:
            sources[ref] = {"label": label(ref)}
        blocks.append({"kind": block.kind, "level": block.level, "segments": parts, "status": status, "issues": issues})
    return {"blocks": blocks, "sources": sources}
