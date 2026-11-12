"""Checks onboarding (agent/onboard.py) against evals/onboarding.toml: python -m evals --onboarding

For each national record, the review is built against the cohort chart as the agent would (surgical history from the
cache, so an existing patient's notes are read once), and each expected item must have its status. Then the import
is built with the patient's answers and checked: nothing already in the chart is imported, every reference points
to our patient, medicines become MedicationStatements as the patient answered, and one Provenance covers it all.
The consent flow itself is checked against the running service, not here.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from agent.config import Settings
from agent.llm import LlmClient
from agent.marks import Practitioner
from agent.onboard import Decision, ImportRefused, Item, import_transaction, new_patient_id, national_id_of, patient_of, review_items
from agent.record import Record
from agent.surgery import SurgeryReader, surgical_history

from .run import ROOT, says


def national_bundles(anchor: date) -> dict[str, dict]:
    sys.path.insert(0, str(ROOT / "synthetic"))
    from national import national_records

    return {national_id_of(patient_of(bundle)): bundle for bundle in national_records(anchor)}


def check_items(expected: list[dict], items: list[Item]) -> list[str]:
    problems = []
    used: set[str] = set()
    for want in expected:
        hits = [item for item in items if item.section == want["section"] and says(item.label, want["match"]) and item.key not in used]
        if not hits:
            problems.append(f"{want['section']} \"{want['match']}\": not in the review")
            continue
        item = hits[0]
        used.add(item.key)
        for field in ("status", "critical", "stale"):
            if field in want and getattr(item, field) != want[field]:
                problems.append(f"{item.label}: {field} {getattr(item, field)!r}, expected {want[field]!r} ({item.reason})")
    problems += [f"{item.label} ({item.section}): {item.status}, expected new ({item.reason})" for item in items if item.key not in used and item.status != "new"]
    return problems


def decisions_for(items: list[Item], answers: list[dict]) -> list[Decision]:
    decisions = []
    for item in items:
        answer = next((answer for answer in answers if says(item.label, answer["match"])), {})
        if item.status == "duplicate":
            decisions.append(Decision(item.key, False))
        elif item.section == "medications":
            decisions.append(Decision(item.key, True, answer.get("taking", "yes"), answer.get("dose")))
        elif item.section == "problems" and item.status == "ask":
            decisions.append(Decision(item.key, True, current=answer.get("current", True)))
        else:
            decisions.append(Decision(item.key, True))
    return decisions


def check_import(bundle: dict, items: list[Item], answers: list[dict], chart: str) -> tuple[list[str], dict]:
    """The import with the patient's answers, and refusals that must hold."""
    problems = []
    national_id = national_id_of(patient_of(bundle))
    patient_id = chart or new_patient_id(national_id)
    by = Practitioner("pr-aydin", "Dr. Elif Aydın")
    options = dict(patient_id=patient_id, existing=bool(chart), practitioner=by, consent="test", onboarding="test",
                   now=datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc))
    # Refusals: a duplicate imported, a medicine with no answer, a stale diagnosis with no answer.
    for item in items:
        if item.status == "duplicate":
            refused = Decision(item.key, True)
        elif item.section == "medications":
            refused = Decision(item.key, True)
        elif item.section == "problems" and item.status == "ask":
            refused = Decision(item.key, True)
        else:
            continue
        try:
            import_transaction(bundle, items, [refused], **options)
            problems.append(f"{item.label}: imported without {'being new' if item.status == 'duplicate' else 'the patient\'s answer'}")
        except ImportRefused:
            pass

    transaction = import_transaction(bundle, items, decisions_for(items, answers), **options)
    written = [entry["resource"] for entry in transaction["entry"]]
    text = json.dumps(transaction)
    national_patient = f"Patient/{patient_of(bundle)['id']}"
    if national_patient in text:
        problems.append(f"the import still refers to {national_patient}")
    if f'"Patient/{patient_id}"' not in text:
        problems.append(f"nothing refers to Patient/{patient_id}")
    kinds = [resource["resourceType"] for resource in written]
    if "MedicationRequest" in kinds:
        problems.append("a medicine was written as an order (MedicationRequest)")
    if ("Patient" in kinds) == bool(chart):
        problems.append("the Patient was " + ("written for a patient already in the chart" if chart else "not written for a new patient"))
    provenance = written[-1]
    targets = {target["reference"] for target in provenance.get("target", [])}
    expected_targets = {f"{resource['resourceType']}/{resource['id']}" for resource in written[:-1]}
    if provenance["resourceType"] != "Provenance" or targets != expected_targets:
        problems.append("the Provenance does not cover exactly what was written")
    duplicates = {item.key.split("/")[1] for item in items if item.status == "duplicate"}
    if any(resource["id"] in duplicates for resource in written):
        problems.append("an item already in the chart was written")
    for answer in answers:
        if "taking" not in answer:
            continue
        statement = next((resource for resource in written if resource["resourceType"] == "MedicationStatement"
                          and says(resource["medicationCodeableConcept"].get("text", ""), answer["match"])), None)
        want = {"yes": "active", "different": "active", "no": "stopped"}[answer["taking"]]
        if statement is None or statement["status"] != want:
            problems.append(f"{answer['match']}: statement {statement and statement['status']}, expected {want}")
        elif answer.get("dose") and statement["dosage"][0]["text"] != answer["dose"]:
            problems.append(f"{answer['match']}: dose {statement['dosage'][0]['text']!r}, expected {answer['dose']!r}")
    for answer in answers:
        if answer.get("current") is False:
            condition = next((resource for resource in written if resource["resourceType"] == "Condition"
                              and says(resource["code"].get("text", ""), answer["match"])), None)
            status = condition and condition["clinicalStatus"]["coding"][0]["code"]
            if status != "resolved":
                problems.append(f"{answer['match']}: imported as {status}, expected resolved")
    summary = {"written": len(written) - 1, "kinds": {kind: kinds.count(kind) for kind in sorted(set(kinds))}}
    return problems, summary


def onboarded_records(anchor: date, expected_path: Path) -> dict[str, Record]:
    """The new patients of onboarding.toml as their charts read after onboarding on the anchor day, with the patient's
    answers given there: for gold questions about imported history."""
    bundles = national_bundles(anchor)
    imported = datetime(anchor.year, anchor.month, anchor.day, 9, 0, tzinfo=timezone.utc)
    records = {}
    for want in tomllib.loads(expected_path.read_text(encoding="utf-8"))["record"]:
        if want["chart"]:
            continue
        bundle = bundles[want["nationalId"]]
        items = review_items(bundle, None, None, anchor)
        patient_id = new_patient_id(want["nationalId"])
        transaction = import_transaction(
            bundle, items, decisions_for(items, want.get("answers", [])), patient_id=patient_id, existing=False,
            practitioner=Practitioner("pr-aydin", "Dr. Elif Aydın"), consent="gold", onboarding="gold", now=imported,
        )
        found: dict[str, list[dict]] = {}
        patient = None
        for entry in transaction["entry"]:
            resource = entry["resource"]
            # As the FHIR server would stamp it on import.
            resource["meta"] = resource.get("meta", {}) | {"lastUpdated": imported.isoformat()}
            if resource["resourceType"] == "Patient":
                patient = resource
            elif resource["resourceType"] != "Provenance":
                found.setdefault(resource["resourceType"], []).append(resource)
        records[patient_id] = Record(patient, found, today=anchor)
    return records


async def run_onboarding(settings: Settings, records: dict[str, Record], anchor: date, expected_path: Path, out: Path) -> int:
    expected = tomllib.loads(expected_path.read_text(encoding="utf-8"))["record"]
    bundles = national_bundles(anchor)
    if missing := sorted(set(bundles) - {item["nationalId"] for item in expected}):
        print(f"onboarding.toml does not list: {', '.join(missing)}")
        return 1
    llm = LlmClient(replace(settings, temperature=0.0))
    reader = SurgeryReader(llm, settings.plan_cache.parent / "surgery")
    results = {}
    try:
        for want in expected:
            bundle = bundles[want["nationalId"]]
            record = records.get(want["chart"]) if want["chart"] else None
            history = await surgical_history(record, reader) if record else None
            items = review_items(bundle, record, history, anchor)
            item_problems = check_items(want.get("items", []), items)
            import_problems, summary = check_import(bundle, items, want.get("answers", []), want["chart"])
            statuses = {status: sum(item.status == status for item in items) for status in ("new", "duplicate", "differs", "ask")}
            results[want["nationalId"]] = {
                "items": len(items), "statuses": statuses, "import": summary,
                "problems": item_problems + import_problems,
            }
            name = patient_of(bundle)["name"][0]["text"]
            print(f"{want['nationalId']} {name}: {len(items)} items {statuses}; import {summary['kinds']}; "
                  f"{'OK' if not results[want['nationalId']]['problems'] else str(len(results[want['nationalId']]['problems'])) + ' problem(s)'}")
            for problem in results[want["nationalId"]]["problems"]:
                print(f"   - {problem}")
    finally:
        await llm.close()
    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-onboarding"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = sum(bool(result["problems"]) for result in results.values())
    print(f"\n{len(results) - failed}/{len(results)} records as expected. Report: {folder / 'results.json'}")
    return 0
