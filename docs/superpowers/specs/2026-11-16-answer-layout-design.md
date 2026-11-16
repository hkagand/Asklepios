# ASKlepios answers a doctor can scan

Status: draft for approval, 16 Nov 2026. A small change; this is the short design.

## Why

ASKlepios answers are correct but read like a document. For a question that reads the epicrisis reports, the panel shows five dense bullets one under the other, every bullet with the same weight, and a doctor in a consult has to read all of them to find the two facts that matter. The answer should be taken in at a glance, with the detail one click away.

The user picked layout A from four mockups (`.superpowers/brainstorm/1354-1794835500/content/answer-layouts.html`, card "A · Answer first, one line per fact").

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

- **Lead:** one or two sentences that answer the question by themselves.
- **Rows:** one per fact: a date when the fact has one, a bold title, and a few words. Rows start folded.
- **Opening a row** shows its detail sentence, if it has one, and its source chips. A row without detail opens to its sources alone.
- **Markers:** a row shows "check" or "no source" when the row or its detail has that status, folded or open, so a flagged statement is never hidden. "Unverified" statements stay hidden behind the existing "Show N unverified statements" link.
- **Complication badge:** shown on a row when the row or its detail cites an epicrisis report that records a complication (the flag the Reports tab already uses). There is no "resolved" badge: only the model's wording says that, and it stays in the text.
- **Footer:** the number of distinct sources next to the existing lookups and time.

## Goals

- Every ASKlepios answer in the panel uses this layout when the model's text has the shape below.
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

**The shape the model is asked for** (the "Style" part of the system prompt in `agent/chat.py` replaces "Lead with the direct answer, then short "-" bullets"):

```
<one or two sentences that answer the question> [ids]
- <date> · **<title>** · <a few words> [ids]
  - <one sentence of detail, only when it adds something> [ids]
- **<title>** · <a few words> [ids]
```

- The date is written as the prompt already requires ("28 Jan 2019"; "Jan 2019" or "2019" when the record gives no more) and is left out when the fact has none (a current medicine, an allergy).
- At most seven rows; the title is two to four words; the words after it fit on one line.
- Every row and every detail line ends with its ids, as every bullet does today.
- The existing rules stay: no tables, no advice, the language of the question, the briefing's four labels.

**Parsing.** `split_blocks` in `agent/citations.py` already returns indented bullets as level 1. A level-0 bullet whose text starts with an optional date, then a bold title, is a row; the level-1 bullets that follow it are its detail. Where the split into date, title and rest is made (the agent, which would add the fields to the block it sends, or the panel) is the builder's choice; the agent is preferred, because the deterministic checks live in `evals/` and the web has no tests.

**Panel.** `AnswerView` in `web/src/components/Copilot.tsx` draws rows as a three-column grid (date, title and words, chevron), keeps one open/closed state per row, and draws every other block as today. The source chip, the markers and the source drawer are reused unchanged.

## Checks and measurement

- **Deterministic check first** (a new check in `evals/`, written before the code): the thyroid answer above, as text, parses into a lead and six rows with the right dates, titles and detail; a row with a flagged detail reports the flag; an old-style answer (plain bullets, a table, a briefing with labels) parses exactly as it does today.
- **Web build:** `npm --prefix web run build`.
- **Browser:** the thyroid, anaesthesia, stroke and "none on file" questions, a medicine question and a Turkish question, checked by eye in the panel, with a screenshot of each.
- **Gold set:** two runs of three repeats on the new prompt and two on the code before it, same day. Kept only if the 79 questions lose at most 6 of 474 against that control and no category is more than 2 under it. The gold checks read the whole answer text, folded or not, so they need no change.
- **Shape rate:** from the same runs, the share of answers with bullets in which every level-0 bullet is a row. Reported; below 80% the prompt wording is revisited once.

## Left to the builder

- The exact prompt wording, within the shape above.
- Where the row fields are computed (agent preferred).
- Keyboard behaviour and the open/close animation, in the panel's existing style.

## Calls made without the user

- Sources are shown when a row is opened, not on the folded row, as in the mockup. The markers stay visible on the folded row.
- The Complication badge comes from the cited report, so a row that cites the thyroidectomy report for another fact (levothyroxine started) also gets it.
- A briefing asked in the chat keeps its labels.
- The work goes on a new branch, `answer-layout`, on top of `epicrisis-reports`.
