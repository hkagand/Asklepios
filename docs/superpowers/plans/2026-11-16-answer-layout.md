# Scannable ASKlepios Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An ASKlepios answer is a one- or two-sentence lead followed by one folded row per fact (date, bold title, a few words) that opens to its detail and sources.

**Architecture:** The model keeps answering in text, in a fixed bullet shape set by the system prompt. The agent recognises a bullet in that shape and adds a `row` field to the block it already sends; the panel draws blocks with `row` as rows and every other block as today. Verification, sources and gold scoring are untouched because the block's `segments` stay the full text.

**Tech Stack:** Python 3.12 (`agent/`, `evals/`), React 19 + TypeScript + Tailwind (`web/`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-16-answer-layout-design.md`

## Global Constraints

- The facts, the sources and the verification status of each statement are what they are today. A block's `segments` are not changed.
- An answer that does not have the shape is still shown in full, as today.
- A "check" or "no source" marker on a row or on its detail is visible while the row is folded.
- Lead: one or two sentences. At most seven rows. Title: two to four words. The words after the title fit on one line.
- No timeline, no status badges other than "Complication", no "resolved" badge, no JSON answers.
- The "Complication" badge is shown when a row or its detail cites an epicrisis report whose `epicrisisFacts(...).complications` is not empty (the rule in `web/src/views/Reports.tsx`).
- The prepared pre-visit brief card (`PreparedBriefView`) is not changed. A briefing asked in the chat keeps its four bold labels.
- Kept only if, on the same day and model, the 79 gold questions lose at most 6 of 474 against the code before this branch and no category is more than 2 under it.
- Shape rate below 80% means the prompt wording is revisited once, then reported.
- Never read, print or edit `agent/.env`. Keep each file's line endings. Commit messages end with a `Co-Authored-By` line for the model that wrote the commit.

## Review Focus

1. **A flagged detail under a folded row.** A row whose only "check" is on its detail line must show the marker while folded. Pinned in Task 2, Step 2 (fixture answer).
2. **A row whose own statement is unverified and hidden.** Its detail lines must still be shown, as plain nested bullets, and "Show N unverified statements" must bring the row back. Pinned in Task 2, Step 2.
3. **Turkish answers.** "28 Oca 2019 · **Total tiroidektomi** · ..." and "Ocak 2019 · ..." must be rows. Pinned in Task 1, Step 1.
4. **A sentence that merely starts with a year or a bold word.** "In 2019 she had **a thyroidectomy** ..." and "**Note:** the record ..." must not become rows. Pinned in Task 1, Step 1.
5. **Long rows in the narrow panel.** A title and words longer than one line must wrap inside the row, never be cut off, and the chevron must stay on the first line. Pinned in Task 2, Step 2.

---

### Task 1: Recognise a row in the agent

**Files:**
- Modify: `agent/citations.py` (next to `split_blocks`, and the `blocks.append(...)` line in `verify`)
- Create: `evals/layout.py`
- Modify: `evals/run.py` (argument `--layout`, dispatched like `--epicrisis`; argument `--shape-of RUN`, repeatable)

**Interfaces:**
- Produces: `agent.citations.row_of(text: str) -> dict | None`, returning `{"when": str | None, "title": str, "skip": int}` or `None`. `skip` is the number of characters of `text` up to and including the closing `**` of the title and the spaces after it, so `text[skip:]` is what follows the title, separator included.
- Produces: in `verify`, every block dict of kind `"bullet"` and level 0 for which `row_of(block.text)` is not `None` gets the key `"row"` with that dict. No other block has the key. `segments` are unchanged.
- Produces: `evals.layout.run_layout() -> int` (0 when every check passes) and `evals.layout.shape_rate(run: Path) -> tuple[int, int]` (answers in shape, answers with at least one level-0 bullet), read from the run's `results.jsonl` field `raw`.

- [ ] **Step 1: Write the failing check `evals/layout.py`**

`run_layout` prints one line per check (`name: OK` or the problems, like `evals/epicrisis.py`) and returns 1 on any problem. Checks:

```python
ROWS = {  # text -> (when, title, what follows the title)
    "28 Jan 2019 · **Total thyroidectomy** · vocal cord paresis, recovered [DocumentReference/epi-1]":
        ("28 Jan 2019", "Total thyroidectomy", "· vocal cord paresis, recovered [DocumentReference/epi-1]"),
    "Jan 2019 · **Total thyroidectomy** · x [DocumentReference/epi-1]": ("Jan 2019", "Total thyroidectomy", "· x [DocumentReference/epi-1]"),
    "2019 - **Radioiodine ablation** - levothyroxine started [DocumentReference/epi-2]":
        ("2019", "Radioiodine ablation", "- levothyroxine started [DocumentReference/epi-2]"),
    "**Levothyroxine 100 µg** · daily since 2020 [MedicationRequest/med-1]":
        (None, "Levothyroxine 100 µg", "· daily since 2020 [MedicationRequest/med-1]"),
    "**TSH 1.37 mIU/L**, free T4 1.36 ng/dL: in range [Observation/obs-1]":
        (None, "TSH 1.37 mIU/L", ", free T4 1.36 ng/dL: in range [Observation/obs-1]"),
    "**No known allergies** [AllergyIntolerance/alg-1]": (None, "No known allergies", "[AllergyIntolerance/alg-1]"),
    "28 Oca 2019 · **Total tiroidektomi** · ses kısıklığı düzeldi [DocumentReference/epi-1]":
        ("28 Oca 2019", "Total tiroidektomi", "· ses kısıklığı düzeldi [DocumentReference/epi-1]"),
    "Ocak 2019: **Total tiroidektomi** [DocumentReference/epi-1]": ("Ocak 2019", "Total tiroidektomi", "[DocumentReference/epi-1]"),
}
NOT_ROWS = (
    "In 2019 she had **a total thyroidectomy** with a vocal cord paresis [DocumentReference/epi-1]",
    "Treated in 2019: **total thyroidectomy** [DocumentReference/epi-1]",
    "A neck ultrasound showed **no sonographic evidence of recurrence** [DiagnosticReport/dr-1]",
    "Restaging CT chest, abdomen and pelvis: ordered 1 Oct 2026, no result on file [ServiceRequest/sr-1]",
    "**Note:** the record does not say why [DocumentReference/doc-1]",
)
```

- `rows`: for each `ROWS` item, `row_of(text)` gives that `when` and `title`, and `text[row["skip"]:]` equals the third value.
- `not rows`: `row_of(text) is None` for each `NOT_ROWS` item (a title of one to sixty characters that ends in a colon inside the bold, as in "**Note:**", is a label, not a title).
- `answer`: `verify(THYROID, evidence=..., resolve=lambda token: token, label=str, context="")` on the spec's thyroid answer written in the shape (a two-sentence lead, six level-0 bullets of which the second has one indented detail bullet), with an `Evidence` that has every cited id added: exactly six blocks carry `"row"`; the lead and the detail block do not; the detail block has `level == 1`; for every block, the text joined from its `segments` still contains the block's date and title.
- `old style`: an answer with plain bullets, one with a markdown table and one briefing with the four bold labels (`**Reason for visit**` ... as bullets) give blocks with no `"row"` key at all, and the same `kind` and `level` list as `split_blocks` gives today (write the expected lists out).

- [ ] **Step 2: Run it and see it fail**

Run: `python -m evals --layout`
Expected: fails on import of `row_of` (or exits 1 with the `rows` problems).

- [ ] **Step 3: Implement `row_of` and the `"row"` key**

`row_of` matches, at the start of the text only: an optional date (optional day number, optional month word of at most ten letters in any language with an optional full stop, a four-digit year starting 19 or 20) followed by one of `· | : - – —` with spaces around it; then `**title**` with a title of 2 to 60 characters without `*` that does not end in a colon. Nothing else is a row.

- [ ] **Step 4: Add `shape_rate` and the two arguments**

`python -m evals --layout` runs the checks. `python -m evals --shape-of evals/runs/<run>` (repeatable, no model call) prints, per run and pooled, `in shape / answers with bullets` using `split_blocks` and `row_of` on each result's `raw`: an answer is in shape when it has at least one level-0 bullet and every level-0 bullet is a row.

- [ ] **Step 5: Run the checks**

Run: `python -m evals --layout` — every check `OK`, exit 0.
Run: `python -m evals --lint` and `python -m evals --epicrisis` — unchanged (lint clean, 22 checks OK).
Run: `python -m evals --shape-of evals/runs/20261116T120554Z-gpt-oss-120b` — prints a rate near 0 (today's answers are not in the shape), no error.

- [ ] **Step 6: Commit**

`git add agent/citations.py evals/layout.py evals/run.py` — "Recognise an answer bullet written as a row"

---

### Task 2: Draw rows in the panel

**Files:**
- Modify: `web/src/agent.ts` (`Block` gains `row?: { when: string | null; title: string; skip: number }`)
- Modify: `web/src/components/Copilot.tsx` (`AnswerView`, `group`, a new `Row` component; `BlockContent`, `Citation`, `MARKERS` reused)

**Interfaces:**
- Consumes: the `row` key from Task 1.
- Produces: nothing for later tasks.

- [ ] **Step 1: Implement the row drawing**

- `group` keeps consecutive bullets as one list; inside a list, a level-0 bullet with `row` takes the level-1 bullets that directly follow it as its `details`. Everything else is grouped as today.
- `Row`: a header that is one `<button type="button" aria-expanded>` laid out as a grid of three columns (date in tabular small slate text, 62px wide, empty when `when` is null; title in semibold followed by the block's text from `skip` on, with citation segments left out; a chevron), and, when open, a region below it (not inside the button) with each detail drawn by `BlockContent` and then the row's own citation chips. Text wraps; nothing is truncated; the chevron stays on the first line.
- The header shows the marker of the worst status among the row and its details (`check` before `unsourced`), with the same `MARKERS` styling and the issues of those blocks as its title.
- The header shows the `Badge tone="rose"` "Complication" from `web/src/views/Reports.tsx` when any id cited by the row or its details is, in `resources`, an epicrisis report with complications.
- Blocks with status `unsupported` are filtered as today; details whose row is filtered out are drawn as today's nested bullets.
- The footer line starts with `N sources · ` (`Object.keys(answer.sources).length`, "1 source" for one) before the existing lookups and time.
- Rows start folded. Each row keeps its own open state; a new answer starts with all rows folded.

- [ ] **Step 2: Check it in the browser with a fixture**

There are no web tests, so check by eye with a temporary fixture: in `Copilot.tsx`, behind `import.meta.env.DEV && location.hash.includes('layout-fixture')`, show one hard-coded `Answer` built from Task 1's thyroid answer plus: a row whose detail has status `check`, a row with status `unsupported`, a row with a title and words of about 160 characters, and one old-style bullet. Start the `web` preview, open `#/patients/p-2043?layout-fixture`, and confirm with `read_page` and a screenshot at the panel's width and at mobile width:
  - the folded row with the flagged detail shows "check";
  - the unsupported row is absent, its detail is shown, and "Show 1 unverified statement" brings the row back;
  - the long row wraps and its chevron is on the first line;
  - Enter and Space on a focused row open and close it; a chip inside an open row opens the source drawer;
  - the old-style bullet looks as it does today.
Remove the fixture before committing.

- [ ] **Step 3: Build**

Run: `npm --prefix web run build`
Expected: no type errors.

- [ ] **Step 4: Commit**

`git add web/src/agent.ts web/src/components/Copilot.tsx` — "Draw an answer's facts as rows that open to their detail and sources"

---

### Task 3: Ask the model for the shape, and measure

**Files:**
- Modify: `agent/chat.py` (the first "Style" bullet of `SYSTEM_PROMPT`)
- Modify: `README.md` (the ASKlepios description of answers, and the list of checks)

**Interfaces:**
- Consumes: `python -m evals --shape-of` from Task 1; the panel from Task 2.

- [ ] **Step 1: Replace the first Style bullet**

Replace `- Lead with the direct answer, then short "-" bullets. No tables. Write dates like "15 Oct 2026".` with wording that asks for, in this order: the direct answer in one or two sentences; then at most seven "-" bullets, one fact each, written as `date · **title** · a few words [ids]`, the date left out when the fact has none, the title two to four words, the whole bullet on one line; under a bullet, one indented "  - " line with one sentence of detail and its ids, only when it adds something; no tables; dates like "15 Oct 2026". Every other bullet of the prompt stays as it is, including the briefing's four labels and the citation rule.

- [ ] **Step 2: Deterministic checks**

Run: `python -m evals --layout`, `python -m evals --lint`, `python -m evals --epicrisis`
Expected: all pass (`--epicrisis` asserts some prompt strings; if one names the replaced sentence, update that assertion in the same commit).

- [ ] **Step 3: Look at six answers in the browser**

Restart the `agent` preview. Ask in the panel and screenshot each: p-2043 "Any prior things I need to know about her thyroid?"; p-2045 "Anything the anaesthetist should know from her earlier operations?"; p-2044 "Has he ever had a stroke?"; p-3001 "Has she been in hospital before?"; p-2041 "Why is he taking magnesium oxide?"; p-2041 "Son vizitte planlanıp henüz yapılmayanlar neler?". For each, note whether it has a lead, how many rows, and anything that reads worse than before.

- [ ] **Step 4: Measure against a same-day control**

Two runs of `python -m evals --repeats 3` on this branch and two on commit `6f88d5c` (in a scratch working copy outside the repository, with the model settings taken from this checkout's `agent/.env` into the environment without printing them and `AGENT_PLAN_CACHE` pointing at this checkout's `agent/cache/plans`). Report per category and per case that differs by two or more, and `python -m evals --shape-of` for the two branch runs.

Keep the prompt only if the 79 questions lose at most 6 of 474 against the control and no category is more than 2 under it. If the shape rate is below 80%, revise the wording once and measure again. If the limits are not met after that, revert Step 1's change, keep Tasks 1 and 2 (they change nothing for unshaped answers), and report.

- [ ] **Step 5: README**

In the ASKlepios description, say that an answer is a short lead and one row per fact that opens to its detail and sources, that an answer not written that way is shown as plain bullets, and give the measured numbers. Add `--layout` and `--shape-of` to the list of checks.

- [ ] **Step 6: Commit**

`git add agent/chat.py README.md` (and `evals/epicrisis.py` if an assertion changed) — "Ask for answers as a short lead and one line per fact"
