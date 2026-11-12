"""Demo reset: the FHIR server back to the synthetic data as loaded, so a demo can be run again from the start.

Off unless AGENT_DEMO_RESET=1. Refused unless every Patient on the server is marked synthetic (HTEST), so it can never
touch real records. On the FHIR server:
  1. every resource the baseline bundles (synthetic/output/*.json, as synthetic/load.py loads them) do not contain is
     deleted, in one transaction: what the demo wrote, such as review and communication marks, visit Encounters,
     signed notes and their Provenance, onboarded patients and the history imported for them
  2. the baseline bundles are posted again (every entry a PUT), undoing any change to a resource they contain
The agent's working state is cleared by the caller (app.py): visits, onboarding sessions, chat sessions, and the
national record service's requests, tokens and messages. Caches of what the model read from notes are kept: they are
keyed by the note's text, so they stay right, and reading every note again would take minutes.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .fhir import FhirClient

# Resource types the demo can write beyond those in the baseline.
WRITTEN = ("Task", "Communication", "Provenance", "MedicationStatement", "Encounter", "DocumentReference", "Patient",
           "AllergyIntolerance", "Condition", "Procedure", "Observation")
SYNTHETIC = "HTEST"


class ResetRefused(Exception):
    pass


def baseline(folder: Path) -> tuple[list[dict], dict[str, set[str]]]:
    """The baseline bundles, in load order, and the ids they write by resource type."""
    bundles = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]
    if not bundles:
        raise ResetRefused(f"No baseline bundles in {folder}; run synthetic/generate.py first.")
    ids: dict[str, set[str]] = {}
    for bundle in bundles:
        for entry in bundle["entry"]:
            resource = entry["resource"]
            ids.setdefault(resource["resourceType"], set()).add(resource["id"])
    return bundles, ids


async def _ids(fhir: FhirClient, resource_type: str) -> list[str]:
    found = await fhir.search(resource_type, {"_elements": "id", "_count": "1000"})
    return [resource["id"] for resource in found]


async def reset_fhir(fhir: FhirClient, folder: Path) -> dict:
    """Deletes what the baseline does not hold and loads the baseline again; returns what it did."""
    bundles, ids = baseline(folder)
    patients = await fhir.search("Patient", {"_elements": "id,meta"})
    if real := [patient["id"] for patient in patients if not any(label.get("code") == SYNTHETIC for label in patient.get("meta", {}).get("security", []))]:
        raise ResetRefused(f"The FHIR server holds patients not marked synthetic ({', '.join(real[:5])}); the demo reset only runs on synthetic data.")
    extra = [
        (resource_type, resource_id)
        for resource_type in sorted(set(ids) | set(WRITTEN))
        for resource_id in await _ids(fhir, resource_type)
        if resource_id not in ids.get(resource_type, set())
    ]
    if extra:
        # One transaction, so references among the deleted resources (a Provenance naming a note) do not block it.
        await fhir.transaction({
            "resourceType": "Bundle", "type": "transaction",
            "entry": [{"request": {"method": "DELETE", "url": f"{resource_type}/{resource_id}"}} for resource_type, resource_id in extra],
        })
    for bundle in bundles:
        await fhir.transaction(bundle)
    return {
        "deleted": dict(Counter(resource_type for resource_type, _ in extra)),
        "reloaded": sum(len(bundle["entry"]) for bundle in bundles),
    }
