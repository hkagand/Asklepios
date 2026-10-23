"""Writes the synthetic cohort as FHIR R4 transaction bundles.

    python synthetic/generate.py [--anchor YYYY-MM-DD] [--seed 2041] [--out synthetic/output]

The anchor date is "today" for the cohort: histories end just before it and
upcoming appointments start on or after it. Output is deterministic for a
given anchor and seed, and resource IDs are stable, so reloading overwrites.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from chart import shared_resources, transaction
from cohort import build_cohort


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

    print(f"\nAnchor {args.anchor.isoformat()}, seed {args.seed}: {len(charts)} patients, {sum(totals.values())} resources")
    for resource_type, count in sorted(totals.items()):
        print(f"  {resource_type:<20} {count:>6}")
    print(f"Bundles written to {args.out}")


if __name__ == "__main__":
    main()
