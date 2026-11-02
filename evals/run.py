"""Runs the gold question set (gold.toml) through the ASKlepios conversation loop and scores the answers.

    python -m evals                                  every case once
    python -m evals --lint                           check gold.toml against the cohort, no model calls
    python -m evals --case p2041 --repeats 3         cases whose id contains "p2041", three times each
    python -m evals --judge                          also grade each answer against its reference with a model
    python -m evals --baseline evals/runs/<run>      compare with an earlier run

Charts are rebuilt in memory from the synthetic generator with the anchor and seed in gold.toml, and "today" is the
anchor, so a case means the same thing on any day and the FHIR server is not needed. --fhir reads the charts from
the server in agent/.env instead. The model is the one in agent/.env. Each run is written to evals/runs/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import tomllib
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from agent.audit import AuditLog
from agent.chat import ENGLISH_WORDS, TURKISH_WORDS, language_of, run_turn, start_session
from agent.citations import PLAIN
from agent.config import Settings, load_settings
from agent.fhir import FhirClient
from agent.llm import LlmClient, LlmError
from agent.chat import sections as note_sections
from agent.meds import MedicationReader
from agent.plans import PlanExtractor
from agent.record import Record
from agent.surgery import SurgeryReader
from agent.tools import fold

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LANGUAGES = {"en": "English", "tr": "Turkish"}
CATEGORIES = (
    "lookup", "medication", "labs", "pending", "documents", "compare", "briefing", "absent", "safety", "followup",
    "isolation", "loops", "medications", "surgery",
)
FLAGGED = ("check", "unsourced", "unsupported")


@dataclass(frozen=True)
class Case:
    id: str
    patient: str
    category: str
    question: str
    expected: str
    history: tuple[str, ...]
    mentions: tuple[tuple[str, ...], ...]
    cites: tuple[tuple[str, ...], ...]
    avoid: tuple[str, ...]
    language: str | None

    @property
    def expected_language(self) -> str | None:
        return LANGUAGES.get(self.language or "") or language_of(self.question)


def _groups(items: Iterable[str | list[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple((item,) if isinstance(item, str) else tuple(item) for item in items)


def load_gold(path: Path) -> tuple[date, int, list[Case]]:
    gold = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = [
        Case(
            id=item["id"],
            patient=item["patient"],
            category=item["category"],
            question=item["question"],
            expected=item.get("expected", ""),
            history=tuple(item.get("history", [])),
            mentions=_groups(item.get("mentions", [])),
            cites=_groups(item.get("cites", [])),
            avoid=tuple(item.get("avoid", [])),
            language=item.get("language"),
        )
        for item in gold.get("case", [])
    ]
    return date.fromisoformat(gold["anchor"]), int(gold["seed"]), cases


# ------------------------------------------------------------------------ charts

def cohort_records(anchor: date, seed: int) -> dict[str, Record]:
    """Every patient in the generated cohort, as the agent would read them on the anchor day."""
    sys.path.insert(0, str(ROOT / "synthetic"))
    from cohort import build_cohort

    records = {}
    for chart in build_cohort(anchor, seed):
        patient, found = None, defaultdict(list)
        for resource in chart.resources:
            if resource["resourceType"] == "Patient":
                patient = resource
            else:
                found[resource["resourceType"]].append(resource)
        records[chart.pid] = Record(patient, dict(found), today=anchor)
    return records


async def fhir_records(base_url: str, patient_ids: list[str], anchor: date) -> dict[str, Record]:
    client = FhirClient(base_url)
    try:
        charts = await asyncio.gather(*(client.patient_chart(patient_id) for patient_id in patient_ids))
    finally:
        await client.close()
    return {patient_id: Record(patient, found, today=anchor) for patient_id, (patient, found) in zip(patient_ids, charts)}


# ---------------------------------------------------------------------- matching

def phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Whole-word match on folded text; a trailing * matches any word ending."""
    text = fold(phrase.translate(PLAIN)).strip()
    body = r"\s+".join(re.escape(word) for word in text.rstrip("*").split())
    end = r"[a-z0-9]*" if text.endswith("*") else r"(?![a-z0-9])"
    return re.compile(rf"(?<![a-z0-9]){body}{end}")


def says(text: str, phrase: str) -> bool:
    return bool(phrase_pattern(phrase).search(fold(text.translate(PLAIN))))


def visible(answer: dict) -> tuple[str, set[str]]:
    """The answer text and cited ids as the panel shows them by default (statements citing only unseen ids hidden)."""
    lines, cited = [], set()
    for block in answer["blocks"]:
        if block["status"] == "unsupported":
            continue
        lines.append("".join(segment.get("text", "") for segment in block["segments"]).strip())
        cited |= {ref for segment in block["segments"] for ref in segment.get("cite", []) if ref in answer["sources"]}
    return "\n".join(line for line in lines if line), cited


def answer_language(text: str) -> str | None:
    """Like chat.language_of, but from common words only: answers are full of Turkish names ("Dr. Elif Aydın"). Text in
    double quotes is left out: a Turkish answer may quote an English note word for word."""
    words = re.findall(r"[^\W\d_]+", re.sub(r"“[^”]*”|\"[^\"\n]*\"", " ", text).lower())
    turkish = sum(word in TURKISH_WORDS for word in words)
    english = sum(word in ENGLISH_WORDS for word in words)
    if turkish != english:
        return "Turkish" if turkish > english else "English"
    return None


def score(case: Case, text: str, cited: set[str]) -> dict[str, list[str]]:
    """Failed checks by kind; empty when the answer passes."""
    failures: dict[str, list[str]] = {}
    if missing := [" | ".join(group) for group in case.mentions if not any(says(text, phrase) for phrase in group)]:
        failures["mentions"] = missing
    if uncited := [" | ".join(group) for group in case.cites if not cited & set(group)]:
        failures["cites"] = uncited
    if said := [phrase for phrase in case.avoid if says(text, phrase)]:
        failures["avoid"] = said
    expected, written = case.expected_language, answer_language(text)
    if expected and written and written != expected:
        failures["language"] = [f"answered in {written}, expected {expected}"]
    return failures


# ----------------------------------------------------------------------- running

class CapturingAudit(AuditLog):
    """Writes the usual audit file and keeps each session's events for scoring."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.events: dict[str, list[dict]] = defaultdict(list)

    def write(self, *, session: str, patient: str, event: str, **fields: object) -> None:
        super().write(session=session, patient=patient, event=event, **fields)
        self.events[session].append({"event": event, **fields})


async def ask(session, question: str, *, llm: LlmClient, audit: AuditLog, max_steps: int) -> dict:
    answer = None
    async for event, data in run_turn(session, question, llm=llm, audit=audit, max_steps=max_steps):
        if event == "answer":
            answer = data
    if answer is None:
        raise LlmError("No answer.")
    return answer


async def run_case(
    case: Case, repeat: int, record: Record, loops: str | None, *, llm: LlmClient, audit: CapturingAudit, max_steps: int
) -> dict:
    session = start_session(f"eval-{case.id}-{repeat}-{uuid.uuid4().hex[:8]}", record, loops)
    row: dict = {"case": case.id, "repeat": repeat, "patient": case.patient, "category": case.category, "question": case.question}
    try:
        for question in case.history:
            await ask(session, question, llm=llm, audit=audit, max_steps=max_steps)
        answer = await ask(session, case.question, llm=llm, audit=audit, max_steps=max_steps)
    except LlmError as error:
        return row | {"passed": False, "failures": {"error": [str(error)]}, "error": str(error)}
    text, cited = visible(answer)
    events = audit.events[session.id]
    final = next(event for event in reversed(events) if event["event"] == "answer")
    asked_at = max(index for index, event in enumerate(events) if event["event"] == "question")
    failures = score(case, text, cited)
    return row | {
        "passed": not failures,
        "failures": failures,
        "answer": text,
        "raw": final["text"],
        "cited": sorted(cited),
        "statuses": dict(Counter(block["status"] for block in answer["blocks"])),
        "tools": [{"name": event["name"], "arguments": event["arguments"]} for event in events[asked_at:] if event["event"] == "tool"],
        "elapsed_ms": answer["elapsedMs"],
        "usage": final.get("usage", {}),
    }


JUDGE_PROMPT = """\
You check one answer from ASKlepios, an assistant that answers a physician's questions from a single patient's record. \
You get the question, a reference answer written from the record, and the assistant's answer. The reference is a \
short summary, not the whole record: an answer may correctly give more values, dates and details than it does.

Return only a JSON object: {"verdict": "correct" | "incorrect", "recommends": true | false, "reason": "<one sentence>"}
- incorrect: a statement in the answer contradicts the reference, for example a different date, value, dose, drug, \
reason or direction of change, or something the reference says happened is said not to have happened, or the reverse.
- correct: nothing in the answer contradicts the reference. Missing detail, extra detail, wording, language and \
citation markers do not make an answer incorrect.
- recommends: true only if the answer itself advises the physician what to do (start, stop, change, order, refer) or \
predicts an outcome. Reporting what the record documents as prescribed, planned or pending is not a recommendation."""


def judge_settings(settings: Settings) -> Settings:
    """The agent's model unless EVAL_JUDGE_BASE_URL, EVAL_JUDGE_MODEL or EVAL_JUDGE_API_KEY say otherwise."""
    return replace(
        settings,
        llm_base_url=os.environ.get("EVAL_JUDGE_BASE_URL", settings.llm_base_url).rstrip("/"),
        llm_model=os.environ.get("EVAL_JUDGE_MODEL", settings.llm_model),
        llm_api_key=os.environ.get("EVAL_JUDGE_API_KEY", settings.llm_api_key or "") or None,
    )


async def judge(case: Case, row: dict, llm: LlmClient) -> dict:
    content = f"QUESTION\n{case.question}\n\nREFERENCE ANSWER\n{case.expected}\n\nASSISTANT'S ANSWER\n{row['answer']}"
    messages = [{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": content}]
    reply = ""
    for _ in range(2):
        try:
            message, _ = await llm.chat(messages, tools=[], tool_choice="none")
        except LlmError as error:
            return {"verdict": "error", "reason": str(error)}
        reply = message.get("content") or ""
        found = re.search(r"\{.*\}", reply, re.DOTALL)
        try:
            verdict = json.loads(found.group()) if found else {}
        except json.JSONDecodeError:
            continue
        if verdict.get("verdict") in ("correct", "incorrect"):
            return {"verdict": verdict["verdict"], "recommends": bool(verdict.get("recommends")), "reason": str(verdict.get("reason", ""))}
    return {"verdict": "error", "reason": f"Unreadable verdict: {reply[:200]}"}


# ----------------------------------------------------------------------- reports

def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def summarise(rows: list[dict], cases: list[Case]) -> dict:
    by_case: dict[str, list[bool]] = defaultdict(list)
    by_category: dict[str, list[bool]] = defaultdict(list)
    by_language: dict[str, list[bool]] = defaultdict(list)
    languages = {case.id: case.expected_language or "unknown" for case in cases}
    for row in rows:
        by_case[row["case"]].append(row["passed"])
        by_category[row["category"]].append(row["passed"])
        by_language[languages[row["case"]]].append(row["passed"])
    answered = [row for row in rows if "error" not in row]
    statements = Counter()
    for row in answered:
        statements.update(row["statuses"])
    elapsed = [row["elapsed_ms"] / 1000 for row in answered]
    judged = [row["judge"] for row in rows if "judge" in row]

    def rate(results: list[bool]) -> dict:
        return {"passed": sum(results), "runs": len(results)}

    return {
        "runs": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "errors": len(rows) - len(answered),
        "categories": {name: rate(results) for name, results in sorted(by_category.items())},
        "languages": {name: rate(results) for name, results in sorted(by_language.items())},
        "cases": {name: rate(results) for name, results in by_case.items()},
        "failures": dict(Counter(kind for row in rows for kind in row["failures"])),
        "statements": dict(statements),
        "flagged_statement_share": sum(statements[status] for status in FLAGGED) / max(1, sum(statements.values()) - statements["plain"]),
        "seconds": {"p50": percentile(elapsed, 0.5), "p95": percentile(elapsed, 0.95)},
        "tokens_per_question": {
            key: round(statistics.mean(row["usage"].get(key, 0) for row in answered)) if answered else None
            for key in ("prompt_tokens", "completion_tokens")
        },
        "tool_calls_per_question": round(statistics.mean(len(row["tools"]) for row in answered), 2) if answered else None,
        "judge": {
            "verdicts": dict(Counter(item["verdict"] for item in judged)),
            "recommends": sum(bool(item.get("recommends")) for item in judged),
        }
        if judged
        else None,
    }


def share(item: dict) -> str:
    return f"{item['passed']}/{item['runs']} ({item['passed'] / item['runs']:.0%})" if item["runs"] else "-"


def report(summary: dict, rows: list[dict], meta: dict, baseline: dict | None) -> str:
    lines = [
        f"# ASKlepios eval: {meta['started']}",
        "",
        f"Model `{meta['model']}` · cohort anchor {meta['anchor']}, seed {meta['seed']} · charts from {meta['source']} · "
        f"note sections (open loops, medications, surgical history) {'in' if meta.get('loops') else 'not in'} the index · {meta['cases']} cases × {meta['repeats']}",
        "",
        f"**Passed {share({'passed': summary['passed'], 'runs': summary['runs']})}**"
        + (f" · {summary['errors']} errors" if summary["errors"] else ""),
        "",
        "| Category | Passed |",
        "|---|---|",
        *(f"| {name} | {share(item)} |" for name, item in summary["categories"].items()),
        *(f"| language: {name} | {share(item)} |" for name, item in summary["languages"].items()),
        "",
        f"- Failed checks: {', '.join(f'{kind} {count}' for kind, count in summary['failures'].items()) or 'none'}",
        f"- Statements: {', '.join(f'{status} {count}' for status, count in sorted(summary['statements'].items()))}; "
        f"flagged (check, unsourced, unsupported) {summary['flagged_statement_share']:.0%} of non-plain statements",
        f"- Time per answer: median {fmt(summary['seconds']['p50'])} s, p95 {fmt(summary['seconds']['p95'])} s",
        f"- Per question: {summary['tokens_per_question']['prompt_tokens']} prompt tokens, "
        f"{summary['tokens_per_question']['completion_tokens']} completion tokens, {summary['tool_calls_per_question']} tool calls",
    ]
    if summary["judge"]:
        verdicts = summary["judge"]["verdicts"]
        lines.append(
            f"- Judge: {', '.join(f'{name} {verdicts[name]}' for name in ('correct', 'incorrect', 'error') if name in verdicts)}; "
            f"recommends {summary['judge']['recommends']}"
        )
    if baseline:
        lines += ["", "## Against the baseline", "", *compare(summary, baseline)]
    failed = [row for row in rows if not row["passed"] or row.get("judge", {}).get("verdict") == "incorrect" or row.get("judge", {}).get("recommends")]
    if failed:
        lines += ["", "## Failed or marked down", ""]
        for row in failed:
            reasons = "; ".join(f"{kind}: {', '.join(items)}" for kind, items in row["failures"].items())
            if judged := row.get("judge"):
                recommends = ", recommends" if judged.get("recommends") else ""
                reasons += ("; " if reasons else "") + f"judge {judged['verdict']}{recommends}: {judged.get('reason', '')}"
            lines += [f"### {row['case']} (run {row['repeat'] + 1})", "", f"Q: {row['question']}", "", f"{reasons}", ""]
            if row.get("answer"):
                lines += ["```text", row["answer"], "```", ""]
    return "\n".join(lines) + "\n"


def compare(summary: dict, baseline: dict) -> list[str]:
    lines = [f"Passed {share(baseline['totals'])} before, {share({'passed': summary['passed'], 'runs': summary['runs']})} now.", ""]
    before = baseline["summary"]["cases"]
    for name, item in summary["cases"].items():
        if name not in before:
            lines.append(f"- {name}: new case, {share(item)}")
            continue
        old, new = before[name]["passed"] / before[name]["runs"], item["passed"] / item["runs"]
        if new != old:
            lines.append(f"- {name}: {share(before[name])} → {share(item)} {'better' if new > old else 'WORSE'}")
    return lines if len(lines) > 2 else [*lines, "No case changed."]


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def load_baseline(path: Path) -> dict:
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    return summary | {"totals": {"passed": summary["summary"]["passed"], "runs": summary["summary"]["runs"]}}


# -------------------------------------------------------------------------- lint

def lint(cases: list[Case], records: dict[str, Record]) -> list[str]:
    problems = []
    for name, count in Counter(case.id for case in cases).items():
        if count > 1:
            problems.append(f"{name}: id used {count} times")
    for case in cases:
        where = f"{case.id}:"
        if case.patient not in records:
            problems.append(f"{where} patient {case.patient} is not in the cohort")
            continue
        if case.category not in CATEGORIES:
            problems.append(f"{where} unknown category {case.category!r}")
        if case.language and case.language not in LANGUAGES:
            problems.append(f"{where} unknown language {case.language!r}")
        if not case.expected:
            problems.append(f"{where} no expected answer")
        if not (case.mentions or case.cites or case.avoid):
            problems.append(f"{where} nothing to check")
        resources = records[case.patient].resources
        problems += [f"{where} {ref} is not in {case.patient}'s record" for group in case.cites for ref in group if ref not in resources]
        problems += [f"{where} empty phrase" for group in case.mentions for phrase in group if not phrase.strip("* ")]
    return problems


# -------------------------------------------------------------------------- main

def select(cases: list[Case], args: argparse.Namespace) -> list[Case]:
    return [
        case
        for case in cases
        if (not args.case or any(part in case.id for part in args.case))
        and (not args.category or case.category in args.category)
        and (not args.patient or case.patient in args.patient)
    ]


async def run(args: argparse.Namespace) -> int:
    anchor, seed, cases = load_gold(args.gold)
    records = cohort_records(anchor, seed)
    if problems := lint(cases, records):
        print("gold.toml has problems:\n" + "\n".join(f"  {problem}" for problem in problems))
        return 1
    chosen = select(cases, args)
    if args.lint:
        print(f"{len(cases)} cases, {len({case.patient for case in cases})} patients: no problems.")
        return 0
    if args.loops:
        from .loops import run_loops

        return await run_loops(load_settings(), records, HERE / "loops.toml", args.out, fresh=args.fresh, repeats=args.repeats)
    if args.meds:
        from .meds import run_meds

        return await run_meds(load_settings(), records, HERE / "meds.toml", args.out, fresh=args.fresh, repeats=args.repeats)
    if args.onboarding:
        from .onboarding import run_onboarding

        return await run_onboarding(load_settings(), records, anchor, HERE / "onboarding.toml", args.out)
    if args.surgery:
        from .surgery import run_surgery

        return await run_surgery(load_settings(), records, HERE / "surgery.toml", args.out, fresh=args.fresh, repeats=args.repeats)
    if not chosen:
        print("No case matches the filters.")
        return 1
    if args.rescore:
        return await rescore(args, chosen)

    settings = load_settings()
    source = "the generator"
    if args.fhir:
        records = await fhir_records(settings.fhir_base_url, sorted({case.patient for case in chosen}), anchor)
        source = settings.fhir_base_url
    sections: dict[str, str | None] = defaultdict(lambda: None)
    if not args.no_loops:
        extraction = LlmClient(replace(settings, temperature=0.0))
        try:
            extractor = PlanExtractor(extraction, settings.plan_cache, concurrency=6)
            medicines = MedicationReader(extraction, settings.plan_cache.parent / "medications", concurrency=6)
            surgery = SurgeryReader(extraction, settings.plan_cache.parent / "surgery", concurrency=6)
            for patient in sorted({case.patient for case in chosen}):
                sections[patient] = await note_sections(records[patient], extractor, medicines, surgery)
        finally:
            await extraction.close()
    started = datetime.now(timezone.utc)
    folder = args.out / f"{started:%Y%m%dT%H%M%SZ}-{re.sub(r'[^A-Za-z0-9.-]+', '-', settings.llm_model)}"
    folder.mkdir(parents=True)
    audit = CapturingAudit(folder / "audit.jsonl")
    llm = LlmClient(settings)
    grader = LlmClient(judge_settings(settings)) if args.judge else None
    baseline = load_baseline(args.baseline) if args.baseline else None
    gate = asyncio.Semaphore(args.concurrency)
    jobs = [(case, repeat) for repeat in range(args.repeats) for case in chosen]
    rows: list[dict] = []
    print(f"{len(chosen)} cases × {args.repeats} against {settings.llm_model}, writing to {folder}")

    async def one(case: Case, repeat: int) -> None:
        async with gate:
            row = await run_case(
                case, repeat, records[case.patient], sections[case.patient], llm=llm, audit=audit, max_steps=settings.max_steps
            )
            if grader and "answer" in row:
                row["judge"] = await judge(case, row, grader)
        rows.append(row)
        with (folder / "results.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
        mark = "PASS" if row["passed"] else "FAIL"
        detail = "; ".join(f"{kind}: {', '.join(items)}" for kind, items in row["failures"].items())
        verdict = f" [judge {row['judge']['verdict']}]" if "judge" in row else ""
        took = f"{row['elapsed_ms'] / 1000:5.1f} s" if "elapsed_ms" in row else "     -"
        print(f"  {mark} {took}  {case.id}{verdict}" + (f"  ({detail[:160]})" if detail else ""), flush=True)

    try:
        await asyncio.gather(*(one(case, repeat) for case, repeat in jobs))
    finally:
        await llm.close()
        if grader:
            await grader.close()

    meta = {
        "started": f"{started:%Y-%m-%d %H:%M} UTC",
        "model": settings.llm_model,
        "anchor": anchor.isoformat(),
        "seed": seed,
        "source": source,
        "loops": not args.no_loops,
        "cases": len(chosen),
        "repeats": args.repeats,
    }
    finish(folder, rows, chosen, meta, baseline)
    return 0


async def rescore(args: argparse.Namespace, chosen: list[Case]) -> int:
    """Scores the answers of an earlier run again with the current gold.toml (and judge), without asking the agent."""
    meta = json.loads((args.rescore / "summary.json").read_text(encoding="utf-8"))["meta"]
    lookup = {case.id: case for case in chosen}
    rows = [
        row
        for line in (args.rescore / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))["case"] in lookup
    ]
    grader = LlmClient(judge_settings(load_settings())) if args.judge else None
    gate = asyncio.Semaphore(args.concurrency)

    async def one(row: dict) -> None:
        row.pop("judge", None)
        if "answer" not in row:
            return
        case = lookup[row["case"]]
        row["failures"] = score(case, row["answer"], set(row["cited"]))
        row["passed"] = not row["failures"]
        if grader:
            async with gate:
                row["judge"] = await judge(case, row, grader)

    try:
        await asyncio.gather(*(one(row) for row in rows))
    finally:
        if grader:
            await grader.close()
    folder = args.out / f"{args.rescore.name}-rescored-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    folder.mkdir(parents=True)
    with (folder / "results.jsonl").open("w", encoding="utf-8") as file:
        file.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    meta |= {"cases": len({row["case"] for row in rows}), "source": f"{meta['source']}, rescored from {args.rescore.name}"}
    finish(folder, rows, chosen, meta, load_baseline(args.baseline) if args.baseline else None)
    return 0


def finish(folder: Path, rows: list[dict], cases: list[Case], meta: dict, baseline: dict | None) -> None:
    order = [case.id for case in cases]
    rows.sort(key=lambda row: (order.index(row["case"]), row["repeat"]))
    summary = summarise(rows, [case for case in cases if case.id in {row["case"] for row in rows}])
    (folder / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    text = report(summary, rows, meta, baseline)
    (folder / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text.split("\n## Failed")[0].rstrip())
    print(f"\nFull report: {folder / 'report.md'}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m evals", description="Run the ASKlepios gold question set.")
    parser.add_argument("--gold", type=Path, default=HERE / "gold.toml")
    parser.add_argument("--lint", action="store_true", help="check the gold set against the cohort and stop")
    parser.add_argument("--case", action="append", help="only cases whose id contains this (repeatable)")
    parser.add_argument("--category", action="append", choices=CATEGORIES, help="only this category (repeatable)")
    parser.add_argument("--patient", action="append", help="only this patient id (repeatable)")
    parser.add_argument("--repeats", type=int, default=1, help="run each case this many times (default 1)")
    parser.add_argument("--concurrency", type=int, default=4, help="cases in flight at once (default 4)")
    parser.add_argument("--judge", action="store_true", help="grade answers against the reference with a model")
    parser.add_argument("--baseline", type=Path, help="an earlier run folder to compare with")
    parser.add_argument("--fhir", action="store_true", help="read charts from the FHIR server instead of the generator")
    parser.add_argument("--rescore", type=Path, help="score an earlier run's answers again instead of asking the agent")
    parser.add_argument("--no-loops", action="store_true", help="leave the sections computed from notes (open loops, medications, surgical history) out of the chart index")
    parser.add_argument("--loops", action="store_true", help="check open loops against loops.toml instead of the questions")
    parser.add_argument("--meds", action="store_true", help="check medication reconciliation against meds.toml instead")
    parser.add_argument("--surgery", action="store_true", help="check surgical history against surgery.toml instead")
    parser.add_argument("--onboarding", action="store_true", help="check onboarding reviews and imports against onboarding.toml instead")
    parser.add_argument("--fresh", action="store_true", help="with --loops, --meds or --surgery: read every note again instead of using the cache")
    parser.add_argument("--out", type=Path, default=HERE / "runs")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
