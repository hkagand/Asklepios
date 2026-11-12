"""Checks the open loops (agent/loops.py) against evals/loops.toml: python -m evals --loops

Each run extracts the plans (from the plan cache, or from scratch with --fresh) and matches them against each cohort
patient's record. An expected item counts when an item quoting its phrase has its status; every other open item is a
false alarm.
"""

from __future__ import annotations

import json
import tempfile
import tomllib
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings
from agent.llm import LlmClient
from agent.loops import OPEN, Loop, loop_line, open_loops
from agent.marks import Practitioner, communication, review_task
from agent.plans import PlanExtractor
from agent.record import Record

from .run import says


def load_expected(path: Path) -> dict[str, dict]:
    patients = tomllib.loads(path.read_text(encoding="utf-8"))["patient"]
    return {patient["id"]: {"items": patient.get("items", []), "marks": patient.get("marks", [])} for patient in patients}


def add_marks(record: Record, marks: list[dict]) -> None:
    """Puts review and communication marks on the record, as the panel would through the agent service."""
    for number, mark in enumerate(marks, 1):
        missing = [ref for ref in mark["about"] if ref not in record.resources]
        if missing:
            raise SystemExit(f"loops.toml: {record.id} has no {', '.join(missing)}")
        by = Practitioner(mark["by"], mark["by"])
        if mark["kind"] == "review":
            made = [review_task(record, ref, by, None) for ref in mark["about"]]
        else:
            made = [communication(record, mark["about"], by, mark.get("medium", "phone"), None, None)]
        for index, resource in enumerate(made):
            resource["id"] = f"eval-{number}-{index}"
            record.resources[f"{resource['resourceType']}/{resource['id']}"] = resource


def allowed(item: dict) -> list[str]:
    """An expected item's status, or the list of statuses that are all acceptable."""
    return item["status"] if isinstance(item["status"], list) else [item["status"]]


def check(expected: list[dict], loops: list[Loop]) -> dict:
    used: set[int] = set()
    results = []
    for item in expected:
        candidates = [index for index, loop in enumerate(loops) if index not in used and says(loop.line, item["match"])]
        right = [index for index in candidates if loops[index].status in allowed(item)]
        chosen = right[0] if right else candidates[0] if candidates else None
        if chosen is not None:
            used.add(chosen)
        found = loops[chosen].status if chosen is not None else None
        results.append({**item, "found": found, "ok": found in allowed(item)})
    alarms = [loop_line(loop) for index, loop in enumerate(loops) if index not in used and loop.status in OPEN]
    return {"expected": results, "false_alarms": alarms}


async def run_loops(settings: Settings, records: dict[str, Record], expected_path: Path, out: Path, *, fresh: bool, repeats: int) -> int:
    expected = load_expected(expected_path)
    if missing := sorted(set(records) - set(expected)):
        print(f"loops.toml does not list: {', '.join(missing)}")
        return 1
    for patient, record in records.items():
        add_marks(record, expected[patient]["marks"])
    llm = LlmClient(replace(settings, temperature=0.0))
    runs = []
    try:
        for repeat in range(repeats):
            with tempfile.TemporaryDirectory() as scratch:
                extractor = PlanExtractor(llm, Path(scratch) if fresh else settings.plan_cache, concurrency=6)
                found = {patient: await open_loops(record, extractor) for patient, record in records.items()}
            runs.append({patient: check(expected[patient]["items"], loops) | {"unread": unread} for patient, (loops, unread) in found.items()})
            print(f"run {repeat + 1}: {summary_line(runs[-1])}")
    finally:
        await llm.close()

    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-loops"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    text = report(runs, settings.llm_model, fresh)
    (folder / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"Report: {folder / 'report.md'}")
    return 0


def tally(run: dict) -> dict:
    expected = [item for patient in run.values() for item in patient["expected"]]
    opened = [item for item in expected if set(allowed(item)) & set(OPEN)]
    return {
        "items": len(expected),
        "right": sum(item["ok"] for item in expected),
        "open": len(opened),
        "open_right": sum(item["ok"] for item in opened),
        "false_alarms": sum(len(patient["false_alarms"]) for patient in run.values()),
        "unread": sum(len(patient["unread"]) for patient in run.values()),
    }


def summary_line(run: dict) -> str:
    counts = tally(run)
    return (
        f"{counts['right']}/{counts['items']} expected items with the right status; open loops found "
        f"{counts['open_right']}/{counts['open']}; {counts['false_alarms']} false alarms; {counts['unread']} notes unread"
    )


def report(runs: list[dict], model: str, fresh: bool) -> str:
    lines = [
        "# Open loops check",
        "",
        f"Model `{model}` · plans {'extracted from scratch' if fresh else 'from the plan cache'} · {len(runs)} run(s)",
        "",
        *(f"- Run {number}: {summary_line(run)}" for number, run in enumerate(runs, 1)),
    ]
    misses: Counter[str] = Counter()
    alarms: Counter[str] = Counter()
    for run in runs:
        for patient, result in run.items():
            for item in result["expected"]:
                if not item["ok"]:
                    expected = " or ".join(allowed(item))
                    misses[f"{patient}: \"{item['match']}\" expected {expected}, found {item['found'] or 'nothing'}"] += 1
            for alarm in result["false_alarms"]:
                alarms[f"{patient}: {alarm}"] += 1
    if misses:
        lines += ["", "## Expected items not found as expected", "", *(f"- {text} ({count}/{len(runs)} runs)" for text, count in misses.most_common())]
    if alarms:
        lines += ["", "## False alarms", "", *(f"- {text} ({count}/{len(runs)} runs)" for text, count in alarms.most_common())]
    return "\n".join(lines) + "\n"
