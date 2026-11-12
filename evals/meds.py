"""Checks medication reconciliation (agent/meds.py) against evals/meds.toml: python -m evals --meds

Each run reads the notes (from the cache, or from scratch with --fresh), works out the open loops and reconciles every
cohort patient. An expected finding counts when a discrepancy of its kind names its drug; every other discrepancy is
a false alarm.
"""

from __future__ import annotations

import json
import tempfile
import tomllib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings
from agent.llm import LlmClient
from agent.loops import open_loops
from agent.meds import DISCREPANCIES, MedicationReader, reconcile
from agent.plans import PlanExtractor
from agent.record import Record

from .run import says


def discrepancies(picture: dict) -> list[dict]:
    found = [
        {"drug": drug["name"], "kind": finding["kind"], "text": finding["text"]}
        for drug in picture["drugs"]
        for finding in drug["findings"]
        if finding["kind"] in DISCREPANCIES
    ]
    return found + [{"drug": item["drug"], "kind": "not_ordered", "text": item["finding"]["text"]} for item in picture["unlisted"]]


def check(expected: list[dict], picture: dict) -> dict:
    found = discrepancies(picture)
    used: set[int] = set()
    results = []
    for item in expected:
        hit = next(
            (index for index, finding in enumerate(found) if index not in used and finding["kind"] == item["kind"] and says(finding["drug"], item["drug"])),
            None,
        )
        if hit is not None:
            used.add(hit)
        results.append({**item, "ok": hit is not None})
    alarms = [f"{finding['drug']} {finding['kind']}: {finding['text']}" for index, finding in enumerate(found) if index not in used]
    return {"expected": results, "false_alarms": alarms, "unread": picture["unread"]}


async def run_meds(settings: Settings, records: dict[str, Record], expected_path: Path, out: Path, *, fresh: bool, repeats: int) -> int:
    expected = {patient["id"]: patient.get("findings", []) for patient in tomllib.loads(expected_path.read_text(encoding="utf-8"))["patient"]}
    if missing := sorted(set(records) - set(expected)):
        print(f"meds.toml does not list: {', '.join(missing)}")
        return 1
    llm = LlmClient(replace(settings, temperature=0.0))
    runs = []
    try:
        for repeat in range(repeats):
            with tempfile.TemporaryDirectory() as scratch:
                plans_dir = Path(scratch) / "plans" if fresh else settings.plan_cache
                medicines_dir = Path(scratch) / "medications" if fresh else settings.plan_cache.parent / "medications"
                plans = PlanExtractor(llm, plans_dir, concurrency=6)
                medicines = MedicationReader(llm, medicines_dir, concurrency=6)
                run = {}
                for patient, record in records.items():
                    loops, _ = await open_loops(record, plans)
                    run[patient] = check(expected[patient], await reconcile(record, medicines, loops))
            runs.append(run)
            print(f"run {repeat + 1}: {summary_line(run)}")
    finally:
        await llm.close()
    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-meds"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Medication reconciliation check", "", f"Model `{settings.llm_model}` · {len(runs)} run(s)", ""]
    lines += [f"- Run {number}: {summary_line(run)}" for number, run in enumerate(runs, 1)]
    for number, run in enumerate(runs, 1):
        for patient, result in run.items():
            lines += [f"- Run {number}, {patient}: missed {item['drug']} {item['kind']}" for item in result["expected"] if not item["ok"]]
            lines += [f"- Run {number}, {patient}: false alarm {alarm}" for alarm in result["false_alarms"]]
    text = "\n".join(lines) + "\n"
    (folder / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text + f"Report: {folder / 'report.md'}")
    return 0


def summary_line(run: dict) -> str:
    expected = [item for result in run.values() for item in result["expected"]]
    alarms = sum(len(result["false_alarms"]) for result in run.values())
    unread = sum(len(result["unread"]) for result in run.values())
    return f"{sum(item['ok'] for item in expected)}/{len(expected)} expected discrepancies found; {alarms} false alarms; {unread} notes unread"
