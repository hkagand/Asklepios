# Remove Admission, Keep the History Import: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take patient admission out of Asklepios (the New patient tab, the consent flow, the simulated national service) while the two outside-history patients arrive in the chart already imported, by running the kept import logic when the synthetic data is generated.

**Architecture:** `agent/onboard.py` keeps the review and import of a national patient summary and gains one unattended entry point, `settled_import`. `synthetic/national.py` holds each person's summary, the answers settled with them and their first appointment, and calls that entry point; `generate.py` writes the result as ordinary patient bundles. The evals and the generator build these charts through the same function.

**Tech Stack:** Python 3.12 (FastAPI agent, stdlib generator), React 19 + Vite + TypeScript + Tailwind, HAPI FHIR R4 in Docker. There is no unit-test framework in this repository: the deterministic checks are `python -m evals --lint` and `python -m evals --onboarding`, the type check is `npm run build`, and the model-graded check is the gold set against a baseline.

**Spec:** `docs/superpowers/specs/2026-11-12-remove-admission-keep-history-import-design.md`

## Global Constraints

- Resource ids of imported items stay as they are (`nr-alg-p-3001-001`, `nr-ms-p-3001-001`, `nr-cond-p-3001-003`, …): gold cases cite them.
- The imported Patient resources keep the HTEST security label, or the demo reset refuses to run.
- Generation stays deterministic for a given anchor and seed, and adding the two patients changes no other chart.
- Text a doctor reads never says "onboarding", "New patient" (as a screen) or "consent code". "At onboarding" becomes "when their history was taken".
- Imported items keep the `national-import` tag; medicines stay MedicationStatements, never orders.
- p-2042 (Nermin Aktaş) is not imported into. Her national record stays an eval input only.
- File, module and flag names stay: `agent/onboard.py`, `evals/onboarding.py`, `evals/onboarding.toml`, `--onboarding`, gold category `onboarding` and the gold case ids. (The spec leaves renaming to the builder; keeping them makes the baseline comparison case-for-case.)
- `.claude/launch.json` is untracked and local: edit it, do not `git add` it.
- Commit messages follow the repository's style (one imperative sentence, e.g. "Add a demo reset that puts every chart back…") and end with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- The gold anchor is `2026-10-23` (a Friday), seed `2041`. The history is therefore taken on Thursday `2026-10-22`.

## Review Focus

1. **Anchor on a Monday or a weekend.** The history must still be taken on a working day before the anchor, and the appointment must fall on or after it. Pinned in Task 4, Step 1 (`check_generated` runs for `2026-10-24` and `2026-10-26` as well).
2. **`generate.py` run before the agent's requirements are installed.** A person following ONBOARDING.md out of order should get one line telling them what to install, not a traceback from inside `agent/`. Pinned in Task 4, Step 5.
3. **A server that still holds items imported the old way** (tagged `national-import`, no import-day extension). ASKlepios must still name the source, simply without an import day, and must not fall back to the load time. Pinned in Task 3, Step 1 (`check_imported_text`).
4. **An unattended import that meets something it cannot settle**: "no known allergies" on the summary against a chart that records allergies. With no clinician to refuse it, the import must skip that item and carry on, not raise. Pinned in Task 3, Step 1 (`check_unattended`).
5. **A lab series that mixes results taken here and elsewhere.** No generated patient has one, so nothing exercises it. The outside points must be marked one by one and the row badge must not claim the whole series. Pinned in Task 6, Step 3 (a reviewer reads the condition; Step 4 checks the all-imported case in the browser).

---

### Task 1: Branch and baseline

**Files:** none changed. Commits the spec and this plan.

**Interfaces:**
- Produces: `evals/runs/<baseline>/` (gitignored), whose folder name later tasks pass to `--baseline`. Write the folder name into the task notes.

- [ ] **Step 1: Branch**

```bash
git switch -c remove-admission
git add docs/superpowers
git commit -m "Describe removing patient admission while keeping the history import"
```

- [ ] **Step 2: Confirm the deterministic checks pass before any change**

Run: `python -m evals --lint` → expected: `68 cases, … patients: no problems.` (the count may differ; "no problems" is what matters)
Run: `python -m evals --onboarding` → expected: `3/3 records as expected.`

`--onboarding` reads `agent/.env` and, if p-2042's surgical history is not cached, calls the model once. If the model endpoint is unreachable, stop and tell the user: nothing in this plan can be measured without it.

- [ ] **Step 3: Take the baseline**

Run: `python -m evals --repeats 3`
Expected: a report under `evals/runs/<timestamp>-<model>/`. Note the folder name and the onboarding category's pass count (out of 18).

Run: `python -m evals --visits` and note that p-3001's visit raises the penicillin allergy alert.

- [ ] **Step 4: Keep a copy of the cohort as generated today**

Run: `python synthetic/generate.py --anchor 2026-10-23 --seed 2041 --out evals/runs/cohort-before`
(`evals/runs/` is gitignored.) Task 4 compares against it to show that no other chart changed.

---

### Task 2: Remove the admission screens, endpoints and service

**Files:**
- Delete: `web/src/views/Onboard.tsx`, `national/__init__.py`, `national/__main__.py`, `national/app.py`
- Modify: `web/src/App.tsx` (import line 10, route branch lines 30-31, nav link line 163, reset confirmation lines 70-73)
- Modify: `web/src/route.ts` (the `onboard` member of `Route` and its line in `parse`)
- Modify: `web/src/agent.ts` (the whole "onboarding (agent/onboard.py)" section, lines 460-543; `national` in `DemoReset`, line 216)
- Modify: `web/vite.config.ts` (the `/national` proxy, lines 11-15)
- Modify: `agent/app.py` (module docstring lines 26-30; imports lines 77-89; `app.state.national` and `app.state.onboardings` lines 119-120 and 137; the onboarding block lines 348-495; reset lines 825-826 and 843-849)
- Modify: `agent/config.py` (`national_base_url`, lines 34 and 70)
- Modify: `agent/onboard.py` (remove `import httpx`, `NationalError`, `NationalClient`)
- Modify: `agent/demo.py` (docstring lines 6-11 only)
- Modify: `.claude/launch.json` (remove the `national` configuration; not committed)

**Interfaces:**
- Consumes: nothing.
- Produces: `agent/onboard.py` still exports `review_items`, `Item`, `Decision`, `ImportRefused`, `import_transaction`, `new_patient_id`, `national_id_of`, `patient_of`, unchanged. `POST /api/demo/reset` no longer returns `national`.

- [ ] **Step 1: Remove the web screen**

Delete `Onboard.tsx`; remove its import, route branch and nav link from `App.tsx`; remove `onboard` from `route.ts` so `#/onboard` falls through to `{ page: 'worklist' }`; remove the onboarding section and `national` from `agent.ts`; remove the proxy.

The reset confirmation becomes exactly:

```
Reset the demo?

Everything done since the synthetic data was loaded is removed: visits and signed notes, and review and "patient told" marks. Every chart goes back to how it was loaded.
```

- [ ] **Step 2: Type-check the web app**

Run: `npm --prefix web run build`
Expected: exits 0. A dangling import of anything removed fails here.

- [ ] **Step 3: Remove the agent endpoints, the client and the service**

In `agent/app.py` remove everything listed above, then remove each import that no longer has a use (`secrets` is used only by the removed block; `Literal` and `Counter` are still used elsewhere and stay). The reset docstring becomes "Puts the demo back to the synthetic data as loaded (demo.py): the FHIR server, visits and chat sessions." Delete the `national/` package and the two settings lines.

- [ ] **Step 4: Verify the agent still imports and nothing refers to what was removed**

Run: `python -c "import agent.app, agent.onboard; print('ok')"` → expected: `ok`
Run: `python -m evals --lint` → expected: no problems
Run: `python -m evals --onboarding` → expected: `3/3 records as expected.`
Search (expected: no matches outside `docs/`, `README.md`, `ONBOARDING.md`, which Task 7 owns):

```bash
git grep -n -i -E "NationalClient|NationalError|national_base_url|NATIONAL_BASE_URL|/api/onboarding|8090|python -m national|nationalPhone|nationalPeople" -- . ":!docs" ":!README.md" ":!ONBOARDING.md" ":!web/package-lock.json"
```

- [ ] **Step 5: Commit**

```bash
git add -A web agent national
git commit -m "Remove the New patient screen, the consent endpoints and the simulated national service"
```

---

### Task 3: Make the import unattended

**Files:**
- Modify: `agent/record.py` (new constant; `Record.imported_from`, lines 371-385)
- Modify: `agent/onboard.py` (`import_transaction`, new `decisions_from_answers` and `settled_import`)
- Modify: `evals/onboarding.py` (the checks; `decisions_for` moves out; `onboarded_records` and `check_import` use the new signature)
- Test: `python -m evals --onboarding`

**Interfaces:**
- Consumes: Task 2's `agent/onboard.py`.
- Produces, in `agent/record.py`:
  - `IMPORTED_ON = "urn:demo:asklepios:imported-on"`: the url of a resource-level extension whose `valueDate` is the day the history was taken.
- Produces, in `agent/onboard.py`:
  - `import_transaction(bundle: dict, items: list[Item], decisions: list[Decision], *, patient_id: str, existing: bool, taken: datetime) -> dict`. The parameters `practitioner`, `consent`, `onboarding` and `now` are gone.
  - `decisions_from_answers(items: list[Item], answers: list[dict]) -> list[Decision]`. An answer is `{"match": <phrase in the item's label>, "taking": "yes"|"no"|"different", "dose": str}` for a medicine or `{"match": …, "current": bool}` for a problem.
  - `settled_import(bundle: dict, answers: list[dict], *, taken: datetime, record: Record | None = None, history: dict | None = None) -> dict`: the FHIR transaction for a summary whose answers are already settled.

- [ ] **Step 1: Write the failing checks in `evals/onboarding.py`**

Change `check_import`'s `options` to `dict(patient_id=patient_id, existing=bool(chart), taken=TAKEN)` with a module constant `TAKEN = datetime(2026, 10, 22, 9, 0, tzinfo=timezone(timedelta(hours=3)))`, replace the local `decisions_for` with `decisions_from_answers` imported from `agent.onboard`, and add after `provenance` is read:

```python
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
```

Add two functions and call both from `run_onboarding`, appending their problems to the record's (for `check_imported_text`) and printing the others under a line `unattended import:`:

```python
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
    """With nobody to refuse it, "no known allergies" against a chart with allergies is skipped, not fatal."""
    try:
        transaction = settled_import(bundles["00000003002"], [], taken=TAKEN, record=records["p-1019"], history=None)
    except ImportRefused as error:
        return [f"the import stopped: {error}"]
    kinds = [entry["resource"]["resourceType"] for entry in transaction["entry"]]
    problems = ["no known allergies was written over recorded allergies"] if "AllergyIntolerance" in kinds else []
    return problems + (["a Patient was written for a patient already in the chart"] if "Patient" in kinds else [])
```

(00000003002 is Murat Özdemir, whose summary records no known allergies; p-1019 has a penicillin allergy.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m evals --onboarding`
Expected: FAIL at import (`decisions_from_answers`, `settled_import`, `IMPORTED_ON` do not exist).

- [ ] **Step 3: Implement in `agent/record.py`**

Add `IMPORTED_ON`. `Record.imported_from` takes the import day from that extension's `valueDate` and never reads `meta.lastUpdated`; with no extension it returns the text without an "imported …" part.

- [ ] **Step 4: Implement in `agent/onboard.py`**

- `import_transaction` with the signature above. `stamp = taken.isoformat(timespec="seconds")`. Every written resource except the Provenance gets `extension: [{"url": IMPORTED_ON, "valueDate": taken.date().isoformat()}]`.
- The new Patient's hospital-number identifier gains `"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR", "display": "Medical record number"}]}`, as `PatientChart.__init__` in `synthetic/chart.py` writes it.
- The Provenance: id `prov-national-{patient_id}-{taken:%Y%m%d}`; no `policy`; `agent` is `[{type: custodian, who: ORGANIZATION}, {type: informant, who: {"display": SERVICE}}]` (same code system as today).
- `decisions_from_answers`: the body of today's `decisions_for` in `evals/onboarding.py`, matching with `fold(answer["match"]) in fold(item.label)`, plus one rule: an allergy item with status `differs` gets `Decision(item.key, False)`.
- `settled_import`: `review_items(bundle, record, history, taken.date())`, then `decisions_from_answers`, then `import_transaction` with `patient_id=record.id if record else new_patient_id(national_id)` and `existing=record is not None`.
- Update the module docstring: it describes the review and the unattended import of a national summary; the consent steps and "the clinician accepts" are gone.

- [ ] **Step 5: Bring `onboarded_records` in line**

It calls `import_transaction(..., taken=datetime(anchor.year, anchor.month, anchor.day, 9, 0, tzinfo=timezone(timedelta(hours=3))))` for now (Task 4 replaces this function), and no longer writes `meta.lastUpdated`.

- [ ] **Step 6: Run to verify it passes**

Run: `python -m evals --onboarding` → expected: `3/3 records as expected.` and `unattended import: OK`
Run: `python -m evals --lint` → expected: no problems

- [ ] **Step 7: Commit**

```bash
git add agent/onboard.py agent/record.py evals/onboarding.py
git commit -m "Import a national summary without a clinician: settled answers in, the hospital as custodian"
```

---

### Task 4: Generate the two patients already imported

**Files:**
- Modify: `synthetic/national.py` (`Person`, the two new people, new functions)
- Modify: `synthetic/chart.py` (`PatientChart.appointment`, line 882)
- Modify: `synthetic/generate.py` (write the imported patients; stop writing `output/national/`)
- Modify: `synthetic/cohort.py` (comment at line 2510 only)
- Modify: `evals/onboarding.py`, `evals/onboarding.toml`, `evals/run.py` (lines 444-448, 464-467)
- Test: `python -m evals --onboarding`, `python -m evals --lint`

**Interfaces:**
- Consumes: `settled_import` from Task 3.
- Produces, in `synthetic/national.py`:
  - `Person(chart, national_id, phone, answers: tuple[dict, ...] = (), visit: tuple[int, int, int] | None = None)`. `visit` is (working days after the anchor, hour, minute); only people not yet in the chart have one.
  - `people(anchor: date) -> list[Person]`
  - `history_taken(anchor: date) -> datetime`: 09:00 (+03:00) on the last working day before the anchor.
  - `FIRST_VISIT = "New patient: first visit"`
  - `imported_charts(anchor: date) -> dict[str, list[dict]]`: patient id → that patient's resources, Patient first, then the imported items, the Provenance, and one Appointment. Only people with a `visit`.
- Produces, in `evals/onboarding.py`: `imported_records(anchor: date) -> dict[str, Record]` (replaces `onboarded_records`).
- Values: Gülay Kaplan `answers=({"match": "atorvastatin", "taking": "no"}, {"match": "asthma", "current": False})`, `visit=(0, 15, 30)`. Murat Özdemir `answers=({"match": "ramipril", "taking": "different", "dose": "10 mg once daily"},)`, `visit=(1, 15, 30)`. Both with `AYDIN` (pr-aydin). 15:30 is not one of `CLINIC_TIMES`. Nermin Aktaş: no answers, no visit.

- [ ] **Step 1: Write the failing check in `evals/onboarding.py`**

```python
def check_generated(records: dict[str, Record], anchor: date) -> list[str]:
    """The imported patients as the generator writes them: settled, synthetic, and on a clinic list."""
    from national import FIRST_VISIT, history_taken, imported_charts  # synthetic/ is on sys.path via national_bundles

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
```

`run_onboarding` gains a `seed: int` parameter (passed from `run.py`) and calls `check_generated` for the gold anchor, and for `date(2026, 10, 24)` (a Saturday) and `date(2026, 10, 26)` (a Monday) with `records` rebuilt by `cohort_records(that_day, seed)` for each. It prints `generated patients: OK` or the problems.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m evals --onboarding`
Expected: FAIL with `ImportError: cannot import name 'FIRST_VISIT'`.

- [ ] **Step 3: Implement in `synthetic/chart.py` and `synthetic/national.py`**

- `PatientChart.appointment(self, start, clinician, description, *, minutes=20, kind=("FOLLOWUP", "A follow up visit from a previous appointment"))`; `kind` fills the `appointmentType` coding. Existing callers are unchanged.
- `imported_charts` builds each person, takes `summary(person, anchor)`, calls `settled_import(bundle, list(person.answers), taken=history_taken(anchor))`, and adds `person.chart.appointment(at(add_workdays(anchor, days), hour, minute), AYDIN, FIRST_VISIT, kind=("ROUTINE", "Routine appointment - default if not valued"))`. It imports `agent.onboard` inside the function, after putting the repository root on `sys.path`, so `national_records` and the rest of `synthetic/` stay standard-library only.
- The Appointment's patient reference is `person.chart.ref` (`Patient/p-3001`), which is the id the import gives the patient.
- Update the module docstring: the records are the input of an import run at generation; no service serves them.

- [ ] **Step 4: Use it in the evals**

- `imported_records(anchor)` builds a `Record(patient, found, today=anchor)` per chart from `imported_charts`, leaving the Provenance out of `found` (the agent does not read Provenance from the server either).
- `run.py`: `question_records = records | imported_records(anchor)`.
- `check_import` and `run_onboarding` take each record's answers from `people(anchor)` by national id; the `answers` keys and their header lines leave `onboarding.toml`, whose header now says the answers live in `synthetic/national.py`.

- [ ] **Step 5: Write the bundles in `synthetic/generate.py`**

After the cohort loop, for each `(pid, resources)` of `imported_charts(args.anchor)`: write `transaction(resources)` to `<out>/<pid>.json`, add to `totals`, print the same row format. Remove the block that writes `<out>/national/` and delete that folder if it exists (`shutil.rmtree(..., ignore_errors=True)`). Wrap the `imported_charts` call so an `ImportError` exits with exactly:

```
The imported patients need the agent's packages: pip install -r agent/requirements.txt
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m evals --onboarding` → expected: `3/3 records as expected.`, `unattended import: OK`, `generated patients: OK`
Run: `python -m evals --lint` → expected: no problems
Run: `python synthetic/generate.py --anchor 2026-10-23 --seed 2041` → expected: rows for `P-3001` and `P-3002`, a total of 23 patients, and files `synthetic/output/p-3001.json`, `p-3002.json`; no `synthetic/output/national/`.
Confirm no other chart changed, against the copy Task 1 made:

```bash
diff -rq --exclude=national --exclude="p-300*" evals/runs/cohort-before synthetic/output
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add synthetic evals
git commit -m "Generate the two national-record patients already imported, each with a first appointment"
```

---

### Task 5: Say "when their history was taken"

**Files:**
- Modify: `agent/record.py` (comment line 181, docstrings lines 372 and 625, the group heading at line 697)
- Modify: `agent/meds.py` (`reported`, lines 285-300)
- Modify: `agent/chat.py` (lines 55-56)
- Modify: `web/src/views/Overview.tsx` (comment line 403, badge title line 406), `web/src/model.ts` (comments lines 30 and 205)
- Modify: `evals/gold.toml` (lines 616-675: the section comment and four `expected` texts)

**Interfaces:**
- Consumes: Task 4's charts (history taken on 22 Oct 2026 for the gold anchor).
- Produces: no code interface. Exact copy:
  - `agent/record.py` heading: `What the patient says they take (said when their history was taken; not orders):`
  - `agent/meds.py`: `said = f"when their history was taken on {day}"`, or `"when their history was taken"` with no date. The two sentences around it are unchanged.
  - `agent/chat.py`: `- Lines that start "From the national record (simulated)" were imported from records kept elsewhere, before the patient's first visit here: whenever you use one, say it comes from the national record, with the facility and date the line gives.`
  - Badge title: `Imported from the national record (simulated) before the first visit`
  - `gold.toml` `expected` texts: "imported on 23 Oct 2026" → "imported on 22 Oct 2026"; "Per what she said at onboarding on 23 Oct 2026" → "Per what she said when her history was taken on 22 Oct 2026"; "recorded as no longer current at onboarding" → "recorded as no longer current when her history was taken"; "He said at onboarding that" → "He said when his history was taken that". `mentions`, `cites`, ids and categories are untouched.

- [ ] **Step 1: Write the failing check**

Run (expected today: matches in the files above):

```bash
git grep -n -i "onboarding" -- agent/record.py agent/meds.py agent/chat.py agent/jottings.py agent/considerations.py agent/visits.py web/src
```

- [ ] **Step 2: Make the edits above**

- [ ] **Step 3: Verify**

Run the grep again → expected: no matches.
Run: `python -m evals --lint` → no problems. Run: `npm --prefix web run build` → exits 0.
Run: `python -m evals --category onboarding --repeats 3` → expected: at least as many passes as the baseline's onboarding category (Task 1). If fewer, read the failing answers in the run's `report.md` and revise the `agent/chat.py` or `agent/record.py` wording, not the gold checks.

- [ ] **Step 4: Commit**

```bash
git add agent web/src evals/gold.toml
git commit -m "Say when the patient's history was taken instead of onboarding"
```

---

### Task 6: Mark outside results in the Labs tab

**Files:**
- Modify: `web/src/components/ui.tsx` (add `NationalBadge`), `web/src/views/Overview.tsx` (use it from there; delete the local one at lines 403-410)
- Modify: `web/src/model.ts` (add `measuredElsewhere`)
- Modify: `web/src/views/Labs.tsx` (`ResultRow`, the `Trend` tooltip and point table)

**Interfaces:**
- Consumes: `isImported` in `web/src/model.ts`; Task 5's badge title.
- Produces:
  - `export function NationalBadge(): JSX.Element` in `components/ui.tsx`: the violet "National record" badge, same title as Task 5.
  - `export function measuredElsewhere(observation: fhir4.Observation): string | undefined` in `model.ts`: `undefined` for a result taken here; for an imported one, the first `performer` display without a trailing " laboratory" (e.g. `Demo State Hospital`), or `another facility` when the result names none.

- [ ] **Step 1: Move the badge and add `measuredElsewhere`**

- [ ] **Step 2: Mark the results in `Labs.tsx`**

- Point table in `Trend` (one row per result): an imported result shows `<NationalBadge />` and its facility next to the date.
- Tooltip in `Trend`: an imported point adds a line `Measured at <facility> · national record`.
- `ResultRow`, Latest and Previous cells: under the date, the facility of that result when it is imported, in the badge's violet, with the badge's title.
- `ResultRow`, Test cell: `<NationalBadge />` only when every point of the series is imported.

- [ ] **Step 3: Check the mixed case by reading**

Each of the four places must decide per point from `measuredElsewhere(point.observation)`, except the Test-cell badge, which must use `series.points.every(…)`. A series with one outside result among results taken here must show no row badge and exactly one marked point.

- [ ] **Step 4: Verify**

Run: `npm --prefix web run build` → exits 0.
With HAPI loaded from Task 4's output (`docker compose up -d`, `python synthetic/load.py`) and the `agent` and `web` servers started from `.claude/launch.json`, open `http://localhost:5173/#/patients/p-3001/labs`.
Expected: every row's Test cell shows "National record"; "Demo State Hospital" appears under each Latest and Previous date and in each row of the HbA1c point table. Open `#/patients/p-2041/labs`: no badge and no facility anywhere. Take a screenshot of each.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "Mark results measured elsewhere in the Labs tab, with the facility"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md` (line 15 Onboarding bullet; line 17 cohort bullet; line 61 demo reset paragraph; lines 87-93 step 6; lines 95-127 "National record service (simulated)" and "Onboarding"; line 209 "what a patient said at onboarding"; lines 276-278 and 300 in Evaluate; the Layout block near line 309)
- Modify: `ONBOARDING.md` (the services table row for port 8090, line 11; step 7 "three terminals" and "Terminal 1", lines 143-149, renumbering the other two; the troubleshooting row at line 222)
- Modify: `agent/.env.example` only if it mentions the national service (it does not today; leave it)

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Rewrite the README parts**

- The cohort bullet says 23 patients: 21 with full histories here, and two (Gülay Kaplan, p-3001; Murat Özdemir, p-3002) whose history came from the national record before their first visit.
- Replace the two sections with one, "History from the national record", covering: what the two patients carry (keep the "Worth catching" facts from today's table, for p-3001 and p-3002); that the items are tagged, shown with a National record badge on the Overview and in Labs, and cited by ASKlepios as "· national record"; that medicines are what the patient said, never orders; that the import (`agent/onboard.py`, `settled_import`) runs when the data is generated, with the answers in `synthetic/national.py`, and is kept as the building block for fetching a summary from a system such as e-Nabız later; that Asklepios has no admission screen and reads no national service. Keep the "ASKlepios and imported items" paragraph, with "at onboarding" reworded.
- Step 6 ("Optional: the simulated national record service") is deleted. The demo reset paragraph no longer lists onboarded patients, onboarding sessions or the national service. The Layout block drops `national/`.
- Evaluate: `--onboarding` "checks the import of a national summary … and the two generated patients"; the onboarding cases "ask about p-3001 and p-3002 as generated".

- [ ] **Step 2: Edit ONBOARDING.md** as listed.

- [ ] **Step 3: Verify**

```bash
git grep -n -i -E "8090|python -m national|New patient|consent code|e-Nabız is|Demo people|three terminals" -- README.md ONBOARDING.md
```

Expected: no matches, except a sentence that names e-Nabız as the future source.

- [ ] **Step 4: Commit**

```bash
git add README.md ONBOARDING.md
git commit -m "Document the national-record patients as generated, and drop the admission steps"
```

---

### Task 8: Whole-change verification

**Files:** none.

- [ ] **Step 1: Clean data**

```bash
docker compose down
docker compose up -d
python synthetic/generate.py --anchor 2026-10-23 --seed 2041
python synthetic/load.py
```

Expected: `p-3001.json` and `p-3002.json` each load with `201 Created` entries, and no "also holds resources this load did not write" note.

- [ ] **Step 2: Deterministic checks**

Run: `python -m evals --lint`, `python -m evals --onboarding` → as in Task 4, Step 6.
Run: `python -m evals --visits` → p-3001's visit still raises the penicillin alert.

- [ ] **Step 3: Gold set against the baseline**

Run: `python -m evals --repeats 3 --baseline evals/runs/<baseline folder from Task 1>`
Expected: the onboarding category passes at least as often as in the baseline, and no other category drops by more than one case-run. A larger drop is treated as caused by the new wording: revise it (Task 5) and run again.

- [ ] **Step 4: The screens, with `AGENT_TODAY=2026-10-23` and `AGENT_DEMO_RESET=1` in `agent/.env`**

Start `agent` and `web` from `.claude/launch.json` and check, with a screenshot of each:
- The top bar has My day and All appointments only. `http://localhost:5173/#/onboard` shows All appointments.
- Viewing as Dr. Elif Aydın, My day for 23 Oct 2026 lists Gülay Kaplan at 15:30 with "New patient: first visit". All appointments lists her with hospital number P-3001, and Murat Özdemir (P-3002) on the next working day.
- p-3001's Overview shows the National record badges and "What the patient says they take"; the patient header shows P-3001.
- Asking ASKlepios "Does she have any allergies?" answers penicillin with a "· national record" chip and "imported 22 Oct 2026".
- Start a visit for p-3002: the agenda has "Confirm Ramipril …" with "when their history was taken on 22 Oct 2026".
- Reset demo: the confirmation has the new text; after it, both patients are still listed.

- [ ] **Step 5: Hand back**

Report the baseline and final pass counts per category, the screenshots, and anything that did not meet its expected result. Do not merge or push; the user decides how the branch is integrated.
