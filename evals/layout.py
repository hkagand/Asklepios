"""Checks the shape of an answer that the chat panel draws as rows: python -m evals --layout

An answer is a short lead and then one bullet per fact, written "date · **title** · a few words [ids]", with an
indented bullet under it for a sentence of detail. agent/citations.py marks such a bullet as a row; every other block
is as it was. With --shape-of RUN the share of a gold run's answers that are written this way is counted instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.citations import Evidence, row_of, split_blocks, verify

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

THYROID = """\
Thyroid cancer treated in 2019, with no sign of recurrence since [DocumentReference/epi-3, DiagnosticReport/dr-1]. \
She takes levothyroxine 100 microgram daily and her TSH is in range [MedicationRequest/med-1, Observation/obs-1].
- 10 Dec 2018 · **Nodule biopsy** · suspicious, Bethesda V [DocumentReference/epi-2]
- 28 Jan 2019 · **Total thyroidectomy** · vocal cord paresis, recovered [DocumentReference/epi-3]
  - Right vocal cord paresis after loss of the nerve signal, recovered by May 2019; low calcium for two weeks [DocumentReference/epi-3]
- Feb 2019 · **Radioiodine ablation** · levothyroxine started [DocumentReference/epi-4]
- 14 Apr 2023 · **Neck node biopsy** · benign [DocumentReference/epi-6]
- 10 Oct 2025 · **Neck ultrasound** · no recurrence [DiagnosticReport/dr-1]
- 10 Jul 2026 · **TSH 1.37 mIU/L** · in range [Observation/obs-1]
"""
THYROID_ROWS = [
    ("10 Dec 2018", "Nodule biopsy"), ("28 Jan 2019", "Total thyroidectomy"), ("Feb 2019", "Radioiodine ablation"),
    ("14 Apr 2023", "Neck node biopsy"), ("10 Oct 2025", "Neck ultrasound"), ("10 Jul 2026", "TSH 1.37 mIU/L"),
]

# Answers written the old way: (text, the kind and level of each block as split_blocks gives them today).
OLD_STYLE = {
    "plain bullets": (
        "He takes ramipril 10 mg once daily [MedicationRequest/med-1].\n"
        "- Ordered on 3 Mar 2026 [MedicationRequest/med-1]\n"
        "- The note of 2 Sep 2026 says 5 mg [DocumentReference/doc-1]\n"
        "  - He halved it himself [DocumentReference/doc-1]\n",
        [("paragraph", 0), ("bullet", 0), ("bullet", 0), ("bullet", 1)],
    ),
    "a table": (
        "Results:\n| Test | Value |\n|---|---|\n| TSH | 1.37 mIU/L [Observation/obs-1] |\n",
        [("paragraph", 0), ("bullet", 0), ("bullet", 0)],
    ),
    "a briefing": (
        "- **Reason for visit**\n- Follow-up of thyroid cancer [Encounter/enc-1]\n"
        "- **Background:**\n- Total thyroidectomy in 2019 [DocumentReference/epi-3]\n",
        [("heading", 0), ("bullet", 0), ("heading", 0), ("bullet", 0)],
    ),
}


def _verified(text: str) -> list[dict]:
    """The blocks the panel gets for an answer, with every id it cites counted as read."""
    evidence = Evidence()
    evidence.add(text)
    return verify(text, evidence=evidence, resolve=lambda token: token, label=str, context="")["blocks"]


def _text(block: dict) -> str:
    return "".join(segment.get("text", "") for segment in block["segments"])


def check_rows() -> list[str]:
    problems = []
    for text, (when, title, rest) in ROWS.items():
        row = row_of(text)
        if row is None:
            problems.append(f"not a row: {text!r}")
        elif (row["when"], row["title"], text[row["skip"]:]) != (when, title, rest):
            problems.append(f"{text!r} gives {(row['when'], row['title'], text[row['skip']:])}, expected {(when, title, rest)}")
    return problems


def check_not_rows() -> list[str]:
    return [f"a row: {text!r} gives {row}" for text in NOT_ROWS if (row := row_of(text)) is not None]


def check_answer() -> list[str]:
    """The thyroid answer of the design: a lead, six rows, and one detail line under the second row."""
    blocks = _verified(THYROID)
    problems = []
    rows = [block for block in blocks if "row" in block]
    found = [(block["row"]["when"], block["row"]["title"]) for block in rows]
    if found != THYROID_ROWS:
        problems.append(f"rows {found}, expected {THYROID_ROWS}")
    shape = [(block["kind"], block["level"], "row" in block) for block in blocks]
    expected = [("paragraph", 0, False), ("bullet", 0, True), ("bullet", 0, True), ("bullet", 1, False)] + [("bullet", 0, True)] * 4
    if shape != expected:
        problems.append(f"blocks {shape}, expected {expected}")
    for block in rows:
        if not all(part in _text(block) for part in (block["row"]["when"], block["row"]["title"])):
            problems.append(f"the segments of the row {block['row']['title']!r} lost its date or title: {_text(block)!r}")
        if not _text(block)[block["row"]["skip"]:].startswith("·"):
            problems.append(f"skip of the row {block['row']['title']!r} does not end after its title: {_text(block)[block['row']['skip']:]!r}")
    return problems


def check_old_style() -> list[str]:
    """An answer written the old way gives the blocks it gave before, and none of them is a row."""
    problems = []
    for name, (text, expected) in OLD_STYLE.items():
        split = [(block.kind, block.level) for block in split_blocks(text)]
        if split != expected:
            problems.append(f"{name}: split_blocks gives {split}, expected {expected}")
        blocks = _verified(text)
        if [(block["kind"], block["level"]) for block in blocks] != expected:
            problems.append(f"{name}: verify gives {[(block['kind'], block['level']) for block in blocks]}, expected {expected}")
        if marked := [_text(block) for block in blocks if "row" in block]:
            problems.append(f"{name}: marked as rows: {marked}")
    return problems


def run_layout() -> int:
    checks = {"rows": check_rows(), "not rows": check_not_rows(), "answer": check_answer(), "old style": check_old_style()}
    for name, problems in checks.items():
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
    return 1 if any(checks.values()) else 0


def shape_rate(run: Path) -> tuple[int, int]:
    """(answers in the shape, answers with at least one bullet) of a gold run: an answer is in the shape when every
    one of its top-level bullets is a row."""
    shaped = bulleted = 0
    for line in (run / "results.jsonl").read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        bullets = [block for block in split_blocks(json.loads(line).get("raw") or "") if block.kind == "bullet" and block.level == 0]
        if bullets:
            bulleted += 1
            shaped += all(row_of(block.text) for block in bullets)
    return shaped, bulleted


def run_shape(runs: list[Path]) -> int:
    total = [0, 0]
    for run in runs:
        shaped, bulleted = shape_rate(run)
        total = [total[0] + shaped, total[1] + bulleted]
        print(f"{run.name}: {shaped} of {bulleted} answers with bullets are in the shape")
    if len(runs) > 1:
        print(f"together: {total[0]} of {total[1]}")
    return 0
