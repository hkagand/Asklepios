# Remove patient admission; keep the import of outside history

Date: 2026-11-12. Status: awaiting approval.

## Intent

Asklepios is for doctors during a consultation. Admitting a patient (identifying them, getting their consent,
registering them) is not something a doctor does in an appointment, so the product stops offering it. The team has
decided to forget the admission process entirely: it is not moved to a desk screen or another role.

A patient's history from elsewhere (the national record) still matters to the doctor. It is treated as already
acquired and settled with the patient before the consultation. The doctor opens the patient from their appointments,
sees that history in the chart next to everything else, and can ask ASKlepios about it.

The code that turns a national patient summary into chart records is kept, because the team expects to fetch patient
information later through an API request to a system such as e-Nabız. That code is the part of today's onboarding
that would carry over to a real integration.

## Goals

- No screen, route or agent endpoint lets a clinician identify, consent or register a patient.
- Gülay Kaplan (p-3001) and Murat Özdemir (p-3002) are in the chart after `generate.py` and `load.py`, with their
  outside history imported and the patient's answers already recorded. Nobody has to click anything to create them.
- Both appear in My day and All appointments like any other patient.
- Everything that reads imported history keeps working: the National record badges and "What the patient says they
  take" on the overview, ASKlepios's source lines and citation chips, medication reconciliation, the visit agenda,
  live help on jottings, and clinical considerations.
- The import logic remains a callable, tested unit: a national summary (IPS bundle) plus the patient's answers in,
  one FHIR transaction with a Provenance out.

## Non-goals

- A desk or receptionist screen, a second role, or any replacement admission flow.
- A real e-Nabız integration, or a stand-in service for one.
- A screen where the doctor confirms, accepts or skips imported items. The history arrives settled; the doctor reads
  it.
- Changing what the imported clinical items look like in FHIR (the `national-import` tag, MedicationStatements,
  resource ids). The imported Patient resource is the one exception; see "The Patient resource" below.

## Anti-goals

- Imported history that looks as if it was ordered or recorded here. The source stays visible where it is today (the
  Overview, ASKlepios's lines and citation chips) and becomes visible in the Labs tab, where it is missing today.
- Leftover admission wording in what the doctor reads ("at onboarding", "New patient", "consent code").
- Gold questions about p-3001 and p-3002 silently dropped or weakened to make the change pass.

## Approaches considered

1. **Plain cohort patients.** Write the two patients' settled charts by hand in the generator and delete the national
   records, the review and the import. Deletes the most code and leaves one concept ("recorded elsewhere" as a
   property of the data). Loses the import logic, and the settled charts would have to be re-expressed and re-verified.
2. **Keep the import as a generation step (chosen).** Keep the national records and the review and import code; run
   them once when the data is generated, with fixed answers. `evals/onboarding.py` (`onboarded_records`) already does
   this in memory for the gold questions. Less new code, and the resource ids and gold cases hold by construction. The
   cost is that the review logic (new, duplicate, differs, ask) stays for a step no screen uses, and data generation
   now needs the agent package.
3. **Hide the tab only.** Rejected: it leaves a service, a consent flow and endpoints nobody can reach, and the two
   patients would still not exist.

The team chose 2, for the reason under Intent: the import is what a future API integration would reuse.

## What goes

- Web: the New patient link in the top bar, the `onboard` route, `web/src/views/Onboard.tsx`, the onboarding section
  of `web/src/agent.ts` (types and calls, `nationalPeople`, `nationalPhone`), and the `/national` proxy in
  `web/vite.config.ts`.
- Agent: the four `/api/onboarding/*` endpoints and their request models and session state in `agent/app.py`;
  `NationalClient` and `NationalError`; `national_base_url` / `NATIONAL_BASE_URL` in `agent/config.py`; the
  onboarding-session clearing and the national-service reset in the demo reset.
- The `national/` package (the simulated service: consent requests, SMS codes, tokens, demo phone, demo people,
  access log).
- Docs: the service and the New patient steps in `README.md` and `ONBOARDING.md` (including port 8090, "Terminal 1",
  and the troubleshooting row).

## What stays

- `synthetic/national.py`: the three national records as IPS bundles. They remain the input of the import.
- The review and import functions of `agent/onboard.py` (`review_items`, `Decision`, `import_transaction` and what
  they use). Comparing a summary with an existing chart stays, since a real import would meet patients who are
  already in the chart.
- `python -m evals --onboarding` and `evals/onboarding.toml`: they are the tests of that logic, including the
  duplicate detection against p-2042.
- The six gold questions on p-3001 and p-3002, the scripted visit and the considerations case that use p-3001.
- The demo reset. With the two patients in the baseline bundles, a reset keeps them; nothing in the app creates
  patients any more.

## What changes

**Generation.** `synthetic/generate.py` runs the import for the two new patients and writes the resulting transaction
bundles to `synthetic/output/` next to the other patient bundles, so `load.py` loads them and the demo reset restores
them. The national records are no longer written out as files for a service to read, unless the builder needs them
there.

**The patient's answers** (which medicines they take, whether an old diagnosis is current) are data the generator
needs, not only eval expectations. They get one home that both the generator and the evals read. Today they live in
`evals/onboarding.toml`:

- p-3001: atorvastatin not taken; asthma no longer current; everything else as listed.
- p-3002: ramipril taken at 10 mg once daily, not the 5 mg listed.

**When the history was taken.** It was settled before the consultation, so the import is stamped on the working day
before the anchor (my call; today's gold charts use the anchor day itself). The Provenance, each
MedicationStatement's `dateAsserted` and the "imported …" text ASKlepios shows must all give that day. Today that
text comes from `meta.lastUpdated` (`Record.imported_from` in `agent/record.py`), which a FHIR server sets to the
time of loading; after a load or a demo reset it would show the wrong day, and under `AGENT_TODAY` a day in the
future. The import day must come from something the load does not overwrite.

**Who imported it.** The Provenance today names the acting clinician as verifier. No clinician is involved now. It
names the hospital (Organization/org-demo-hospital) instead (my call), keeps the national record as informant, and
drops the consent-request policy id, since no consent request exists in the system any more.

**Appointments.** Each of the two patients gets a first appointment with one of our clinicians on a clinic day on or
after the anchor, with a reason such as "New patient: first visit", so they show in My day and All appointments and
the visit agenda has its reason line. Which clinician and time is the builder's choice; they must not collide with
existing slots.

**The Patient resource.** The import writes the hospital number (MRN) without the `MR` type coding that cohort
patients carry, so `medicalRecordNumber` in `web/src/fhir.ts` and the patient line in `agent/record.py` find none:
the MRN is blank in the All appointments row, the patient header and ASKlepios's PATIENT line. The import is fixed
to write the identifier as the cohort does (my call), so these two read like any other patient. Address and GP stay
absent: the national summary gives neither.

**Labs tab** (decided by the team). `web/src/views/Labs.tsx` shows imported results with no mark, so an HbA1c
measured at Demo State Hospital reads like one taken here. Each imported result in the Labs tab carries the same
National record mark as the Overview (`isImported` in `web/src/model.ts`), and the facility where it was measured is
visible. A series that mixes results taken here and elsewhere marks the outside ones individually. The "Active
problems" column in All appointments stays unmarked (my call): it is a summary, and the chart shows the source.

**p-2042 (Nermin Aktaş)** is not imported into (my call). Her national record stays as an eval input only, so her
caesarean section remains "only in notes", which the surgical-history gold set and README rely on.

**Wording.** Text a doctor reads no longer says "onboarding". "At onboarding" becomes "when their history was taken"
(my call), in: the chart index and citation lines in `agent/record.py`, the reconciliation findings in
`agent/meds.py`, the system prompt line in `agent/chat.py`, the badge title and list heading in
`web/src/views/Overview.tsx`, the reset confirmation in `web/src/App.tsx`, and the `expected` texts in
`evals/gold.toml`. The prompt line in `agent/chat.py` is sent with every question, so the rewording can shift any gold
case, not only the six on these patients.

**Measuring it** (my call). The gold cases do not pass deterministically today, so "passes" means "no worse than
before":

- Before any change, take a baseline of the full gold set with `python -m evals --repeats 3`.
- After the change, run the same and compare with `--baseline`. Done means the onboarding category passes at least as
  often as in the baseline, and no other category drops by more than one case-run. A larger drop is treated as caused
  by the new wording and the wording is revised.
- `python -m evals --visits` must still raise the penicillin alert for p-3001's scripted visit.
- `python -m evals --considerations` is run only if a clinical model is configured; it is not a condition of done.

**Evals.** The gold runner stops building these charts separately (`onboarded_records` in `evals/run.py`); the
generator and the evals build them the same way, from one function. Whether p-3001 and p-3002 also join the loops,
medication and surgery checks is the builder's choice; if they do, the expected files gain their findings (for
example p-3002's ramipril difference, p-3001's 2016 cholecystectomy) rather than counting them as false alarms.

**Docs.** `README.md` describes the two patients as cohort patients whose history came from the national record
before their first visit, and the import as a kept building block for a future integration, not a feature of the
screens. The README's statement that the cohort has 21 patients, and the "National record service" and "Onboarding"
sections, are updated to match.

## Constraints

- Resource ids of imported items stay as they are (`nr-alg-p-3001-001`, `nr-ms-p-3001-001`, …): gold cases cite them.
- The imported Patient resources keep the HTEST security label, or the demo reset refuses to run.
- Generation stays deterministic for a given anchor and seed, and adding the two patients changes no other chart.
- `.claude/launch.json` has a `national` entry. The file is untracked and local to one machine; the entry is removed
  there but is not part of the commit.

## Left to the builder

- Module and function names. `agent/onboard.py` may be renamed to say what it now is (an import of outside history);
  the `--onboarding` flag and `onboarding.toml` may follow or stay.
- Where the import step sits in the generator, and how the generator reaches the agent package.
- How the import day is carried on the resources.
- Whether `Decision`/`Item` keep the "ask" status as is. It now means "needs the patient's answer, supplied with the
  import" rather than "the clinician asks".

## Done looks like

- `python synthetic/generate.py --anchor … && python synthetic/load.py` gives a server with p-3001 and p-3002, each
  with imported history, a Provenance and an appointment.
- The web app has no New patient link; `#/onboard` falls back to the appointment list; `npm run build` passes.
- `python -m national` no longer exists and nothing refers to port 8090.
- `python -m evals --lint` and `python -m evals --onboarding` pass, and the gold set is no worse than the baseline, as
  defined under "Measuring it".
- p-3001 and p-3002 show their hospital number in All appointments and in the patient header.
- In p-3001's Labs tab, every result shows the National record mark and Demo State Hospital.
- With `AGENT_DEMO_RESET=1`, a reset leaves both patients in place.
