"""Checks live help on visit jottings (agent/jottings.py) against evals/visits.toml: python -m evals --visits

Each scripted visit gets its agenda from the record as the agent builds it (open loops and reconciliation from the
cache), then its jottings are reviewed in order, each seeing the earlier ones, and agenda items they cover are ticked.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings
from agent.jottings import review
from agent.notes import draft as draft_note
from agent.notes import note_text, numbers_in, section_text, values
from agent.record import Document
from agent.llm import LlmClient
from agent.loops import open_loops
from agent.meds import MedicationReader, reconcile
from agent.plans import PlanExtractor
from agent.record import Record
from agent.visits import Jotting, Visit, todays_appointment
from agent.visits import agenda as build_agenda

from .run import says

# Stricter than the agent's own filter: no gap may name an action.
ADVICE = re.compile(r"\b(start|prescrib\w*|give|order|consider\w*|recommend\w*|rule out|diagnos\w*|refer\w*|treat\w*|increase|decrease|stop|switch)\b", re.IGNORECASE)


def check(want: dict, result: dict, agenda: list[dict]) -> list[str]:
    problems = []
    if "section" in want:
        allowed = want["section"] if isinstance(want["section"], list) else [want["section"]]
        if result["section"] not in allowed:
            problems.append(f"section {result['section']}, expected {' or '.join(allowed)}")
    if "alerts" in want and sorted(alert["kind"] for alert in result["alerts"]) != sorted(want["alerts"]):
        problems.append(f"alerts {[alert['text'] for alert in result['alerts']]}, expected {want['alerts']}")
    kinds = {item["kind"] for item in agenda if item["id"] in result["covers"]}
    if missing := [kind for kind in want.get("covers", []) if kind not in kinds]:
        problems.append(f"did not tick a {', '.join(missing)} agenda item (ticked {sorted(kinds) or 'none'})")
    if "link" in want and not any(says(link["label"], want["link"]) for link in result["links"]):
        problems.append(f"no link to {want['link']} (links {[link['label'] for link in result['links']]})")
    if want.get("gaps") is True and not result["gaps"]:
        problems.append("no documentation gaps listed")
    if want.get("gaps") is False and result["gaps"]:
        problems.append(f"gaps listed: {result['gaps']}")
    if advice := [gap for gap in result["gaps"] if ADVICE.search(gap)]:
        problems.append(f"gaps read as advice: {advice}")
    return problems


async def check_note(llm: LlmClient, plans: PlanExtractor, record: Record, agenda, jottings: list[tuple[str, dict]], expected_plan: list[str]) -> tuple[list[str], dict]:
    """Drafts the note as the agent would, checks it, and reads its plan back the way open loops will."""
    visit = Visit(id="visit-eval", patient=record.id, practitioner="pr-aydin", practitioner_name="Dr. Elif Aydın",
                  started=f"{record.today.isoformat()}T09:00:00+03:00", agenda=agenda,
                  jottings=[Jotting(f"J{index}", f"{record.today.isoformat()}T09:0{index}:00+03:00", text, "pr-aydin", result)
                            for index, (text, result) in enumerate(jottings, 1)])
    drafted = await draft_note(llm, record, visit)
    problems = []
    for section, items in drafted["sections"].items():
        problems += [f"{section}: \"{item['text']}\": {', '.join(item['issues'])}" for item in items if item["issues"]]
    if drafted["unused"]:
        problems.append(f"jottings not in the note: {', '.join(drafted['unused'])}")
    # A jotting that gives its own measurement ("BP 138/84") gets no record values: earlier readings next to it would
    # read as part of this visit.
    said = {f"J{index}": text for index, (text, _) in enumerate(jottings, 1)}
    for section, items in drafted["sections"].items():
        for item in items:
            cited = [said[source] for source in item["sources"] if source in said]
            if any(values(text) for text in cited) and values(item["text"]) - numbers_in(" ".join(cited)):
                problems.append(f"{section}: \"{item['text']}\" adds record values to a jotting that gives its own")
    sections = {section: section_text(section, items) for section, items in drafted["sections"].items()}
    when = datetime.fromisoformat(visit.started)
    text = note_text(record, visit.practitioner_name, "Internal Medicine", when, sections)
    document = Document(ref="DocumentReference/note-visit-eval", kind="note", category="Progress note",
                        title="Internal medicine visit note", when=when, author=visit.practitioner_name, text=text)
    items = await plans.items(document)
    for phrase in expected_plan:
        if not any(says(item.quote, phrase) for item in items):
            problems.append(f"plan \"{phrase}\" not read back from the note (plan items: {[item.quote for item in items]})")
    return problems, {"sections": drafted["sections"], "unused": drafted["unused"], "text": text, "plan": [item.quote for item in items]}


async def run_visits(settings: Settings, records: dict[str, Record], expected_path: Path, out: Path, *, repeats: int) -> int:
    visits = tomllib.loads(expected_path.read_text(encoding="utf-8"))["visit"]
    if unknown := sorted({visit["patient"] for visit in visits} - set(records)):
        print(f"visits.toml names patients not in the cohort: {', '.join(unknown)}")
        return 1
    llm = LlmClient(replace(settings, temperature=0.0))
    plans = PlanExtractor(llm, settings.plan_cache)
    medicines = MedicationReader(llm, settings.plan_cache.parent / "medications")
    runs = []
    try:
        for repeat in range(repeats):
            run = []
            for visit in visits:
                record = records[visit["patient"]]
                loops, _ = await open_loops(record, plans)
                picture = await reconcile(record, medicines, loops)
                items = build_agenda(record, loops, picture, todays_appointment(record))
                agenda = [{"id": item.id, "kind": item.kind, "text": item.text} for item in items]
                earlier: list[str] = []
                reviewed: list[tuple[str, dict]] = []
                for want in visit["jottings"]:
                    result = await review(llm, record, agenda, earlier, want["text"])
                    problems = check(want, result, agenda)
                    run.append({"patient": visit["patient"], "jotting": want["text"], "result": result, "problems": problems})
                    earlier.append(want["text"])
                    reviewed.append((want["text"], result))
                problems, note = await check_note(llm, plans, record, items, reviewed, visit.get("plan", []))
                run.append({"patient": visit["patient"], "jotting": "(the note)", "result": note, "problems": problems})
            runs.append(run)
            jottings = [item for item in run if item["jotting"] != "(the note)"]
            notes = [item for item in run if item["jotting"] == "(the note)"]
            print(f"run {repeat + 1}: {sum(not item['problems'] for item in jottings)}/{len(jottings)} jottings as expected; "
                  f"{sum(not item['problems'] for item in notes)}/{len(notes)} notes clean with their plan read back")
            for item in run:
                for problem in item["problems"]:
                    print(f"   - {item['patient']} \"{item['jotting']}\": {problem}")
    finally:
        await llm.close()
    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-visits"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Report: {folder / 'results.json'}")
    return 0
