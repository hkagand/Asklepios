"""Checks clinical considerations (agent/considerations.py) against evals/considerations.toml:
python -m evals --considerations [--compare] [--repeats 3]

Each scripted visit gets the code alerts its jottings would raise, then the considerations are made once from all the
jottings, by the clinical model (CLINICAL_LLM_*) and, with --compare, by the agent's own model on the same prompt and
checks, so the two can be weighed: does a small local clinical model do this job as well as the large general one?
"""

from __future__ import annotations

import asyncio
import json
import time
import tomllib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings
from agent.considerations import consider
from agent.jottings import allergy_alerts, dose_alerts
from agent.llm import LlmClient
from agent.record import Record
from agent.visits import Jotting, Visit

from .run import says

# A consideration citing more record items than this recites the record rather than reasoning from the jottings.
MANY = 3


def visit_of(record: Record, case: dict) -> Visit:
    started = f"{record.today.isoformat()}T09:00:00+03:00"
    jottings = [
        Jotting(f"J{number}", started, text, "pr-aydin", {"status": "done", "alerts": allergy_alerts(record, text) + dose_alerts(record, text, None)})
        for number, text in enumerate(case["jottings"], 1)
    ]
    return Visit(id=f"visit-eval-{case['id']}", patient=record.id, practitioner="pr-aydin", practitioner_name="Dr. Elif Aydın",
                 started=started, jottings=jottings)


def check(case: dict, result: dict) -> dict:
    """What the considerations caught, missed and said that they must not."""
    if result["status"] != "done":
        return {"failed": result.get("error", "no answer"), "caught": [], "missed": [want["about"] for want in case.get("expect", [])], "said": []}
    items = result["items"]
    caught, missed = [], []
    for want in case.get("expect", []):
        kinds = want.get("kind")
        hit = any(
            all(any(says(item["text"], phrase) for phrase in group) for group in want["all"]) and (not kinds or item["kind"] in kinds)
            for item in items
        )
        (caught if hit else missed).append(want["about"])
    said = [f"{phrase}: {item['text']}" for phrase in case.get("forbid", []) for item in items if says(item["text"], phrase)]
    return {"failed": None, "caught": caught, "missed": missed, "said": said}


def summary(rows: list[dict]) -> dict:
    done = [row for row in rows if not row["check"]["failed"]]
    expected = sum(len(row["check"]["caught"]) + len(row["check"]["missed"]) for row in rows)
    items = [item for row in done for item in row["result"]["items"]]
    seconds = sorted(row["result"].get("seconds", 0) for row in rows)
    return {
        "runs": len(rows),
        "passed": sum(not row["check"]["failed"] and not row["check"]["missed"] and not row["check"]["said"] for row in rows),
        "caught": sum(len(row["check"]["caught"]) for row in rows),
        "expected": expected,
        "said": sum(len(row["check"]["said"]) for row in rows),
        "failed": len(rows) - len(done),
        "kept": len(items),
        "dropped": sum(len(row["result"].get("dropped", [])) for row in done),
        "many": sum(sum(1 for source in item["basis"] if source["ref"]) > MANY for item in items),
        "medianSeconds": seconds[len(seconds) // 2] if seconds else None,
        "maxSeconds": seconds[-1] if seconds else None,
    }


async def run_model(name: str, settings: Settings, records: dict[str, Record], cases: list[dict], repeats: int, concurrency: int) -> list[dict]:
    llm = LlmClient(settings)
    gate = asyncio.Semaphore(concurrency)
    rows: list[dict] = []

    async def one(case: dict, repeat: int) -> None:
        record = records[case["patient"]]
        async with gate:
            started = time.perf_counter()
            result = await consider(llm, record, visit_of(record, case))
            result.setdefault("seconds", round(time.perf_counter() - started, 1))
        rows.append({"model": name, "case": case["id"], "repeat": repeat, "result": result, "check": check(case, result)})

    try:
        await asyncio.gather(*(one(case, repeat) for repeat in range(repeats) for case in cases))
    finally:
        await llm.close()
    order = {case["id"]: index for index, case in enumerate(cases)}
    return sorted(rows, key=lambda row: (order[row["case"]], row["repeat"]))


def describe(name: str, rows: list[dict]) -> list[str]:
    total = summary(rows)
    lines = [
        f"{name}: {total['passed']}/{total['runs']} visits as expected; caught {total['caught']}/{total['expected']} expected considerations; "
        f"{total['said']} forbidden claims; {total['failed']} unusable answers",
        f"   {total['kept']} kept, {total['dropped']} dropped by the checks, {total['many']} citing more than {MANY} record items; "
        f"median {total['medianSeconds']} s, slowest {total['maxSeconds']} s",
    ]
    for row in rows:
        problems = ([f"failed: {row['check']['failed']}"] if row["check"]["failed"] else []) + [f"missed {about}" for about in row["check"]["missed"]] + [
            f"said {claim}" for claim in row["check"]["said"]
        ]
        if problems:
            lines.append(f"   - {row['case']} (run {row['repeat'] + 1}): {'; '.join(problems)}")
    return lines


async def run_considerations(settings: Settings, records: dict[str, Record], expected_path: Path, out: Path, *, repeats: int, compare: bool) -> int:
    cases = tomllib.loads(expected_path.read_text(encoding="utf-8"))["visit"]
    if unknown := sorted({case["patient"] for case in cases} - set(records)):
        print(f"considerations.toml names patients not in the cohort: {', '.join(unknown)}")
        return 1
    models: list[tuple[str, Settings, int]] = []
    if settings.clinical:
        # One at a time: a local model on one GPU answers requests in turn anyway.
        models.append((settings.clinical.llm_model, settings.clinical, 1))
    if compare or not settings.clinical:
        models.append((settings.llm_model, replace(settings, temperature=0.0), 4))
    if not settings.clinical:
        print("No clinical model is configured (CLINICAL_LLM_BASE_URL, CLINICAL_LLM_MODEL): checking the agent's model only.")
    results = {}
    for name, model_settings, concurrency in models:
        rows = await run_model(name, model_settings, records, cases, repeats, concurrency)
        results[name] = {"summary": summary(rows), "rows": rows}
        print("\n".join(describe(name, rows)))
    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-considerations"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Report: {folder / 'results.json'}")
    return 0
