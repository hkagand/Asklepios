"""Loads the generated transaction bundles into a FHIR server.

    python synthetic/load.py [--base http://localhost:8080/fhir] [--dir synthetic/output]

Bundles are posted in file-name order, so the shared Organization and
Practitioners are in place before the patient bundles that reference them.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


def wait_for(base: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"{base}/metadata", timeout=10) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            if time.monotonic() > deadline:
                raise SystemExit(f"No response from {base} after {timeout:.0f}s ({error}). Is the server running?")
        print("Waiting for the FHIR server...")
        time.sleep(5)


def post(base: str, path: Path) -> dict:
    request = urllib.request.Request(
        base,
        data=path.read_bytes(),
        method="POST",
        headers={"Content-Type": "application/fhir+json; charset=utf-8", "Accept": "application/fhir+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            issues = [issue.get("diagnostics", "") for issue in json.loads(body).get("issue", [])]
            detail = "\n  ".join(issues) or body[:2000]
        except json.JSONDecodeError:
            detail = body[:2000]
        raise SystemExit(f"{path.name}: HTTP {error.code}\n  {detail}") from None


def count(base: str, resource_type: str) -> int:
    with urllib.request.urlopen(f"{base}/{resource_type}?_summary=count", timeout=60) as response:
        return json.load(response).get("total", 0)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Load generated bundles into a FHIR server.")
    parser.add_argument("--base", default="http://localhost:8080/fhir")
    parser.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent / "output")
    parser.add_argument("--wait", type=float, default=180, help="seconds to wait for the server to come up")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    files = sorted(args.dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No bundles in {args.dir}; run generate.py first.")
    wait_for(base, args.wait)

    totals: Counter[str] = Counter()
    expected: Counter[str] = Counter()
    for path in files:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        expected.update(entry["resource"]["resourceType"] for entry in bundle["entry"])
        started = time.monotonic()
        response = post(base, path)
        statuses = Counter(entry["response"]["status"] for entry in response.get("entry", []))
        totals.update(statuses)
        summary = ", ".join(f"{number} × {status}" for status, number in sorted(statuses.items()))
        print(f"{path.name:<16} {summary}  ({time.monotonic() - started:.1f}s)")
    print(f"\nLoaded {sum(totals.values())} resources into {base}")

    extra = {name: found - wanted for name, wanted in sorted(expected.items()) if (found := count(base, name)) > wanted}
    if extra:
        print(
            "\nThe server also holds resources this load did not write, left over from an earlier anchor date or seed: "
            + ", ".join(f"{name} +{number}" for name, number in extra.items())
            + "\nFor a clean dataset: docker compose down; docker compose up -d; then run this script again."
        )


if __name__ == "__main__":
    main()
