# Epicrisis reports: generate them for every patient and let ASKlepios answer from them

Date: 2026-11-13. Status: awaiting approval. Builds on the `remove-admission` branch (not yet merged into `main`).

## Intent

After an operation, a screening or any admission, the doctor writes an epicrisis report: what the patient came with,
what was done, what was found, and any complications. Later, when the patient comes back, another doctor needs to
know whether anything in those reports bears on today's question. Reading ten reports to find one line does not
happen in a consultation.

The team wants the doctor to ask ASKlepios in plain words, for example "any prior things I need to know about the
patient's thyroid?", and get the relevant passages from the patient's epicrisis reports with references, and to be
able to open the reports themselves.

A vector database and semantic retrieval were considered and set aside for now: one patient's reports are few
enough for the model to read directly. This change gives patients reports to read and lets the model read them.

## Goals

- Three new showcase patients, each with a ten-year story and 8 to 10 epicrisis reports that are part of it.
- Each of the 21 existing cohort patients has 5 to 10 epicrisis reports from the last ten years that their chart
  does not contradict.
- A doctor can open and read a patient's epicrisis reports in the chart.
- ASKlepios answers questions about earlier admissions, procedures, findings and complications from those reports,
  citing each report it uses, and says plainly when none of them is relevant.
- Questions that have nothing to do with earlier admissions cost no more than they do today.

## Non-goals

- A vector database, embeddings, chunking or any retrieval index.
- Scanned or PDF reports, OCR, or reports in Turkish. The reports are English text, like the rest of the chart.
- Reproducing a real hospital's layout, name or branding. The team's sample report (a real patient's) lends its
  structure and field names only; nothing from it is stored in the repository.
- A screen for writing an epicrisis.
- Reports for the two national-record patients (p-3001, p-3002): they are new to the hospital.
- Rewriting the existing 21 patients' stories so that their conditions began earlier.
- Inpatient Encounter resources for the admissions (see "What does not change").

## Anti-goals

- A report that contradicts the chart: a medicine prescribed before its order existed, a diagnosis the problem list
  does not have, an operation in a patient whose notes say there were none.
- ASKlepios answering "nothing relevant" without having read the reports, or without saying how many it read.
- Existing gold questions weakened or dropped to make room for the new history.
- Old discharge prescriptions and recommendations showing up as today's open loops or medication discrepancies.

## Approaches considered

### How the model gets the reports

1. **Feed everything, always.** Every question carries the full text of all reports. Nothing can be missed, but every
   question pays: for the largest charts the model reads roughly 40 to 70% more per step, and unrelated answers may
   get worse from the extra text.
2. **One line per report always, all reports in full on request (chosen).** The chart index lists each report in one
   line; one tool call returns every report in full. Unrelated questions stay as cheap as today, questions about the
   past still see everything. It depends on the model choosing to call the tool, which the gold questions check.
3. **Titles only, opened one by one.** Rejected: this is how notes work today, and it is where a relevant report is
   missed.

The team chose 2 on the condition that it is the better one. Approach 1 is therefore kept as a switch in the evals
only (my call): it is measured on the same questions, not shipped. See "Measuring it".

### How the reports fit the patients

The 21 existing patients have short, recent stories: most were first seen in 2024 to 2026 and diagnosed then, and
their notes say so ("no discrete nodules, thyroid ultrasound not needed"; "new heart failure"; "no previous
colonoscopy"). Reports that are both years old and about the current condition would contradict those notes.

1. **Showcase patients plus background reports (chosen).** Three new patients carry the histories the feature is
   for. The existing patients get older reports about other episodes that their notes do not contradict. Nothing
   the existing gold questions rely on moves. This is how the gallstone patient (p-2042) was added for surgical
   history.
2. **Background reports only.** Less work, but reports would rarely bear on a patient's current condition, and the
   team's thyroid question would have a thin answer.
3. **Rewrite the existing stories to start years earlier.** Rejected: it changes notes and results across the
   cohort, and most of the 68 gold answers would have to be rewritten.

## The reports

**One report per admission.** It has two parts, after the team's sample:

- *Epicrisis:* report number, approval date, service, doctor; admission and discharge dates; complaint and history;
  past and family history; examination on admission, by system; treatment plan and hospital course; admission
  diagnoses and discharge diagnoses with ICD-10 codes; discharge prescription; discharge recommendations and
  follow-up; condition at discharge.
- *Operation or procedure report*, only when there was one: date; pre- and post-procedure diagnosis; what was
  performed; team; anaesthesia; wound class; the operation note; estimated blood loss; drains; complications;
  pathology specimen.

The headings are fixed, one per line, so code can read a report's fields without a model.

**Written by the generator** from templates, with plain code and its own random numbers, like the existing notes.
No model writes them, so the data and the evals are reproducible.

### The three showcase patients

Each is a fixed story with its own random numbers, like p-2041 and p-2042: a problem list, medication orders, a few
outpatient visits with notes and results, an upcoming appointment, and 8 to 10 epicrisis reports. Fixed names that
the random name lists do not produce. These outlines are my proposal:

| Patient | Story | Reports include |
|---|---|---|
| p-2043, a woman in her fifties, endocrinology follow-up | A multinodular goitre found eight years ago; papillary thyroid carcinoma; now on levothyroxine after surgery | fine-needle aspiration of a thyroid nodule; total thyroidectomy with transient low calcium and a hoarse voice from a vocal cord palsy that recovered; radioiodine treatment; a later aspiration of a neck lymph node (benign); and unrelated admissions: a laparoscopic cholecystectomy, a wrist fracture fixed with a plate, pneumonia |
| p-2044, a man in his sixties, cardiology follow-up | A heart attack eight years ago; two stents; on aspirin, a statin, a beta-blocker and a stomach-protecting medicine | emergency stenting with a puncture-site haematoma; a second planned stent; a bleeding duodenal ulcer while on two antiplatelet drugs, with transfusion and one drug stopped; an inguinal hernia repair planned around his antiplatelet treatment; a chest pain admission where angiography showed the stents open; pneumonia |
| p-2045, a woman in her late fifties, seen before planned surgery | Several operations over ten years | a gallbladder operation converted from keyhole to open, with a difficult intubation recorded and a wound infection; an incisional hernia repair with mesh; a leg vein clot after surgery treated for three months; a knee replacement under spinal anaesthesia chosen because of the airway; a colonoscopy with polyp removal and bleeding the next day; a kidney stone |

They let a doctor ask, for example: "anything I need to know about her thyroid?", "anything that matters before I
prescribe an anti-inflammatory?", "what should the anaesthetist know?", and get an answer that draws on several
reports and leaves others out.

### Background reports for the existing 21 patients

Five to ten per patient, drawn from episodes that leave no lasting diagnosis and that the patient's notes do not
contradict: pneumonia (including COVID-19 in 2020 to 2021), gastroenteritis with dehydration, a urinary infection,
cellulitis, renal colic, an observation after a head injury, a fracture, childbirth where age and sex fit, and for
patients open to it an appendicectomy, an inguinal hernia repair, a septoplasty or a carpal tunnel release.

Where an existing story already contains an admission-worthy event with no discharge summary, it gets its report:
p-1009's knee replacement of 12 Mar 2019 and p-2042's ERCP of 27 Aug 2026.

**Every patient's set contains** at least one report with a complication, which may be medical (for example a drip-site
phlebitis or a hospital-acquired infection) or procedural, and at least one report that has nothing to do with
their main condition.

The existing notes are not changed to mention these admissions: outpatient notes that are silent about an old
pneumonia do not contradict it.

**This content is my proposal and wants a clinical eye.** It is template data, so a clinician's changes can be
applied before or after the build without touching the rest.

## Rules that keep the chart true

1. **Reports describe episodes.** In an existing patient, a report never introduces a chronic diagnosis, an allergy
   or a long-term medicine. Complications are bound to the episode and resolved. (The showcase patients' problem
   lists and medication orders are written together with their reports, so they agree by construction.)
2. **Discharge prescriptions** list short courses for that admission, and long-term medicines only if their order in
   the chart was already active on that date.
3. **Dates.** Admission before discharge, both before the anchor and no more than ten years before it; the patient's
   age and the onset dates of their problems agree with what the report says. No report is written for an admission
   that already has a discharge summary note (p-1004, p-1007).
4. **Operations and procedures.** An operation is what surgical history counts as one today. It gets a Procedure
   record, as operations done here have, and the expected operations in `evals/surgery.toml` are extended to include
   it. Diagnostic procedures (endoscopy, biopsy, fine-needle aspiration, angiography, polyp removal) get a procedure
   report but no Procedure record, and stay out of surgical history, as its reader already treats them.
5. **Patients closed to new operations**, because their notes or gold questions state their surgical history:
   p-1003 and p-1014 (none), p-1009 (only the knee replacement), p-1011 (the hysterectomy keeps its disagreeing
   years, 2011 in the note and 2012 in the record, so it gets no report), p-2041 and p-2042 (their notes list their
   earlier operations). These six get medical admissions and diagnostic procedures only, apart from the two reports
   named above.
6. **p-2041** has two questions whose answer is "not on file" (a PET scan; an echocardiogram or ejection fraction).
   None of his reports mentions either.
7. **Nothing else moves.** Every existing resource of the 21 patients keeps its id and content: the reports and new
   Procedure records use their own id prefixes and draw no number from the shared random sequence, as the
   past-surgery additions do. The three new patients change no other chart.

## How ASKlepios uses them

- **Chart index.** A new section, EPICRISIS REPORTS, has one line per report, newest first, built by code from the
  report's fields: admission and discharge dates, service, discharge diagnoses, operation or procedure, complications
  ("none" when the report says so), condition at discharge, and the report's id.
- **A new tool** returns every epicrisis report of the patient in full, in one call, each under its id and dates.
  If the reports together exceed a size limit, the newest are returned and the result says how many were left out
  and from when; it never truncates silently.
- **Instructions.** For any question about earlier admissions, operations, procedures, complications, or "anything
  I should know about X", the model reads the reports with that tool before answering. It cites each report it
  uses. When none is relevant it says how many reports it read, over what period, and that none mentions X.
- **Citations** work as for notes: a report the model read counts as opened, and its id is a valid source.
- **Briefs** ("Brief me for today's visit") may mention earlier admissions from the index lines.

## How the existing readers treat them

- **Open loops and medication reconciliation ignore them.** Both read each clinician's latest *note*; an epicrisis
  is its own kind of document, not a note, so a 2019 discharge plan is never today's plan.
- **Surgical history reads them.** An operation report is the best source for an operation; it joins the Procedure
  record as a source. The first load reads each report once with the model and caches it, like other documents.
- **`search_record` and `read_documents`** cover them like any other document.
- The cohort's three existing discharge summaries and operation notes stay notes, untouched.

## In the chart

- The Reports tab gets an "Epicrisis reports" group: one row per report with dates, service, discharge diagnoses and
  a complication mark, opening to the full text with its headings.
- The Visits & notes tab and its count do not include them.
- The patient band and Overview are unchanged (my call): the index lines reach the doctor through briefs and
  answers.
- The three showcase patients appear in My day and All appointments like any other patient.

## What does not change

- No inpatient Encounter is written for an admission. "Last visit" and "Since last visit" keep meaning outpatient
  visits, which several gold answers depend on.
- For the existing 21 patients: problem lists, medication orders, allergies, results and notes.

## Measuring it

- **A deterministic check**, in the style of `--onboarding`, that fails the run on any problem: the 21 existing
  patients have 5 to 10 reports and the showcase patients 8 to 10; the rules above hold (dates, prescriptions
  against orders, operations against Procedure records, the six closed patients); every report's fields parse;
  generation is deterministic; and every pre-existing resource of the 21 patients is byte-identical to before.
- `python -m evals --lint`, `--onboarding` and `--surgery` (with `surgery.toml` extended) pass, and `--loops` and
  `--meds` report the same findings for the 21 patients as before.
- **New gold questions**, in their own category, on the showcase patients and at least two existing ones, covering
  at least: a body-system question with relevant and irrelevant reports; a complication question; a finding that
  matters for anaesthesia; a medicine-safety question answered from an old bleed; a question where no report is
  relevant; a question in Turkish; and a question unrelated to admissions, where the reports must not be read.
- **Against a baseline.** Two identical runs of this model differ by several answers (on 12 Nov, 189 and 191 of 204
  for the same code), so each side is run twice with three repeats and pooled:
  - the 68 existing questions lose no more than 6 answers of 408 in total, and no category loses more than 2;
  - each new question passes at least 4 of its 6 runs, and the new category passes at least 85% pooled.
- **Approach 1 on the same new questions**, by the eval switch: the chart index carries the reports in full and the
  tool is withheld. Reported side by side: pass rate, tokens per question, time per answer. Approach 2 stands unless
  approach 1 passes at least 3 more of the new category's pooled answers; in that case the numbers go to the team
  and nothing switches by itself.

## Left to the builder

- The wording of the report templates, and which admissions each existing patient gets within the catalogue and
  rules.
- The showcase patients' names, exact dates, results and outpatient notes, within the outlines above.
- The marker that makes a DocumentReference an epicrisis and not a note.
- The tool's name and the size limit.
- How the Reports tab lays the report out.
- Module and file names.

## Done looks like

- After generating and loading, the chart has 26 patients; each of the 21 existing ones shows 5 to 10 epicrisis
  reports in the Reports tab and each showcase patient 8 to 10.
- Asked "anything I need to know about her thyroid?" for p-2043, ASKlepios names the aspiration, the thyroidectomy
  with its two complications, the radioiodine treatment and the later lymph-node aspiration, cites each, and leaves
  the gallbladder, wrist and pneumonia admissions out.
- Asked about something no report covers, it says how many reports it read and that none mentions it.
- Open loops and medication reconciliation show the same findings as before for every existing patient.
- The checks under "Measuring it" pass, and the comparison with approach 1 is reported.
