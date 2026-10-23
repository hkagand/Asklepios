"""Ask questions about a patient from the command line, without the web app.

    python -m agent.ask p-2041 "What changed since the last visit?" "Why was oxaliplatin stopped?"
    python -m agent.ask p-2041 --index
    python -m agent.ask p-2041 --tool lab_series "{\\"test\\": \\"Hb\\"}"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from . import tools
from .audit import AuditLog
from .chat import run_turn, start_session
from .config import load_settings
from .fhir import FhirClient
from .llm import LlmClient
from .record import Record

MARKS = {"ok": "  ", "plain": "  ", "check": "? ", "unsourced": "~ ", "unsupported": "x "}


def render(answer: dict) -> str:
    lines = []
    for block in answer["blocks"]:
        text = "".join(
            part["text"] if "text" in part else " " + " ".join(f"[{answer['sources'].get(ref, {}).get('label', ref)}]" for ref in part["cite"])
            for part in block["segments"]
        )
        bullet = "  " * block["level"] + ("- " if block["kind"] == "bullet" else "")
        lines.append(f"{MARKS[block['status']]}{bullet}{text}")
        lines += [f"      ! {issue}" for issue in block["issues"]]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("patient", help="Patient id, e.g. p-2041")
    parser.add_argument("questions", nargs="*", help="Questions, asked in order in one conversation")
    parser.add_argument("--index", action="store_true", help="Print the chart index the model starts from")
    parser.add_argument("--tool", nargs=2, metavar=("NAME", "JSON"), help="Run one tool and print its output")
    args = parser.parse_args()

    settings = load_settings()
    fhir = FhirClient(settings.fhir_base_url)
    try:
        patient, found = await fhir.patient_chart(args.patient)
    finally:
        await fhir.close()
    record = Record(patient, found)
    if args.index:
        print(record.index())
        return
    if args.tool:
        result = tools.run(record, *args.tool)
        print(f"[{result.label}]\n{result.text}")
        return

    llm = LlmClient(settings)
    session = start_session(f"cli-{uuid.uuid4()}", record)
    try:
        for question in args.questions:
            print(f"\n>>> {question}")
            async for event, data in run_turn(
                session, question, llm=llm, audit=AuditLog(settings.audit_log), max_steps=settings.max_steps
            ):
                if event == "step":
                    print(f"    · {data['label']}")
                else:
                    print(render(data))
                    print(f"    ({len(data['steps'])} tool calls, {data['elapsedMs'] / 1000:.1f} s)")
    finally:
        await llm.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
