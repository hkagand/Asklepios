"""Builds one patient's FHIR R4 resources in chronological order.

Every value a note quotes is read back from results already stored on the
chart, so notes and structured data cannot disagree.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from catalog import ANALYTES, ATC, CLINICIANS, ICD10, LOINC, PANELS, SNOMED, UCUM, VITALS, Clinician

TZ = timezone(timedelta(hours=3))
ORGANIZATION_ID = "org-demo-hospital"
ORGANIZATION_NAME = "Demo General Hospital"
MRN_SYSTEM = "urn:demo:asklepios:mrn"

# HL7 "test health data" label: every resource is marked as synthetic.
SYNTHETIC_META = {
    "security": [
        {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
            "code": "HTEST",
            "display": "test health data",
        }
    ]
}

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

NOTE_TYPES = {
    "progress": ("11506-3", "Progress note"),
    "consult": ("11488-4", "Consult note"),
    "discharge": ("18842-5", "Discharge summary"),
}

REPORT_CATEGORIES = {
    "imaging": ("RAD", "Radiology"),
    "echo": ("CUS", "Cardiac Ultrasound"),
    "pathology": ("SP", "Surgical Pathology"),
    "molecular": ("GE", "Genetics"),
    "endoscopy": ("OTH", "Other"),
}

ORDER_CATEGORIES = {
    "laboratory": ("108252007", "Laboratory procedure"),
    "imaging": ("363679005", "Imaging"),
    "referral": ("3457005", "Patient referral"),
    "procedure": ("103693007", "Diagnostic procedure"),
}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def instant(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def day_text(moment: date | datetime) -> str:
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def workday(day: date, *, forward: bool) -> date:
    step = timedelta(days=1 if forward else -1)
    while day.weekday() >= 5:
        day += step
    return day


def add_workdays(day: date, count: int) -> date:
    day = workday(day, forward=True)
    while count > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def egfr_ckd_epi_2021(creatinine: float, age: int, female: bool) -> float:
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    ratio = creatinine / kappa
    value = 142 * min(ratio, 1) ** alpha * max(ratio, 1) ** -1.200 * 0.9938**age
    return value * 1.012 if female else value


def number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _round(value: float, decimals: int) -> float | int:
    return int(round(value)) if decimals == 0 else round(value, decimals)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _ref(resource: dict, display: str | None = None) -> dict:
    reference = {"reference": f"{resource['resourceType']}/{resource['id']}"}
    if display:
        reference["display"] = display
    return reference


def clinician_ref(clinician: Clinician) -> dict:
    return {"reference": f"Practitioner/{clinician.id}", "display": clinician.display}


def _quantity(value: float, unit: str, ucum: str) -> dict:
    return {"value": value, "unit": unit, "system": UCUM, "code": ucum}


def _range_text(low: float | None, high: float | None, decimals: int, unit: str) -> str:
    if low is not None and high is not None:
        return f"{number(low, decimals)}–{number(high, decimals)} {unit}"
    if high is not None:
        return f"< {number(high, decimals)} {unit}"
    return f"≥ {number(low, decimals)} {unit}"


def shared_resources() -> list[dict]:
    organization = {
        "resourceType": "Organization",
        "id": ORGANIZATION_ID,
        "meta": SYNTHETIC_META,
        "active": True,
        "type": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                        "code": "prov",
                        "display": "Healthcare Provider",
                    }
                ]
            }
        ],
        "name": ORGANIZATION_NAME,
    }
    practitioners = [
        {
            "resourceType": "Practitioner",
            "id": c.id,
            "meta": SYNTHETIC_META,
            "active": True,
            "name": [{"family": c.family, "given": [c.given], "prefix": ["Dr."], "text": c.display}],
            "qualification": [{"code": {"text": c.specialty}}],
        }
        for c in CLINICIANS.values()
    ]
    return [organization, *practitioners]


def transaction(resources: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": resource,
                "request": {"method": "PUT", "url": f"{resource['resourceType']}/{resource['id']}"},
            }
            for resource in resources
        ],
    }


class PatientChart:
    def __init__(
        self,
        *,
        number: int,
        given: str,
        family: str,
        gender: str,
        birth_date: date,
        city: str,
        gp: Clinician,
    ) -> None:
        self.pid = f"p-{number}"
        self.mrn = f"P-{number}"
        self.given = given
        self.family = family
        self.gender = gender
        self.birth_date = birth_date
        self.gp = gp
        self.height_cm: float | None = None
        self.resources: list[dict] = []
        self._counters: dict[str, int] = defaultdict(int)
        self._history: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._add(
            {
                "resourceType": "Patient",
                "id": self.pid,
                "meta": SYNTHETIC_META,
                "identifier": [
                    {
                        "use": "usual",
                        "type": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                    "code": "MR",
                                    "display": "Medical record number",
                                }
                            ]
                        },
                        "system": MRN_SYSTEM,
                        "value": self.mrn,
                    }
                ],
                "active": True,
                "name": [{"use": "official", "family": family, "given": [given], "text": self.name}],
                "gender": gender,
                "birthDate": birth_date.isoformat(),
                "address": [{"city": city, "country": "TR"}],
                "generalPractitioner": [clinician_ref(gp)],
                "managingOrganization": {"reference": f"Organization/{ORGANIZATION_ID}", "display": ORGANIZATION_NAME},
            }
        )

    # ----------------------------------------------------------------- basics

    @property
    def name(self) -> str:
        return f"{self.given} {self.family}"

    @property
    def ref(self) -> dict:
        return {"reference": f"Patient/{self.pid}", "display": self.name}

    @property
    def female(self) -> bool:
        return self.gender == "female"

    def age_on(self, day: date) -> int:
        years = day.year - self.birth_date.year
        if (day.month, day.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    def age_sex(self, moment: datetime) -> str:
        return f"{self.age_on(moment.date())}-year-old {'woman' if self.female else 'man'}"

    def _add(self, *resources: dict) -> None:
        self.resources.extend(resources)

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self.pid}-{self._counters[prefix]:03d}"

    def _base(self, resource_type: str, prefix: str) -> dict:
        return {"resourceType": resource_type, "id": self._next_id(prefix), "meta": SYNTHETIC_META}

    # ----------------------------------------------------- problems/allergies

    def condition(
        self,
        icd: str,
        display: str,
        *,
        onset: date,
        text: str | None = None,
        clinician: Clinician | None = None,
        stage: str | None = None,
        note: str | None = None,
    ) -> dict:
        condition = self._base("Condition", "cond") | {
            "clinicalStatus": {
                "coding": [
                    {"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active", "display": "Active"}
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": "confirmed",
                        "display": "Confirmed",
                    }
                ]
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                            "code": "problem-list-item",
                            "display": "Problem List Item",
                        }
                    ]
                }
            ],
            "code": {"coding": [{"system": ICD10, "code": icd, "display": display}], "text": text or display},
            "subject": self.ref,
            "onsetDateTime": onset.isoformat(),
            "recordedDate": onset.isoformat(),
        }
        if clinician:
            condition["asserter"] = clinician_ref(clinician)
        if stage:
            condition["stage"] = [{"summary": {"text": stage}}]
        if note:
            condition["note"] = [{"text": note}]
        self._add(condition)
        return condition

    def no_known_allergies(self, recorded: date) -> None:
        self._add(
            self._base("AllergyIntolerance", "alg")
            | {
                "clinicalStatus": {
                    "coding": [
                        {"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                            "code": "confirmed",
                        }
                    ]
                },
                "code": {
                    "coding": [{"system": SNOMED, "code": "716186003", "display": "No known allergy"}],
                    "text": "No known allergies",
                },
                "patient": self.ref,
                "recordedDate": recorded.isoformat(),
            }
        )

    def allergy(self, substance: str, reaction: str, *, recorded: date, criticality: str, severity: str) -> None:
        self._add(
            self._base("AllergyIntolerance", "alg")
            | {
                "clinicalStatus": {
                    "coding": [
                        {"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                            "code": "confirmed",
                        }
                    ]
                },
                "type": "allergy",
                "category": ["medication"],
                "criticality": criticality,
                "code": {"text": substance},
                "patient": self.ref,
                "recordedDate": recorded.isoformat(),
                "reaction": [{"manifestation": [{"text": reaction}], "severity": severity}],
            }
        )

    # ------------------------------------------------------------ medications

    def start_med(
        self,
        text: str,
        dosage: str,
        *,
        start: date | datetime,
        prescriber: Clinician,
        atc: tuple[str, str] | None = None,
        reason: str | None = None,
    ) -> dict:
        start_day = start.date() if isinstance(start, datetime) else start
        concept: dict = {"text": text}
        if atc:
            concept["coding"] = [{"system": ATC, "code": atc[0], "display": atc[1]}]
        medication = self._base("MedicationRequest", "med") | {
            "status": "active",
            "intent": "order",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category",
                            "code": "outpatient",
                            "display": "Outpatient",
                        }
                    ]
                }
            ],
            "medicationCodeableConcept": concept,
            "subject": self.ref,
            "authoredOn": instant(start) if isinstance(start, datetime) else start_day.isoformat(),
            "requester": clinician_ref(prescriber),
            "dosageInstruction": [{"text": dosage, "timing": {"repeat": {"boundsPeriod": {"start": start_day.isoformat()}}}}],
        }
        if reason:
            medication["reasonCode"] = [{"text": reason}]
        self._add(medication)
        return medication

    def stop_med(self, medication: dict, *, end: date | datetime, reason: str) -> None:
        end_day = end.date() if isinstance(end, datetime) else end
        medication["status"] = "stopped"
        medication["statusReason"] = {"text": reason}
        medication["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]["end"] = end_day.isoformat()

    def hold_med(self, medication: dict, *, reason: str) -> None:
        medication["status"] = "on-hold"
        medication["statusReason"] = {"text": reason}

    def change_med(
        self,
        medication: dict,
        *,
        when: datetime,
        text: str,
        dosage: str,
        prescriber: Clinician,
        reason: str,
    ) -> dict:
        self.stop_med(medication, end=when, reason=reason)
        coding = medication["medicationCodeableConcept"].get("coding")
        atc = (coding[0]["code"], coding[0]["display"]) if coding else None
        previous_reason = medication.get("reasonCode", [{}])[0].get("text")
        return self.start_med(text, dosage, start=when, prescriber=prescriber, atc=atc, reason=previous_reason)

    # -------------------------------------------------------------- encounters

    def visit(
        self,
        start: datetime,
        clinician: Clinician,
        kind: str,
        reason: str,
        *,
        minutes: int = 20,
        inpatient_until: datetime | None = None,
    ) -> dict:
        end = inpatient_until or start + timedelta(minutes=minutes)
        encounter = self._base("Encounter", "enc") | {
            "status": "finished",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "IMP" if inpatient_until else "AMB",
                "display": "inpatient encounter" if inpatient_until else "ambulatory",
            },
            "type": [{"text": kind}],
            "serviceType": {"text": clinician.specialty},
            "subject": self.ref,
            "participant": [
                {
                    "type": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                                    "code": "PPRF",
                                    "display": "primary performer",
                                }
                            ]
                        }
                    ],
                    "individual": clinician_ref(clinician),
                }
            ],
            "period": {"start": instant(start), "end": instant(end)},
            "reasonCode": [{"text": reason}],
            "serviceProvider": {"reference": f"Organization/{ORGANIZATION_ID}", "display": ORGANIZATION_NAME},
        }
        if inpatient_until:
            encounter["hospitalization"] = {"dischargeDisposition": {"text": "Home"}}
        self._add(encounter)
        return encounter

    def set_height(self, height_cm: float) -> None:
        self.height_cm = round(height_cm)

    def vitals(self, encounter: dict, *, sbp: float, dbp: float, hr: float, weight: float) -> str:
        """Records vital signs for an encounter and returns them as note text."""
        moment = datetime.fromisoformat(encounter["period"]["start"]) + timedelta(minutes=2)
        sbp, dbp, hr, weight = round(sbp), round(dbp), round(hr), round(weight, 1)
        bp = self._vital_base("bp", moment, encounter)
        bp["component"] = [
            {"code": self._vital_code("sbp"), "valueQuantity": self._vital_quantity("sbp", sbp)},
            {"code": self._vital_code("dbp"), "valueQuantity": self._vital_quantity("dbp", dbp)},
        ]
        observations = [bp, self._vital("hr", hr, moment, encounter), self._vital("weight", weight, moment, encounter)]
        text = f"BP {sbp}/{dbp} mmHg, HR {hr}/min, weight {weight:.1f} kg"
        if self.height_cm:
            bmi = round(weight / (self.height_cm / 100) ** 2, 1)
            observations.append(self._vital("bmi", bmi, moment, encounter))
            if not self._history["height"]:
                observations.append(self._vital("height", self.height_cm, moment, encounter))
            text += f" (BMI {bmi:.1f})"
        for key, value in (("sbp", sbp), ("dbp", dbp)):
            self._history[key].append((moment, value))
        self._add(*observations)
        return text + "."

    def _vital_code(self, key: str) -> dict:
        vital = VITALS[key]
        return {"coding": [{"system": LOINC, "code": vital.loinc, "display": vital.display}], "text": vital.name}

    def _vital_quantity(self, key: str, value: float) -> dict:
        vital = VITALS[key]
        return _quantity(value, vital.unit, vital.ucum)

    def _vital_base(self, key: str, moment: datetime, encounter: dict) -> dict:
        return self._base("Observation", "obs") | {
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "vital-signs",
                            "display": "Vital Signs",
                        }
                    ]
                }
            ],
            "code": self._vital_code(key),
            "subject": self.ref,
            "encounter": _ref(encounter),
            "effectiveDateTime": instant(moment),
        }

    def _vital(self, key: str, value: float, moment: datetime, encounter: dict) -> dict:
        observation = self._vital_base(key, moment, encounter)
        observation["valueQuantity"] = self._vital_quantity(key, value)
        self._history[key].append((moment, value))
        return observation

    # ------------------------------------------------------------------ orders

    def order(
        self,
        panel_key: str,
        *,
        ordered: datetime,
        due: date,
        requester: Clinician,
        encounter: dict | None = None,
        reason: str | None = None,
        priority: str = "routine",
    ) -> dict:
        panel = PANELS[panel_key]
        code: dict = {"text": panel.name}
        if panel.loinc:
            code["coding"] = [{"system": LOINC, "code": panel.loinc, "display": panel.display}]
        return self._service_request("laboratory", code, ordered, due, requester, encounter, reason, priority)

    def order_many(
        self,
        panel_keys: list[str],
        *,
        ordered: datetime,
        due: date,
        requester: Clinician,
        encounter: dict | None = None,
        reason: str | None = None,
    ) -> dict[str, dict]:
        return {
            key: self.order(key, ordered=ordered, due=due, requester=requester, encounter=encounter, reason=reason)
            for key in panel_keys
        }

    def order_service(
        self,
        text: str,
        *,
        category: str,
        ordered: datetime,
        due: date,
        requester: Clinician,
        encounter: dict | None = None,
        reason: str | None = None,
        priority: str = "routine",
    ) -> dict:
        return self._service_request(category, {"text": text}, ordered, due, requester, encounter, reason, priority)

    def complete(self, order: dict) -> None:
        order["status"] = "completed"

    def _service_request(
        self,
        category: str,
        code: dict,
        ordered: datetime,
        due: date,
        requester: Clinician,
        encounter: dict | None,
        reason: str | None,
        priority: str,
    ) -> dict:
        snomed, display = ORDER_CATEGORIES[category]
        request = self._base("ServiceRequest", "sr") | {
            "status": "active",
            "intent": "order",
            "category": [{"coding": [{"system": SNOMED, "code": snomed, "display": display}], "text": category.capitalize()}],
            "priority": priority,
            "code": code,
            "subject": self.ref,
            "occurrenceDateTime": due.isoformat(),
            "authoredOn": instant(ordered),
            "requester": clinician_ref(requester),
        }
        if encounter:
            request["encounter"] = _ref(encounter)
        if reason:
            request["reasonCode"] = [{"text": reason}]
        self._add(request)
        return request

    # ----------------------------------------------------------------- results

    def result(
        self,
        panel_key: str,
        values: dict[str, float],
        *,
        collected: datetime,
        requester: Clinician,
        order: dict | None = None,
    ) -> dict[str, float]:
        """Stores one resulted panel and returns the rounded values."""
        panel = PANELS[panel_key]
        if order is None:
            order = self.order(panel_key, ordered=collected - timedelta(minutes=45), due=collected.date(), requester=requester)
        issued = collected + timedelta(hours=panel.turnaround_hours)
        values = {key: _round(value, ANALYTES[key].decimals) for key, value in values.items()}
        if "egfr" in panel.analytes and "egfr" not in values and "cr" in values:
            age = self.age_on(collected.date())
            values["egfr"] = _round(egfr_ckd_epi_2021(values["cr"], age, self.female), 0)
        observations = [
            self._lab_observation(key, values[key], collected, issued, order) for key in panel.analytes if key in values
        ]
        code: dict = {"text": panel.name}
        if panel.loinc:
            code["coding"] = [{"system": LOINC, "code": panel.loinc, "display": panel.display}]
        report = self._base("DiagnosticReport", "dr") | {
            "basedOn": [_ref(order)],
            "status": "final",
            "category": [
                {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB", "display": "Laboratory"}]}
            ],
            "code": code,
            "subject": self.ref,
            "effectiveDateTime": instant(collected),
            "issued": instant(issued),
            "performer": [{"reference": f"Organization/{ORGANIZATION_ID}", "display": f"{ORGANIZATION_NAME} Laboratory"}],
            "result": [_ref(observation) for observation in observations],
        }
        self.complete(order)
        self._add(*observations, report)
        return {key: values[key] for key in panel.analytes if key in values}

    def draw(
        self,
        collected: datetime,
        panels: dict[str, dict[str, float]],
        *,
        requester: Clinician,
        orders: dict[str, dict] | None = None,
    ) -> dict[str, float]:
        drawn: dict[str, float] = {}
        for key, values in panels.items():
            drawn |= self.result(key, values, collected=collected, requester=requester, order=(orders or {}).get(key))
        return drawn

    def _lab_observation(self, key: str, value: float, collected: datetime, issued: datetime, order: dict) -> dict:
        analyte = ANALYTES[key]
        low, high = analyte.reference_range(self.gender)
        observation = self._base("Observation", "obs") | {
            "basedOn": [_ref(order)],
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                            "display": "Laboratory",
                        }
                    ]
                }
            ],
            "code": {"coding": [{"system": LOINC, "code": analyte.loinc, "display": analyte.display}], "text": analyte.name},
            "subject": self.ref,
            "effectiveDateTime": instant(collected),
            "issued": instant(issued),
            "valueQuantity": _quantity(value, analyte.unit, analyte.ucum),
        }
        flag = "H" if high is not None and value > high else "L" if low is not None and value < low else None
        if flag:
            observation["interpretation"] = [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                            "code": flag,
                            "display": "High" if flag == "H" else "Low",
                        }
                    ]
                }
            ]
        reference: dict = {"text": _range_text(low, high, analyte.decimals, analyte.unit)}
        if low is not None:
            reference["low"] = _quantity(low, analyte.unit, analyte.ucum)
        if high is not None:
            reference["high"] = _quantity(high, analyte.unit, analyte.ucum)
        observation["referenceRange"] = [reference]
        self._history[key].append((collected, value))
        return observation

    def report(
        self,
        kind: str,
        title: str,
        *,
        performed: datetime,
        issued: datetime,
        interpreter: Clinician,
        findings: str,
        conclusion: str,
        order: dict | None = None,
        loinc: tuple[str, str] | None = None,
    ) -> dict:
        category, category_display = REPORT_CATEGORIES[kind]
        code: dict = {"text": title}
        if loinc:
            code["coding"] = [{"system": LOINC, "code": loinc[0], "display": loinc[1]}]
        text = f"{title.upper()}\n{day_text(performed)} · {interpreter.display}, {interpreter.specialty}\n\n{findings.strip()}\n\nCONCLUSION\n{conclusion.strip()}\n"
        report = self._base("DiagnosticReport", "dr") | {
            "status": "final",
            "category": [
                {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": category, "display": category_display}]}
            ],
            "code": code,
            "subject": self.ref,
            "effectiveDateTime": instant(performed),
            "issued": instant(issued),
            "performer": [clinician_ref(interpreter)],
            "resultsInterpreter": [clinician_ref(interpreter)],
            "conclusion": conclusion.strip(),
            "presentedForm": [{"contentType": "text/plain; charset=utf-8", "language": "en", "data": _b64(text), "title": title}],
        }
        if order:
            report["basedOn"] = [_ref(order)]
            self.complete(order)
        self._add(report)
        return report

    # ------------------------------------------------------------------- notes

    def note(
        self,
        *,
        when: datetime,
        author: Clinician,
        title: str,
        body: str,
        kind: str = "progress",
        encounter: dict | None = None,
    ) -> dict:
        loinc, type_display = NOTE_TYPES[kind]
        header = (
            f"{title.upper()}\n"
            f"{self.name} · MRN {self.mrn} · {self.age_on(when.date())} y, {self.gender}\n"
            f"{day_text(when)} · {author.display}, {author.specialty}\n\n"
        )
        text = header + body.strip() + "\n"
        document = self._base("DocumentReference", "doc") | {
            "status": "current",
            "docStatus": "final",
            "type": {"coding": [{"system": LOINC, "code": loinc, "display": type_display}], "text": type_display},
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                            "code": "clinical-note",
                            "display": "Clinical Note",
                        }
                    ]
                }
            ],
            "subject": self.ref,
            "date": instant(when),
            "author": [clinician_ref(author)],
            "description": title,
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain; charset=utf-8",
                        "language": "en",
                        "data": _b64(text),
                        "title": title,
                        "creation": instant(when),
                    }
                }
            ],
        }
        if encounter:
            document["context"] = {"encounter": [_ref(encounter)], "period": encounter["period"]}
        self._add(document)
        return document

    def appointment(self, start: datetime, clinician: Clinician, description: str, *, minutes: int = 20) -> dict:
        appointment = self._base("Appointment", "appt") | {
            "status": "booked",
            "serviceType": [{"text": clinician.specialty}],
            "appointmentType": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0276",
                        "code": "FOLLOWUP",
                        "display": "A follow up visit from a previous appointment",
                    }
                ]
            },
            "description": description,
            "start": instant(start),
            "end": instant(start + timedelta(minutes=minutes)),
            "minutesDuration": minutes,
            "participant": [
                {"actor": self.ref, "status": "accepted"},
                {"actor": clinician_ref(clinician), "status": "accepted"},
            ],
        }
        self._add(appointment)
        return appointment

    # ------------------------------------------------- reading back for notes

    def last(self, key: str, before: datetime) -> tuple[datetime, float] | None:
        earlier = [entry for entry in self._history[key] if entry[0] < before]
        return max(earlier, key=lambda entry: entry[0]) if earlier else None

    def value(self, key: str, before: datetime) -> float:
        entry = self.last(key, before)
        if entry is None:
            raise KeyError(f"{self.pid}: no {key} result before {before}")
        return entry[1]

    def fmt(self, key: str, value: float) -> str:
        analyte = ANALYTES[key]
        unit = analyte.unit
        separator = "" if unit == "%" else " "
        return f"{number(value, analyte.decimals)}{separator}{unit}"

    def labs_text(self, keys: list[str], *, before: datetime, compare: tuple[str, ...] = ()) -> str:
        """Latest results before a moment, grouped by collection date, as note text."""
        groups: dict[date, list[str]] = {}
        for key in keys:
            entry = self.last(key, before)
            if entry is None:
                continue
            moment, value = entry
            text = f"{ANALYTES[key].short} {self.fmt(key, value)}"
            if key in compare:
                prior = self.last(key, moment)
                if prior:
                    text += f" (prior {self.fmt(key, prior[1])}, {day_text(prior[0])})"
            groups.setdefault(moment.date(), []).append(text)
        lines = [f"Labs {day_text(day)}: " + "; ".join(parts) + "." for day, parts in sorted(groups.items(), reverse=True)]
        return "\n".join(lines)

    def bundle(self) -> dict:
        return transaction(self.resources)
