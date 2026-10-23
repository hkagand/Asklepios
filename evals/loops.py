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
from agent.plans import PlanExtractor
from agent.record import Record

from .run import says


def load_expected(path: Path) -> dict[str, list[dict]]:
    return {patient["id"]: patient.get("items", []) for patient in tomllib.loads(path.read_text(encoding="utf-8"))["patient"]}


def check(expected: list[dict], loops: list[Loop]) -> dict:
    used: set[int] = set()
    results = []
    for item in expected:
        candidates = [index for index, loop in enumerate(loops) if index not in used and says(loop.line, item["match"])]
        right = [index for index in candidates if loops[index].status == item["status"]]
        if right:
            used.add(right[0])
            results.append({**item, "found": item["status"]})
        elif candidates:
            used.add(candidates[0])
            results.append({**item, "found": loops[candidates[0]].status})
        else:
            results.append({**item, "found": None})
    alarms = [loop_line(loop) for index, loop in enumerate(loops) if index not in used and loop.status in OPEN]
    return {"expected": results, "false_alarms": alarms}


async def run_loops(settings: Settings, records: dict[str, Record], expected_path: Path, out: Path, *, fresh: bool, repeats: int) -> int:
    expected = load_expected(expected_path)
    if missing := sorted(set(records) - set(expected)):
        print(f"loops.toml does not list: {', '.join(missing)}")
        return 1
    llm = LlmClient(replace(settings, temperature=0.0))
    runs = []
    try:
        for repeat in range(repeats):
            with tempfile.TemporaryDirectory() as scratch:
                extractor = PlanExtractor(llm, Path(scratch) if fresh else settings.plan_cache, concurrency=6)
                found = {patient: await open_loops(record, extractor) for patient, record in records.items()}
            runs.append({patient: check(expected[patient], loops) | {"unread": unread} for patient, (loops, unread) in found.items()})
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
    opened = [item for item in expected if item["status"] in OPEN]
    return {
        "items": len(expected),
        "right": sum(item["found"] == item["status"] for item in expected),
        "open": len(opened),
        "open_right": sum(item["found"] == item["status"] for item in opened),
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
                if item["found"] != item["status"]:
                    misses[f"{patient}: \"{item['match']}\" expected {item['status']}, found {item['found'] or 'nothing'}"] += 1
            for alarm in result["false_alarms"]:
                alarms[f"{patient}: {alarm}"] += 1
    if misses:
        lines += ["", "## Expected items not found as expected", "", *(f"- {text} ({count}/{len(runs)} runs)" for text, count in misses.most_common())]
    if alarms:
        lines += ["", "## False alarms", "", *(f"- {text} ({count}/{len(runs)} runs)" for text, count in alarms.most_common())]
    return "\n".join(lines) + "\n"
