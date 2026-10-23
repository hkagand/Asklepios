"""HTTP API for the chat panel.

POST /api/patients/{patient_id}/chat streams server-sent events:
  step    {"tool", "label"}        one per tool call, as it happens
  answer  {"blocks", "sources", ...} the verified answer
  error   {"message"}

GET /api/patients/{patient_id}/loops returns the open loops: each clinician's latest plan checked against the record.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .audit import AuditLog
from .chat import Sessions, run_turn
from .config import load_settings
from .fhir import FhirClient, FhirError, PatientNotFound
from .llm import LlmClient, LlmError
from .loops import open_loops
from .plans import PlanExtractor
from .record import Record

FHIR_ID = re.compile(r"[A-Za-z0-9\-.]{1,64}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    fhir = FhirClient(settings.fhir_base_url)
    llm = LlmClient(settings)
    extraction = LlmClient(replace(settings, temperature=0.0))
    plans = PlanExtractor(extraction, settings.plan_cache)
    app.state.settings = settings
    app.state.llm = llm
    app.state.fhir = fhir
    app.state.plans = plans
    app.state.audit = AuditLog(settings.audit_log)
    app.state.sessions = Sessions(fhir, plans)
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
    return {"model": app.state.settings.llm_model}


@app.post("/api/patients/{patient_id}/chat")
async def chat(patient_id: str, request: ChatRequest) -> StreamingResponse:
    if not FHIR_ID.fullmatch(patient_id):
        raise HTTPException(status_code=400, detail="Invalid patient id.")
    return StreamingResponse(
        _events(patient_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/patients/{patient_id}/loops")
async def loops(patient_id: str) -> dict:
    if not FHIR_ID.fullmatch(patient_id):
        raise HTTPException(status_code=400, detail="Invalid patient id.")
    state = app.state
    try:
        patient, found = await state.fhir.patient_chart(patient_id)
    except PatientNotFound as error:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} is not on the FHIR server.") from error
    except FhirError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    record = Record(patient, found)
    items, unread = await open_loops(record, state.plans)
    state.audit.write(
        session="-", patient=patient_id, event="loops", statuses=dict(Counter(item.status for item in items)), unread=unread
    )
    return {"patient": patient_id, "today": record.today.isoformat(), "loops": [item.as_json() for item in items], "unread": unread}


async def _events(patient_id: str, request: ChatRequest) -> AsyncIterator[str]:
    state = app.state
    try:
        session = await state.sessions.get(request.session_id, patient_id)
        async with session.lock:
            turn = run_turn(
                session, request.question.strip(), llm=state.llm, audit=state.audit, max_steps=state.settings.max_steps
            )
            async for event, data in turn:
                yield _sse(event, data)
    except PatientNotFound:
        yield _sse("error", {"message": f"Patient {patient_id} is not on the FHIR server."})
    except (FhirError, LlmError) as error:
        yield _sse("error", {"message": str(error)})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
