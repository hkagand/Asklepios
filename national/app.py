"""A simulated national health record service, for demonstrating patient onboarding with synthetic data.

It stands in for a national system such as e-Nabız, which a hospital reaches only through an approved integration
and only with the patient's consent. It serves the synthetic International Patient Summaries written by
synthetic/generate.py (synthetic/output/national/) and nothing else. It is not e-Nabız and talks to no real system.

Access works as it should with real records: knowing a national id is not enough.

POST /consent-requests                   {"nationalId", "name", "birthDate", "requester"}: when all three match a
                                         record, a one-time code is "sent by SMS" to the patient's phone
POST /consent-requests/{id}/confirm      {"code"}: the code the patient reads out gives a token for four hours,
                                         for that patient only; three wrong codes close the request
GET  /fhir/Patient/$summary?identifier=  the patient's IPS document, with the token as a Bearer credential

GET  /demo/people                        who has a record, to try onboarding with (a demo aid; a real service has none)
GET  /demo/phone                         the simulated phones: every SMS sent, newest first
GET  /demo/access-log                    every request, granted or refused
POST /demo/reset                         forgets every request, token, message and log entry (the demo reset)

State is in memory: restarting the service forgets requests and tokens.
"""

from __future__ import annotations

import json
import os
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("NATIONAL_DATA", ROOT / "synthetic" / "output" / "national"))
NATIONAL_ID = "urn:demo:asklepios:national-id"
CODE_LIFETIME = timedelta(minutes=10)
ACCESS_LIFETIME = timedelta(hours=4)
ATTEMPTS = 3
SECTIONS = {
    "allergies": "AllergyIntolerance", "problems": "Condition", "medications": "MedicationRequest",
    "procedures": "Procedure", "results": "Observation",
}


def fold(text: str) -> str:
    """Lower case without accents or extra spaces, so "GÜLAY  kaplan" matches "Gülay Kaplan"."""
    plain = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "I"))
    return " ".join("".join(character for character in plain if not unicodedata.combining(character)).lower().split())


def now() -> datetime:
    return datetime.now(timezone.utc)


def masked(phone: str) -> str:
    """"+90 500 000 30 01" -> "+90 5•• ••• 30 01": enough for the patient to recognise, not to reuse."""
    digits = [index for index, character in enumerate(phone) if character.isdigit()]
    hidden = set(digits[3:-4])
    return "".join("•" if index in hidden else character for index, character in enumerate(phone))


class Record:
    def __init__(self, bundle: dict) -> None:
        self.bundle = bundle
        patient = next(entry["resource"] for entry in bundle["entry"] if entry["resource"]["resourceType"] == "Patient")
        self.national_id = next(item["value"] for item in patient["identifier"] if item["system"] == NATIONAL_ID)
        self.name = patient["name"][0]["text"]
        self.birth_date = patient["birthDate"]
        self.phone = next(item["value"] for item in patient.get("telecom", []) if item["system"] == "phone")
        self.gender = patient.get("gender")
        self.counts = {section: sum(entry["resource"]["resourceType"] == kind for entry in bundle["entry"]) for section, kind in SECTIONS.items()}


def load_records(folder: Path) -> dict[str, Record]:
    records = [Record(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(folder.glob("*.json"))]
    return {record.national_id: record for record in records}


class ConsentRequest(BaseModel):
    national_id: str = Field(alias="nationalId", pattern=r"^\d{11}$")
    name: str = Field(min_length=1, max_length=200)
    birth_date: str = Field(alias="birthDate", pattern=r"^\d{4}-\d{2}-\d{2}$")
    requester: str = Field(default="Demo General Hospital", max_length=200)


class Confirmation(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


app = FastAPI(title="National record service (simulated)")
app.state.records = load_records(DATA)
app.state.requests = {}  # id -> {"nationalId", "code", "expires", "attempts", "status", "requester"}
app.state.tokens = {}  # token -> {"nationalId", "expires", "requester"}
app.state.phone = []  # SMS sent, oldest first
app.state.log = []


def log(event: str, **fields: object) -> None:
    app.state.log.append({"time": now().isoformat(timespec="seconds"), "event": event, **fields})


@app.get("/health")
def health() -> dict:
    return {"service": "National record service (simulated)", "records": len(app.state.records)}


@app.post("/consent-requests", status_code=201)
def request_consent(body: ConsentRequest) -> dict:
    record = app.state.records.get(body.national_id)
    if record is None or fold(record.name) != fold(body.name) or record.birth_date != body.birth_date:
        # The same answer whether the number is unknown or the name or birth date is wrong: a caller learns nothing.
        log("consent-refused", nationalId=body.national_id, requester=body.requester, reason="no matching record")
        raise HTTPException(status_code=404, detail="No record matches this identity number, name and date of birth.")
    request_id = secrets.token_hex(8)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = now() + CODE_LIFETIME
    app.state.requests[request_id] = {
        "nationalId": record.national_id, "code": code, "expires": expires, "attempts": 0, "status": "sent",
        "requester": body.requester,
    }
    app.state.phone.append({
        "to": masked(record.phone),
        "patient": record.name,
        "time": now().isoformat(timespec="seconds"),
        "text": (
            f"{body.requester} asks to see your national health record. Code: {code}. "
            "Share it only if you agree. It expires in 10 minutes. (Simulated message)"
        ),
    })
    log("consent-requested", nationalId=record.national_id, requester=body.requester, request=request_id)
    return {"requestId": request_id, "sentTo": masked(record.phone), "expiresAt": expires.isoformat(timespec="seconds")}


@app.post("/consent-requests/{request_id}/confirm")
def confirm(request_id: str, body: Confirmation) -> dict:
    request = app.state.requests.get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="No such consent request.")
    if request["status"] != "sent":
        raise HTTPException(status_code=409, detail=f"This request is {request['status']}; start a new one.")
    if now() > request["expires"]:
        request["status"] = "expired"
        log("consent-expired", nationalId=request["nationalId"], request=request_id)
        raise HTTPException(status_code=410, detail="The code has expired; start a new request.")
    if not secrets.compare_digest(body.code, request["code"]):
        request["attempts"] += 1
        left = ATTEMPTS - request["attempts"]
        if left == 0:
            request["status"] = "closed"
        log("consent-wrong-code", nationalId=request["nationalId"], request=request_id, attemptsLeft=left)
        raise HTTPException(status_code=403, detail=f"Wrong code; {left} attempt(s) left." if left else "Wrong code; the request is closed.")
    request["status"] = "confirmed"
    token = secrets.token_urlsafe(24)
    expires = now() + ACCESS_LIFETIME
    app.state.tokens[token] = {"nationalId": request["nationalId"], "expires": expires, "requester": request["requester"]}
    log("consent-granted", nationalId=request["nationalId"], request=request_id, expiresAt=expires.isoformat(timespec="seconds"))
    return {"accessToken": token, "tokenType": "Bearer", "expiresAt": expires.isoformat(timespec="seconds"), "nationalId": request["nationalId"]}


@app.get("/fhir/Patient/$summary")
def patient_summary(identifier: str, authorization: str | None = Header(default=None)) -> dict:
    system, _, value = identifier.rpartition("|")
    if system and system != NATIONAL_ID:
        raise HTTPException(status_code=400, detail=f"Identifier system must be {NATIONAL_ID}.")
    grant = app.state.tokens.get((authorization or "").removeprefix("Bearer ").strip())
    if grant is None or now() > grant["expires"]:
        log("summary-refused", nationalId=value, reason="no valid access token")
        raise HTTPException(status_code=401, detail="A valid access token from the patient's consent is required.")
    if grant["nationalId"] != value:
        log("summary-refused", nationalId=value, reason="token is for another patient")
        raise HTTPException(status_code=403, detail="This access token is for another patient.")
    log("summary-read", nationalId=value, requester=grant["requester"])
    return app.state.records[value].bundle


@app.get("/demo/people")
def people() -> dict:
    return {"people": [
        {"nationalId": record.national_id, "name": record.name, "birthDate": record.birth_date, "gender": record.gender, "counts": record.counts}
        for record in app.state.records.values()
    ]}


@app.get("/demo/phone")
def phone() -> dict:
    return {"messages": list(reversed(app.state.phone))}


@app.get("/demo/access-log")
def access_log() -> dict:
    return {"events": list(reversed(app.state.log))}


@app.post("/demo/reset")
def reset() -> dict:
    """Back to a fresh start: no consent requests, tokens, messages or log entries. The records stay."""
    for state in (app.state.requests, app.state.tokens, app.state.phone, app.state.log):
        state.clear()
    return {"records": len(app.state.records)}
