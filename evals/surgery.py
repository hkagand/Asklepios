"""Checks surgical history (agent/surgery.py) against evals/surgery.toml: python -m evals --surgery

Each run reads the notes and reports (from the cache, or from scratch with --fresh) and lists every cohort patient's
operations. An expected operation counts when an operation whose name says its phrase is listed with every detail the
expectation gives; every other operation listed is a false alarm.
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
from agent.record import Record
from agent.surgery import SurgeryReader, surgical_history

from .run import says


def wrong(item: dict, operation: dict) -> list[str]:
    """The details of an expectation the listed operation gets wrong."""
    problems = []
    if "year" in item and operation["year"] != item["year"]:
        problems.append(f"year {operation['year']}, expected {item['year']}")
    if "region" in item and operation["region"] != item["region"]:
        problems.append(f"region {operation['region']}, expected {item['region']}")
    if "approach" in item and operation["approach"] != item["approach"]:
        problems.append(f"approach {operation['approach']}, expected {item['approach']}")
    if "implant" in item and not any(says(implant, item["implant"]) for implant in operation["implants"]):
        problems.append(f"implants {operation['implants']}, expected {item['implant']}")
    if "only_in_notes" in item and operation["onlyInNotes"] != item["only_in_notes"]:
        problems.append(f"only in notes {operation['onlyInNotes']}, expected {item['only_in_notes']}")
    if "years_differ" in item and operation["yearsDiffer"] != item["years_differ"]:
        problems.append(f"years differ {operation['yearsDiffer']}, expected {item['years_differ']}")
    kinds = {source["kind"] for source in operation["sources"]}
    if missing := [kind for kind in item.get("sources", []) if kind not in kinds]:
        problems.append(f"no {', '.join(missing)} source")
    return problems


def check(expected: dict, history: dict) -> dict:
    operations = history["operations"]
    used: set[int] = set()
    results = []
    for item in expected.get("operations", []):
        hit = next((index for index, operation in enumerate(operations) if index not in used and says(operation["name"], item["match"])), None)
        if hit is None:
            results.append({**item, "ok": False, "found": "not listed"})
            continue
        used.add(hit)
        problems = wrong(item, operations[hit])
        results.append({**item, "ok": not problems, "found": "; ".join(problems) or "as expected"})
    alarms = [f"{operation['name']} ({operation['when']})" for index, operation in enumerate(operations) if index not in used]
    none_ok = bool(history["noneStated"]) == bool(expected.get("none_stated", False))
    return {"expected": results, "false_alarms": alarms, "none_stated_ok": none_ok, "unread": history["unread"]}


async def run_surgery(settings: Settings, records: dict[str, Record], expected_path: Path, out: Path, *, fresh: bool, repeats: int) -> int:
    expected = {patient["id"]: patient for patient in tomllib.loads(expected_path.read_text(encoding="utf-8"))["patient"]}
    if missing := sorted(set(records) - set(expected)):
        print(f"surgery.toml does not list: {', '.join(missing)}")
        return 1
    llm = LlmClient(replace(settings, temperature=0.0))
    runs = []
    try:
        for repeat in range(repeats):
            with tempfile.TemporaryDirectory() as scratch:
                reader = SurgeryReader(llm, Path(scratch) if fresh else settings.plan_cache.parent / "surgery", concurrency=6)
                run = {patient: check(expected[patient], await surgical_history(record, reader)) for patient, record in records.items()}
            runs.append(run)
            print(f"run {repeat + 1}: {summary_line(run)}")
    finally:
        await llm.close()
    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-surgery"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Surgical history check", "", f"Model `{settings.llm_model}` · {len(runs)} run(s)", ""]
    lines += [f"- Run {number}: {summary_line(run)}" for number, run in enumerate(runs, 1)]
    for number, run in enumerate(runs, 1):
        for patient, result in run.items():
            lines += [f"- Run {number}, {patient}: {item['match']}: {item['found']}" for item in result["expected"] if not item["ok"]]
            lines += [f"- Run {number}, {patient}: false alarm {alarm}" for alarm in result["false_alarms"]]
            if not result["none_stated_ok"]:
                lines.append(f"- Run {number}, {patient}: \"no previous operations\" statement not as expected")
    text = "\n".join(lines) + "\n"
    (folder / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text + f"Report: {folder / 'report.md'}")
    return 0


def summary_line(run: dict) -> str:
    expected = [item for result in run.values() for item in result["expected"]]
    alarms = sum(len(result["false_alarms"]) for result in run.values())
    none_ok = sum(result["none_stated_ok"] for result in run.values())
    unread = sum(len(result["unread"]) for result in run.values())
    return (
        f"{sum(item['ok'] for item in expected)}/{len(expected)} expected operations listed correctly; {alarms} false alarms; "
        f"\"none\" statements {none_ok}/{len(run)}; {unread} documents unread"
    )
