# Asklepios

A clinician-facing chart viewer and a record-grounded assistant, **ASKlepios**, for one open patient. The physician can ask about history, labs, treatments, pending work and what changed between reports; answers cite the FHIR resources they came from.

This repository is a synthetic demo. Every patient is invented. Do not load real records until the model endpoint, logging and access control have been reviewed for that use.

## What it is

- **Chart viewer** (`web/`): worklist, then a patient page with overview, labs, visits and reports. Built with React, Vite and Tailwind. Talks to HAPI FHIR through a Vite proxy.
- **ASKlepios** (`agent/`): a FastAPI service that answers questions about the patient whose chart is open. The model never sees raw FHIR JSON. It gets a compact chart index plus five read-only tools (`read_documents`, `lab_series`, `medication_history`, `order_history`, `search_record`). Citations are checked before they reach the panel.
- **Open loops** (`agent/plans.py`, `agent/loops.py`): what each clinician's latest note planned, checked against what the record shows happened since. See [Open loops](#open-loops).
- **Synthetic cohort** (`synthetic/`): 20 seeded patients with labs, visit notes, imaging and pathology reports, medications, orders and appointments. Reloading overwrites the same resource ids.

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

HAPI is at `http://localhost:8080/fhir`.

**2. Generate and load the cohort**

```bash
python synthetic/generate.py --anchor 2026-10-23 --seed 2041
python synthetic/load.py
```

`--anchor` is “today” for the stories: histories end just before it, upcoming appointments start on or after it. The same anchor and seed always produce the same ids, so a reload overwrites.

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

Open [http://localhost:5173](http://localhost:5173). The worklist lists the loaded patients. Open a chart and use **ASKlepios** in the right-hand panel.

To ask from the terminal instead of the browser:

```bash
python -m agent.ask p-2041 "Why was oxaliplatin stopped?"
```

## Open loops

Follow-up that was planned in a note but never ordered, booked, resulted or recorded.

1. The model reads each clinician's most recent note and lists its plan items: tests, imaging, referrals, follow-up visits, calls, meetings and medication changes, each with a due time. Every item must quote the note word for word. If a line of the note's PLAN section is not covered by any item, the model is asked again.
2. Plain code does the rest. It works out due dates, matches each item against orders, results, reports, appointments, visits and medication orders, and gives it a status: `missing`, `dose_mismatch`, `overdue`, `not_ordered`, `no_trace` (a call or meeting the record cannot show), `pending`, `conditional` or `done`. For a medication started or changed, the planned dose ("80 mg once daily for 7 days, then 40 mg") is compared with the dosage of the order written for it. An order at another dose is `dose_mismatch`. The cohort seeds one such case (p-1007, furosemide written at 60 mg).
3. Open orders that no current plan covers are added, for example a referral from an earlier visit.

In the chart viewer, the **Open loops** card at the top of the overview groups the items:
- **Needs action:** not done, ordered at another dose, overdue, or not yet ordered.
- **Cannot be confirmed from the record:** calls, meetings and similar steps the record has no entry for.
- **In progress.**

Done and conditional items are collapsed. Each item shows the note line it came from and buttons that open its sources. The worklist shows each patient's counts (late, other dose, to order, unconfirmed, pending).

When the agent service is not running, both pages fall back to the plain open orders.

`GET /api/patients/{id}/loops` returns the items with their evidence ids, and `GET /api/loops/summary?patients=…` returns the counts. ASKlepios also gets the items in its chart index as an OPEN LOOPS section, so it can answer "what was planned and not done?" with sources.

Each note is read once. The extracted plan is cached in `agent/cache/plans/` (gitignored, or `AGENT_PLAN_CACHE`), keyed by the note text, the model and the prompt version. The note text is sent to the model in `agent/.env`, as chat questions are.

## Evaluate

`evals/gold.toml` holds the gold questions: one case per question, with the reference answer, the facts the answer must state, the sources it must cite and anything it must not say. The cases cover lookups, medication history, lab trends, pending work, reading notes and reports, comparing reports, briefings, questions the record cannot answer, requests for advice, follow-up questions, other patients, and Turkish.

```bash
python -m evals --lint
python -m evals --repeats 3
```

`--lint` checks the gold file against the cohort without calling the model. A run sends every case through the same conversation loop as the chat panel, using the model in `agent/.env`. The charts are rebuilt in memory from the generator, with "today" set to the anchor in `gold.toml`, so results do not depend on the date or on HAPI (`--fhir` reads from HAPI instead).

A case passes when the answer, as the panel shows it, states every required fact, cites every required source (one the assistant actually opened) and is in the expected language. The report also gives the verifier's statement statuses, time per answer, tokens and tool calls.

Other options:

- `--case <part of an id>`, `--category`, `--patient`: run part of the set.
- `--judge`: also grades each answer against its reference with a model: correct, partial or incorrect, and whether it recommends anything. By default the judge is the agent's model; set `EVAL_JUDGE_BASE_URL`, `EVAL_JUDGE_MODEL` and `EVAL_JUDGE_API_KEY` to use another.
- `--baseline evals/runs/<run>`: lists the cases that got better or worse since an earlier run.
- `--rescore evals/runs/<run>`: scores that run's saved answers again with the current `gold.toml` (and `--judge`), without asking the agent. Use it after fixing a check that was too strict.
- `--no-loops`: leaves the OPEN LOOPS section out of the chart index, to compare with and without it.
- `--loops`: checks the open loops of every cohort patient against `evals/loops.toml` instead of asking questions. It reports expected items found with the right status, and open items nobody expected (false alarms). Add `--fresh --repeats 3` to extract every plan again each time and see how much extraction varies.

Each run writes `results.jsonl` (every answer with its checks), `summary.json`, `report.md` and its own `audit.jsonl` to `evals/runs/` (gitignored). The model is not deterministic, so compare runs made with `--repeats 3` or more.

## Layout

```
agent/          ASKlepios service, tools, citation verifier, audit log
evals/          gold question set and eval runner
synthetic/      cohort generator and FHIR loader
web/            chart viewer and chat panel
docker-compose.yml
```

Generated bundles go to `synthetic/output/` (gitignored). Chat turns are appended to `agent/logs/audit.jsonl` (also gitignored).

## Notes

- ASKlepios only reads the patient bound to the open chart. Tools do not take a patient id.
- Answers can be incomplete or wrong. The panel marks statements that are unsourced or that contain numbers and dates the model was not shown. Check the cited sources before acting on an answer.
- For real patient data the model endpoint must be covered by an appropriate processing agreement, or run on your own hardware. Changing the endpoint is a change to `agent/.env`, not to the code.
