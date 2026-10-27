# Asklepios

A clinician-facing chart viewer and a record-grounded assistant, **ASKlepios**, for one open patient. The physician can ask about history, labs, treatments, pending work and what changed between reports; answers cite the FHIR resources they came from.

This repository is a synthetic demo. Every patient is invented. Do not load real records until the model endpoint, logging and access control have been reviewed for that use.

## What it is

- **Chart viewer** (`web/`): a clinician's day, the appointment list, then a patient page with overview, labs, visits, reports and medications. Built with React, Vite and Tailwind. Talks to HAPI FHIR through a Vite proxy.
- **ASKlepios** (`agent/`): a FastAPI service that answers questions about the patient whose chart is open. The model never sees raw FHIR JSON. It gets a compact chart index plus five read-only tools (`read_documents`, `lab_series`, `medication_history`, `order_history`, `search_record`). Citations are checked before they reach the panel.
- **Open loops** (`agent/plans.py`, `agent/loops.py`): what each clinician's latest note planned, open orders and new results, tracked from order to result, review and telling the patient. See [Open loops](#open-loops).
- **Medication reconciliation** (`agent/meds.py`): the medication orders against what the notes say, with a timeline per drug. See [Medications](#medications).
- **Surgical history** (`agent/surgery.py`): every earlier operation, merged from Procedure records, notes and reports, by body region. See [Surgical history](#surgical-history).
- **My day and prepared briefs** (`agent/briefs.py`): a clinician's clinic list with what needs attention, and a pre-visit brief per patient written before the clinic. See [My day](#my-day).
- **Synthetic cohort** (`synthetic/`): 21 seeded patients with labs, visit notes, imaging and pathology reports, medications, orders, procedures and appointments, and a few deliberate gaps for the checks above to find. Reloading overwrites the same resource ids.

The model is any OpenAI-compatible chat-completions endpoint that supports tool calling (vLLM, a LiteLLM proxy, and similar). Point `agent/.env` at it.

## Requirements

- Docker, for the FHIR server
- Python 3.12 or newer
- Node.js 20 or newer
- An OpenAI-compatible model endpoint with tool calling

## Run locally

From the repository root.

**1. Start HAPI FHIR**

```bash
docker compose up -d
```

HAPI is at `http://localhost:8080/fhir`. It keeps its data in memory: `docker compose restart` empties it.

**2. Generate and load the cohort**

```bash
python synthetic/generate.py --anchor 2026-10-23 --seed 2041
python synthetic/load.py
```

`--anchor` is “today” for the stories: histories end just before it, upcoming appointments start on or after it, on working days. Use today's date, since the chart viewer and the agent work with the real date. The same anchor and seed always produce the same ids, so a reload overwrites. A different anchor leaves resources from the old one behind (the loader says so); restart HAPI before loading for a clean dataset. Patient names depend on the anchor too.

**3. Configure the model**

```bash
cp agent/.env.example agent/.env
```

Fill in `LLM_BASE_URL`, `LLM_MODEL` and, if the endpoint needs one, `LLM_API_KEY`. Leave `FHIR_BASE_URL` as `http://localhost:8080/fhir` unless HAPI is elsewhere.

`agent/.env` is gitignored. Do not commit keys or internal hostnames.

**4. Start ASKlepios**

```bash
python -m agent
```

Listens on `http://127.0.0.1:8000`. Override the port with `AGENT_PORT`.

**5. Start the web app**

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) and choose who is viewing (top right). **My day** shows that clinician's next clinic day; **All appointments** lists every patient. Open a chart and use **ASKlepios** in the right-hand panel.

To ask from the terminal instead of the browser:

```bash
python -m agent.ask p-2041 "Why was oxaliplatin stopped?"
```

## Who is viewing, and marks

The "Viewing as" picker names a practitioner from the FHIR server. The web app sends it with every request to the agent (`X-Practitioner`), and the audit log records it. **It is a stand-in for sign-in, not authentication**: anyone can choose any name. Real use needs SMART on FHIR or similar.

Clinicians can leave two kinds of mark. They are the only things Asklepios writes; clinical records are never changed.

- **Reviewed:** a FHIR `Task` (completed, `focus` = the result, `owner` = the practitioner).
- **Patient told:** a FHIR `Communication` (`sender` = the practitioner, `recipient` = the patient, `about` = the results, with how and when).

Both carry an Asklepios tag. A mark is withdrawn by setting it to entered-in-error, never deleted, and only by the clinician who made it. Every mark and withdrawal goes to the audit log.

## Open loops

Follow-up that was planned in a note but never ordered, booked, resulted, reviewed or told to the patient.

1. The model reads each clinician's most recent note and lists its plan items: tests, imaging, referrals, follow-up visits, calls, meetings and medication changes, each with a due time. Every item must quote the note word for word. If a line of the note's PLAN section is not covered by any item, the model is asked again.
2. Plain code does the rest. It works out due dates, matches each item against orders, results, reports, appointments, visits and medication orders, and gives it a status. For a medication started or changed, the planned dose is compared with the dosage of the order written for it.
3. Open orders that no current plan covers are added, for example a referral from an earlier visit, and so are results since the last visit that no plan covers.

A test or scan is tracked through five stages: **ordered** (the order), **performed** (sample taken or scan done), **resulted** (final result issued), **reviewed** (a review mark) and **patient told** (a communication mark). A later visit note that quotes the result by its date counts for the last two, shown as inferred.

| Status | Meaning |
|---|---|
| `missing` | due date passed, nothing ordered, booked or resulted |
| `dose_mismatch` | a medication ordered as planned but at another dose (seeded: p-1007, furosemide 60 mg for a planned 80 mg) |
| `overdue` | ordered or booked, due date passed, no result |
| `to_review` | result on file, not reviewed |
| `not_ordered` | planned, nothing ordered yet |
| `no_trace` | a call or meeting the record cannot show |
| `to_inform` | reviewed, nothing records that the patient was told |
| `pending` | ordered or booked, not yet due |
| `conditional` | only if something happens |
| `done` | done; for a test, reviewed and the patient told |

The **Open loops** card at the top of the overview groups the items:
- **Needs action**
- **Results to review or tell the patient**, with **Mark reviewed**, **Patient told…** and **Undo my marks**
- **Cannot be confirmed from the record**
- **In progress**

Each test shows its stage ladder. The appointment list shows each patient's counts. When the agent service is not running, both fall back to the plain open orders.

`GET /api/patients/{id}/loops` returns the items with their stages and evidence ids, and `GET /api/loops/summary?patients=…` returns the counts. ASKlepios gets the items in its chart index as an OPEN LOOPS section.

## Medications

The record holds medication orders, not what the patient takes: there are no dispensing or administration records. The Medications tab says so at the top, and so does ASKlepios when asked what a patient is taking.

- **Orders and notes:** each drug's current order next to what the latest notes say about it. The model reads each clinician's latest note for the medicines it mentions: dose, status as written, and whether the patient themself stopped or added it. Every mention quotes the note.
- **Discrepancies (plain code):**
  - a note gives another dose than the current order;
  - a note says the drug was stopped while the order is still active;
  - a note says the patient takes a drug no order lists;
  - a planned change written at another dose, or a planned stop not recorded (from open loops).
  - An active order no note of the last year mentions is shown for information.
  - The cohort seeds three: p-1003 (ramipril dose), p-1008 (rosuvastatin stopped by the patient), p-1017 (over-the-counter ibuprofen).
- **Timeline:** each drug's orders as bars (active, on hold, stopped) with dose labels, and ticks where notes name the drug.
- **Adherence:** what the notes say about how the patient takes medicines, quoted.

`GET /api/patients/{id}/medications` returns all of it. ASKlepios gets the discrepancies in its chart index as a MEDICATION RECONCILIATION section.

## Surgical history

Before an operation, the surgeon needs every earlier one: when, what, open or laparoscopic, where on the body, and any implants or complications. The Overview tab has a **Surgical history** card, and the patient band says how many operations are recorded and how many were abdominal.

- **Sources, merged:** Procedure records (operations done here, or reported by the patient: `asserter` is the patient), notes ("Past surgical history: open appendicectomy 1996") and reports (operation notes, endoscopy reports). The model reads the notes and reports that use surgical words and lists the operations each states, quoting it. Planned or proposed operations, family members' operations, diagnostic tests and cancelled operations are left out; open loops follows the planned ones.
- **Plain code:** the date ("1996", "June 2015", "aged 22", or the document's own date for an operation note); the body region from words in the name and body site (abdomen and pelvis, chest, head and neck, spine and limbs, or other, so nothing is hidden); and merging mentions of the same kind of operation at most a year apart. When sources give different years, both are shown.
- **Flags:** done here, done elsewhere, only in notes (no Procedure record), implants and complications. Indirect signs (scars, post-surgical change on imaging) are listed apart, and so is a note saying the patient has had no operations.
- **What was searched:** the card says how many procedure records, notes and reports it read and since when, so "none recorded" says what it rests on. Operations done elsewhere may not be in the record.
- **Region filter:** All, or one region with its count, so "No chest operations recorded" is a statement, not a blank.
- **Without the agent service** the card lists the Procedure records alone and says that notes were not read.
- ASKlepios gets the list as a SURGICAL HISTORY section of its chart index. Asked whether a patient is fit for an operation, it says that is the surgeon's decision and lists the earlier operations, implants and complications.
- The cohort's cases: p-2042 (gallstones before a laparoscopic cholecystectomy, after an appendicectomy the patient reported, a caesarean section only in notes, and an umbilical hernia repair with mesh done here), p-2041 (cholecystectomy only in a note; a port), p-1009 (knee replacement: nothing abdominal), p-1011 (hysterectomy, the note and the Procedure record disagree on the year), p-1014 (no previous operations; the mother's operation is family history).

`GET /api/patients/{id}/surgery` returns the operations with their sources, the signs, and what was searched.

## My day

**My day** is the selected clinician's clinic list. It defaults to the next day with appointments, and you can step back or forward a day.

- **Totals for the day's patients:** visits, results to review, open follow-ups, medication discrepancies, briefs ready.
- **Per patient:** time, reason, brief state and open-loop badges.

**Prepare briefs** asks ASKlepios to "brief me for the visit" for each patient, in the background, through the same conversation loop and citation check as the chat panel. A brief is stored with a fingerprint of the chart. When anything in the chart changes (a new result, a review mark), the brief shows as outdated until prepared again. Opening a patient from My day opens the chat panel with the prepared brief at the top.

From the terminal, for example before a clinic starts:

```bash
python -m agent.briefs --practitioner pr-aydin
```

Endpoints: `GET /api/clinicians/{id}/day?day=…`, `POST /api/clinicians/{id}/briefs?day=…`, `GET /api/patients/{id}/brief`.

## Caches

Each note is read once per kind of reading. The results are cached under `agent/cache/` (gitignored; the base is set by `AGENT_PLAN_CACHE`), keyed by the note text, the model and the prompt version:
- `plans/`: plan items
- `medications/`: medicines mentioned
- `surgery/`: operations mentioned in notes and reports
- `briefs/`: prepared briefs

Note text is sent to the model in `agent/.env`, as chat questions are.

## Evaluate

`evals/gold.toml` holds the gold questions: one case per question, with the reference answer, the facts the answer must state, the sources it must cite and anything it must not say. The cases cover:
- lookups, medication history, lab trends and pending work;
- reading notes and reports, and comparing reports;
- briefings, follow-up questions, and questions the record cannot answer;
- requests for advice, and questions about other patients;
- open loops, medication reconciliation, surgical history, and Turkish.

```bash
python -m evals --lint
python -m evals --repeats 3
```

`--lint` checks the gold file against the cohort without calling the model. A run sends every case through the same conversation loop as the chat panel, using the model in `agent/.env`. The charts are rebuilt in memory from the generator, with "today" set to the anchor in `gold.toml`, so results do not depend on the date or on HAPI (`--fhir` reads from HAPI instead).

A case passes when the answer, as the panel shows it, states every required fact, cites every required source (one the assistant actually opened) and is in the expected language. The report also gives the verifier's statement statuses, time per answer, tokens and tool calls.

Other options:

- `--case <part of an id>`, `--category`, `--patient`: run part of the set.
- `--judge`: also checks each answer against its reference with a model, for contradictions and for advice. By default the judge is the agent's model; set `EVAL_JUDGE_BASE_URL`, `EVAL_JUDGE_MODEL` and `EVAL_JUDGE_API_KEY` to use another.
- `--baseline evals/runs/<run>`: lists the cases that got better or worse since an earlier run.
- `--rescore evals/runs/<run>`: scores that run's saved answers again with the current `gold.toml` (and `--judge`), without asking the agent. Use it after fixing a check that was too strict.
- `--no-loops`: leaves the sections computed from notes (OPEN LOOPS, MEDICATION RECONCILIATION, SURGICAL HISTORY) out of the chart index, to compare with and without them.
- `--loops`: checks the open loops of every cohort patient against `evals/loops.toml`. That file can also put review and communication marks on a patient first, to check the review stages.
- `--meds`: checks medication reconciliation against `evals/meds.toml`.
- `--surgery`: checks surgical history against `evals/surgery.toml`: each expected operation with its year, region, approach, implant and sources, and no others.
- `--fresh` (with `--loops`, `--meds` or `--surgery`): reads every note again instead of using the cache. With `--repeats 3`, it shows how much extraction varies.

`--loops`, `--meds` and `--surgery` report the expected findings that were found and the ones nobody expected (false alarms). Each run writes its results and `report.md` to `evals/runs/` (gitignored). The model is not deterministic, so compare runs made with `--repeats 3` or more.

## Layout

```
agent/          ASKlepios service: chat, tools, citation verifier, open loops, medications, surgical history, briefs, marks, audit log
evals/          gold question set, open-loop, medication and surgery gold files, eval runner
synthetic/      cohort generator and FHIR loader
web/            chart viewer, My day and chat panel
docker-compose.yml
```

Generated bundles go to `synthetic/output/` (gitignored). Chat turns, marks and other actions are appended to `agent/logs/audit.jsonl` (also gitignored).

## Notes

- ASKlepios only reads the patient bound to the open chart. Tools do not take a patient id.
- Answers can be incomplete or wrong. The panel marks statements that are unsourced or that contain numbers and dates the model was not shown. Check the cited sources before acting on an answer.
- Asklepios does not write orders or change medications. Its only writes are the review and communication marks above.
- For real patient data the model endpoint must be covered by an appropriate processing agreement, or run on your own hardware. Changing the endpoint is a change to `agent/.env`, not to the code.
