"""Clinical considerations during a visit, from a second, clinical model. Experimental, and off unless configured.

A clinical model (for example MedGemma 1.5 4B on a local Ollama: CLINICAL_LLM_BASE_URL and CLINICAL_LLM_MODEL) reads
the record and the jottings so far and suggests up to four things the clinician may want to keep in mind:
  cause     a possible explanation of what the jottings describe
  check     something worth asking, examining or checking
  caution   something in the record that bears on what the jottings describe or plan
They are for the clinician to weigh, not facts: they are never written into the note or to FHIR, and the code alerts
of jottings.py stay the safety net (a small model can miss an allergy, or state a wrong rule with confidence).

The model cites its basis by short ids: J1 for a jotting, R1 for a record item. Code keeps a consideration only if
  - it cites at least one jotting of this visit, and only ids it was shown
  - every number in it appears in what it cites
  - it does not admit to resting on something the record does not state, and is not the prompt's example
and marks one that cites a record item a code alert in this visit already names.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from .llm import LlmClient, LlmError
from .notes import numbers_in
from .record import FLAGS, GROUPS, Record, ref_of
from .visits import Visit

KINDS = ("cause", "check", "caution")
MAX_ITEMS = 4
REF = re.compile(r"\s*\[[A-Za-z]+/[A-Za-z0-9.\-]+\]")
# Values that stand alone ("38.4", "500 mg"), not digits in a name such as HbA1c, B12 or COVID-19.
VALUE = re.compile(r"(?<![\w\-.,])\d+(?:[.,]\d+)?(?![A-Za-z\d])")
# A consideration that says it rests on what the record does not state.
UNSUPPORTED = re.compile(r"\bnot (?:explicitly |specifically )?(?:stated|mentioned|documented|recorded|given)\b|\bassum\w*\b", re.IGNORECASE)

# The worked example in the prompt; a small model sometimes copies it as an answer.
EXAMPLE = [
    {"kind": "cause", "text": "A dry cough can be a side effect of an ACE inhibitor such as lisinopril.", "basis": ["J1", "R2"]},
    {"kind": "check", "text": "Ask about fever, sputum, breathlessness and smoking to judge other causes of the cough.", "basis": ["J1"]},
]
MAX_TOKENS = 800  # four short considerations; a small model left unbounded can run on for minutes

PROMPT = f"""\
You support a physician during a clinic visit. You get the physician's jottings so far (J1, J2...) and the patient's \
record (R1, R2...): problems, allergies, medicines and abnormal results.

Give two to four clinical considerations about what the jottings describe or plan, most important first. Each is one of:
- "cause": a possible explanation of a complaint or finding in a jotting
- "check": something worth asking, examining or checking about what a jotting describes
- "caution": a record item that bears on what a jotting describes or plans (an allergy, a condition, a medicine, a result)
Each is one or two sentences and cites its basis: the jotting it follows from and the one to three record items it \
uses. Use only facts in the jottings and the record; give no numbers they do not contain. Do not restate the record.

Example. Jottings: J1: Cough for 3 weeks, dry. Record: R1: Essential hypertension. R2: Lisinopril 10 mg once daily.
{json.dumps({"considerations": EXAMPLE})}

Return only a JSON object in that form."""


def record_items(record: Record) -> list[tuple[str, str]]:
    """(line, ref) for each record item the model may cite: problems, allergies, medicines, and the latest result of
    each test only when it is abnormal. A small model given the whole record recites it instead of thinking about the
    jottings, so it gets less."""
    items = [(record.condition_line(item), ref_of(item)) for item in record.conditions]
    items += [(record.allergy_line(item), ref_of(item)) for item in record.allergies]
    items += [(record.medication_line(item), ref_of(item)) for item in record.medications if item.get("status") in ("active", "on-hold")]
    items += [(record.statement_line(item), ref_of(item)) for item in record.statements]
    for group in GROUPS:
        for series in record.series:
            last = series.points[-1]
            if series.group == group and last.flag in FLAGS:
                reference = f"; reference {series.range}" if series.range else ""
                items.append((f"Latest {series.name}: {series.reading(last)}{reference}", last.ref))
    return [(REF.sub("", line).strip(), ref) for line, ref in items]


def basis(record: Record, visit: Visit) -> dict[str, dict]:
    """What may be cited, by short id: each jotting, and each record item with its FHIR reference."""
    shown = {jotting.id: {"text": jotting.text} for jotting in visit.jottings}
    for number, (line, ref) in enumerate(record_items(record), 1):
        shown[f"R{number}"] = {"text": line, "ref": ref}
    return shown


def signature(visit: Visit) -> list[list[str]]:
    """The jottings a set of considerations was made from; a later change makes it stale."""
    return [[jotting.id, jotting.text] for jotting in visit.jottings]


def _parse(reply: str) -> list[dict]:
    """The considerations in a reply: {"considerations": [...]}, or the bare list a small model sometimes gives,
    possibly in a code fence and followed by other text."""
    start = re.search(r"[\[{]", reply)
    if not start:
        raise ValueError("no JSON in the reply")
    data, _ = json.JSONDecoder().raw_decode(reply[start.start():])
    if isinstance(data, dict):
        data = data.get("considerations")
    if not isinstance(data, list):
        raise ValueError("no considerations list")
    return [item for item in data if isinstance(item, dict)]


def values(text: str) -> set[str]:
    return numbers_in(" ".join(VALUE.findall(text)))


def check(items: list[dict], shown: dict[str, dict], alerted: set[str]) -> tuple[list[dict], list[dict]]:
    """The considerations kept, with their basis; and those dropped, with why."""
    kept, dropped = [], []
    for item in items:
        text = " ".join(str(item.get("text", "")).split())
        kind = item.get("kind") if item.get("kind") in KINDS else "check"
        cited = list(dict.fromkeys(str(source).strip() for source in item.get("basis") or []))
        if not text:
            continue
        reason = None
        if unknown := [source for source in cited if source not in shown]:
            reason = f"cites {', '.join(unknown)}, which it was not shown"
        elif not any(source.startswith("J") for source in cited):
            reason = "rests on no jotting of this visit"
        elif missing := sorted(values(text) - numbers_in(" ".join(shown[source]["text"] for source in cited))):
            reason = f"{', '.join(missing)} is not in what it cites"
        elif UNSUPPORTED.search(text):
            reason = "rests on something the record does not state"
        elif any(text == example["text"] for example in EXAMPLE):
            reason = "copies the prompt's example"
        elif any(text == other["text"] for other in kept):
            reason = "repeats another consideration"
        if reason:
            dropped.append({"kind": kind, "text": text, "reason": reason})
            continue
        refs = [shown[source].get("ref") for source in cited]
        kept.append({
            "kind": kind,
            "text": text,
            "basis": [{"id": source, "ref": shown[source].get("ref")} for source in cited],
            "alerted": any(ref in alerted for ref in refs if ref),
        })
    return kept[:MAX_ITEMS], dropped + [{**item, "reason": "beyond the first four"} for item in kept[MAX_ITEMS:]]


async def consider(llm: LlmClient, record: Record, visit: Visit) -> dict:
    """The clinical model's considerations for the visit so far, checked; "status" is "done" or "failed"."""
    shown = basis(record, visit)
    lines = "\n".join(f"{source}: {item['text']}" for source, item in shown.items() if source.startswith("R")) or "(nothing recorded)"
    jottings = "\n".join(f"{jotting.id}: {jotting.text}" for jotting in visit.jottings)
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"JOTTINGS\n{jottings}\n\nRECORD\n{lines}"},
    ]
    result: dict = {"model": llm.model, "jottings": signature(visit), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    started = time.perf_counter()
    problem = ""
    try:
        for _ in range(2):
            message, usage = await llm.chat(messages, tools=[], tool_choice="none", json_mode=True, max_tokens=MAX_TOKENS)
            try:
                items = _parse(message.get("content") or "")
                break
            except (ValueError, json.JSONDecodeError) as error:
                problem = str(error)
        else:
            raise LlmError(f"The clinical model's answer was not usable ({problem}).")
    except LlmError as error:
        return result | {"status": "failed", "error": str(error), "seconds": round(time.perf_counter() - started, 1)}
    alerted = {ref for jotting in visit.jottings for alert in (jotting.review or {}).get("alerts", []) for ref in alert.get("refs", [])}
    kept, dropped = check(items, shown, alerted)
    for item in kept:
        for source in item["basis"]:
            source["label"] = record.label(source["ref"]) if source["ref"] else shown[source["id"]]["text"]
    return result | {
        "status": "done",
        "items": kept,
        "dropped": dropped,
        "seconds": round(time.perf_counter() - started, 1),
        "promptTokens": usage.get("prompt_tokens"),
    }
