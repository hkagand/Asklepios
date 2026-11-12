"""Live help on each jotting of a visit: what the model reads from it, and what plain code checks against the record.

From the model (one short call per jotting, temperature 0):
  section   subjective, objective, assessment or plan
  covers    agenda items the jotting addresses
  links     record items it refers to (only ids the model was shown)
  gaps      up to three things a complete note would record about what the jotting raises and no jotting has yet
            ("pain severity"): documentation only. Anything that reads as advice is dropped by code.

From plain code:
  allergy   the jotting names a drug the patient is recorded as allergic to, or one of its class
  dose      the jotting gives a current dose of an ordered medicine that differs from the order
  covers    a medicine or allergy agenda item the jotting names is ticked
"""

from __future__ import annotations

import json
import re

from .llm import LlmClient, LlmError
from .loops import doses, ordered_doses
from .meds import drug_words
from .record import GROUPS, Record, code_of, ref_of, text_of
from .tools import fold

SECTIONS = ("subjective", "objective", "assessment", "plan")
NO_KNOWN_ALLERGY = "716186003"
# Drugs a recorded allergy also rules out, by the allergy's name.
ALLERGY_CLASSES = {
    "penicillin": (
        "penicillin", "amoxicillin", "amoxycillin", "ampicillin", "co-amoxiclav", "amoxiclav", "augmentin",
        "flucloxacillin", "piperacillin", "benzylpenicillin", "phenoxymethylpenicillin",
    ),
    "sulfonamide": ("sulfamethoxazole", "co-trimoxazole", "cotrimoxazole", "bactrim", "septrin", "sulfadiazine", "sulfasalazine"),
}
# A jotting that changes a medicine is a plan, not a report of the dose taken now.
CHANGE = re.compile(r"\b(increase|increased|decrease|decreased|reduce|reduced|start|started|stop|stopped|switch|change|titrate|up to|down to)\b", re.IGNORECASE)
# Gaps that read as advice rather than documentation.
ADVICE = re.compile(
    r"\b(start|prescribe|give|order|consider\w*|recommend\w*|rule out|diagnos\w*|refer\w*|test for|check for|treat\w*|increase|decrease|stop|medication change\w*)\b",
    re.IGNORECASE,
)
MAX_GAPS = 3

PROMPT = """\
You help a clinician document a visit while it happens. You get a summary of the patient's record (each line ends \
with its id in brackets), the visit agenda (each item starts with its id), the jottings so far, and one new jotting \
the clinician just typed.

Return only JSON: {"section": "...", "covers": [...], "links": [...], "gaps": [...]}
- "section": where the jotting belongs in the visit note: "subjective" (what the patient reports), "objective" \
(examination findings, measurements, results), "assessment" (the clinician's impression) or "plan" (what will be done).
- "covers": ids of agenda items this jotting addresses, e.g. ["A2"]; [] if none.
- "links": ids from the record summary that this jotting refers to, e.g. a result it discusses or a medicine it \
names; [] if none.
- "gaps": only for a subjective jotting (a complaint or symptom the patient reports): up to three details of it \
that a complete history records and that neither this jotting nor an earlier one gives, such as onset, duration, \
severity, character, what brings it on or eases it, associated symptoms. Short phrases, e.g. "pain severity", \
"duration of the fever". Documentation only: never suggest a diagnosis, test, treatment, dose or referral. [] for \
measurements, results, assessments and plans, and when nothing is missing.
Use only ids that appear in the summary or the agenda. Do not add facts the jotting does not state."""


def summary(record: Record) -> str:
    """The record lines the model may link to: problems, allergies, medicines, latest results."""
    lines = ["PROBLEMS", *(f"- {record.condition_line(item)}" for item in record.conditions)]
    lines += ["ALLERGIES", *(f"- {record.allergy_line(item)}" for item in record.allergies)]
    lines += ["MEDICINES", *(f"- {record.medication_line(item)}" for item in record.medications if item.get("status") in ("active", "on-hold"))]
    lines += [f"- {record.statement_line(item)}" for item in record.statements]
    lines.append("LATEST RESULTS")
    for group in GROUPS:
        lines += [f"- {record.latest_line(series)}" for series in record.series if series.group == group]
    return "\n".join(lines)


def known_ids(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Za-z]+/[A-Za-z0-9.\-]+", text))


async def model_review(llm: LlmClient, record: Record, agenda: list[dict], earlier: list[str], jotting: str) -> dict:
    """What the model reads from one jotting; ids and gaps are checked before they are kept."""
    context = summary(record)
    agenda_text = "\n".join(f"{item['id']}: {item['text']}" for item in agenda) or "(none)"
    earlier_text = "\n".join(f"- {text}" for text in earlier) or "(none)"
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"RECORD SUMMARY\n{context}\n\nAGENDA\n{agenda_text}\n\nJOTTINGS SO FAR\n{earlier_text}\n\nNEW JOTTING\n{jotting}"},
    ]
    for _ in range(2):
        message, _ = await llm.chat(messages, tools=[], tool_choice="none")
        found = re.search(r"\{.*\}", message.get("content") or "", re.DOTALL)
        try:
            data = json.loads(found.group()) if found else None
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            break
    else:
        raise LlmError("The model's reading of the jotting was not usable.")
    ids = known_ids(context)
    agenda_ids = {item["id"] for item in agenda}
    section = data.get("section") if data.get("section") in SECTIONS else None
    # Gaps are history-taking: kept only for what the patient reports.
    gaps = [str(gap).strip() for gap in data.get("gaps") or [] if str(gap).strip()] if section == "subjective" else []
    return {
        "section": section,
        "covers": [item for item in data.get("covers") or [] if item in agenda_ids],
        "links": list(dict.fromkeys(item for item in data.get("links") or [] if item in ids)),
        "gaps": [gap for gap in gaps if not ADVICE.search(gap)][:MAX_GAPS],
    }


def _names(text: str, words: tuple[str, ...]) -> bool:
    folded = fold(text)
    return any(re.search(rf"(?<![a-z]){re.escape(fold(word))}", folded) for word in words)


def allergy_alerts(record: Record, jotting: str) -> list[dict]:
    # A jotting about the allergy itself ("confirms penicillin allergy") is documentation, not a drug being given.
    if re.search(r"allerg", fold(jotting)):
        return []
    alerts = []
    for allergy in record.allergies:
        if code_of(allergy.get("code")) == NO_KNOWN_ALLERGY:
            continue
        substance = text_of(allergy.get("code"))
        words = (substance,) + next((drugs for name, drugs in ALLERGY_CLASSES.items() if name in fold(substance)), ())
        if _names(jotting, words):
            criticality = f" ({allergy['criticality']} criticality)" if allergy.get("criticality") else ""
            alerts.append({"kind": "allergy", "text": f"{substance} allergy on record{criticality}.", "refs": [ref_of(allergy)]})
    return alerts


def dose_alerts(record: Record, jotting: str, section: str | None) -> list[dict]:
    """A current dose in the jotting that differs from the active order; a planned change is not a discrepancy."""
    written = doses(jotting)
    if not written or section == "plan" or CHANGE.search(jotting):
        return []
    words = set(re.findall(r"[a-z]+", fold(jotting)))
    alerts = []
    for medication in record.medications:
        if medication.get("status") != "active":
            continue
        name = text_of(medication.get("medicationCodeableConcept"))
        if not drug_words(name) & words:
            continue
        ordered = ordered_doses(medication)
        if ordered and not set(written) & set(ordered):
            alerts.append({
                "kind": "dose",
                "text": f"The order for {name} is {', '.join(ordered)}; the jotting says {', '.join(written)}.",
                "refs": [ref_of(medication)],
            })
    return alerts


def code_covers(agenda: list[dict], jotting: str) -> list[str]:
    """Medicine and allergy agenda items the jotting names."""
    covered = []
    for item in agenda:
        if item["kind"] == "medication" and drug_words(item["text"].removeprefix("Confirm ")) & set(re.findall(r"[a-z]+", fold(jotting))):
            covered.append(item["id"])
        elif item["kind"] == "allergy" and re.search(r"allerg", fold(jotting)):
            covered.append(item["id"])
    return covered


async def review(llm: LlmClient, record: Record, agenda: list[dict], earlier: list[str], jotting: str) -> dict:
    """The full review of one jotting: the model's reading, then the code's checks."""
    try:
        reading = await model_review(llm, record, agenda, earlier, jotting)
        status = "done"
    except LlmError as error:
        reading, status = {"section": None, "covers": [], "links": [], "gaps": [], "error": str(error)}, "failed"
    alerts = allergy_alerts(record, jotting) + dose_alerts(record, jotting, reading["section"])
    covers = list(dict.fromkeys([*reading["covers"], *code_covers(agenda, jotting)]))
    links = [{"ref": ref, "label": record.label(ref)} for ref in reading["links"]]
    return reading | {"covers": covers, "links": links, "alerts": alerts, "status": status}
