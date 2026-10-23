# Asklepios

A clinician-facing chart viewer and a record-grounded assistant, **ASKlepios**, for one open patient. The physician can ask about history, labs, treatments, pending work and what changed between reports; answers cite the FHIR resources they came from.

This repository is a synthetic demo. Every patient is invented. Do not load real records until the model endpoint, logging and access control have been reviewed for that use.

## What it is

- **Chart viewer** (`web/`): worklist, then a patient page with overview, labs, visits and reports. Built with React, Vite and Tailwind. Talks to HAPI FHIR through a Vite proxy.
- **ASKlepios** (`agent/`): a FastAPI service that answers questions about the patient whose chart is open. The model never sees raw FHIR JSON. It gets a compact chart index plus five read-only tools (`read_documents`, `lab_series`, `medication_history`, `order_history`, `search_record`). Citations are checked before they reach the panel.
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

## Layout

```
agent/          ASKlepios service, tools, citation verifier, audit log
synthetic/      cohort generator and FHIR loader
web/            chart viewer and chat panel
docker-compose.yml
```

Generated bundles go to `synthetic/output/` (gitignored). Chat turns are appended to `agent/logs/audit.jsonl` (also gitignored).

## Notes

- ASKlepios only reads the patient bound to the open chart. Tools do not take a patient id.
- Answers can be incomplete or wrong. The panel marks statements that are unsourced or that contain numbers and dates the model was not shown. Check the cited sources before acting on an answer.
- For real patient data the model endpoint must be covered by an appropriate processing agreement, or run on your own hardware. Changing the endpoint is a change to `agent/.env`, not to the code.
