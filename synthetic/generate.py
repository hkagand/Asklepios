"""Writes the synthetic cohort as FHIR R4 transaction bundles.

    python synthetic/generate.py [--anchor YYYY-MM-DD] [--seed 2041] [--out synthetic/output]

The anchor date is "today" for the cohort: histories end just before it and
upcoming appointments start on or after it. Output is deterministic for a
given anchor and seed, and resource IDs are stable, so reloading overwrites.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from chart import shared_resources, transaction
from cohort import build_cohort
from national import imported_charts


def write(path: Path, bundle: dict) -> None:
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate the synthetic FHIR cohort.")
    parser.add_argument("--anchor", type=date.fromisoformat, default=date.today(), help="'today' for the cohort (default: today)")
    parser.add_argument("--seed", type=int, default=2041)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "output")
    args = parser.parse_args()

    charts = build_cohort(args.anchor, args.seed)

    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("*.json"):
        old.unlink()
    shared = shared_resources()
    write(args.out / "00-shared.json", transaction(shared))

    totals = Counter(resource["resourceType"] for resource in shared)
    for chart in charts:
        write(args.out / f"{chart.pid}.json", chart.bundle())
        totals.update(resource["resourceType"] for resource in chart.resources)
        print(f"{chart.mrn:<7} {chart.name:<20} {len(chart.resources):>5} resources")

    # Two more patients, whose history was imported from the national record before their first visit.
    try:
        imported = imported_charts(args.anchor)
    except ImportError as error:
        raise SystemExit("The imported patients need the agent's packages: pip install -r agent/requirements.txt") from error
    for pid, resources in imported.items():
        write(args.out / f"{pid}.json", transaction(resources))
        totals.update(resource["resourceType"] for resource in resources)
        print(f"{pid.upper():<7} {resources[0]['name'][0]['text']:<20} {len(resources):>5} resources")

    print(f"\nAnchor {args.anchor.isoformat()}, seed {args.seed}: {len(charts) + len(imported)} patients, {sum(totals.values())} resources")
    for resource_type, count in sorted(totals.items()):
        print(f"  {resource_type:<20} {count:>6}")
    print(f"Bundles written to {args.out}")
    # National records used to be written here for a service to read; nothing reads them now.
    shutil.rmtree(args.out / "national", ignore_errors=True)


if __name__ == "__main__":
    main()
