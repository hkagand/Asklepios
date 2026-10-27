"""Pre-visit briefs prepared ahead of a clinic.

    python -m agent.briefs --practitioner pr-aydin [--date 2026-10-26]

A brief is ASKlepios's answer to "brief me for the visit", asked through the same conversation loop and citation
check as the chat panel, for each patient with an appointment that day. It is stored with a fingerprint of the
chart it was written from: when anything in the chart changes (a new result, a review mark), the brief shows as
outdated until it is prepared again. Without --date, the clinician's next day with appointments is used.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from .audit import AuditLog
from .chat import run_turn, sections, start_session
from .fhir import FhirClient
from .llm import LlmClient, LlmError
from .meds import MedicationReader
from .plans import PlanExtractor
from .surgery import SurgeryReader
from .record import Record, day_text, moment

BRIEF_VERSION = 1
QUESTION = "Brief me for the visit on {day} with {clinician}."
AUTHOR = "asklepios-briefs"


def fingerprint(record: Record) -> str:
    """Changes when any resource of the chart changes, and when "today" does (due dates and overdue days move)."""
    parts = sorted(
        f"{ref}@{resource.get('meta', {}).get('versionId', '')}:{resource.get('meta', {}).get('lastUpdated', '')}:{resource.get('status', '')}"
        for ref, resource in record.resources.items()
    )
    return hashlib.sha256((f"{BRIEF_VERSION}\n{record.today}\n" + "\n".join(parts)).encode()).hexdigest()[:20]


def patient_of(appointment: dict) -> str | None:
    return next(
        (
            participant["actor"]["reference"].split("/", 1)[1]
            for participant in appointment.get("participant", [])
            if participant.get("actor", {}).get("reference", "").startswith("Patient/")
        ),
        None,
    )


class Briefs:
    def __init__(
        self,
        cache_dir: Path,
        *,
        fhir: FhirClient,
        llm: LlmClient,
        plans: PlanExtractor,
        medicines: MedicationReader,
        surgery: SurgeryReader,
        audit: AuditLog,
        max_steps: int,
    ) -> None:
        self._dir = cache_dir
        self._fhir = fhir
        self._llm = llm
        self._plans = plans
        self._medicines = medicines
        self._surgery = surgery
        self._audit = audit
        self._max_steps = max_steps
        self.running: set[str] = set()

    def _path(self, patient_id: str) -> Path:
        return self._dir / f"{patient_id}.json"

    def stored(self, record: Record) -> dict | None:
        """The last brief prepared for this patient, with "current" telling whether the chart has changed since."""
        path = self._path(record.id)
        if not path.exists():
            return None
        brief = json.loads(path.read_text(encoding="utf-8"))
        return brief | {"current": brief["fingerprint"] == fingerprint(record)}

    def state(self, record: Record) -> str:
        if record.id in self.running:
            return "preparing"
        brief = self.stored(record)
        return "missing" if brief is None else "ready" if brief["current"] else "outdated"

    async def prepare(self, record: Record, appointment: dict) -> dict:
        """Asks for the brief and stores it. Raises LlmError if the model gives no answer."""
        self.running.add(record.id)
        try:
            start = moment(appointment.get("start"))
            clinician = next(
                (
                    participant["actor"].get("display", "")
                    for participant in appointment.get("participant", [])
                    if participant.get("actor", {}).get("reference", "").startswith("Practitioner/")
                ),
                "the clinician",
            )
            question = QUESTION.format(day=day_text(start.date()) if start else "the next appointment", clinician=clinician)
            session = start_session(f"brief-{record.id}", record, await sections(record, self._plans, self._medicines, self._surgery))
            answer = None
            async for event, data in run_turn(session, question, llm=self._llm, audit=self._audit, max_steps=self._max_steps, user=AUTHOR):
                if event == "answer":
                    answer = data
            if answer is None:
                raise LlmError("No answer.")
            brief = {
                "patient": record.id,
                "appointment": f"Appointment/{appointment['id']}",
                "visit": start.isoformat() if start else None,
                "question": question,
                "preparedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "fingerprint": fingerprint(record),
                "answer": answer,
            }
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(record.id).write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
            return brief
        finally:
            self.running.discard(record.id)

    async def chart(self, patient_id: str) -> Record:
        patient, found = await self._fhir.patient_chart(patient_id)
        return Record(patient, found)


async def appointments_on(fhir: FhirClient, practitioner: str, day: date) -> list[dict]:
    found = await fhir.search("Appointment", {"actor": f"Practitioner/{practitioner}", "date": day.isoformat()})
    booked = [appointment for appointment in found if appointment.get("status") in ("booked", "arrived", "fulfilled", "checked-in")]
    return sorted(booked, key=lambda appointment: appointment.get("start", ""))


async def next_clinic_day(fhir: FhirClient, practitioner: str, today: date) -> date:
    """Today if there are appointments, else the first later day that has some (today if none at all)."""
    found = await fhir.search("Appointment", {"actor": f"Practitioner/{practitioner}", "date": f"ge{today.isoformat()}", "_sort": "date"})
    days = sorted({start.date() for appointment in found if (start := moment(appointment.get("start"))) and start.date() >= today})
    return days[0] if days else today


# --------------------------------------------------------------------------- CLI

async def _main(args: argparse.Namespace) -> int:
    from .config import load_settings

    settings = load_settings()
    fhir = FhirClient(settings.fhir_base_url)
    llm = LlmClient(settings)
    extraction = LlmClient(replace(settings, temperature=0.0))
    briefs = Briefs(
        settings.plan_cache.parent / "briefs",
        fhir=fhir,
        llm=llm,
        plans=PlanExtractor(extraction, settings.plan_cache),
        medicines=MedicationReader(extraction, settings.plan_cache.parent / "medications"),
        surgery=SurgeryReader(extraction, settings.plan_cache.parent / "surgery"),
        audit=AuditLog(settings.audit_log),
        max_steps=settings.max_steps,
    )
    try:
        day = args.date or await next_clinic_day(fhir, args.practitioner, datetime.now().date())
        booked = await appointments_on(fhir, args.practitioner, day)
        print(f"{len(booked)} appointments for {args.practitioner} on {day_text(day)}")
        for appointment in booked:
            patient_id = patient_of(appointment)
            if not patient_id:
                continue
            record = await briefs.chart(patient_id)
            if not args.force and briefs.state(record) == "ready":
                print(f"  {patient_id}: brief already current")
                continue
            try:
                brief = await briefs.prepare(record, appointment)
            except LlmError as error:
                print(f"  {patient_id}: failed ({error})")
                continue
            print(f"  {patient_id}: prepared ({brief['answer']['elapsedMs'] / 1000:.1f} s)")
    finally:
        await fhir.close()
        await llm.close()
        await extraction.close()
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m agent.briefs", description="Prepare pre-visit briefs for a clinic day.")
    parser.add_argument("--practitioner", required=True, help="Practitioner id, e.g. pr-aydin")
    parser.add_argument("--date", type=date.fromisoformat, help="clinic day (default: the next day with appointments)")
    parser.add_argument("--force", action="store_true", help="prepare again even when a current brief exists")
    raise SystemExit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
