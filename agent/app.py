"""HTTP API for the chat panel.

POST /api/patients/{patient_id}/chat streams server-sent events:
  step    {"tool", "label"}        one per tool call, as it happens
  answer  {"blocks", "sources", ...} the verified answer
  error   {"message"}

GET /api/patients/{patient_id}/loops returns the open loops: each clinician's latest plan checked against the record.
GET /api/loops/summary?patients=p-1,p-2 counts them by status for each patient, for the worklist.
GET /api/patients/{patient_id}/medications reconciles the medication orders with what the notes say (meds.py).
GET /api/patients/{patient_id}/surgery lists earlier operations from Procedure records, notes and reports (surgery.py).

Visits (visits.py), for the acting practitioner:
POST /api/patients/{patient_id}/visits             starts a visit (an Encounter in progress) with its agenda
GET  /api/patients/{patient_id}/visit              the visit in progress, if any
POST /api/visits/{visit_id}/jottings               {"text"}; PUT and DELETE /api/visits/{visit_id}/jottings/{id}
POST /api/visits/{visit_id}/agenda/{item_id}       {"done"}
POST /api/visits/{visit_id}/draft                  drafts the note from the jottings, checked
POST /api/visits/{visit_id}/sign                   {"subjective", "objective", "assessment", "plan"}: signs it
POST /api/visits/{visit_id}/cancel                 closes the visit without a note
GET  /api/visits/{visit_id}/considerations         the clinical model's latest considerations (experimental; off
                                                   unless CLINICAL_LLM_MODEL is set): remade in the background after
                                                   each change to the jottings. POST makes them now and waits.
POST /api/visits/{visit_id}/considerations/feedback  {"index", "text", "useful"}: the clinician's verdict on one

Onboarding from the national record service (simulated; onboard.py), all for the acting practitioner:
POST /api/onboarding/consent                       {"nationalId", "name", "birthDate"}: the patient is texted a code
POST /api/onboarding/consent/{request_id}/confirm  {"code"}: reads the summary; returns the items for review
GET  /api/onboarding/{onboarding_id}               the review again
POST /api/onboarding/{onboarding_id}/accept        {"decisions": [{"key", "import", "taking", "dose", "current"}]}
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
import secrets
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
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
from .onboard import (
    NATIONAL_ID,
    Decision,
    ImportRefused,
    NationalClient,
    NationalError,
    import_transaction,
    new_patient_id,
    patient_of,
    review_items,
)
from .onboard import SERVICE as ONBOARDING_SOURCE
from .plans import PlanExtractor
from .surgery import SurgeryReader, surgical_history
from .considerations import consider, signature
from .jottings import review as review_jotting
from .notes import draft as draft_visit_note
from .notes import sign_transaction, specialty_of
from .visits import Visit, VisitStore, new_visit_id, todays_appointment
from .visits import agenda as visit_agenda
from .visits import encounter as visit_encounter
from .record import Record, clinic_today, ref_of

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
    app.state.national = NationalClient(settings.national_base_url)
    app.state.onboardings = {}
    app.state.visits = VisitStore(settings.plan_cache.parent / "visits")
    app.state.extraction = extraction
    # The second, clinical model (considerations.py), when one is configured.
    app.state.clinical = LlmClient(settings.clinical) if settings.clinical else None
    app.state.considering = {}  # visit id -> the task making its considerations
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
    await app.state.national.close()
    await fhir.close()
    await llm.close()
    await extraction.close()
    if app.state.clinical:
        await app.state.clinical.close()


app = FastAPI(title="ASKlepios agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9\-]{8,64}$")
    question: str = Field(min_length=1, max_length=4000)


@app.get("/api/health")
async def health() -> dict:
    """The model, the clinical model if one is configured, and the clinic day the agent works with; `fixedToday` when
    AGENT_TODAY sets it."""
    clinical = app.state.clinical.model if app.state.clinical else None
    return {"model": app.state.settings.llm_model, "clinicalModel": clinical, "today": clinic_today().isoformat(), "fixedToday": "AGENT_TODAY" in os.environ}


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

# ------------------------------------------------------------------- onboarding

class ConsentBody(BaseModel):
    national_id: str = Field(alias="nationalId", pattern=r"^\d{11}$")
    name: str = Field(min_length=1, max_length=200)
    birth_date: date = Field(alias="birthDate")


class CodeBody(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class DecisionBody(BaseModel):
    key: str = Field(max_length=200)
    import_it: bool = Field(alias="import")
    taking: Literal["yes", "no", "different"] | None = None
    dose: str | None = Field(default=None, max_length=200)
    current: bool | None = None


class AcceptBody(BaseModel):
    decisions: list[DecisionBody] = Field(min_length=1, max_length=300)


def _onboarding_view(session: dict) -> dict:
    national = patient_of(session["bundle"])
    return {
        "onboarding": session["id"],
        "patient": {
            "name": (national.get("name") or [{}])[0].get("text"),
            "birthDate": national.get("birthDate"),
            "gender": national.get("gender"),
            "nationalId": session["nationalId"],
            "existing": session["existing"],
            "id": session["patientId"],
        },
        "source": {"service": ONBOARDING_SOURCE, "summaryDate": session["bundle"].get("timestamp")},
        "expiresAt": session["expiresAt"],
        "items": [item.as_json() for item in session["items"]],
        "imported": session.get("imported"),
    }


def _national_error(error: NationalError) -> HTTPException:
    return HTTPException(status_code=error.status if error.status < 500 else 502, detail=error.detail)


@app.post("/api/onboarding/consent")
async def onboarding_consent(body: ConsentBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Asks the national record service to text the patient a code; nothing is read before the patient gives it."""
    clinician = required(practitioner)
    try:
        sent = await app.state.national.request_consent(
            body.national_id, body.name, body.birth_date.isoformat(), f"{clinician.name}, Demo General Hospital"
        )
    except NationalError as error:
        app.state.audit.write(session="-", patient="-", event="onboarding-consent-refused", user=clinician.id, status=error.status)
        raise _national_error(error) from error
    app.state.audit.write(session="-", patient="-", event="onboarding-consent-requested", user=clinician.id, request=sent["requestId"])
    return sent


@app.post("/api/onboarding/consent/{request_id}/confirm")
async def onboarding_confirm(request_id: str, body: CodeBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """With the patient's code: reads their national summary and lists every item for review against our chart."""
    clinician = required(practitioner)
    state = app.state
    if not FHIR_ID.fullmatch(request_id):
        raise HTTPException(status_code=400, detail="Invalid request id.")
    try:
        grant = await state.national.confirm(request_id, body.code)
        bundle = await state.national.summary(grant["nationalId"], grant["accessToken"])
    except NationalError as error:
        state.audit.write(session="-", patient="-", event="onboarding-code-refused", user=clinician.id, status=error.status)
        raise _national_error(error) from error
    national_id = grant["nationalId"]
    try:
        found = await state.fhir.search("Patient", {"identifier": f"{NATIONAL_ID}|{national_id}"})
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    record, history = None, None
    if found:
        record = await _record(found[0]["id"])
        history = await surgical_history(record, state.surgery)
    items = review_items(bundle, record, history, clinic_today())
    session = {
        "id": secrets.token_hex(8),
        "nationalId": national_id,
        "consent": request_id,
        "bundle": bundle,
        "existing": bool(found),
        "patientId": found[0]["id"] if found else new_patient_id(national_id),
        "items": items,
        "expiresAt": grant["expiresAt"],
        "by": clinician.id,
    }
    state.onboardings[session["id"]] = session
    state.audit.write(
        session="-", patient=session["patientId"], event="onboarding-summary-read", user=clinician.id,
        onboarding=session["id"], existing=session["existing"], statuses=dict(Counter(item.status for item in items)),
    )
    return _onboarding_view(session)


def _onboarding(onboarding_id: str) -> dict:
    session = app.state.onboardings.get(onboarding_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No such onboarding; request consent again.")
    if datetime.fromisoformat(session["expiresAt"]) < datetime.now(timezone.utc):
        del app.state.onboardings[onboarding_id]
        raise HTTPException(status_code=410, detail="The patient's consent has expired; request it again.")
    return session


@app.get("/api/onboarding/{onboarding_id}")
async def onboarding_review(onboarding_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    required(practitioner)
    return _onboarding_view(_onboarding(onboarding_id))


@app.post("/api/onboarding/{onboarding_id}/accept")
async def onboarding_accept(onboarding_id: str, body: AcceptBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Writes what the clinician accepted, with a Provenance; nothing already in the chart is changed."""
    clinician = required(practitioner)
    session = _onboarding(onboarding_id)
    decisions = [
        Decision(item.key, item.import_it, item.taking, item.dose.strip() if item.dose else None, item.current)
        for item in body.decisions
    ]
    try:
        transaction = import_transaction(
            session["bundle"], session["items"], decisions, patient_id=session["patientId"], existing=session["existing"],
            practitioner=clinician, consent=session["consent"], onboarding=session["id"],
        )
    except ImportRefused as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        await app.state.fhir.transaction(transaction)
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    written = [f"{entry['resource']['resourceType']}/{entry['resource']['id']}" for entry in transaction["entry"]]
    session["existing"] = True
    session["imported"] = written
    app.state.audit.write(
        session="-", patient=session["patientId"], event="onboarding-imported", user=clinician.id, onboarding=session["id"],
        written=written,
    )
    return {"patient": session["patientId"], "written": written[:-1], "provenance": written[-1]}

# ------------------------------------------------------------------- visits

class StartVisitBody(BaseModel):
    appointment: str | None = Field(default=None, pattern=r"^Appointment/[A-Za-z0-9\-.]{1,64}$")


class JottingBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TickBody(BaseModel):
    done: bool


def _visit(visit_id: str) -> Visit:
    if not FHIR_ID.fullmatch(visit_id):
        raise HTTPException(status_code=400, detail="Invalid visit id.")
    visit = app.state.visits.get(visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="No such visit.")
    return visit


def _open_visit(visit_id: str) -> Visit:
    visit = _visit(visit_id)
    if visit.status != "open":
        raise HTTPException(status_code=409, detail=f"This visit is {visit.status}.")
    return visit


@app.post("/api/patients/{patient_id}/visits")
async def start_visit(patient_id: str, body: StartVisitBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Starts a visit (an Encounter in progress) with its agenda from the record, or returns the one already open."""
    clinician = required(practitioner)
    state = app.state
    current = state.visits.open_for(checked(patient_id))
    if current is not None:
        return current.as_json()
    record, items, _ = await _loops(patient_id, clinician.id)
    picture = await reconcile(record, state.medicines, items)
    appointment = None
    if body.appointment:
        appointment = record.resources.get(body.appointment)
        if appointment is None:
            raise HTTPException(status_code=404, detail=f"{body.appointment} is not this patient's appointment.")
    else:
        appointment = todays_appointment(record)
    visit = Visit(
        id=new_visit_id(), patient=patient_id, practitioner=clinician.id, practitioner_name=clinician.name,
        started=now_text(), appointment=ref_of(appointment) if appointment else None,
        reason=(appointment or {}).get("description"), agenda=visit_agenda(record, items, picture, appointment),
    )
    try:
        await state.fhir.update(visit_encounter(record, visit, clinician))
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    state.visits.save(visit)
    state.audit.write(session="-", patient=patient_id, event="visit-started", user=clinician.id, visit=visit.id, agenda=len(visit.agenda))
    return visit.as_json()


@app.get("/api/patients/{patient_id}/visit")
async def current_visit(patient_id: str) -> dict:
    """The patient's visit in progress, or {"visit": null}."""
    visit = app.state.visits.open_for(checked(patient_id))
    return {"visit": visit.as_json() if visit else None}


@app.get("/api/visits/{visit_id}")
async def get_visit(visit_id: str) -> dict:
    return _visit(visit_id).as_json()


async def _review(visit_id: str, jotting_id: str) -> dict:
    """Reviews one jotting (jottings.py) outside the lock, then keeps the review if the jotting is unchanged."""
    store = app.state.visits
    visit = _open_visit(visit_id)
    jotting = next(item for item in visit.jottings if item.id == jotting_id)
    earlier = [item.text for item in visit.jottings if item.id != jotting_id]
    agenda = [{"id": item.id, "kind": item.kind, "text": item.text} for item in visit.agenda]
    record = await _record(visit.patient)
    result = await review_jotting(app.state.extraction, record, agenda, earlier, jotting.text)
    async with store.lock(visit_id):
        visit = _open_visit(visit_id)
        visit.apply_review(jotting_id, jotting.text, result)
        store.save(visit)
    return visit.as_json()


async def _consider(visit_id: str, user: str) -> dict:
    """The clinical model's considerations for the visit as it stands, kept only if the jottings have not changed
    while the model worked (a newer run is on its way then)."""
    visit = _open_visit(visit_id)
    record = await _record(visit.patient)
    result = await consider(app.state.clinical, record, visit)
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        if signature(visit) == result["jottings"]:
            visit.considerations = result
            app.state.visits.save(visit)
    app.state.audit.write(
        session="-", patient=visit.patient, event="visit-considerations", user=user, visit=visit_id, model=result["model"],
        status=result["status"], items=len(result.get("items", [])), dropped=len(result.get("dropped", [])), seconds=result.get("seconds"),
    )
    return result


async def _consider_in_background(visit_id: str, user: str) -> None:
    try:
        await _consider(visit_id, user)
    except HTTPException:
        pass  # the visit was signed or cancelled meanwhile


def _stop_considering(visit_id: str) -> None:
    if task := app.state.considering.pop(visit_id, None):
        task.cancel()


def _start_considering(visit_id: str, user: str) -> None:
    """Makes the considerations again in the background, cancelling a run still working on older jottings."""
    if app.state.clinical is None:
        return
    _stop_considering(visit_id)
    task = asyncio.create_task(_consider_in_background(visit_id, user))
    app.state.considering[visit_id] = task
    task.add_done_callback(lambda done: app.state.considering.pop(visit_id) if app.state.considering.get(visit_id) is done else None)


def _considerations(visit: Visit) -> dict:
    current = visit.considerations is not None and visit.considerations.get("jottings") == signature(visit)
    return {
        "enabled": app.state.clinical is not None,
        "model": app.state.clinical.model if app.state.clinical else None,
        "running": visit.id in app.state.considering,
        "current": current,
        "considerations": visit.considerations,
    }


@app.get("/api/visits/{visit_id}/considerations")
async def get_considerations(visit_id: str) -> dict:
    """The latest considerations; `current` is false while they were made from earlier jottings."""
    return _considerations(_visit(visit_id))


@app.post("/api/visits/{visit_id}/considerations")
async def make_considerations(visit_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Makes the considerations now from the jottings as they stand, and waits for them."""
    clinician = required(practitioner)
    if app.state.clinical is None:
        raise HTTPException(status_code=409, detail="No clinical model is configured (CLINICAL_LLM_BASE_URL and CLINICAL_LLM_MODEL).")
    if not _open_visit(visit_id).jottings:
        raise HTTPException(status_code=422, detail="Add jottings first: the considerations follow from them.")
    _stop_considering(visit_id)
    await _consider(visit_id, clinician.id)
    return _considerations(_visit(visit_id))


class FeedbackBody(BaseModel):
    index: int = Field(ge=0, lt=20)
    text: str = Field(min_length=1, max_length=2000)
    useful: bool


@app.post("/api/visits/{visit_id}/considerations/feedback")
async def rate_consideration(visit_id: str, body: FeedbackBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """The clinician's verdict on one consideration, kept with it and in the audit log, to judge the clinical model."""
    clinician = required(practitioner)
    async with app.state.visits.lock(visit_id):
        visit = _visit(visit_id)
        items = (visit.considerations or {}).get("items") or []
        if body.index >= len(items) or items[body.index]["text"] != body.text:
            raise HTTPException(status_code=409, detail="These considerations have changed; rate the ones shown now.")
        item = items[body.index]
        item["feedback"] = "useful" if body.useful else "not-useful"
        app.state.visits.save(visit)
    app.state.audit.write(
        session="-", patient=visit.patient, event="visit-consideration-rated", user=clinician.id, visit=visit_id,
        model=visit.considerations["model"], kind=item["kind"], useful=body.useful, text=item["text"],
    )
    return _considerations(visit)


@app.post("/api/visits/{visit_id}/jottings")
async def add_jotting(visit_id: str, body: JottingBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Adds a jotting and returns the visit once the jotting is reviewed (sections, links, gaps, alerts, ticks); the
    considerations follow in the background."""
    clinician = required(practitioner)
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        jotting = visit.jot(body.text.strip(), clinician.id)
        app.state.visits.save(visit)
    app.state.audit.write(session="-", patient=visit.patient, event="visit-jotting", user=clinician.id, visit=visit.id, jotting=jotting.id)
    reviewed = await _review(visit_id, jotting.id)
    _start_considering(visit_id, clinician.id)
    return reviewed


@app.put("/api/visits/{visit_id}/jottings/{jotting_id}")
async def edit_jotting(visit_id: str, jotting_id: str, body: JottingBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    clinician = required(practitioner)
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        jotting = next((item for item in visit.jottings if item.id == jotting_id), None)
        if jotting is None:
            raise HTTPException(status_code=404, detail="No such jotting.")
        jotting.text, jotting.review = body.text.strip(), {"status": "pending"}
        # Ticks this jotting made are made again from its new reading.
        for item in visit.agenda:
            if item.done_by == jotting_id:
                item.done, item.done_by = False, None
        app.state.visits.save(visit)
    app.state.audit.write(session="-", patient=visit.patient, event="visit-jotting-edited", user=clinician.id, visit=visit.id, jotting=jotting_id)
    reviewed = await _review(visit_id, jotting_id)
    _start_considering(visit_id, clinician.id)
    return reviewed


@app.delete("/api/visits/{visit_id}/jottings/{jotting_id}")
async def delete_jotting(visit_id: str, jotting_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    clinician = required(practitioner)
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        if not any(item.id == jotting_id for item in visit.jottings):
            raise HTTPException(status_code=404, detail="No such jotting.")
        visit.jottings = [item for item in visit.jottings if item.id != jotting_id]
        for item in visit.agenda:
            if item.done_by == jotting_id:
                item.done, item.done_by = False, None
        if not visit.jottings:
            visit.considerations = None
        app.state.visits.save(visit)
    app.state.audit.write(session="-", patient=visit.patient, event="visit-jotting-deleted", user=clinician.id, visit=visit.id, jotting=jotting_id)
    if visit.jottings:
        _start_considering(visit_id, clinician.id)
    else:
        _stop_considering(visit_id)
    return visit.as_json()


@app.post("/api/visits/{visit_id}/agenda/{item_id}")
async def tick_agenda(visit_id: str, item_id: str, body: TickBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    required(practitioner)
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        item = next((entry for entry in visit.agenda if entry.id == item_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="No such agenda item.")
        item.done, item.done_by = body.done, "clinician" if body.done else None
        app.state.visits.save(visit)
    return visit.as_json()


class SignBody(BaseModel):
    subjective: str = Field(default="", max_length=8000)
    objective: str = Field(default="", max_length=8000)
    assessment: str = Field(default="", max_length=8000)
    plan: str = Field(default="", max_length=8000)


@app.post("/api/visits/{visit_id}/draft")
async def draft_note(visit_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Drafts the note from the jottings and checks it (notes.py); the clinician edits it before signing."""
    clinician = required(practitioner)
    visit = _open_visit(visit_id)
    if not visit.jottings:
        raise HTTPException(status_code=422, detail="Add jottings first: the note is drafted from them.")
    record = await _record(visit.patient)
    try:
        drafted = await draft_visit_note(app.state.extraction, record, visit)
    except LlmError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        visit.draft = drafted | {"jottings": [item.id for item in visit.jottings]}
        app.state.visits.save(visit)
    issues = sum(len(item["issues"]) > 0 for items in drafted["sections"].values() for item in items)
    app.state.audit.write(session="-", patient=visit.patient, event="visit-note-drafted", user=clinician.id, visit=visit.id,
                          flagged=issues, unused=drafted["unused"])
    return visit.as_json()


@app.post("/api/visits/{visit_id}/sign")
async def sign_note(visit_id: str, body: SignBody, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Signs the note as edited: a DocumentReference by the clinician, the Encounter finished, and a Provenance."""
    clinician = required(practitioner)
    sections = {"subjective": body.subjective, "objective": body.objective, "assessment": body.assessment, "plan": body.plan}
    if not any(text.strip() for text in sections.values()):
        raise HTTPException(status_code=422, detail="The note is empty.")
    record = await _record(_open_visit(visit_id).patient)
    try:
        specialty = specialty_of(await app.state.fhir.read("Practitioner", clinician.id))
    except FhirError:
        specialty = ""
    async with app.state.visits.lock(visit_id):
        visit = _open_visit(visit_id)
        transaction, note = sign_transaction(record, visit, clinician, specialty, sections)
        try:
            await app.state.fhir.transaction(transaction)
        except FhirError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        visit.note = note
        app.state.visits.save(visit)
    _stop_considering(visit_id)
    app.state.audit.write(session="-", patient=visit.patient, event="visit-note-signed", user=clinician.id, visit=visit.id, note=note)
    return visit.as_json()


@app.post("/api/visits/{visit_id}/cancel")
async def cancel_visit(visit_id: str, practitioner: Practitioner | None = Depends(acting)) -> dict:
    """Closes a visit without a note: the Encounter is marked cancelled, nothing else is written."""
    clinician = required(practitioner)
    visit = _open_visit(visit_id)
    visit.status = "cancelled"
    record = await _record(visit.patient)
    try:
        await app.state.fhir.update(visit_encounter(record, visit, clinician))
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    app.state.visits.save(visit)
    _stop_considering(visit_id)
    app.state.audit.write(session="-", patient=visit.patient, event="visit-cancelled", user=clinician.id, visit=visit.id)
    return visit.as_json()


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
