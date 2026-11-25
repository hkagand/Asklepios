# ASKlepios answers a doctor can scan

Status: approved 16 Nov 2026 and built. The design changed during the build; "What changed during the build" below says how, and the sections after it describe what was built.

## Why

ASKlepios answers are correct but read like a document. For a question that reads the epicrisis reports, the panel shows five dense bullets one under the other, every bullet with the same weight, and a doctor in a consult has to read all of them to find the two facts that matter. The answer should be taken in at a glance, with the detail one click away.

The user picked layout A from four mockups (`.superpowers/brainstorm/1354-1794835500/content/answer-layouts.html`, card "A · Answer first, one line per fact").

## What changed during the build

The approved design had the model write each fact short: a lead of one or two sentences, then at most seven rows of a date, a bold title and "a few words", with a longer sentence on an indented line. Two wordings of that were measured on the gold set (16 Nov 2026, gpt-oss-120b, two runs of three repeats each, same-day control 430 of 474):

- Brief rows with the caps: 419 of 474, 11 under the control (limit 6). 51 of the 58 failed checks were facts left out: "Ferritin was last measured on 6 Feb 2026" without the value, the ramipril order without the note's 5 mg, no count of the reports read.
- The same with "never leave a fact out to be brief": 432 of 474, but three categories more than 2 under (surgery, medications, briefing), again from answers that stopped at the lead and dropped a discrepancy.

On seeing an opened row the user asked: "Let's keep the facts in there too. The initial bigger text version should still be visible when I click on it." So the shortening moved from the model to the panel:

- The model writes each bullet as fully as before. The prompt only asks it to start the bullet with a bold title, with the date before it.
- The panel folds a row to one line and shows the whole fact when the row is opened.
- There is no rule about the lead and no cap on rows.

Measured on 25 Nov 2026 (two runs of three repeats, same-day control on the code before this branch): 448 of 474 against 435 of 474, no category more than 2 under, and 419 of the 435 answers with bullets had every top-level bullet drawn as a row. The wording is kept.

## What the doctor sees

For the question "Any prior things I need to know about her thyroid?":

```
Thyroid cancer treated in 2019, no sign of recurrence. Total thyroidectomy
and radioiodine; on levothyroxine 100 µg with TSH in range.

Dec 2018   Nodule biopsy · suspicious (Bethesda V)                    ›
Jan 2019   Total thyroidectomy  [Complication]                        ⌄
             Right vocal cord paresis after loss of the nerve signal,
             recovered by May 2019. Low calcium for two weeks.
             [Epicrisis · 1 Feb 2019]
Feb 2019   Radioiodine ablation · levothyroxine started               ›
Apr 2023   Neck node biopsy · benign                                  ›
Oct 2025   Neck ultrasound · no recurrence                            ›
Jul 2026   TSH 1.37, free T4 1.36 · in range                          ›

6 sources · 1 lookup · 8.2 s
```

- **Lead:** the direct answer, as the model has always written it.
- **Rows:** one per bullet that starts with a bold title. Folded, a row is one line: the date when the fact has one, the bold title, and the start of the fact, cut with an ellipsis. Rows start folded.
- **Opening a row** shows the fact in full with its source chips, then any indented detail lines under it.
- **Markers:** a row shows "check" or "no source" when the row or its detail has that status, folded or open, so a flagged statement is never hidden. "Unverified" statements stay hidden behind the existing "Show N unverified statements" link.
- **Complication badge:** shown on a row when the row or its detail cites an epicrisis report that records a complication (the flag the Reports tab already uses). There is no "resolved" badge: only the model's wording says that, and it stays in the text.
- **Footer:** the number of distinct sources next to the existing lookups and time.

## Goals

- Every bullet of an ASKlepios answer that starts with a bold title is drawn as a row.
- The facts, the sources and the verification of each statement are what they are today.
- An answer that does not have the shape is still shown in full, as today.

## Not in this change

- A timeline or status badges (mockups B and C).
- Structured (JSON) answers from the model.
- The prepared pre-visit brief card, which has its own layout. A briefing asked in the chat keeps its four bold labels; bullets under them are drawn as rows when they have the shape.
- Any change to what is cited or how citations are verified.

## What would make it a failure

- A statement, a source or a "check" marker that the old layout showed and the new one cannot reach.
- Answers that score worse on the gold questions because the model, asked to be brief, drops required facts.
- A layout that only works for the thyroid question.

## Approaches

1. **The model writes its bullets in a fixed shape; the panel draws that shape (picked).** The answer stays text, so citation verification, the markers and the gold scoring keep working, and a bullet in the old style is still shown as a plain bullet. Costs a prompt change that must be measured, and the model will not follow the shape every time at low reasoning effort.
2. **The model returns structured data.** Guarantees the shape, but verification, scoring and the panel are all built on text and would be rewritten: several times the work and risk.
3. **The panel reshapes today's text.** No model change, but it cannot write the lead and cutting sentences mechanically gives ragged rows. Not considered further.

The user picked 1 ("Go recommended").

## How

**What the model is asked for** (one bullet added to the "Style" part of the system prompt in `agent/chat.py`; the sentence "Lead with the direct answer, then short "-" bullets" stays):

```
- <date> · **<title>** · <the fact, as fully as before> [ids]
- **<title>** · <the fact> [ids]
```

- The title is two to four words and only a label: after it the bullet says everything it would have said without one.
- The date goes before the title when the fact has one.
- Every other rule stays: citations on every bullet, no tables, no advice, the language of the question, the briefing's four labels.

**What the recogniser accepts.** At low reasoning effort the model does not hold one form, so `row_of` in `agent/citations.py` accepts the date before the title, in the bold part ("**date** · title", "**date** · **title**", "**date · title**"), in brackets at the end of the title, straight after the title, and a period in the date's place ("25-28 Feb 2019"). A bold label that ends in a colon and a sentence that merely contains a bold word are not rows. Each form has a case in `python -m evals --layout`.

**Parsing.** `split_blocks` in `agent/citations.py` already returns indented bullets as level 1. `verify` adds a `row` field (`when`, `title`, `skip`: where the fact starts after the date and title) to a level-0 bullet that `row_of` recognises; its `segments` are unchanged, so verification and scoring see the same text. The level-1 bullets that follow a row are its detail.

**Panel.** `AnswerView` in `web/src/components/Copilot.tsx` draws a row as a grid of date, title and fact (one line, cut off, while folded), badges and markers, and a chevron; it keeps one open/closed state per row and draws every other block as before. The source chip, the markers and the source drawer are reused unchanged.

## Checks and measurement

- **Deterministic check first** (a new check in `evals/`, written before the code): the thyroid answer above, as text, parses into a lead and six rows with the right dates, titles and detail; a row with a flagged detail reports the flag; an old-style answer (plain bullets, a table, a briefing with labels) parses exactly as it does today.
- **Web build:** `npm --prefix web run build`.
- **Browser:** the thyroid, anaesthesia, stroke and "none on file" questions, a medicine question and a Turkish question, checked by eye in the panel, with a screenshot of each.
- **Gold set:** two runs of three repeats on the new prompt and two on the code before it, same day. Kept only if the 79 questions lose at most 6 of 474 against that control and no category is more than 2 under it. The gold checks read the whole answer text, folded or not, so they need no change.
- **Shape rate:** from the same runs, the share of answers with bullets in which every level-0 bullet is a row (`python -m evals --shape-of`). Reported.

## Left to the builder

- The exact prompt wording, within the shape above.
- Where the row fields are computed (agent preferred).
- Keyboard behaviour and the open/close animation, in the panel's existing style.

## Calls made without the user

- Sources are shown when a row is opened, not on the folded row, as in the mockup. The markers stay visible on the folded row.
- When no row of a list has a date, the date column is left out for that list.
- A period in the date's place is cut off in the folded row and shown whole when the row is opened.
- The Complication badge comes from the cited report, so a row that cites the thyroidectomy report for another fact (levothyroxine started) also gets it.
- A briefing asked in the chat keeps its labels.
- The work goes on a new branch, `answer-layout`, on top of `epicrisis-reports`.
