"""Surgical history: every earlier operation the record shows, merged from Procedure records, notes and reports.

Operations done here are often Procedure resources; operations done elsewhere, or long ago, are often only a line in a
note ("Past surgical history: open appendicectomy 1996"). The model reads notes and reports that mention surgery and
lists the operations each states, quoting it word for word (SurgeryReader). Everything else is plain code:

  when      parsed from what the document says ("1996", "June 2015", "aged 22"), or the document date for an
            operation note; a Procedure gives its own date
  region    from words in the operation's name and body site (abdomen and pelvis, chest, head and neck, spine and
            limbs), "other" when no word is known, so nothing is hidden
  merging   mentions of the same kind of operation whose years fit together (one year apart at most) are one entry
            with all their sources; differing years are shown, not resolved
  searched  what was read, so "none recorded" says what it rests on

Planned or proposed operations are left out: open loops (loops.py) follows those.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .llm import LlmError
from .plans import NoteReader, plain
from .record import Document, Record, day_text, moment, ref_of, text_of
from .tools import fold

REGIONS = {
    "abdomen": "Abdomen and pelvis",
    "chest": "Chest",
    "head_neck": "Head and neck",
    "spine_limbs": "Spine and limbs",
    "other": "Other",
}
# Word beginnings, after fold() (lower case, no accents, "caesarean" -> "cesarean"). The first region with a match wins.
REGION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "abdomen",
        (
            "abdom", "append", "cholecyst", "gallbladder", "gall bladder", "bile duct", "biliary", "ercp", "sphincterotom",
            "hernia", "umbilic", "inguinal", "cesarean", "c-section", "hysterect", "oophorect", "salping", "ovar", "uter",
            "myomect", "colect", "hemicolect", "colon", "bowel", "intestin", "ileo", "ileum", "sigmoid", "rect", "anterior resection",
            "hartmann", "stoma", "colostom", "ileostom", "laparotom", "laparoscop", "gastr", "stomach", "bariatric", "splen",
            "pancrea", "whipple", "liver", "hepat", "nephr", "kidney", "ureter", "bladder", "cystect", "prostat", "adrenal",
            "pelvi", "periton", "diverticul", "fundoplic", "tubal", "sterilis", "steriliz", "ectopic",
        ),
    ),
    (
        "chest",
        (
            "thorac", "cardiac", "heart", "coronary", "cabg", "valve", "lung", "lobectom", "pneumonect", "mastect", "breast",
            "esophag", "pacemaker", "defibrillator", "port-a-cath", "portacath", "port a cath", "implanted port",
            "venous access", "sternotom",
        ),
    ),
    (
        "head_neck",
        (
            "thyroid", "parathyroid", "tonsil", "adenoid", "sinus", "cataract", "retin", "eye", "ear ", "tympan", "crani",
            "brain", "neck", "laryn", "parotid", "dental", "carotid",
        ),
    ),
    (
        "spine_limbs",
        (
            "knee", "hip", "shoulder", "elbow", "wrist", "ankle", "hand", "foot", "toe", "finger", "spine", "spinal",
            "lumbar", "lamin", "disc", "discect", "arthroplast", "arthroscop", "menisc", "ligament", "carpal", "fracture",
            "amputat", "varicose", "femor", "femur", "tibia", "humer", "bunion",
        ),
    ),
)
# Kinds of operation, for merging mentions of the same one. A name in none of them is its own kind.
FAMILIES: dict[str, tuple[str, ...]] = {
    "appendicectomy": ("appendic", "appendec"),
    "cholecystectomy": ("cholecystectom",),
    "hernia repair": ("hernia",),
    "caesarean section": ("cesarean", "c-section", "c section"),
    "hysterectomy": ("hysterectom",),
    "knee replacement": ("knee replacement", "knee arthroplast"),
    "hip replacement": ("hip replacement", "hip arthroplast"),
    "ercp": ("ercp", "sphincterotom"),
    "venous access port": ("port-a-cath", "portacath", "port a cath", "implanted port", "venous access port"),
    "thyroidectomy": ("thyroidectom",),
    "colectomy": ("colectom", "hemicolectom", "anterior resection", "hartmann"),
    "mastectomy": ("mastectom",),
    "coronary bypass": ("cabg", "coronary artery bypass"),
}
APPROACH_WORDS = (
    ("laparoscopic", ("laparoscop",)),
    ("robotic", ("robot",)),
    ("endoscopic", ("ercp", "endoscop", "sphincterotom")),
    ("percutaneous", ("percutaneous",)),
    ("open", ("open ", "laparotom", "abdominal hysterect")),
)
APPROACHES = ("open", "laparoscopic", "robotic", "endoscopic", "percutaneous")
SIDES = ("left", "right", "bilateral")
# A document is read only if it uses one of these: notes about anything else have no operations to find.
SURGICAL = re.compile(
    r"ectom|otom|ostom|plast|repair|operat|surg|resect|replacement|cesarean|caesarean|c-section|ercp|laparoscop|mesh|"
    r"clips|stent|bypass|transplant|port-a-cath|portacath|implant|amputat|graft|ablation|excision|scar|prosthe",
    re.IGNORECASE,
)
MONTH_NAMES = {name: number for number, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")), 1) for name in names}
NUMBER_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

PROMPT = """\
You list the operations and invasive procedures a patient has had, as one clinical note or report states them.

Include operations of any kind (open, laparoscopic, robotic); therapeutic endoscopic procedures that cut, remove or \
place something (ERCP with sphincterotomy or stone extraction, stenting); insertion of implanted devices (ports, \
pacemakers, joint prostheses); and an operation this document describes as being done on its own date.
Leave out operations that are planned, proposed, recommended, considered or discussed but not done; operations on \
family members; diagnostic tests (colonoscopy, endoscopy, imaging) and biopsies or polyps removed during them; \
cancelled operations; medicines and chemotherapy.

Return only JSON: {"operations": [...], "clues": [...], "none_stated": null}.
Each operation:
- "quote": the words that state it, copied exactly from one line (leave out list markers such as "- ").
- "name": the operation as written, e.g. "open appendicectomy", "laparoscopic cholecystectomy".
- "when": when it was done, as written: "1996", "June 2015", "aged 22", "10 years ago"; "this document" when the \
document itself records it being done on its date; null if not stated.
- "approach": "open", "laparoscopic", "robotic", "endoscopic" or "percutaneous" as the document says; null if not stated.
- "side": "left", "right" or "bilateral"; null if not stated.
- "elsewhere": true when the document says it was done at another hospital or abroad; otherwise false.
- "complications": complications stated, as written; [] if none or not stated.
- "implants": devices left in place, as written: mesh, prosthesis, port, stent; [] if none.
Each clue: indirect evidence of an earlier operation that the document does not state as an operation, such as \
surgical clips or post-surgical change on imaging, an absent organ, or healed scars: \
{"quote": "...", "finding": "<a few words>"}.
"none_stated": the exact words when the document says the patient has had no operations, e.g. "No previous \
operations."; otherwise null.
List each operation once per document. Do not add operations the document does not state."""


@dataclass(frozen=True)
class Operation:
    quote: str
    name: str
    when: str | None
    approach: str | None
    side: str | None
    elsewhere: bool
    complications: tuple[str, ...]
    implants: tuple[str, ...]


@dataclass(frozen=True)
class DocumentSurgery:
    operations: tuple[Operation, ...]
    clues: tuple[tuple[str, str], ...]  # (quote, finding)
    none_stated: str | None


class SurgeryReader(NoteReader[DocumentSurgery]):
    prompt = PROMPT
    version = 1
    what = "surgical history"

    def parse(self, reply: str, note_text: str) -> DocumentSurgery:
        found = re.search(r"\{.*\}", reply, re.DOTALL)
        if not found:
            raise ValueError("no JSON object in the reply")
        data = json.loads(found.group())
        if not isinstance(data, dict) or not isinstance(data.get("operations"), list):
            raise ValueError("the reply has no operations list")
        note = plain(note_text)

        def quoted(value: object) -> str | None:
            quote = str(value or "").strip().lstrip("-•* ").strip()
            return quote if quote and plain(quote) in note else None

        def words(value: object) -> tuple[str, ...]:
            return tuple(str(item).strip() for item in value if str(item).strip()) if isinstance(value, list) else ()

        operations = []
        for raw in data["operations"]:
            if not isinstance(raw, dict) or not (quote := quoted(raw.get("quote"))) or not str(raw.get("name") or "").strip():
                continue
            operations.append(
                Operation(
                    quote=quote,
                    name=str(raw["name"]).strip(),
                    when=str(raw["when"]).strip() if raw.get("when") else None,
                    approach=raw.get("approach") if raw.get("approach") in APPROACHES else None,
                    side=raw.get("side") if raw.get("side") in SIDES else None,
                    elsewhere=bool(raw.get("elsewhere")),
                    complications=words(raw.get("complications")),
                    implants=words(raw.get("implants")),
                )
            )
        clues = tuple(
            (quote, str(raw.get("finding") or "").strip())
            for raw in data.get("clues") or []
            if isinstance(raw, dict) and (quote := quoted(raw.get("quote")))
        )
        return DocumentSurgery(tuple(operations), clues, quoted(data.get("none_stated")))

    def dump(self, result: DocumentSurgery) -> object:
        return {
            "operations": [asdict(item) for item in result.operations],
            "clues": [list(item) for item in result.clues],
            "none_stated": result.none_stated,
        }

    def load(self, data: object) -> DocumentSurgery:
        return DocumentSurgery(
            tuple(
                Operation(**{**item, "complications": tuple(item["complications"]), "implants": tuple(item["implants"])})
                for item in data["operations"]
            ),
            tuple(tuple(item) for item in data["clues"]),
            data["none_stated"],
        )


# ----------------------------------------------------------------- reading code

def _has(folded: str, word: str) -> bool:
    return bool(re.search(rf"(?<![a-z]){re.escape(word)}", folded))


def region_of(*texts: str) -> str:
    folded = " ".join(fold(text) for text in texts if text) + " "
    return next((region for region, words in REGION_WORDS if any(_has(folded, word) for word in words)), "other")


def family_of(name: str) -> str:
    folded = fold(name)
    for family, words in FAMILIES.items():
        if any(_has(folded, word) for word in words):
            return family
    kept = [word for word in re.findall(r"[a-z]+", folded) if word not in ("open", "laparoscopic", "robotic", "left", "right", "with", "and", "the", "of")]
    return " ".join(kept)


def approach_of(name: str) -> str | None:
    folded = fold(name) + " "
    return next((approach for approach, words in APPROACH_WORDS if any(_has(folded, word) for word in words)), None)


@dataclass(frozen=True)
class When:
    day: date | None
    precision: str  # "day", "month", "year" or "none"
    approximate: bool = False

    @property
    def year(self) -> int | None:
        return self.day.year if self.day else None

    def text(self) -> str:
        if not self.day:
            return "date not recorded"
        if self.precision == "day":
            return day_text(self.day)
        if self.precision == "month":
            return day_text(self.day).split(" ", 1)[1]
        return f"about {self.day.year}" if self.approximate else str(self.day.year)


def parse_when(text: str | None, written: date, born: date | None) -> When:
    """A date from what a document says. "this document" is the document's own date."""
    if not text:
        return When(None, "none")
    folded = fold(text)
    if "this document" in folded or folded in ("today", "on this date"):
        return When(written, "day")
    if found := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", folded):
        return When(date(int(found[1]), int(found[2]), int(found[3])), "day")
    months = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
    if found := re.search(rf"\b(\d{{1,2}}) ({months})\.? (\d{{4}})\b", folded):
        return When(date(int(found[3]), MONTH_NAMES[found[2]], int(found[1])), "day")
    if found := re.search(rf"\b({months})\.?,? (\d{{4}})\b", folded):
        return When(date(int(found[2]), MONTH_NAMES[found[1]], 1), "month")
    if found := re.search(r"\b(19\d{2}|20\d{2})\b", folded):
        return When(date(int(found[1]), 1, 1), "year")
    if born and (found := re.search(r"\b(?:aged|age|at age|at the age of|at)\s+(\d{1,3})\b", folded)):
        return When(date(born.year + int(found[1]), 1, 1), "year", approximate=True)
    if found := re.search(rf"\b(\d{{1,2}}|{'|'.join(NUMBER_WORDS)}) years? ago\b", folded):
        count = int(found[1]) if found[1].isdigit() else NUMBER_WORDS[found[1]]
        return When(date(written.year - count, 1, 1), "year", approximate=True)
    return When(None, "none")


def procedure_when(record: Record, procedure: dict) -> When:
    performed = moment(procedure.get("performedDateTime") or procedure.get("performedPeriod", {}).get("start"))
    if performed:
        return When(performed.date(), "day")
    born = date.fromisoformat(record.patient["birthDate"]) if record.patient.get("birthDate") else None
    return parse_when(procedure.get("performedString"), record.today, born)


@dataclass
class Mention:
    name: str
    family: str
    region: str
    approach: str | None
    side: str | None
    when: When
    elsewhere: bool
    here: bool
    complications: tuple[str, ...]
    implants: tuple[str, ...]
    source: dict


@dataclass
class Entry:
    mentions: list[Mention] = field(default_factory=list)

    def fits(self, mention: Mention) -> bool:
        first = self.mentions[0]
        if mention.family != first.family:
            return False
        sides = {item.side for item in self.mentions if item.side}
        if mention.side and sides and mention.side not in sides:
            return False
        years = [item.when.year for item in self.mentions if item.when.year]
        return not mention.when.year or not years or all(abs(mention.when.year - year) <= 1 for year in years)

    def as_json(self) -> dict:
        mentions = self.mentions
        procedures = [item for item in mentions if item.source["kind"] == "procedure"]
        rank = {"day": 0, "month": 1, "year": 2, "none": 3}
        dated = sorted(
            (item for item in mentions if item.when.day),
            key=lambda item: (item.source["kind"] != "procedure", item.when.approximate, rank[item.when.precision]),
        )
        when = dated[0].when if dated else When(None, "none")
        years = sorted({item.when.year for item in mentions if item.when.year and not item.when.approximate})
        name = procedures[0].name if procedures else max((item.name for item in mentions), key=len)
        approach = next((item.approach for item in sorted(mentions, key=lambda item: item.source["kind"] != "procedure") if item.approach), None)
        region = next((item.region for item in procedures if item.region != "other"), None) or next(
            (item.region for item in mentions if item.region != "other"), "other"
        )
        here = any(item.here for item in mentions)
        return {
            "name": name[:1].upper() + name[1:],
            "date": when.day.isoformat() if when.day else None,
            "precision": when.precision,
            "when": when.text(),
            "year": when.year,
            "yearsDiffer": years if len(years) > 1 else [],
            "approach": approach,
            "side": next((item.side for item in mentions if item.side), None),
            "region": region,
            "regionLabel": REGIONS[region],
            "complications": unique(text for item in mentions for text in item.complications),
            "implants": unique(text for item in mentions for text in item.implants),
            "doneHere": here,
            "elsewhere": not here and any(item.elsewhere for item in mentions),
            "onlyInNotes": not procedures,
            "sources": unique_sources([item.source for item in mentions]),
        }


def unique(texts) -> list[str]:
    """Each text once, dropping one that a longer text already says ("mesh" beside "polypropylene mesh 6 × 6 cm")."""
    texts = sorted(dict.fromkeys(texts), key=len, reverse=True)
    kept: list[str] = []
    for text in texts:
        if not any(plain(text) in plain(other) for other in kept):
            kept.append(text)
    return kept


def unique_sources(sources: list[dict]) -> list[dict]:
    seen, kept = set(), []
    for source in sources:
        if (source["ref"], source.get("quote")) not in seen:
            seen.add((source["ref"], source.get("quote")))
            kept.append(source)
    return kept


def from_procedure(record: Record, procedure: dict) -> Mention:
    name = text_of(procedure.get("code")) or "Procedure"
    sites = " ".join(text_of(item) for item in procedure.get("bodySite", []))
    reported = procedure.get("asserter", {}).get("reference", "").startswith("Patient/")
    ref = ref_of(procedure)
    return Mention(
        name=name,
        family=family_of(name),
        region=region_of(name, sites),
        approach=approach_of(name),
        side=next((side for side in SIDES if _has(fold(f"{name} {sites}"), side)), None),
        when=procedure_when(record, procedure),
        elsewhere=reported,
        here=not reported,
        complications=tuple(text_of(item) for item in procedure.get("complication", []) if text_of(item)),
        implants=tuple(
            item.get("manipulated", {}).get("display", "") for item in procedure.get("focalDevice", [])
            if item.get("manipulated", {}).get("display")
        ),
        source={"ref": ref, "kind": "procedure", "label": record.label(ref), "quote": None},
    )


def from_document(record: Record, document: Document, operation: Operation) -> Mention:
    born = date.fromisoformat(record.patient["birthDate"]) if record.patient.get("birthDate") else None
    when = parse_when(operation.when, document.when.date(), born)
    # An operation note or procedure report recording the operation on its own date was done here.
    here = when.precision == "day" and when.day == document.when.date() and not operation.elsewhere
    return Mention(
        name=operation.name,
        family=family_of(operation.name),
        region=region_of(operation.name, operation.quote),
        approach=operation.approach or approach_of(operation.name),
        side=operation.side,
        when=when,
        elsewhere=operation.elsewhere,
        here=here,
        complications=operation.complications,
        implants=operation.implants,
        source={
            "ref": document.ref, "kind": document.kind, "label": record.label(document.ref), "quote": operation.quote,
            "date": document.when.date().isoformat(),
        },
    )


def mentions_surgery(document: Document) -> bool:
    return bool(SURGICAL.search(document.text))


async def surgical_history(record: Record, reader: SurgeryReader) -> dict:
    """Every earlier operation in the record, newest first, with sources; clues; and what was searched."""
    documents = [document for document in record.documents if document.when.date() <= record.today]
    read = [document for document in documents if mentions_surgery(document)]
    found = await asyncio.gather(*(reader.read(document) for document in read), return_exceptions=True)

    mentions = [from_procedure(record, procedure) for procedure in record.procedures]
    clues, none_stated, unread = [], [], []
    for document, result in sorted(zip(read, found), key=lambda pair: pair[0].when):
        if isinstance(result, LlmError):
            unread.append(document.ref)
            continue
        if isinstance(result, BaseException):
            raise result
        mentions += [from_document(record, document, operation) for operation in result.operations]
        source = {"ref": document.ref, "label": record.label(document.ref), "date": document.when.date().isoformat()}
        clues += [{**source, "quote": quote, "finding": finding} for quote, finding in result.clues]
        if result.none_stated:
            none_stated.append({**source, "quote": result.none_stated})

    entries: list[Entry] = []
    for mention in mentions:  # Procedure records first, then documents oldest first
        entry = next((entry for entry in entries if entry.fits(mention)), None)
        if entry is None:
            entries.append(Entry([mention]))
        else:
            entry.mentions.append(mention)
    operations = sorted((entry.as_json() for entry in entries), key=lambda item: item["date"] or "", reverse=True)

    notes = [document for document in documents if document.kind == "note"]
    reports = [document for document in documents if document.kind == "report"]
    earliest = min((document.when.date() for document in documents), default=None)
    return {
        "patient": record.id,
        "today": record.today.isoformat(),
        "operations": operations,
        "clues": clues,
        "noneStated": none_stated,
        "regions": REGIONS,
        "searched": {
            "procedures": len(record.procedures),
            "notes": len(notes),
            "reports": len(reports),
            "documentsRead": len(read),
            "earliest": earliest.isoformat() if earliest else None,
        },
        "unread": unread,
    }


def index_section(history: dict) -> str:
    """The SURGICAL HISTORY section of the chart index: each operation with its sources, then what was searched."""
    lines = []
    for operation in history["operations"]:
        parts = [
            f"{operation['name']}, {operation['when']}",
            operation["approach"] or "approach not recorded",
            REGIONS[operation["region"]].lower(),
        ]
        if operation["side"]:
            parts.append(operation["side"])
        if operation["implants"]:
            parts.append("implant: " + "; ".join(operation["implants"]))
        if operation["complications"]:
            parts.append("complications: " + "; ".join(operation["complications"]))
        if operation["yearsDiffer"]:
            parts.append("sources give different years: " + " and ".join(str(year) for year in operation["yearsDiffer"]))
        if operation["doneHere"]:
            parts.append("done at this hospital")
        elif operation["elsewhere"]:
            parts.append("done elsewhere")
        if operation["onlyInNotes"]:
            parts.append("only in notes, no procedure record")
        refs = ", ".join(dict.fromkeys(source["ref"] for source in operation["sources"]))
        lines.append("; ".join(parts) + f" [{refs}]")
    lines += [f'Sign of earlier surgery, {clue["finding"]}: "{clue["quote"]}" [{clue["ref"]}]' for clue in history["clues"]]
    lines += [f'A note states: "{item["quote"]}" [{item["ref"]}]' for item in history["noneStated"]]
    searched = history["searched"]
    since = f" since {day_text(date.fromisoformat(searched['earliest']))}" if searched["earliest"] else ""
    head = (
        "SURGICAL HISTORY: earlier operations from procedure records, notes and reports, newest first. Searched "
        f"{searched['procedures']} procedure records, {searched['notes']} notes and {searched['reports']} reports{since}; "
        "operations done elsewhere may not be recorded."
    )
    return head + "\n" + "\n".join(f"- {line}" for line in lines or ["no operations recorded"])
