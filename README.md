# Asklepios

A clinician-facing chart viewer and a record-grounded assistant, **ASKlepios**, for one open patient. The physician can ask about history, labs, treatments, pending work and what changed between reports; answers cite the FHIR resources they came from.

This repository is a synthetic demo. Every patient is invented. Do not load real records until the model endpoint, logging and access control have been reviewed for that use.

## What it is

- **Chart viewer** (`web/`): a clinician's day, the appointment list, then a patient page with overview, labs, visits, reports and medications. Built with React, Vite and Tailwind. Talks to HAPI FHIR through a Vite proxy.
- **ASKlepios** (`agent/`): a FastAPI service that answers questions about the patient whose chart is open. The model never sees raw FHIR JSON. It gets a compact chart index plus six read-only tools (`read_documents`, `lab_series`, `medication_history`, `order_history`, `search_record`, `read_epicrisis`). Citations are checked before they reach the panel.
- **Open loops** (`agent/plans.py`, `agent/loops.py`): what each clinician's latest note planned, open orders and new results, tracked from order to result, review and telling the patient. See [Open loops](#open-loops).
- **Medication reconciliation** (`agent/meds.py`): the medication orders against what the notes say, with a timeline per drug. See [Medications](#medications).
- **Surgical history** (`agent/surgery.py`): every earlier operation, merged from Procedure records, notes, reports and epicrisis reports, by body region. See [Surgical history](#surgical-history).
- **Epicrisis reports** (`agent/epicrisis.py`, `synthetic/epicrisis.py`): hospital discharge reports, one per admission, with the operation or procedure report when there was one, generated for every patient except the two from the national record, and read by ASKlepios when a question is about the patient's past. See [Epicrisis reports](#epicrisis-reports).
- **Visits** (`agent/visits.py`): a workspace for the visit itself, with an agenda from the record and the clinician's jottings. See [Visits](#visits).
- **History from the national record** (`agent/onboard.py`, `synthetic/national.py`): two patients arrive with a history taken from a national record before their first visit, shown with its source. Asklepios has no admission screen. See [History from the national record](#history-from-the-national-record).
- **My day and prepared briefs** (`agent/briefs.py`): a clinician's clinic list with what needs attention, and a pre-visit brief per patient written before the clinic. See [My day](#my-day).
- **Synthetic cohort** (`synthetic/`): 26 seeded patients. 24 have labs, visit notes, imaging and pathology reports, medications, orders, procedures, appointments and epicrisis reports, with a few deliberate gaps for the checks above to find; three of them, p-2043 to p-2045, are showcase patients with a ten-year history. Two are new to the hospital, with a history imported from the national record and a first appointment. Reloading overwrites the same resource ids.

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

Generating needs the agent's packages (`pip install -r agent/requirements.txt`): two patients are built with the agent's import of a national record summary.

`--anchor` is “today” for the stories: histories end just before it, upcoming appointments start on or after it, on working days. Use today's date: the chart viewer and the agent work with the real date, unless `AGENT_TODAY` fixes it (step 3). The same anchor and seed always produce the same ids, so a reload overwrites. A different anchor leaves resources from the old one behind (the loader says so); restart HAPI before loading for a clean dataset. Patient names depend on the anchor too.

**3. Configure the model**

```bash
cp agent/.env.example agent/.env
```

Fill in `LLM_BASE_URL`, `LLM_MODEL` and, if the endpoint needs one, `LLM_API_KEY`. Leave `FHIR_BASE_URL` as `http://localhost:8080/fhir` unless HAPI is elsewhere.

`agent/.env` is gitignored. Do not commit keys or internal hostnames.

For a demo on a later day, set `AGENT_TODAY` to the anchor (for example `AGENT_TODAY=2026-10-23`). The agent and the chart viewer then treat that day as today, so the cohort reads as it was loaded without reloading it. The top bar shows "Demo date" while it is set. Real timestamps (marks, the audit log, when a brief was prepared) are not affected. If the agent is not running, the chart viewer falls back to the real date.

To run a demo again from the start, set `AGENT_DEMO_RESET=1`: the top bar then has **Reset demo** (`agent/demo.py`, `POST /api/demo/reset`). After a confirmation, it puts the FHIR server back to the bundles in `synthetic/output/` as `load.py` loaded them. In one transaction it deletes every resource those bundles do not hold, which is whatever the demo wrote: visit Encounters, signed notes and their Provenance, and review and communication marks. It then posts the bundles again, which undoes any change to their own resources. It also clears the agent's visits and chat sessions, then reloads the app on the worklist. It takes about 5 seconds. Caches of what the model read from notes are kept: they are keyed by the note's text, so they stay right. The reset refuses to run if the server holds a patient not marked synthetic (HTEST), and each reset is written to the audit log.

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

## History from the national record

Asklepios has no admission screen: nobody identifies, consents or registers a patient in it. A patient's history from elsewhere is taken and settled with them before the consultation, and is in the chart when the doctor opens it.

Two cohort patients show this. Each is new to the hospital, has a first appointment with Dr. Elif Aydın, and carries a history imported from a national health record on the working day before the anchor. The national record is simulated: it stands in for a system such as e-Nabız, talks to no real system, and holds only the synthetic summaries in `synthetic/national.py`, one International Patient Summary (IPS) FHIR document per patient.

| Patient | Name | Worth catching |
|---|---|---|
| p-3001 | Gülay Kaplan, 58 | a penicillin allergy; a statin last prescribed two years ago that the national record still lists, which she no longer takes; childhood asthma still listed as active there, recorded here as resolved |
| p-3002 | Murat Özdemir, 44 | ramipril listed at 5 mg, which he takes at 10 mg |

Birth dates follow the anchor (the record says 58 years before it). Their national ids start with 0, which no real Turkish identity number does.

**In the chart.** Imported problems, allergies, medicines and results carry a **National record** badge on the Overview and in Labs, where each result also names the facility that measured it. Medicines are MedicationStatements: what the patient said they take when their history was taken, never orders. They appear under "What the patient says they take (not orders)". Every imported item carries the `national-import` tag and the day the history was taken, and one Provenance names the national record and the hospital. Nothing recorded here is changed.

**ASKlepios and imported items.** In the chart index every imported line starts "From the national record (simulated)", with the facility and import date, and its citation chip reads "… · national record", so the source shows in every answer. Medicines read as what the patient said when their history was taken ("the patient says they take 10 mg once daily, which differs from the national record"), and such a difference, or a medicine the patient no longer takes, is also a line of MEDICATION RECONCILIATION and an item on the visit agenda.

**The import** (`agent/onboard.py`). `settled_import` takes a summary and the answers settled with the patient, and returns one FHIR transaction. Every item is first reviewed against our chart if the patient is in it: **new**; **duplicate** (already in the chart, not imported again); **differs** (another dose, or "no known allergies" against recorded allergies); **ask** (needs the patient's answer: every medicine, since a prescription does not show it is taken, and a diagnosis recorded long ago that is still listed as active). Operations are matched against the surgical history, so one the chart has only in notes is imported as a dated record. Nobody reviews the import, so it never stops on an item: what cannot be settled (an item already in the chart, or "no known allergies" against a chart that records allergies) is left out and returned with the reason, and an allergy the chart does not have is imported even when the chart says there are none. A new patient gets id `p-` and the last four digits of the national id.

`synthetic/generate.py` runs the import for the two patients, with the answers in `synthetic/national.py`, so it needs the agent's packages (`pip install -r agent/requirements.txt`). The import is kept as the building block for summaries fetched from a national system later; no such integration exists, and Asklepios reads no national service.

A third summary, for Nermin Aktaş (p-2042, already in the chart), is not imported. `python -m evals --onboarding` reviews it against her chart: what the chart already has is recognised, and a caesarean section recorded at another hospital, which the chart has only in notes, is new.

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

- **Sources, merged:** Procedure records (operations done here, or reported by the patient: `asserter` is the patient), notes ("Past surgical history: open appendicectomy 1996") reports (operation notes, endoscopy reports) and epicrisis reports (the whole report except its PAST AND FAMILY HISTORY and PROCEDURE REPORT blocks: earlier operations are read from their own reports, and a diagnostic procedure is not an operation). The model reads the notes and reports that use surgical words and lists the operations each states, quoting it. Planned or proposed operations, family members' operations, diagnostic tests and cancelled operations are left out; open loops follows the planned ones.
- **Plain code:** the date ("1996", "June 2015", "aged 22", or the document's own date for an operation note); the body region from words in the name and body site (abdomen and pelvis, chest, head and neck, spine and limbs, or other, so nothing is hidden); and merging mentions of the same kind of operation at most a year apart. When sources give different years, both are shown.
- **Flags:** done here, done elsewhere, only in notes (no Procedure record), implants (not drains, clips, sutures, staples, packs or catheters, which come out again) and complications, each with its outcome when a document states one. Indirect signs (scars, post-surgical change on imaging) are listed apart, and so is a note saying the patient has had no operations.
- **What was searched:** the card says how many procedure records, notes and reports it read and since when, so "none recorded" says what it rests on. Operations done elsewhere may not be in the record.
- **Region filter:** All, or one region with its count, so "No chest operations recorded" is a statement, not a blank.
- **Without the agent service** the card lists the Procedure records alone and says that notes were not read.
- ASKlepios gets the list as a SURGICAL HISTORY section of its chart index. Asked whether a patient is fit for an operation, it says that is the surgeon's decision and lists the earlier operations, implants and complications.
- The cohort's cases: p-2042 (gallstones before a laparoscopic cholecystectomy, after an appendicectomy the patient reported, a caesarean section only in notes, and an umbilical hernia repair with mesh done here), p-2041 (cholecystectomy only in a note; a port), p-1009 (knee replacement: nothing abdominal), p-1011 (hysterectomy, the note and the Procedure record disagree on the year), p-1014 (no previous operations; the mother's operation is family history).

`GET /api/patients/{id}/surgery` returns the operations with their sources, the signs, and what was searched.

## Epicrisis reports

An epicrisis is the report a hospital writes when a patient leaves it. Each one here has two parts, under fixed upper-case headings. The **epicrisis** gives admission and discharge, complaint and history, past and family history, examination, hospital course, admission and discharge diagnoses with ICD-10 codes, complications during the admission, the discharge prescription, recommendations and the condition at discharge. When there was an operation or a procedure, an **OPERATION REPORT** or a **PROCEDURE REPORT** follows. Each is a FHIR DocumentReference tagged `epicrisis`, from "Demo General Hospital". An operation also gets a tagged Procedure record; a diagnostic procedure (endoscopy, biopsy, fine-needle aspiration, angiography, polyp removal) does not.

The reports are generated, in English, by plain code (`synthetic/epicrisis.py`); no model writes them, and Asklepios has no screen for writing one. For a given anchor and seed they are always the same.

- **Showcase patients** (`synthetic/showcase.py`): three new patients, each with a ten-year story told by eight reports. p-2043 Melahat Tozkoparan has thyroid cancer: an aspiration, a total thyroidectomy with transient hypocalcaemia and a vocal cord paresis that recovered, radioiodine, and a later benign lymph-node aspiration; her follow-up is with Dr. Selin Arslan, endocrinology. p-2044 Hikmet Sarıyaprak had a heart attack and two stents, then a bleeding duodenal ulcer on two antiplatelet drugs; his follow-up is with Dr. Zeynep Kara, cardiology. p-2045 Nadide Yelkovan has had three operations, with a difficult intubation recorded at the first, a wound infection, a clot after surgery, and a knee replacement under spinal anaesthesia because of the airway; Dr. Kerem Yalçın sees her before planned surgery.
- **Background reports** (`synthetic/epicrisis_catalogue.py`): each of the 21 earlier patients has 5 to 7 reports about episodes that leave no lasting diagnosis, consistent with their charts. A report never adds a chronic diagnosis, an allergy or a long-term medicine, and the six patients whose notes or gold questions state their surgical history get no new operations. Their existing resources are unchanged: `evals/cohort-fingerprint.json` pins them.
- p-3001 and p-3002 have none: their history comes from the national record.

**In the chart.** The Reports tab has an **Epicrisis reports** card: one row per report with its period, service, title and discharge diagnoses, and a **Complication** badge, opening to the full text. The Visits & notes tab does not list them.

**ASKlepios and epicrisis reports.**
- The chart index has an EPICRISIS REPORTS section, one line per report. The tool `read_epicrisis` returns all of the patient's reports in full; if they exceed its size limit, whole older reports are left out and the result says so.
- When a question is about the patient's past (earlier admissions, complications, anaesthesia, events after a procedure, "anything I should know about ...", in English or Turkish), plain code reads the reports into the conversation before the model answers, once per conversation (`about_the_past`, called from `agent/chat.py`). Other questions leave it to the model. Which operations a patient has had is answered from SURGICAL HISTORY, and questions about current results, medicines and orders do not read the reports.
- The answer cites each report it uses. When none is relevant, it says how many it read, over what period, and that none mentions the matter; for a patient with none, it says none is on file.

**Other readers.** Open loops and medication reconciliation ignore epicrisis reports: they read notes only. Surgical history reads them without their PAST AND FAMILY HISTORY and PROCEDURE REPORT blocks. Code then drops the diagnostic procedures the model returns (a polyp removal in the gut, a biopsy, an angiography; not a sentinel node or cone biopsy, a nasal polypectomy or a TURBT) and lists them as not counted, groups coronary stent mentions by artery, separates hernia repairs by site, and merges differently worded mentions of one operation when one name's words contain the other's and they share at least two.

**Semantic retrieval** (a vector database) was considered and set aside: one patient's reports fit in what the model reads, so there is nothing to search.

**Reasoning effort.** Answers that need several reports combined are less reliable at the model's low reasoning effort, so a turn that answers from the reports asks for a higher one: `LLM_REASONING_EFFORT_REPORTS`, default `medium`. It applies to a question about the past once the reports are in the conversation, and from the model's own `read_epicrisis` call otherwise. It only ever raises `LLM_REASONING_EFFORT`, does nothing when that is not set, and an empty value turns it off. Every other question keeps the configured effort.

Measured on 16 Nov 2026 with `gpt-oss-120b` and `LLM_REASONING_EFFORT=low`, two runs of three repeats each:

| | With the rule | Without it | Code before epicrisis reports |
|---|---|---|---|
| The eleven `epicrisis` questions | 56 of 66 | 47 of 66 | not applicable |
| The other 68 questions | 377 of 408 | 374 of 408 | 373 of 408 |
| Median time, a turn that reads the reports | 6.7 s | 3.4 s | not applicable |
| Median time, other questions | 1.5 s | 1.4 s | 1.5 s |

**A measured limit.** One `epicrisis` question failed every time in that measurement: asked about complications of p-2043's operations, answers named the vocal cord paresis without saying that it recovered, which only later reports and a clinic note state. Surgical history now lists a complication with its outcome when a document states one ("right vocal cord paresis with a hoarse voice, recovered by Apr 2019"), read from the patient's own note. Measured the same way afterwards, that question passes 3 of 6, the eleven `epicrisis` questions 59 of 66 and the other 68 questions 374 of 408. It is still the one question under 4 of 6: about half the answers leave the outcome out.

## Visits

**Start visit** on a patient's page opens a FHIR Encounter (in progress) for the clinician viewing, linked to today's appointment if there is one, and a **Visit in progress** tab:

- **Agenda from the record**, built by plain code, not suggested by the model: the reason for the appointment; open loops to close (results to review or tell the patient, overdue or missing plans); medicines to confirm (reconciliation findings, and what a patient said when their history was taken); allergies to confirm, or to ask about when none are recorded. Each item links to its source and can be ticked as covered.
- **Jottings**: short lines the clinician types as the patient talks ("BP 138/84", "no fever", "plan: refer to general surgery"), with their time; they can be edited or deleted. The visit note will be drafted from these.

**Live help on each jotting** (`agent/jottings.py`), shown under it within a second or two; the next jotting can be typed meanwhile:

- From the model (one short call, temperature 0): the note **section** (S, O, A or P); the **agenda items** it covers, which are ticked ("✓ J5"); the **record items** it refers to, as source chips (only ids the model was shown); and for what the patient reports, up to three **details not recorded yet** ("onset", "severity", "associated symptoms"). These are history-taking only: anything that reads as advice (a diagnosis, test, treatment, dose or referral) is dropped by code, and none are listed for measurements, results or plans.
- From plain code: an **allergy alert** when a jotting names a drug the patient is allergic to, or one of its class (penicillin covers amoxicillin and co-amoxiclav); a **dose alert** when a jotting gives a current dose that differs from the active order (a planned change is not one); and ticks for medicine and allergy agenda items it names.

**The note** (`agent/notes.py`). **Draft the note** has the model write Subjective, Objective, Assessment and Plan from the jottings only; every line cites the jottings it comes from, and a record item when it gives one of its values. A record item can be quoted only for a jotting that refers to it without a value of its own ("HbA1c discussed with the patient"). A jotting that gives its own measurement ("BP 138/84") gets no earlier readings, so the note never presents them as part of this visit. Agenda items are not sources. Code then checks the draft: a line with no source or an unknown one, a number not in what it cites, and a jotting no line uses are all flagged, never dropped silently. The clinician edits the four sections (the plan one action per line), sees again any allergy or dose alert raised during the visit, and signs. Signing writes, in one transaction, a DocumentReference in the chart's note format with the clinician as author, the Encounter as finished, and a Provenance: the clinician is the author, Asklepios assembled the note from their jottings. Its plan is then read by open loops like any other note, so what the visit planned is tracked from the next day.

Starting a visit when one is open returns it. **Cancel visit** marks the Encounter cancelled and writes nothing else. The working state (agenda ticks, jottings) is kept on the agent under `agent/cache/visits/`, one file per visit, so a reload or restart keeps it.

Endpoints: `POST /api/patients/{id}/visits`, `GET /api/patients/{id}/visit`, `POST /api/visits/{id}/jottings` (and `PUT`/`DELETE` on one), `POST /api/visits/{id}/agenda/{item}`, `POST /api/visits/{id}/draft`, `POST /api/visits/{id}/sign`, `POST /api/visits/{id}/cancel`.

### Clinical considerations (experimental, second model)

Optionally, a second, clinical model suggests what to keep in mind during the visit (`agent/considerations.py`). It is off unless configured in `agent/.env`; for example, MedGemma 1.5 4B on a local [Ollama](https://ollama.com), so the visit context stays on the machine:

```
ollama pull medgemma1.5:4b
CLINICAL_LLM_BASE_URL=http://localhost:11434/v1
CLINICAL_LLM_MODEL=medgemma1.5:4b
```

Any OpenAI-compatible endpoint works (`CLINICAL_LLM_API_KEY` if it needs one). `/api/health` names it as `clinicalModel`.

After each change to the jottings, in the background (the jotting's own help is not delayed; a run still working on older jottings is cancelled), the model reads the jottings and a short record (problems, allergies, medicines, abnormal latest results; about 1,000 tokens) and gives up to four considerations, each a possible **cause** of what the jottings describe, something to **check**, or a **caution** from the record, citing the jottings and record items it rests on. Code keeps one only if it cites a jotting of this visit and only ids it was shown, every value in it is in what it cites, it does not admit to resting on what the record does not state, and it is not a copy of the prompt's example; it marks one whose record item a code alert already names. What was dropped, and why, is kept with the result.

In the visit workspace they appear under the agenda, in a **Clinical considerations** panel marked experimental, which shows only while a clinical model is configured. Each shows its kind, its text, and its basis: the jottings by id and the record items as chips that open the source. The panel says when a run is working or the considerations come from earlier jottings, lists what the checks dropped and why, and has **Ask again**. **Useful** and **Not useful** keep the clinician's verdict with the consideration and in the audit log, to judge the model on real use.

These are suggestions for the clinician to weigh, never written into the note or to FHIR, and the code alerts above remain the safety net. Measured with `python -m evals --considerations --compare --repeats 3` (10 scripted visits, 3 runs each), MedGemma 1.5 4B raised 12 of the 30 expected considerations and gave 3 unusable answers; the agent's model (`big_llm`) raised all 30. MedGemma blamed ramipril rather than metformin for loose stools, missed CKD with an ibuprofen plan and a penicillin allergy with co-amoxiclav, and ran past its token cap on one visit. Both models said amoxicillin may need a dose change at an eGFR of 53, which it does not: wrong rules stated with confidence are not peculiar to small models. On a laptop GPU a run takes about 2 seconds. Endpoints: `GET /api/visits/{id}/considerations` (the latest, whether they match the jottings now, and whether a run is working), `POST` to make them now and wait, and `POST /api/visits/{id}/considerations/feedback` for a verdict.

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
- `surgery/`: operations mentioned in notes, reports and epicrisis reports
- `briefs/`: prepared briefs
- `visits/`: visits in progress (agenda ticks and jottings)

Note text is sent to the model in `agent/.env`, as chat questions are.

## Evaluate

`evals/gold.toml` holds the gold questions: one case per question, with the reference answer, the facts the answer must state, the sources it must cite and anything it must not say. The cases cover:
- lookups, medication history, lab trends and pending work;
- reading notes and reports, and comparing reports;
- briefings, follow-up questions, and questions the record cannot answer;
- requests for advice, and questions about other patients;
- open loops, medication reconciliation, surgical history, epicrisis reports, history from the national record, and Turkish.

The `epicrisis` cases (eleven: nine on the showcase patients, two on existing ones) ask about earlier admissions, complications and anaesthesia. A case can require tools with `tools = [...]` (for example `read_epicrisis`) and forbid them with `no_tools = [...]`. The `onboarding` cases ask about p-3001 and p-3002 as the generator writes them, with their history imported from the national record. `source_labels` checks what the cited source chips show (for example "national record").

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
- `--visits`: checks live help on scripted visit jottings against `evals/visits.toml`: section, alerts, agenda ticks, record links, and gaps (none may read as advice). Then each visit's note is drafted and checked (every line sourced, numbers in their sources, every jotting used), and its plan is read back by the plan reader open loops uses.
- `--considerations`: checks clinical considerations from the second model against `evals/considerations.toml`: scripted visits, each with the considerations it must raise (a caution for ibuprofen with CKD, amlodipine for ankle swelling, a penicillin allergy with co-amoxiclav) and claims it must not make (a renal dose change for amoxicillin at an eGFR of 53). It also counts unusable answers, considerations the checks dropped, ones citing more than three record items, and time. `--compare` runs the agent's own model on the same visits, prompt and checks.
- `--onboarding`: checks the import of a national summary against `evals/onboarding.toml`: each record's review statuses; that the import writes only what can be settled, as the patient answered, with the day the history was taken and one Provenance naming the hospital; that an import nobody watches skips what it cannot settle; and the two patients as the generator writes them. No model calls apart from cached surgical history.
- `--epicrisis`: checks epicrisis reports without calling the model, and exits 1 on any problem: that the original 21 patients' resources are untouched, the background and showcase reports, the tool and its size limit, the surgical history readers (diagnostic procedures dropped, stents grouped, hernias separated, mentions merged), what ASKlepios says when none is on file, and that past questions pre-read the reports once.
- `--epicrisis-in-prompt`: runs the gold questions with every report in the prompt and without `read_epicrisis`, for comparison only; the tools check is skipped.
- `--surgery`: checks surgical history against `evals/surgery.toml`: each expected operation with its year, region, approach, implant and sources, a complication it must list with its outcome, implants and complications it must not list, and no others.
- `--fresh` (with `--loops`, `--meds` or `--surgery`): reads every note again instead of using the cache. With `--repeats 3`, it shows how much extraction varies.

`--loops`, `--meds` and `--surgery` report the expected findings that were found and the ones nobody expected (false alarms). Each run writes its results and `report.md` to `evals/runs/` (gitignored). The model is not deterministic, so compare runs made with `--repeats 3` or more.

## Layout

```
agent/          ASKlepios service: chat, tools, citation verifier, open loops, medications, surgical history, epicrisis reports, briefs, marks,
                visits (jottings, notes, clinical considerations from a second model), audit log
evals/          gold question set, open-loop, medication and surgery gold files, epicrisis checks, eval runner
synthetic/      cohort generator, epicrisis reports and showcase patients, national records (the import's input) and FHIR loader
web/            chart viewer, My day and chat panel
docker-compose.yml
```

Generated bundles go to `synthetic/output/` (gitignored). Chat turns, marks and other actions are appended to `agent/logs/audit.jsonl` (also gitignored).

## Notes

- ASKlepios only reads the patient bound to the open chart. Tools do not take a patient id.
- Answers can be incomplete or wrong. The panel marks statements that are unsourced or that contain numbers and dates the model was not shown. Check the cited sources before acting on an answer.
- Asklepios does not write orders or change medications. Its only writes are the review and communication marks above.
- For real patient data the model endpoint must be covered by an appropriate processing agreement, or run on your own hardware. Changing the endpoint is a change to `agent/.env`, not to the code.
