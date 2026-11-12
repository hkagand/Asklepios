"""Reads the follow-up plan out of a clinical note: what was to be done, and by when.

The model only extracts. Every item must quote the note word for word or it is dropped; due dates, matching against
the record and statuses are worked out in loops.py. Results are cached on disk per note text, model and prompt, so a
note is read once.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Generic, TypeVar

from .citations import PLAIN
from .llm import LlmClient, LlmError
from .record import Document, day_text

T = TypeVar("T")

PROMPT_VERSION = 4
KINDS = ("lab", "imaging", "procedure", "referral", "visit", "contact", "meeting", "medication", "conditional", "advice")
ACTIONS = ("start", "increase", "decrease", "stop", "hold", "continue")
DUE_TYPES = ("date", "within", "before_next_visit", "with_next_bloods", "none")

PROMPT = """\
You extract the follow-up plan from one clinical note. List every action the note says should happen after the visit: \
tests, imaging, procedures, referrals, follow-up visits, phone calls or other contacts, meetings such as a tumour \
board, and medication changes. Read the whole note: mostly the plan, but also planned actions written elsewhere, for \
example in the assessment. Leave out what was done at the visit itself.

Return only JSON: {"items": [...]}, one object per action, with these fields:
- "quote": the words of the note that state this action, copied exactly. Part of one line is fine; never join lines; \
leave out list markers such as "- ".
- "kind": one of
  "lab" blood or urine tests; "imaging" CT, MRI, ultrasound, X-ray, echocardiogram; "procedure" endoscopy, biopsy and \
similar; "referral" to another service or clinic; "visit" a follow-up appointment with this clinic; "contact" a \
phone call, nurse review or message; "meeting" a tumour board or other multidisciplinary meeting; "medication" start, \
change, stop or hold a drug; "conditional" an action only to be taken if something happens, including safety-net \
advice such as "return if the bleeding increases"; "advice" lifestyle \
advice, monitoring at home, continuing unchanged treatment, or something decided against.
- "tests": for lab, imaging and procedure, each test named, as written, e.g. ["HbA1c", "basic metabolic panel"]; \
otherwise [].
- "service": for referral, visit, contact and meeting, which clinic, person or meeting, e.g. "ophthalmology", \
"heart failure nurse", "tumour board"; otherwise null.
- "drug" and "action": for medication, the drug name and one of "start", "increase", "decrease", "stop", "hold", \
"continue"; otherwise null.
- "dose": for medication started or changed, the new dose as written, e.g. "80 mg once daily for 7 days, then 40 mg" \
or "75 micrograms once daily"; otherwise null.
- "due": when it should happen, as the note says:
  {"type": "date", "value": "YYYY-MM-DD"} for a calendar date;
  {"type": "within", "value": "3 months"} for a period from the note date, e.g. "in 1 week", "in 6-8 weeks";
  {"type": "before_next_visit", "value": null}; {"type": "with_next_bloods", "value": null};
  {"type": "none", "value": null} when no time is given.
Every line of the plan must be covered by at least one item; use "advice" for a line with nothing to follow up. Split \
a line that asks for several actions into one item per action, each quoting its own words, e.g. "Stop doxycycline and \
ondansetron" is two medication items. A step that follows a period is its own item, due within that period: in \
"Continue iron for 3 months, then stop" the stop is due within 3 months. One test entry per test or scan; a scan of \
several body regions is one entry. Do not add actions the note does not state and do not interpret results."""

PLAN_HEADINGS = re.compile(r"^(PLAN|RECOMMENDATIONS?|FOLLOW[- ]UP)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PlanItem:
    quote: str
    kind: str
    tests: tuple[str, ...]
    service: str | None
    drug: str | None
    action: str | None
    due_type: str
    due_value: str | None
    dose: str | None = None


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(PLAIN)).strip().lower()


def _text(value: object) -> str | None:
    return (str(value).strip() if value is not None else "") or None


def plan_lines(note_text: str) -> list[str]:
    """The list lines under the note's PLAN (or RECOMMENDATION) heading; empty when the note has no such heading."""
    lines, inside = [], False
    for line in note_text.splitlines():
        stripped = line.strip()
        if stripped and stripped == stripped.upper() and re.search(r"[A-Z]{3}", stripped):
            inside = bool(PLAN_HEADINGS.match(stripped))
        elif inside and re.match(r"([-•*]|\d{1,2}[.)])\s+", stripped):
            lines.append(re.sub(r"^([-•*]|\d{1,2}[.)])\s+", "", stripped))
    return lines


def uncovered(note_text: str, items: list[PlanItem]) -> list[str]:
    quotes = [plain(item.quote) for item in items]
    return [line for line in plan_lines(note_text) if not any(quote in plain(line) for quote in quotes)]


def parse(reply: str, note_text: str) -> list[PlanItem]:
    """The items in a model reply that quote the note exactly. Raises ValueError when the reply is not usable JSON."""
    found = re.search(r"\{.*\}", reply, re.DOTALL)
    if not found:
        raise ValueError("no JSON object in the reply")
    data = json.loads(found.group())
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("the reply has no items list")
    note = plain(note_text)
    items = []
    for raw in data["items"]:
        if not isinstance(raw, dict):
            continue
        quote = str(raw.get("quote") or "").strip().lstrip("-•* ").strip()
        kind = raw.get("kind")
        if not quote or plain(quote) not in note or kind not in KINDS:
            continue
        due = raw.get("due") if isinstance(raw.get("due"), dict) else {}
        due_type = due.get("type") if due.get("type") in DUE_TYPES else "none"
        tests = raw.get("tests") if isinstance(raw.get("tests"), list) else []
        items.append(
            PlanItem(
                quote=quote,
                kind=kind,
                tests=tuple(str(test).strip() for test in tests if str(test).strip()),
                service=_text(raw.get("service")),
                drug=_text(raw.get("drug")),
                action=raw.get("action") if raw.get("action") in ACTIONS else None,
                due_type=due_type,
                due_value=_text(due.get("value")) if due_type in ("date", "within") else None,
                dose=_text(raw.get("dose")) if kind == "medication" else None,
            )
        )
    return items


class NoteReader(Generic[T]):
    """Reads one structured result out of a clinical note with the model. Each note is read once: the result is cached
    on disk per note text, model and prompt version. Subclasses give the prompt and how to parse and check a reply."""

    prompt: str
    version: int
    what: str

    def __init__(self, llm: LlmClient, cache_dir: Path, *, concurrency: int = 4) -> None:
        self._llm = llm
        self._cache_dir = cache_dir
        self._gate = asyncio.Semaphore(concurrency)
        self._running: dict[Path, asyncio.Task[T]] = {}

    def parse(self, reply: str, note_text: str) -> T:
        """The result in a model reply. Raises ValueError (or JSONDecodeError) when the reply is not usable."""
        raise NotImplementedError

    def missed(self, note_text: str, result: T) -> list[str]:
        """Lines of the note the result should cover and does not; asked for again once."""
        return []

    def dump(self, result: T) -> object:
        raise NotImplementedError

    def load(self, data: object) -> T:
        raise NotImplementedError

    async def read(self, document: Document) -> T:
        key = hashlib.sha256(f"{self.version}\n{self._llm.model}\n{document.text}".encode()).hexdigest()[:16]
        path = self._cache_dir / f"{document.ref.replace('/', '_')}-{key}.json"
        if path.exists():
            return self.load(json.loads(path.read_text(encoding="utf-8")))
        task = self._running.get(path)
        if task is None:
            task = self._running[path] = asyncio.create_task(self._extract(document, path))
            task.add_done_callback(lambda _: self._running.pop(path, None))
        return await asyncio.shield(task)

    async def _extract(self, document: Document, path: Path) -> T:
        heading = f"Note written on {day_text(document.when)}" + (f" by {document.author}" if document.author else "")
        messages = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": f"{heading}\n\n{document.text.strip()}"},
        ]
        best: T | None = None
        problem = ""
        async with self._gate:
            for attempt in range(3):
                message, _ = await self._llm.chat(messages, tools=[], tool_choice="none")
                reply = message.get("content") or ""
                try:
                    result = self.parse(reply, document.text)
                except (ValueError, json.JSONDecodeError) as error:
                    problem = str(error)
                    continue
                missed = self.missed(document.text, result)
                if best is None or len(missed) < len(self.missed(document.text, best)):
                    best = result
                if not missed or attempt == 2:
                    break
                # One more try, naming the lines nothing quotes.
                listed = "\n".join(f"- {line}" for line in missed)
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": f"These lines have no item:\n{listed}\nReturn the complete list again."},
                ]
        if best is None:
            raise LlmError(f"Could not read the {self.what} of {document.ref}: {problem}.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.dump(best), ensure_ascii=False, indent=1), encoding="utf-8")
        return best


class PlanExtractor(NoteReader[list[PlanItem]]):
    prompt = PROMPT
    version = PROMPT_VERSION
    what = "plan"

    async def items(self, document: Document) -> list[PlanItem]:
        """The plan items of one note."""
        return await self.read(document)

    def parse(self, reply: str, note_text: str) -> list[PlanItem]:
        return parse(reply, note_text)

    def missed(self, note_text: str, result: list[PlanItem]) -> list[str]:
        return uncovered(note_text, result)

    def dump(self, result: list[PlanItem]) -> object:
        return [asdict(item) for item in result]

    def load(self, data: object) -> list[PlanItem]:
        return [PlanItem(**{**item, "tests": tuple(item["tests"])}) for item in data]
