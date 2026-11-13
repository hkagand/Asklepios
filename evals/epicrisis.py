"""Checks epicrisis reports (hospital discharge reports) and that they leave the existing cohort alone: python -m evals --epicrisis

The existing 21 charts are fingerprinted (evals/cohort-fingerprint.json, written from the generator at the gold anchor).
Resources added for epicrisis reports carry TAG and are left out of the fingerprint, so adding them must not change
what the 21 patients had before. Patients that are not among the file's keys are not compared.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from .run import ROOT

FINGERPRINT = Path(__file__).parent / "cohort-fingerprint.json"
TAG = {"system": "urn:demo:asklepios", "code": "epicrisis"}


def tagged(resource: dict) -> bool:
    return TAG in resource.get("meta", {}).get("tag", [])


def fingerprint(charts: list) -> dict[str, str]:
    """Patient id -> sha256 of the chart's untagged resources as JSON with sorted keys."""
    return {
        chart.pid: hashlib.sha256(
            json.dumps([resource for resource in chart.resources if not tagged(resource)], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        for chart in charts
    }


def build_charts(anchor: date, seed: int) -> list:
    sys.path.insert(0, str(ROOT / "synthetic"))
    from cohort import build_cohort

    return build_cohort(anchor, seed)


def check_untouched(anchor: date, seed: int) -> list[str]:
    """Problems when an existing chart's untagged resources differ from the recorded fingerprint."""
    recorded = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    now = fingerprint(build_charts(anchor, seed))
    problems = [f"{pid}: its resources differ from {FINGERPRINT.name}" for pid, digest in recorded.items() if pid in now and now[pid] != digest]
    problems += [f"{pid}: no longer generated" for pid in recorded if pid not in now]
    return problems


async def run_epicrisis(settings, records, anchor: date, seed: int, out: Path) -> int:
    checks = {"untouched": check_untouched(anchor, seed)}
    for name, problems in checks.items():
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
    return 1 if any(checks.values()) else 0
