"""Checks onboarding (agent/onboard.py) against evals/onboarding.toml: python -m evals --onboarding

For each national record, the review is built against the cohort chart as the agent would (surgical history from the
cache, so an existing patient's notes are read once), and each expected item must have its status. Then the import
is built with the patient's answers (synthetic/national.py) and checked: nothing already in the chart is imported,
every reference points to our patient, medicines become MedicationStatements as the patient answered, each item
carries the day the history was taken, and one Provenance naming the hospital covers it all. Then two checks with
nobody watching: an import that meets what it cannot settle, and the two patients as the generator writes them.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agent.config import Settings
from agent.llm import LlmClient
from agent.onboard import (
    MRN_SYSTEM, Decision, ImportRefused, Item, decisions_from_answers, import_transaction, new_patient_id, national_id_of,
    patient_of, review_items, settled_import,
)
from agent.record import IMPORTED_ON, Record, code_of
from agent.surgery import SurgeryReader, from_procedure, surgical_history

from .run import ROOT, cohort_records, says

# When the history was taken, for the checks of the import itself: the working day before the gold anchor.
TAKEN = datetime(2026, 10, 22, 9, 0, tzinfo=timezone(timedelta(hours=3)))


def national_bundles(anchor: date) -> dict[str, dict]:
    sys.path.insert(0, str(ROOT / "synthetic"))
    from national import national_records

    return {national_id_of(patient_of(bundle)): bundle for bundle in national_records(anchor)}


def settled_answers(anchor: date) -> dict[str, list[dict]]:
    """What was settled with each patient, by national id: the generator's own answers (synthetic/national.py)."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from national import people

    return {person.national_id: list(person.answers) for person in people(anchor)}


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


def check_import(bundle: dict, items: list[Item], answers: list[dict], chart: str) -> tuple[list[str], dict]:
    """The import with the patient's answers, and refusals that must hold."""
    problems = []
    national_id = national_id_of(patient_of(bundle))
    patient_id = chart or new_patient_id(national_id)
    options = dict(patient_id=patient_id, existing=bool(chart), taken=TAKEN)
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

    transaction = import_transaction(bundle, items, decisions_from_answers(items, answers), **options)
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
    patient = next((resource for resource in written if resource["resourceType"] == "Patient"), None)
    if patient and not any(code_of(item.get("type")) == "MR" and item.get("system") == MRN_SYSTEM for item in patient["identifier"]):
        problems.append("the Patient's hospital number has no MR type coding")
    for resource in written[:-1]:
        days = [item.get("valueDate") for item in resource.get("extension", []) if item.get("url") == IMPORTED_ON]
        if days != ["2026-10-22"]:
            problems.append(f"{resource['resourceType']}/{resource['id']}: import day {days}, expected ['2026-10-22']")
    whos = [agent.get("who", {}) for agent in provenance.get("agent", [])]
    if "policy" in provenance:
        problems.append("the Provenance still names a consent request")
    if not any(who.get("reference") == "Organization/org-demo-hospital" for who in whos):
        problems.append("the Provenance does not name the hospital")
    if any(who.get("reference", "").startswith("Practitioner/") for who in whos):
        problems.append("the Provenance names a clinician")
    if provenance.get("recorded") != "2026-10-22T09:00:00+03:00":
        problems.append(f"the Provenance is recorded {provenance.get('recorded')}")
    problems += check_imported_text(written)
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


def check_imported_text(written: list[dict]) -> list[str]:
    """What ASKlepios says about an imported item: the import day from the item, never the load time."""
    problems = []
    item = next(resource for resource in written if resource["resourceType"] not in ("Patient", "Provenance"))
    loaded = item | {"meta": item["meta"] | {"lastUpdated": "2026-11-12T10:00:00+00:00"}}
    if not (Record.imported_from(loaded) or "").endswith("imported 22 Oct 2026"):
        problems.append(f"import text: {Record.imported_from(loaded)!r}")
    old = {key: value for key, value in loaded.items() if key != "extension"}
    text = Record.imported_from(old)
    if text is None or not text.startswith("from the national record") or "imported " in text:
        problems.append(f"an item imported before the extension existed reads {text!r}")
    return problems


def check_unattended(bundles: dict[str, dict], records: dict[str, Record]) -> list[str]:
    """With nobody to refuse it, an import skips only what it cannot settle, says what it left out, and never stops."""
    problems = []
    try:
        # Murat Özdemir's summary records no known allergies; p-1019 has a penicillin allergy.
        settled = settled_import(bundles["00000003002"], [], taken=TAKEN, record=records["p-1019"], history=None)
        kinds = [entry["resource"]["resourceType"] for entry in settled.transaction["entry"]]
        if "AllergyIntolerance" in kinds:
            problems.append("no known allergies was written over recorded allergies")
        if "Patient" in kinds:
            problems.append("a Patient was written for a patient already in the chart")
        if not any(item.section == "allergies" for item, _ in settled.left_out):
            problems.append("the import does not say it left out \"no known allergies\"")

        # The other way round must not lose an allergy: Gülay Kaplan's summary has a penicillin allergy, and
        # p-2042's chart records no known allergies.
        settled = settled_import(bundles["00000003001"], [], taken=TAKEN, record=records["p-2042"], history=None)
        written = [entry["resource"] for entry in settled.transaction["entry"]]
        if not any(resource["resourceType"] == "AllergyIntolerance" and says(resource["code"].get("text", ""), "penicillin") for resource in written):
            problems.append("a penicillin allergy was dropped because the chart records no known allergies")

        # Nothing left to write is a result, not a failure: a summary holding only "no known allergies".
        only = bundles["00000003002"]
        kept = [entry for entry in only["entry"] if entry["resource"]["resourceType"] in ("Patient", "AllergyIntolerance")]
        settled = settled_import(only | {"entry": kept}, [], taken=TAKEN, record=records["p-1019"], history=None)
        if settled.transaction is not None or len(settled.left_out) != 1:
            problems.append(f"nothing to write: transaction {settled.transaction is not None}, {len(settled.left_out)} left out")
    except ImportRefused as error:
        problems.append(f"the import stopped: {error}")
    return problems


def check_done_elsewhere(records: dict[str, Record]) -> list[str]:
    """An operation imported from the national record was not done here, unless the record says it was."""
    problems = []
    for record in records.values():
        for procedure in record.resources.values():
            if procedure["resourceType"] != "Procedure":
                continue
            mention = from_procedure(record, procedure)
            if mention.here or not mention.elsewhere:
                problems.append(f"{record.id}: {mention.name} reads as done at this hospital")
    return problems


def check_generated(records: dict[str, Record], anchor: date) -> list[str]:
    """The imported patients as the generator writes them: settled, synthetic, and on a clinic list."""
    from national import FIRST_VISIT, history_taken, imported_charts  # synthetic/ is on sys.path (national_bundles)

    problems = []
    charts = imported_charts(anchor)
    if sorted(charts) != ["p-3001", "p-3002"]:
        return [f"imported patients: {sorted(charts)}"]
    if json.dumps(charts, sort_keys=True) != json.dumps(imported_charts(anchor), sort_keys=True):
        problems.append("two runs for the same anchor differ")
    taken = history_taken(anchor)
    if taken.date() >= anchor or taken.weekday() >= 5:
        problems.append(f"history taken on {taken.date()}, not a working day before {anchor}")
    booked = {
        (resource["start"], actor["actor"]["reference"])
        for record in records.values() for resource in record.resources.values()
        if resource["resourceType"] == "Appointment" for actor in resource["participant"]
    }
    for patient_id, resources in charts.items():
        patient = resources[0]
        if patient["resourceType"] != "Patient" or patient["id"] != patient_id:
            problems.append(f"{patient_id}: the Patient is not first")
        if not any(label.get("code") == "HTEST" for label in patient.get("meta", {}).get("security", [])):
            problems.append(f"{patient_id}: not marked synthetic")
        appointments = [resource for resource in resources if resource["resourceType"] == "Appointment"]
        if len(appointments) != 1:
            problems.append(f"{patient_id}: {len(appointments)} appointments")
            continue
        appointment = appointments[0]
        actors = {actor["actor"]["reference"] for actor in appointment["participant"]}
        if actors != {f"Patient/{patient_id}", "Practitioner/pr-aydin"}:
            problems.append(f"{patient_id}: appointment with {sorted(actors)}")
        if appointment["description"] != FIRST_VISIT or appointment["start"][:10] < anchor.isoformat():
            problems.append(f"{patient_id}: appointment {appointment['description']!r} at {appointment['start']}")
        if (appointment["start"], "Practitioner/pr-aydin") in booked:
            problems.append(f"{patient_id}: {appointment['start']} is already booked for pr-aydin")
        if appointment["appointmentType"]["coding"][0]["code"] != "ROUTINE":
            problems.append(f"{patient_id}: a first visit is typed as a follow-up")
    return problems


def imported_records(anchor: date) -> dict[str, Record]:
    """The two patients whose history was imported from the national record, as the generator writes them
    (synthetic/national.py) and the agent reads them on the anchor day: for gold questions about imported history."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from national import imported_charts

    records = {}
    for patient_id, resources in imported_charts(anchor).items():
        found: dict[str, list[dict]] = {}
        for resource in resources[1:]:
            # The agent does not read Provenance from the server either.
            if resource["resourceType"] != "Provenance":
                found.setdefault(resource["resourceType"], []).append(resource)
        records[patient_id] = Record(resources[0], found, today=anchor)
    return records


async def run_onboarding(settings: Settings, records: dict[str, Record], anchor: date, seed: int, expected_path: Path, out: Path) -> int:
    expected = tomllib.loads(expected_path.read_text(encoding="utf-8"))["record"]
    bundles = national_bundles(anchor)
    answers = settled_answers(anchor)
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
            import_problems, summary = check_import(bundle, items, answers[want["nationalId"]], want["chart"])
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
    unattended = check_unattended(bundles, records)
    print("unattended import: " + ("OK" if not unattended else "; ".join(unattended)))
    generated = []
    # The gold anchor is a Friday; a Saturday and a Monday move the day the history was taken and the first visit.
    for day in (anchor, date(2026, 10, 24), date(2026, 10, 26)):
        cohort = records if day == anchor else cohort_records(day, seed)
        generated += [f"{day}: {problem}" for problem in check_generated(cohort, day)]
    generated += check_done_elsewhere(imported_records(anchor))
    print("generated patients: " + ("OK" if not generated else "; ".join(generated)))
    folder = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-onboarding"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(results | {"unattended": {"problems": unattended}, "generated": {"problems": generated}}, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = sum(bool(result["problems"]) for result in results.values())
    print(f"\n{len(results) - failed}/{len(results)} records as expected. Report: {folder / 'results.json'}")
    return 1 if failed or unattended or generated else 0
