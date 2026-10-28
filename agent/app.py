"""HTTP API for the chat panel.

POST /api/patients/{patient_id}/chat streams server-sent events:
  step    {"tool", "label"}        one per tool call, as it happens
  answer  {"blocks", "sources", ...} the verified answer
  error   {"message"}

GET /api/patients/{patient_id}/loops returns the open loops: each clinician's latest plan checked against the record.
GET /api/loops/summary?patients=p-1,p-2 counts them by status for each patient, for the worklist.
GET /api/patients/{patient_id}/medications reconciles the medication orders with what the notes say (meds.py).
GET /api/patients/{patient_id}/surgery lists earlier operations from Procedure records, notes and reports (surgery.py).
GET /api/clinicians/{practitioner_id}/day?day=... a clinician's day: appointments, open loops, medications, briefs.
POST /api/clinicians/{practitioner_id}/briefs?day=... starts preparing that day's briefs (briefs.py).
GET /api/patients/{patient_id}/brief the patient's prepared brief, and whether the chart has changed since.

Marks (marks.py), the only writes:
GET  /api/patients/{patient_id}/marks                         reviews and communications that stand
POST /api/patients/{patient_id}/reviews                       {"focus": [refs], "note"}: one Task per result reviewed
POST /api/patients/{patient_id}/communications                {"about": [refs], "medium", "sent", "note"}
POST /api/patients/{patient_id}/marks/{type}/{id}/withdraw    marks one's own mark entered-in-error

Requests name the acting practitioner in the X-Practitioner header (a Practitioner id). This is the demo's stand-in
for sign-in, not authentication: it decides whose name goes on a mark and in the audit log. Marks require it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .audit import AuditLog
from .chat import Sessions, run_turn
from .config import load_settings
from .fhir import FhirClient, FhirError, PatientNotFound
from .llm import LlmClient, LlmError
from .loops import Loop, open_loops
from .marks import REVIEWABLE, Mark, Practitioner, communication, mark_of, marks_of, now_text, ours, review_task
from .briefs import Briefs, appointments_on, next_clinic_day, patient_of
from .meds import DISCREPANCIES, MedicationReader, reconcile
from .plans import PlanExtractor
from .surgery import SurgeryReader, surgical_history
from .record import Record, clinic_today

FHIR_ID = re.compile(r"[A-Za-z0-9\-.]{1,64}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    fhir = FhirClient(settings.fhir_base_url)
    llm = LlmClient(settings)
    extraction = LlmClient(replace(settings, temperature=0.0))
    plans = PlanExtractor(extraction, settings.plan_cache)
    medicines = MedicationReader(extraction, settings.plan_cache.parent / "medications")
    surgery = SurgeryReader(extraction, settings.plan_cache.parent / "surgery")
    app.state.settings = settings
    app.state.llm = llm
    app.state.fhir = fhir
    app.state.plans = plans
    app.state.medicines = medicines
    app.state.surgery = surgery
    app.state.audit = AuditLog(settings.audit_log)
    app.state.sessions = Sessions(fhir, plans, medicines, surgery)
    app.state.practitioners = {}
    app.state.briefs = Briefs(
        settings.plan_cache.parent / "briefs", fhir=fhir, llm=llm, plans=plans, medicines=medicines, surgery=surgery,
        audit=app.state.audit, max_steps=settings.max_steps,
    )
    app.state.brief_tasks = set()
    app.state.brief_gate = asyncio.Semaphore(3)
    yield
    await fhir.close()
    await llm.close()
    await extraction.close()


app = FastAPI(title="ASKlepios agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9\-]{8,64}$")
    question: str = Field(min_length=1, max_length=4000)


@app.get("/api/health")
async def health() -> dict:
    """The model, and the clinic day the agent works with; `fixedToday` when AGENT_TODAY sets it."""
    return {"model": app.state.settings.llm_model, "today": clinic_today().isoformat(), "fixedToday": "AGENT_TODAY" in os.environ}


async def practitioner_named(practitioner_id: str) -> Practitioner:
    """A practitioner on the FHIR server, by id."""
    if not FHIR_ID.fullmatch(practitioner_id):
        raise HTTPException(status_code=400, detail="Invalid practitioner id.")
    known: dict[str, Practitioner] = app.state.practitioners
    if practitioner_id not in known:
        try:
            resource = await app.state.fhir.read("Practitioner", practitioner_id)
        except PatientNotFound as error:
            raise HTTPException(status_code=400, detail=f"Practitioner {practitioner_id} is not on the FHIR server.") from error
        except FhirError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        name = (resource.get("name") or [{}])[0]
        display = name.get("text") or " ".join([*name.get("given", []), name.get("family", "")]).strip()
        known[practitioner_id] = Practitioner(practitioner_id, display or practitioner_id)
    return known[practitioner_id]


async def acting(x_practitioner: str | None = Header(default=None)) -> Practitioner | None:
    """The practitioner the panel says is using it, checked against the FHIR server; None if not given."""
    return await practitioner_named(x_practitioner) if x_practitioner else None


def required(practitioner: Practitioner | None) -> Practitioner:
    if practitioner is None:
        raise HTTPException(status_code=403, detail="Choose who is viewing (top right) before marking anything.")
    return practitioner


def checked(patient_id: str) -> str:
    if not FHIR_ID.fullmatch(patient_id):
        raise HTTPException(status_code=400, detail="Invalid patient id.")
    return patient_id


@app.post("/api/patients/{patient_id}/chat")
async def chat(patient_id: str, request: ChatRequest, practitioner: Practitioner | None = Depends(acting)) -> StreamingResponse:
    return StreamingResponse(
        _events(checked(patient_id), request, practitioner.id if practitioner else None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _record(patient_id: str) -> Record:
    try:
        patient, found = await app.state.fhir.patient_chart(patient_id)
    except PatientNotFound as error:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} is not on the FHIR server.") from error
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return Record(patient, found)


async def _loops(patient_id: str, user: str | None = None) -> tuple[Record, list[Loop], list[str]]:
    state = app.state
    record = await _record(patient_id)
    items, unread = await open_loops(record, state.plans)
    state.audit.write(
        session="-", patient=patient_id, event="loops", user=user,
        statuses=dict(Counter(item.status for item in items)), unread=unread,
    )
    return record, items, unread


@app.get("/api/patients/{patient_id}/loops")
async def loops(patient_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    record, items, unread = await _loops(checked(patient_id), practitioner.id if practitioner else None)
    return {"patient": patient_id, "today": record.today.isoformat(), "loops": [item.as_json() for item in items], "unread": unread}


class ReviewRequest(BaseModel):
    focus: list[str] = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=1000)


class CommunicationRequest(BaseModel):
    about: list[str] = Field(min_length=1, max_length=50)
    medium: Literal["in_person", "phone", "video", "letter", "portal"]
    sent: date | None = None
    note: str | None = Field(default=None, max_length=1000)


def _own_refs(record: Record, refs: list[str]) -> list[str]:
    """The refs, if every one is a result, report, order or note in this patient's record."""
    wrong = [ref for ref in refs if ref not in record.resources or ref.split("/")[0] not in REVIEWABLE]
    if wrong:
        raise HTTPException(status_code=400, detail=f"Not a result, report, order or note of this patient: {', '.join(wrong)}")
    return list(dict.fromkeys(refs))


async def _write(resource: dict) -> Mark:
    try:
        created = await app.state.fhir.create(resource)
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    mark = mark_of(created)
    if mark is None:
        raise HTTPException(status_code=502, detail="The FHIR server did not return the mark it stored.")
    return mark


@app.get("/api/patients/{patient_id}/marks")
async def marks(patient_id: str) -> dict:
    record = await _record(checked(patient_id))
    return {"marks": [mark.as_json() for mark in marks_of(record)]}


@app.post("/api/patients/{patient_id}/reviews")
async def review(patient_id: str, request: ReviewRequest, practitioner: Practitioner | None = Depends(acting)) -> dict:
    by = required(practitioner)
    record = await _record(checked(patient_id))
    focus = _own_refs(record, request.focus)
    created = [await _write(review_task(record, ref, by, request.note)) for ref in focus]
    app.state.audit.write(session="-", patient=patient_id, event="review", user=by.id, focus=focus, marks=[mark.id for mark in created])
    return {"marks": [mark.as_json() for mark in created]}


@app.post("/api/patients/{patient_id}/communications")
async def communicate(patient_id: str, request: CommunicationRequest, practitioner: Practitioner | None = Depends(acting)) -> dict:
    by = required(practitioner)
    record = await _record(checked(patient_id))
    about = _own_refs(record, request.about)
    if request.sent and request.sent > record.today:
        raise HTTPException(status_code=400, detail="A communication cannot be dated in the future.")
    mark = await _write(communication(record, about, by, request.medium, request.sent, request.note))
    app.state.audit.write(
        session="-", patient=patient_id, event="communication", user=by.id, about=about, medium=request.medium, mark=mark.id
    )
    return {"marks": [mark.as_json()]}


@app.post("/api/patients/{patient_id}/marks/{kind}/{mark_id}/withdraw")
async def withdraw(patient_id: str, kind: Literal["Task", "Communication"], mark_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    by = required(practitioner)
    checked(patient_id)
    if not FHIR_ID.fullmatch(mark_id):
        raise HTTPException(status_code=400, detail="Invalid mark id.")
    try:
        resource = await app.state.fhir.read(kind, mark_id)
    except PatientNotFound as error:
        raise HTTPException(status_code=404, detail=f"{kind}/{mark_id} was not found.") from error
    patient = (resource.get("for") or resource.get("subject") or {}).get("reference")
    owner = (resource.get("owner") or resource.get("sender") or {}).get("reference")
    if not ours(resource) or patient != f"Patient/{patient_id}":
        raise HTTPException(status_code=404, detail=f"{kind}/{mark_id} is not an Asklepios mark on this patient.")
    if owner != f"Practitioner/{by.id}":
        raise HTTPException(status_code=403, detail="Only the clinician who made a mark can withdraw it.")
    if resource.get("status") == "entered-in-error":
        return {"withdrawn": f"{kind}/{mark_id}"}
    resource["status"] = "entered-in-error"
    resource.setdefault("note", []).append({"text": f"Withdrawn by {by.name}", "authorReference": by.reference, "time": now_text()})
    try:
        await app.state.fhir.update(resource)
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.audit.write(session="-", patient=patient_id, event="withdraw", user=by.id, mark=f"{kind}/{mark_id}")
    return {"withdrawn": f"{kind}/{mark_id}"}


@app.get("/api/patients/{patient_id}/medications")
async def medications(patient_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    record, items, _ = await _loops(checked(patient_id), practitioner.id if practitioner else None)
    picture = await reconcile(record, app.state.medicines, items)
    app.state.audit.write(
        session="-", patient=patient_id, event="medications", user=practitioner.id if practitioner else None,
        findings=dict(Counter(finding["kind"] for drug in picture["drugs"] for finding in drug["findings"])),
    )
    return picture


@app.get("/api/patients/{patient_id}/surgery")
async def surgery(patient_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    record = await _record(checked(patient_id))
    try:
        history = await surgical_history(record, app.state.surgery)
    except LlmError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.audit.write(
        session="-", patient=patient_id, event="surgery", user=practitioner.id if practitioner else None,
        operations=len(history["operations"]), unread=history["unread"],
    )
    return history


@app.get("/api/clinicians/{practitioner_id}/day")
async def clinic_day(practitioner_id: str, day: date | None = None) -> dict:
    """A clinician's appointments for a day (default: the next day with any), with each patient's open loops,
    medication discrepancies and brief, and totals for the day."""
    clinician = await practitioner_named(practitioner_id)
    state = app.state
    today = clinic_today()
    try:
        day = day or await next_clinic_day(state.fhir, clinician.id, today)
        booked = await appointments_on(state.fhir, clinician.id, day)
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    gate = asyncio.Semaphore(5)

    async def row(appointment: dict) -> dict | None:
        patient_id = patient_of(appointment)
        if not patient_id:
            return None
        async with gate:
            record, items, _ = await _loops(patient_id)
            picture = await reconcile(record, state.medicines, items)
        brief = state.briefs.stored(record)
        discrepancies = sum(
            finding["kind"] in DISCREPANCIES for drug in picture["drugs"] for finding in drug["findings"]
        ) + len(picture["unlisted"])
        return {
            "patient": patient_id,
            "name": record.patient_line().split(",")[0],
            "mrn": next((item.get("value") for item in record.patient.get("identifier", [])), None),
            "appointment": {"ref": f"Appointment/{appointment['id']}", "start": appointment.get("start"), "description": appointment.get("description")},
            "loops": dict(Counter(item.status for item in items)),
            "medications": discrepancies,
            "brief": {"state": state.briefs.state(record), "preparedAt": brief["preparedAt"] if brief else None},
        }

    rows = [item for item in await asyncio.gather(*(row(appointment) for appointment in booked)) if item]
    total = Counter()
    for item in rows:
        total.update(item["loops"])
    return {
        "clinician": {"id": clinician.id, "name": clinician.name},
        "day": day.isoformat(),
        "today": today.isoformat(),
        "totals": {
            "visits": len(rows),
            "toReview": total["to_review"],
            "followUps": sum(total[status] for status in ("missing", "dose_mismatch", "overdue", "not_ordered", "no_trace", "to_inform")),
            "medications": sum(item["medications"] for item in rows),
            "briefsReady": sum(item["brief"]["state"] == "ready" for item in rows),
        },
        "patients": rows,
    }


@app.post("/api/clinicians/{practitioner_id}/briefs")
async def prepare_briefs(practitioner_id: str, day: date | None = None, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Starts preparing the briefs of a clinic day in the background; the day view shows them as they finish."""
    clinician = await practitioner_named(practitioner_id)
    state = app.state
    day = day or await next_clinic_day(state.fhir, clinician.id, clinic_today())
    booked = await appointments_on(state.fhir, clinician.id, day)
    started = []
    for appointment in booked:
        patient_id = patient_of(appointment)
        if not patient_id or patient_id in state.briefs.running:
            continue
        record = await _record(patient_id)
        if state.briefs.state(record) == "ready":
            continue
        state.briefs.running.add(patient_id)
        started.append(patient_id)
        task = asyncio.create_task(_prepare(record, appointment))
        state.brief_tasks.add(task)
        task.add_done_callback(state.brief_tasks.discard)
    state.audit.write(
        session="-", patient="-", event="prepare_briefs", user=practitioner.id if practitioner else None,
        clinician=clinician.id, day=day.isoformat(), patients=started,
    )
    return {"day": day.isoformat(), "started": started}


async def _prepare(record: Record, appointment: dict) -> None:
    async with app.state.brief_gate:
        try:
            await app.state.briefs.prepare(record, appointment)
        except (LlmError, FhirError):
            app.state.briefs.running.discard(record.id)


@app.get("/api/patients/{patient_id}/brief")
async def patient_brief(patient_id: str) -> dict:
    record = await _record(checked(patient_id))
    brief = app.state.briefs.stored(record)
    return {"state": app.state.briefs.state(record), "brief": brief}


@app.get("/api/loops/summary")
async def loop_summary(patients: str) -> dict:
    ids = [patient for patient in patients.split(",") if patient]
    if not ids or len(ids) > 100 or not all(FHIR_ID.fullmatch(patient) for patient in ids):
        raise HTTPException(status_code=400, detail="Give up to 100 patient ids, separated by commas.")
    gate = asyncio.Semaphore(5)

    async def count(patient_id: str) -> dict:
        async with gate:
            try:
                _, items, unread = await _loops(patient_id)
            except HTTPException as error:
                return {"error": error.detail}
        return {"statuses": dict(Counter(item.status for item in items)), "unread": len(unread)}

    return {"patients": dict(zip(ids, await asyncio.gather(*(count(patient) for patient in ids))))}


async def _events(patient_id: str, request: ChatRequest, user: str | None) -> AsyncIterator[str]:
    state = app.state
    try:
        session = await state.sessions.get(request.session_id, patient_id)
        async with session.lock:
            turn = run_turn(
                session, request.question.strip(), llm=state.llm, audit=state.audit, max_steps=state.settings.max_steps,
                user=user,
            )
            async for event, data in turn:
                yield _sse(event, data)
    except PatientNotFound:
        yield _sse("error", {"message": f"Patient {patient_id} is not on the FHIR server."})
    except (FhirError, LlmError) as error:
        yield _sse("error", {"message": str(error)})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
