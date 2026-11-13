"""The catalogue of background epicrisis reports for the existing patients.

Each episode is an admission that leaves no lasting diagnosis: an infection, an injury, a birth, a diagnostic procedure
or an operation that cures what it treats. An episode's builder writes the whole report from the patient as the chart
stands on the admission day: their age and sex, the problems and regular medicines already recorded, their allergy,
and their earlier operations. The builder never adds a problem, an allergy or a regular medicine; a discharge
prescription names a regular medicine only when its order is active on the discharge day.

Every number and choice comes from the random generator handed in, so a report is the same on every build.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from chart import PatientChart, day_text

from epicrisis import Admission, ProcedureReport

# ----------------------------------------------------------------- the people

# Display names only; there are no Practitioner resources for these. The first five are the hospital's own doctors.
AYDIN = "Dr. Elif Aydın"
KARA = "Dr. Zeynep Kara"
OZTURK = "Dr. Can Öztürk"
KOC = "Dr. Ayhan Koç"
YALCIN = "Dr. Kerem Yalçın"
CHEST = "Dr. Nilgün Saraçoğlu"
INFECTION = "Dr. Serdar Uysal"
UROLOGY = "Dr. Taner Bilgiç"
ORTHOPAEDICS = "Dr. Volkan Yeşiltepe"
NEUROSURGERY = "Dr. Sinan Karaöz"
NEUROLOGY = "Dr. Banu Erkol"
OBSTETRICS = "Dr. Pınar Ekinci"
ENT = "Dr. Gökhan Tezel"
THORACIC = "Dr. Ferhat Göksel"
WARDS = {"Internal Medicine": AYDIN, "Chest Diseases": CHEST, "Infectious Diseases": INFECTION, "Nephrology": OZTURK}
ANAESTHETISTS = ("Dr. Aslı Korur", "Dr. Onur Taşdelen")
ASSISTANTS = ("Dr. Mert Ünal", "Dr. Ece Sönmez", "Dr. Kaan Yurt", "Dr. Selma Aksu")

# Short names for the problems a past history lists.
PROBLEM_NAMES = {
    "I10": "hypertension",
    "E11.9": "type 2 diabetes",
    "E11.2": "type 2 diabetes with kidney involvement",
    "E78.5": "dyslipidaemia",
    "E78.0": "hypercholesterolaemia",
    "R73.0": "prediabetes",
    "E66.9": "obesity",
    "K76.0": "fatty liver disease",
    "E06.3": "Hashimoto hypothyroidism",
    "N18.3": "chronic kidney disease stage 3",
    "D50.0": "iron deficiency anaemia",
    "N92.0": "heavy menstrual bleeding",
    "D25.9": "a uterine fibroid",
    "K80.2": "gallstones",
    "C73": "papillary thyroid carcinoma",
    "E89.0": "hypothyroidism after thyroidectomy",
    "I25.1": "coronary artery disease",
}
# Operations a patient had elsewhere, known only from a note, by story: (year, words for a past history).
OUTSIDE_OPERATIONS = {
    "colorectal_cancer": ((2012, "laparoscopic cholecystectomy at another hospital"),),
    "gallstone_disease": ((1996, "open appendicectomy at another hospital"), (2008, "caesarean section at another hospital")),
}
# Regular medicines held while a patient is dry or has a contrast study.
KIDNEY_SENSITIVE = ("metformin", "ramipril", "losartan", "empagliflozin", "dapagliflozin")


def name_of(order: dict) -> str:
    """"Sodium bicarbonate 500 mg tablet" -> "Sodium bicarbonate"."""
    text = re.sub(r"\(.*?\)", "", order["medicationCodeableConcept"]["text"])
    return re.split(r"\d", text)[0].strip().removesuffix(" IV").strip()


def _period(order: dict) -> tuple[date, date | None]:
    bounds = order["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]
    return date.fromisoformat(bounds["start"]), date.fromisoformat(bounds["end"]) if "end" in bounds else None


def _performed(procedure: dict) -> date | None:
    value = procedure.get("performedDateTime")
    return date.fromisoformat(value[:10]) if value else None


@dataclass
class Patient:
    """What the chart says about the patient, read at a given day."""

    chart: PatientChart
    story: str
    variant: int
    closed: bool
    conditions: list[dict]
    orders: list[dict]
    allergy: tuple[str, str] | None  # (substance, reaction)
    operations: list[tuple[date, str]]  # earlier operations to list in a past history, oldest first
    mention_operations: bool  # p-1011: her hysterectomy's year is disputed, so no report names it
    notes: str  # the text of the chart's notes, to read what they say about the patient
    # Problems on the list that are treated and over (a showcase patient's cancer, a healed ulcer), by code: (words for
    # the opening line, the sentence for the past history). A report names them as history, not as a discharge
    # diagnosis.
    treated: dict[str, tuple[str, str]] = field(default_factory=dict)
    habits: str = ""  # a showcase patient's smoking and drinking, for the past history

    @classmethod
    def of(cls, chart: PatientChart, story: str, variant: int, closed: bool) -> Patient:
        conditions = [item for item in chart.resources if item["resourceType"] == "Condition"]
        orders = [item for item in chart.resources if item["resourceType"] == "MedicationRequest"]
        allergy = next(
            (
                (item["code"]["text"], item["reaction"][0]["manifestation"][0]["text"])
                for item in chart.resources
                if item["resourceType"] == "AllergyIntolerance" and "reaction" in item
            ),
            None,
        )
        operations = [(date(year, 6, 1), text) for year, text in OUTSIDE_OPERATIONS.get(story, ())]
        for item in chart.resources:
            if item["resourceType"] == "Procedure" and "category" in item and _performed(item):
                operations.append((_performed(item), f"{item['code']['text'][:1].lower()}{item['code']['text'][1:]}"))
        notes = "\n".join(
            _decoded(item) for item in chart.resources if item["resourceType"] == "DocumentReference"
        )
        return cls(
            chart, story, variant, closed, conditions, orders, allergy, sorted(operations),
            mention_operations=(story, variant) != ("chronic_kidney_disease", 1), notes=notes,
        )

    # -- facts on a day

    def age(self, day: date) -> int:
        return self.chart.age_on(day)

    @property
    def female(self) -> bool:
        return self.chart.female

    def problems(self, day: date) -> list[dict]:
        return [
            item for item in self.conditions
            if date.fromisoformat(item["onsetDateTime"][:10]) <= day and item["code"]["coding"][0]["code"] != "Z72.0"
        ]

    def has(self, code: str, day: date) -> bool:
        return any(item["code"]["coding"][0]["code"].startswith(code) for item in self.problems(day))

    def smoker(self, day: date) -> bool:
        return any(
            item["code"]["coding"][0]["code"] == "Z72.0" and date.fromisoformat(item["onsetDateTime"][:10]) <= day
            for item in self.conditions
        )

    def diabetic(self, day: date) -> bool:
        return self.has("E11", day)

    def kidney_disease(self, day: date) -> bool:
        return self.has("N18", day)

    def medicines(self, day: date) -> list[dict]:
        """Regular medicines whose order is active on the day (an order ends on its end day)."""
        active = []
        for order in self.orders:
            start, end = _period(order)
            if start <= day and (end is None or day < end) and order.get("status") != "on-hold":
                active.append(order)
        return active

    def medicine_names(self) -> set[str]:
        """Every medicine the chart orders, lower case: no short course may share a name with one of them."""
        return {name_of(order).lower() for order in self.orders}

    def no_nsaid(self, day: date) -> bool:
        return self.kidney_disease(day) or self.has("I50", day) or self.age(day) >= 65 or "nsaid" in self.notes.lower()

    def penicillin_allergy(self) -> bool:
        return bool(self.allergy and "penicillin" in self.allergy[0].lower())

    # -- words

    def man(self) -> str:
        return "woman" if self.female else "man"

    def he(self) -> str:
        return "she" if self.female else "he"

    def his(self) -> str:
        return "her" if self.female else "his"

    def known(self, day: date) -> str:
        """" with hypertension and type 2 diabetes", or "" when no problem is recorded yet."""
        names = [
            self.treated[code][0] if code in self.treated else PROBLEM_NAMES.get(code, item["code"]["coding"][0]["display"].lower())
            for item in self.problems(day)
            for code in [item["code"]["coding"][0]["code"]]
        ]
        names = list(dict.fromkeys(names))
        if not names:
            return ""
        return " with " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])


def _decoded(document: dict) -> str:
    import base64

    return base64.b64decode(document["content"][0]["attachment"]["data"]).decode("utf-8")


# ----------------------------------------------------------------- the context of one admission


@dataclass
class Ctx:
    p: Patient
    rng: random.Random
    admitted: date
    complicated: bool
    earlier: list[tuple[date, str]] = field(default_factory=list)  # operations from earlier reports

    @property
    def age(self) -> int:
        return self.p.age(self.admitted)

    def pick(self, *options):
        return self.rng.choice(options)

    def ward(self, *services: str) -> dict[str, str]:
        """One of the services, with the doctor who writes its reports."""
        service = self.rng.choice(services)
        return {"service": service, "doctor": WARDS[service]}

    def days(self, low: int, high: int) -> date:
        return self.admitted + timedelta(days=self.rng.randint(low, high))

    def opening(self) -> str:
        known = self.p.known(self.admitted)
        return f"{self.age}-year-old {self.p.man()}" + (known or self.pick(" with no chronic illness", ", previously fit and well"))

    def past(self, extra: list[str] | None = None) -> str:
        p, day = self.p, self.admitted
        lines = []
        problems = []
        for item in p.problems(day):
            code = item["code"]["coding"][0]["code"]
            if code in p.treated:
                problems.append(p.treated[code][1])
                continue
            name = PROBLEM_NAMES.get(code, item["code"].get("text", item["code"]["coding"][0]["display"]))
            onset = date.fromisoformat(item["onsetDateTime"][:10])
            problems.append(f"{name[:1].upper()}{name[1:]} since {onset.year}.")
        lines.append(" ".join(dict.fromkeys(problems)) if problems else "No chronic illnesses.")
        medicines = [f"{name_of(order).lower()} {order['dosageInstruction'][0]['text'].replace(' orally', '')}" for order in p.medicines(day)]
        lines.append(("Regular medicines: " + "; ".join(medicines) + ".") if medicines else "No regular medicines.")
        lines.append(f"Allergy: {p.allergy[0].lower()} ({p.allergy[1].lower()})." if p.allergy else "No known drug allergies.")
        if p.mention_operations:
            operations = [text for when, text in sorted(p.operations + self.earlier) if when < day]
            years = {text: when.year for when, text in p.operations + self.earlier}
            if operations:
                lines.append("Previous operations: " + "; ".join(f"{text} ({years[text]})" for text in operations) + ".")
            elif p.story == "hypothyroidism" and p.variant == 0:
                lines.append("No previous operations.")
        if p.smoker(day):
            lines.append("Smokes about 20 cigarettes a day.")
        elif p.story == "dyslipidaemia":
            lines.append("Never smoked.")
        elif p.story == "colorectal_cancer":
            lines.append("Ex-smoker (20 pack-years, stopped in 2010).")
        elif p.story == "gallstone_disease":
            lines.append("No alcohol.")
        elif p.habits:
            lines.append(p.habits)
        lines += extra or []
        return " ".join(lines)

    def continuing(self, discharged: date, *, hold: tuple[str, ...] = (), restart: date | None = None) -> list[str]:
        """A line for each regular medicine active on the discharge day."""
        lines = []
        for order in self.p.medicines(discharged):
            name = name_of(order)
            dose = order["dosageInstruction"][0]["text"]
            if name.lower() in hold and restart:
                lines.append(f"{name} {dose}: withheld in hospital; restart on {day_text(restart)} if eating and drinking normally")
            else:
                lines.append(f"{name} {dose}: continue")
        return lines

    def free(self, *names: str) -> str:
        """The first name the chart does not order for anything (a short course must not look like a regular one)."""
        taken = self.p.medicine_names()
        return next(name for name in names if not any(name.lower().startswith(word) or word in name.lower() for word in taken))

    def vitals(
        self, *, temp: tuple[float, float] = (36.5, 37.2), pulse: tuple[int, int] = (70, 88), sbp: tuple[int, int] | None = None,
        rr: tuple[int, int] = (14, 18), spo2: tuple[int, int] = (96, 99), oxygen: str = "on room air",
    ) -> str:
        rng = self.rng
        if sbp is None:
            base = 112 + max(0, self.age - 30) // 2 + (10 if self.p.has("I10", self.admitted) else 0)
            sbp = (base, base + 16)
        systolic = rng.randint(*sbp)
        diastolic = max(55, min(98, round(systolic * rng.uniform(0.56, 0.64))))
        return (
            f"Temperature {rng.uniform(*temp):.1f} °C, pulse {rng.randint(*pulse)}/min, blood pressure {systolic}/{diastolic} mmHg, "
            f"respiratory rate {rng.randint(*rr)}/min, SpO₂ {rng.randint(*spo2)}% {oxygen}."
        )

    def creatinine(self) -> float:
        """A usual creatinine for the patient before this illness."""
        if self.p.kidney_disease(self.admitted):
            return self.rng.uniform(1.35, 1.55) if not self.p.female else self.rng.uniform(1.05, 1.25)
        return self.rng.uniform(0.82, 1.05) if not self.p.female else self.rng.uniform(0.6, 0.82)

    def chronic(self) -> list[tuple[str, str]]:
        """The patient's recorded problems as secondary discharge diagnoses, with the chart's own codes."""
        found = []
        for item in self.p.problems(self.admitted):
            coding = item["code"]["coding"][0]
            if coding["code"] not in [code for code, _ in found] and coding["code"] not in self.p.treated:
                found.append((coding["code"], coding["display"]))
        return found

    def glucose_line(self) -> str:
        if not self.p.diabetic(self.admitted):
            return ""
        return self.pick(
            f"Capillary glucose {self.rng.randint(170, 210)}–{self.rng.randint(230, 290)} mg/dL while unwell, covered with correction-dose insulin and back to the usual range by discharge.",
            f"Glucose ran {self.rng.randint(160, 200)}–{self.rng.randint(220, 270)} mg/dL during the infection; managed with correction-dose insulin.",
        )

    def team(self, surgeon: str, *, anaesthetist: bool = True) -> str:
        assistant = self.pick(*ASSISTANTS)
        team = f"{surgeon} (surgeon); {assistant} (assistant)"
        return f"{team}; {self.pick(*ANAESTHETISTS)} (anaesthetist)" if anaesthetist else team


def join(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _number(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


# ----------------------------------------------------------------- complications shared by medical episodes


def _phlebitis(c: Ctx, when: int) -> tuple[str, tuple[str, str]]:
    arm = c.pick("left", "right")
    return (
        f"Phlebitis at the {arm} forearm cannula site on day {when}; the cannula was removed and it settled with warm compresses.",
        ("I80.8", f"Cannula-site phlebitis, {arm} forearm (resolved)"),
    )


def _aki(c: Ctx, base: float, peak: float) -> tuple[str, tuple[str, str]]:
    return (
        f"Acute kidney injury: creatinine {_number(peak, 2)} mg/dL from a usual {_number(base, 2)} mg/dL, back to "
        f"{_number(base + c.rng.uniform(0.0, 0.08), 2)} mg/dL with intravenous fluids.",
        ("N17.9", "Acute kidney injury, prerenal (resolved)"),
    )


def _hypokalaemia(c: Ctx) -> tuple[str, tuple[str, str]]:
    low = c.rng.uniform(2.8, 3.2)
    return (
        f"Hypokalaemia (potassium {_number(low)} mmol/L), corrected with intravenous and oral potassium.",
        ("E87.6", "Hypokalaemia (corrected)"),
    )


def _delirium(c: Ctx) -> tuple[str, tuple[str, str]]:
    return (
        "Delirium on the second and third nights, managed with reorientation, family at the bedside and a regular "
        "sleep routine; no sedatives needed. Fully oriented by discharge.",
        ("F05.9", "Delirium, secondary to infection (resolved)"),
    )


# ----------------------------------------------------------------- medical episodes


def pneumonia(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("right", "left")
    lobe = c.pick("lower", "lower", "middle") if side == "right" else "lower"
    discharged = c.days(4, 6) if not c.complicated else c.days(6, 8)
    switch = rng.randint(2, 3)
    oral = c.free("Levofloxacin") if p.penicillin_allergy() else c.free("Amoxicillin–clavulanate", "Cefuroxime axetil")
    oral_dose = {"Levofloxacin": "750 mg orally once daily", "Amoxicillin–clavulanate": "1 g orally twice daily", "Cefuroxime axetil": "500 mg orally twice daily"}[oral]
    # Clarithromycin raises statin levels (muscle injury): with a statin, the atypical cover is doxycycline instead.
    statin = next((name_of(order).lower() for order in p.medicines(c.admitted) if name_of(order).lower().endswith("statin")), None)
    if p.penicillin_allergy():
        intravenous = "intravenous levofloxacin"
    elif statin:
        atypical = c.free("Doxycycline", "Azithromycin").lower()
        intravenous = f"intravenous ceftriaxone with oral {atypical} (clarithromycin avoided because of the {statin})"
    else:
        intravenous = "intravenous ceftriaxone with oral clarithromycin"
    complications, extra = "None", []
    if c.complicated:
        text, diagnosis = _delirium(c) if c.age >= 70 else _phlebitis(c, rng.randint(2, 4))
        complications, extra = text, [diagnosis]
    sputum = c.pick("rust-coloured", "yellow-green", "blood-streaked")
    organism = c.pick(
        "Urinary pneumococcal antigen positive; blood cultures negative.",
        "Blood cultures negative; sputum culture grew normal respiratory flora.",
        "Blood and sputum cultures negative; urinary Legionella and pneumococcal antigens negative.",
    )
    return Admission(
        title="Community-acquired pneumonia",
        admitted=c.admitted,
        discharged=discharged,
        **c.ward("Chest Diseases", "Internal Medicine"),
        complaint=join(
            f"{c.opening()}, admitted with {rng.randint(3, 5)} days of fever, cough with {sputum} sputum and",
            f"{side}-sided pleuritic chest pain.",
            c.pick("Breathless on walking across the room.", "Increasingly breathless over the last day.", "Off food and drinking little."),
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(temp=(38.2, 39.4), pulse=(96, 114), rr=(20, 26), spo2=(90, 93)),
            f"Dull to percussion with bronchial breathing and coarse crackles over the {side} {lobe} zone.",
            "Alert and oriented.",
        ),
        course=join(
            f"Chest X-ray: consolidation of the {side} {lobe} lobe; no effusion.",
            f"WBC {_number(rng.uniform(13.5, 19.5))} ×10³/µL with neutrophilia, CRP {rng.randint(130, 260)} mg/L, creatinine {_number(c.creatinine(), 2)} mg/dL.",
            organism,
            f"Treated with {intravenous} and oxygen by nasal cannula for {rng.randint(2, 3)} days.",
            f"Afebrile from day {switch}; switched to oral {oral.lower()} on day {switch + 1}.",
            c.glucose_line(),
            f"CRP {rng.randint(18, 55)} mg/L before discharge; SpO₂ {rng.randint(95, 97)}% on room air, walking on the ward.",
        ),
        admission_diagnoses=(("J18.9", "Community-acquired pneumonia"),),
        discharge_diagnoses=(("J18.1", f"Lobar pneumonia, {side} {lobe} lobe"), *extra, *c.chronic()),
        prescription=(
            f"{oral} {oral_dose} for {rng.randint(3, 5)} more days",
            "Paracetamol 1 g orally up to four times daily as needed",
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Family doctor review in one week. Chest X-ray in six weeks to confirm resolution.",
            "Smoking cessation strongly advised; referred to the stop-smoking clinic." if p.smoker(c.admitted) else "",
            "Return if fever recurs or breathing worsens.",
        ),
        outcome=c.pick("Recovered", "Improved"),
        complications=complications,
    )


def covid(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    discharged = c.days(5, 8) if not c.complicated else c.days(7, 10)
    stay = (discharged - c.admitted).days
    onset = c.admitted - timedelta(days=rng.randint(5, 8))
    dexamethasone_left = max(0, 10 - stay)
    imaging = (
        f"Chest X-ray: patchy bilateral peripheral opacities in both lower zones."
        if p.story in NO_ABDOMINAL_IMAGING
        else f"CT chest: bilateral peripheral ground-glass opacities involving about {rng.choice((20, 25, 30, 40))}% of the lungs, typical of COVID-19 pneumonia."
    )
    complications, extra = "None", []
    if c.complicated:
        if p.diabetic(c.admitted):
            complications = (
                f"Hyperglycaemia on dexamethasone (glucose up to {rng.randint(310, 380)} mg/dL), treated with basal-bolus insulin "
                "while on the steroid; insulin stopped before discharge with glucose back in the usual range."
            )
        else:
            complications = (
                f"Steroid-induced hyperglycaemia (glucose up to {rng.randint(230, 290)} mg/dL) on dexamethasone, covered with "
                "correction-dose insulin; normal fasting glucose again before discharge."
            )
            extra = [("R73.9", "Steroid-induced hyperglycaemia (resolved)")]
    favipiravir = "favipiravir for 5 days" if c.admitted < date(2022, 1, 1) else ""
    return Admission(
        title="COVID-19 pneumonia",
        admitted=c.admitted,
        discharged=discharged,
        **c.ward("Infectious Diseases", "Chest Diseases"),
        complaint=join(
            f"{c.opening()}. Fever, dry cough, aching muscles and loss of taste and smell since {day_text(onset)};",
            f"breathless for the last {rng.randint(2, 4)} days.",
            f"SARS-CoV-2 PCR on a nasopharyngeal swab positive on {day_text(c.admitted - timedelta(days=rng.randint(1, 3)))}.",
            c.pick("A household contact had tested positive the week before.", "Several colleagues at work had been infected." if c.age < 60 else "", ""),
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(temp=(37.8, 38.9), pulse=(92, 110), rr=(22, 28), spo2=(88, 93)),
            "Fine crackles at both bases. Speaking in full sentences.",
        ),
        course=join(
            imaging,
            f"Lymphocytes {_number(rng.uniform(0.5, 0.9))} ×10³/µL, CRP {rng.randint(55, 140)} mg/L, D-dimer "
            f"{_number(rng.uniform(0.7, 1.6))} mg/L, ferritin {rng.randint(420, 980)} ng/mL.",
            f"Treated with {favipiravir + ', ' if favipiravir else ''}dexamethasone 6 mg daily, prophylactic enoxaparin, and oxygen "
            f"by nasal cannula at 2–4 L/min for {rng.randint(3, max(3, stay - 2))} days.",
            f"Weaned to room air; SpO₂ {rng.randint(94, 96)}% at rest and {rng.randint(93, 95)}% on walking before discharge.",
        ),
        admission_diagnoses=(("U07.1", "COVID-19"), ("J12.8", "Viral pneumonia")),
        discharge_diagnoses=(("U07.1", "COVID-19, virus identified"), ("J12.8", "Viral pneumonia due to SARS-CoV-2"), *extra, *c.chronic()),
        prescription=(
            *((f"Dexamethasone 6 mg orally once daily for {_count(dexamethasone_left, 'more day')}",) if dexamethasone_left else ()),
            "Paracetamol 1 g orally up to three times daily as needed",
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Isolate at home until 10 days from the start of symptoms.",
            "Check oxygen saturation at home twice daily; return if it falls below 93% or breathing worsens.",
            f"Chest {'X-ray' if p.story in NO_ABDOMINAL_IMAGING else 'imaging'} and clinic review in 8 weeks.",
        ),
        outcome="Improved",
        complications=complications,
    )


def gastroenteritis(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    discharged = c.days(2, 3) if not c.complicated else c.days(3, 4)
    cause = c.pick("salmonella", "norovirus", "unknown")
    base = c.creatinine()
    peak = base * (rng.uniform(1.6, 2.0) if c.complicated else rng.uniform(1.1, 1.3))
    onset_story = c.pick(
        "after a family wedding meal; several guests were ill",
        "after eating chicken at a roadside restaurant",
        "two days after a grandchild with a stomach bug stayed over" if c.age >= 50 else "after a work canteen lunch; colleagues were ill too",
    )
    held = [order for order in p.medicines(c.admitted) if name_of(order).lower() in KIDNEY_SENSITIVE]
    restart = discharged + timedelta(days=2)
    if cause == "salmonella":
        organism, code = "Stool culture grew Salmonella enteritidis.", ("A02.0", "Salmonella enteritis")
    elif cause == "norovirus":
        organism, code = "Stool PCR positive for norovirus; bacterial culture negative.", ("A08.1", "Acute gastroenteritis due to norovirus")
    else:
        organism, code = "Stool culture and PCR panel negative.", ("A09.9", "Acute gastroenteritis of presumed infectious origin")
    treat_salmonella = cause == "salmonella" and (c.age >= 65 or p.diabetic(c.admitted))
    complications, extra = "None", []
    if c.complicated:
        text, diagnosis = _aki(c, base, peak) if held or c.age >= 60 else _hypokalaemia(c)
        complications, extra = text, [diagnosis]
    return Admission(
        title="Acute gastroenteritis with dehydration",
        admitted=c.admitted,
        discharged=discharged,
        **c.ward("Internal Medicine", "Infectious Diseases"),
        complaint=join(
            f"{c.opening()}. {rng.randint(2, 3)} days of profuse watery diarrhoea, {rng.randint(6, 12)} times a day, and vomiting,",
            f"{onset_story}. Unable to keep fluids down; dizzy on standing. Crampy abdominal pain. No blood in the stool.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(temp=(37.3, 38.4), pulse=(102, 118), sbp=(92, 108)),
            "Dry mucous membranes, reduced skin turgor. Abdomen soft, mildly tender throughout, no guarding; active bowel sounds.",
        ),
        course=join(
            f"Creatinine {_number(peak, 2)} mg/dL, sodium {rng.randint(133, 137)} mmol/L, potassium {_number(rng.uniform(3.2, 3.6))} mmol/L, "
            f"CRP {rng.randint(20, 90)} mg/L.",
            organism,
            "Intravenous 0.9% sodium chloride with potassium and antiemetics.",
            ("Held on admission: " + ", ".join(name_of(order).lower() for order in held) + ".") if held else "",
            "Treated with ciprofloxacin given age and comorbidity." if treat_salmonella else "No antibiotics were needed.",
            f"Diarrhoea settled by day {rng.randint(2, 3)}; eating and drinking normally before discharge.",
        ),
        admission_diagnoses=(("A09.9", "Acute gastroenteritis"), ("E86", "Dehydration")),
        discharge_diagnoses=(code, ("E86", "Dehydration (corrected)"), *extra, *c.chronic()),
        prescription=(
            "Oral rehydration salts, one sachet after each loose stool",
            *((f"{c.free('Ciprofloxacin')} 500 mg orally twice daily for {rng.randint(3, 4)} more days",) if treat_salmonella else ()),
            *c.continuing(discharged, hold=KIDNEY_SENSITIVE, restart=restart),
        ),
        recommendations=join(
            "Hand hygiene at home; do not prepare food for others for 48 hours after the last loose stool.",
            f"Kidney function and potassium with the family doctor on {day_text(restart)}." if held or c.complicated else "",
            "Return if unable to drink or if blood appears in the stool.",
        ),
        outcome="Recovered",
        complications=complications,
    )


def pyelonephritis(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("right", "left")
    discharged = c.days(3, 5) if not c.complicated else c.days(5, 7)
    allergic = p.penicillin_allergy()
    oral = c.free("Ciprofloxacin") if allergic else c.pick(c.free("Cefuroxime axetil"), c.free("Ciprofloxacin"))
    oral_dose = {"Ciprofloxacin": "500 mg orally twice daily", "Cefuroxime axetil": "500 mg orally twice daily"}[oral]
    base = c.creatinine()
    complications, extra = "None", []
    if c.complicated:
        text, diagnosis = _aki(c, base, base * rng.uniform(1.6, 1.9)) if c.age >= 55 else _phlebitis(c, rng.randint(2, 3))
        complications, extra = text, [diagnosis]
    ward = c.ward("Nephrology") if p.kidney_disease(c.admitted) else c.ward("Infectious Diseases", "Internal Medicine")
    return Admission(
        title=f"Acute pyelonephritis, {side}",
        admitted=c.admitted,
        discharged=discharged,
        **ward,
        complaint=join(
            f"{c.opening()}. {rng.randint(2, 4)} days of burning on passing urine and frequency, then fever with rigors,",
            f"{side} loin pain and vomiting since {c.pick('the previous evening', 'the morning of admission')}.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(temp=(38.6, 39.6), pulse=(102, 120), sbp=(100, 118)),
            f"Flushed. Tender {side} renal angle; abdomen soft, no peritonism.",
        ),
        course=join(
            "Urinalysis: leucocytes 3+, nitrites positive.",
            f"WBC {_number(rng.uniform(14.5, 21.0))} ×10³/µL, CRP {rng.randint(140, 280)} mg/L, creatinine {_number(base * rng.uniform(1.05, 1.25), 2)} mg/dL.",
            "Prompt response to treatment, so no imaging was needed." if p.story in NO_ABDOMINAL_IMAGING else "Renal ultrasound: no hydronephrosis or stones.",
            f"Urine and blood cultures grew Escherichia coli sensitive to ceftriaxone, cefuroxime and ciprofloxacin{c.pick(', resistant to ampicillin', '')}.",
            f"Treated with intravenous {'ciprofloxacin' if allergic else 'ceftriaxone'} and fluids; afebrile after {rng.randint(36, 60)} hours",
            f"and switched to oral {oral.lower()}.",
            c.glucose_line(),
        ),
        admission_diagnoses=(("N39.0", "Urinary tract infection with fever"),),
        discharge_diagnoses=(("N10", f"Acute pyelonephritis, {side}"), ("B96.2", "Escherichia coli as the cause"), *extra, *c.chronic()),
        prescription=(
            f"{oral} {oral_dose} to complete {7 if oral == 'Ciprofloxacin' else 10} days of treatment",
            "Paracetamol 1 g orally up to four times daily as needed",
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Drink at least 2 litres a day.",
            "Repeat urine culture only if symptoms return; return with fever or loin pain.",
            "Kidney function with the next routine bloods." if p.kidney_disease(c.admitted) else "",
        ),
        outcome="Recovered",
        complications=complications,
    )


def cellulitis(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("left", "right")
    discharged = c.days(4, 6) if not c.complicated else c.days(6, 9)
    allergic = p.penicillin_allergy()
    portal = c.pick("tinea", "scratch", "bite")
    complications, extra = "None", []
    if c.complicated:
        if allergic:
            complications = (
                "Clostridioides difficile diarrhoea on day 4 after clindamycin (toxin positive); treated with oral vancomycin, "
                "settled within three days."
            )
            extra = [("A04.7", "Clostridioides difficile colitis (treated)")]
        else:
            text, diagnosis = _phlebitis(c, rng.randint(2, 4))
            complications, extra = text, [diagnosis]
    start = {
        "tinea": "starting from cracked, itchy skin between the toes",
        "scratch": "after a scratch while working in the garden",
        "bite": "after an insect bite on the shin",
    }[portal]
    oral = c.free("Clindamycin") if allergic else c.free("Cefalexin")
    oral_dose = "300 mg orally three times daily" if oral == "Clindamycin" else "500 mg orally four times daily"
    return Admission(
        title=f"Cellulitis of the {side} lower leg",
        admitted=c.admitted,
        discharged=discharged,
        **c.ward("Infectious Diseases", "Internal Medicine"),
        complaint=join(
            f"{c.opening()}. {rng.randint(2, 4)} days of spreading redness, swelling and pain of the {side} lower leg,",
            f"{start}, with fever and shivering since the day before admission.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(temp=(37.9, 38.9), pulse=(90, 108)),
            f"Hot, tender, red swelling of the {side} shin from the ankle to below the knee; edge marked. No blisters, crepitus or fluctuance.",
            "Macerated, scaling skin between the fourth and fifth toes." if portal == "tinea" else "",
            "Foot pulses palpable.",
        ),
        course=join(
            f"WBC {_number(rng.uniform(12.0, 16.5))} ×10³/µL, CRP {rng.randint(90, 210)} mg/L. Blood cultures negative.",
            "Doppler ultrasound of the leg veins: no deep vein thrombosis.",
            f"Treated with intravenous {'clindamycin' if allergic else 'cefazolin'}, leg elevation and analgesia.",
            f"Redness receded inside the marked edge by day {rng.randint(3, 4)}; switched to oral {oral.lower()}.",
            "Topical terbinafine started for the athlete's foot." if portal == "tinea" else "",
            c.glucose_line(),
        ),
        admission_diagnoses=(("L03.1", f"Cellulitis, {side} lower leg"),),
        discharge_diagnoses=(
            ("L03.1", f"Cellulitis of the {side} lower leg"),
            *((("B35.3", "Tinea pedis (portal of entry)"),) if portal == "tinea" else ()),
            *extra,
            *c.chronic(),
        ),
        prescription=(
            f"{oral} {oral_dose} to complete 10 days of treatment",
            *(("Terbinafine 1% cream twice daily between the toes for 2 weeks",) if portal == "tinea" else ()),
            *(("Vancomycin 125 mg orally four times daily to complete 10 days",) if c.complicated and allergic else ()),
            "Paracetamol 1 g orally up to four times daily as needed",
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Keep the leg elevated when sitting. Family doctor review at the end of the antibiotic course.",
            "Keep the skin between the toes dry; continue the cream for two weeks after the rash clears." if portal == "tinea" else "",
            "Return if redness spreads again or fever returns.",
        ),
        outcome=c.pick("Recovered", "Improved"),
        complications=complications if c.complicated else "None",
    )


def renal_colic(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("right", "left")
    size = rng.randint(4, 6)
    level = c.pick("distal", "mid")
    discharged = c.days(1, 2) if not c.complicated else c.days(2, 3)
    nsaid = not p.no_nsaid(c.admitted)
    complications, extra = "None", []
    if c.complicated:
        if not p.female and c.age >= 50:
            complications = "Acute urinary retention after morphine on the first night; catheterised for 24 hours and voided normally after removal."
            extra = [("R33", "Acute urinary retention (resolved)")]
        else:
            text, diagnosis = _phlebitis(c, 2)
            complications, extra = text, [diagnosis]
    return Admission(
        title=f"{side.capitalize()} renal colic from a ureteric stone",
        admitted=c.admitted,
        discharged=discharged,
        service="Urology",
        doctor=UROLOGY,
        complaint=join(
            f"{c.opening()}. Sudden severe colicky {side} loin pain radiating to the groin since {c.pick('the early morning', 'the evening before admission', 'midday')},",
            "with nausea and vomiting. Pink urine once. No fever.",
            c.pick("A similar but milder episode some years ago settled at home.", "No previous stones.", ""),
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(pulse=(88, 106)),
            f"Restless, unable to find a comfortable position. {side.capitalize()} renal angle tender; abdomen soft, no peritonism.",
        ),
        course=join(
            f"Urinalysis: blood 3+, nitrites negative. WBC {_number(rng.uniform(8.0, 11.0))} ×10³/µL, CRP {rng.randint(3, 14)} mg/L, "
            f"creatinine {_number(c.creatinine(), 2)} mg/dL.",
            f"Non-contrast CT of the kidneys, ureters and bladder: {size} mm calculus in the {level} {side} ureter with mild hydronephrosis.",
            "Pain controlled with intravenous paracetamol and "
            + ("intramuscular diclofenac" if nsaid else "small doses of morphine; anti-inflammatory drugs avoided")
            + "; tamsulosin started to help the stone pass.",
            f"Passed the stone on day {(discharged - c.admitted).days or 1}, caught in a strainer and sent for analysis; pain-free afterwards.",
        ),
        admission_diagnoses=(("N23", f"Renal colic, {side}"),),
        discharge_diagnoses=(("N20.1", f"Calculus of the {side} ureter ({size} mm), passed spontaneously"), *extra, *c.chronic()),
        prescription=(
            "Paracetamol 1 g orally up to four times daily as needed",
            *((f"{c.free('Diclofenac')} 50 mg orally up to three times daily with food, for up to 5 days if pain returns",) if nsaid else ()),
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Drink 2.5–3 litres a day. Stone analysis result to the family doctor.",
            "Urology clinic in 6 weeks with an ultrasound of the kidneys.",
        ),
        outcome="Recovered",
        complications=complications,
    )


def head_injury(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("left", "right")
    region = c.pick("parietal", "occipital", "frontal")
    discharged = c.days(1, 1) if not c.complicated else c.days(2, 3)
    how = c.pick(
        "slipped on an icy pavement and struck the back of the head",
        "fell from a stepladder while painting at home",
        "struck the head on a low cupboard door and fell",
        "was a restrained passenger in a low-speed car collision",
    )
    # The mechanism decides where the blow landed, where it says.
    if "back of the head" in how:
        region = "occipital"
    elif "cupboard door" in how:
        region = "frontal"
    event = "the injury" if "collision" in how else "the fall"
    complications, extra = "None", []
    if c.complicated:
        complications = (
            f"Hyponatraemia (sodium {rng.randint(127, 130)} mmol/L) on day 2 after hypotonic fluids; fluids stopped, sodium "
            f"{rng.randint(134, 137)} mmol/L the next day."
        )
        extra = [("E87.1", "Hyponatraemia (resolved)")]
    return Admission(
        title="Observation after a head injury",
        admitted=c.admitted,
        discharged=discharged,
        service="Neurosurgery",
        doctor=NEUROSURGERY,
        complaint=join(
            f"{c.opening()}, who {how}. Lost consciousness for under a minute according to a witness; no memory of {event} itself.",
            f"Headache and {rng.randint(2, 3)} episodes of vomiting since. Not taking blood thinners.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(),
            f"GCS 15 (14 on the ambulance record). {rng.randint(2, 4)} cm scalp swelling over the {side} {region} region, skin intact.",
            "Pupils equal and reactive; no focal neurological deficit. Cervical spine not tender, full painless movement.",
        ),
        course=join(
            "CT head within an hour of arrival: no intracranial haemorrhage and no skull fracture; soft-tissue swelling only.",
            "Admitted for neurological observation because of the loss of consciousness and repeated vomiting.",
            "GCS 15 throughout; no further vomiting; headache eased with paracetamol.",
        ),
        admission_diagnoses=(("S06.0", "Head injury with brief loss of consciousness"),),
        discharge_diagnoses=(("S06.0", "Concussion"), ("S00.0", f"Scalp haematoma, {side} {region}"), *extra, *c.chronic()),
        prescription=("Paracetamol 1 g orally up to four times daily as needed for headache", *c.continuing(discharged)),
        recommendations=join(
            "Head injury advice sheet given. An adult to stay with the patient for the first 24 hours at home.",
            "No driving or contact sport for one week. Return at once with worsening headache, vomiting, drowsiness, confusion or weakness.",
        ),
        outcome="Recovered",
        complications=complications,
    )


def fracture_treated_without_surgery(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("left", "right")
    nsaid = not p.no_nsaid(c.admitted)
    if c.pick("humerus", "ribs") == "humerus":
        discharged = c.days(2, 4) if not c.complicated else c.days(4, 5)
        complications, extra = "None", []
        if c.complicated:
            complications = "Constipation from opioid analgesia, relieved with laxatives on day 3."
            extra = [("K59.0", "Opioid-induced constipation (resolved)")]
        return Admission(
            title=f"Fracture of the {side} proximal humerus",
            admitted=c.admitted,
            discharged=discharged,
            service="Orthopaedics and Traumatology",
            doctor=ORTHOPAEDICS,
            complaint=join(
                f"{c.opening()}. {c.pick('Slipped on a wet floor at home', 'Tripped on an uneven pavement', 'Missed a step on the stairs')}",
                f"and fell onto the {side} side; pain and swelling of the shoulder, unable to lift the arm.",
            ),
            past_history=c.past(),
            examination=join(
                c.vitals(pulse=(78, 96)),
                f"Bruising over the {side} upper arm; tender over the proximal humerus. Radial pulse present; sensation over the",
                "badge area and the hand intact.",
            ),
            course=join(
                f"X-ray: minimally displaced two-part fracture of the surgical neck of the {side} humerus.",
                "Treated without surgery in a collar-and-cuff sling.",
                f"Admitted for pain control and because {p.he()} could not manage at home with one arm; seen daily by the physiotherapist.",
                "Managing dressing and washing with help and walking independently before discharge.",
            ),
            admission_diagnoses=(("S42.2", f"Fracture of the {side} proximal humerus"),),
            discharge_diagnoses=(("S42.2", f"Fracture of the surgical neck of the {side} humerus, minimally displaced"), *extra, *c.chronic()),
            prescription=(
                "Paracetamol 1 g orally four times daily",
                f"{c.free('Tramadol')} 50 mg orally up to three times daily as needed for 7 days",
                *(("Lactulose 15 mL orally twice daily while taking tramadol",) if c.complicated else ()),
                *c.continuing(discharged),
            ),
            recommendations=join(
                "Sling for three weeks; pendulum exercises from day 7 as shown by the physiotherapist.",
                "Fracture clinic in one week with a repeat X-ray.",
            ),
            outcome="Improved",
            complications=complications,
        )
    discharged = c.days(3, 5) if not c.complicated else c.days(6, 8)
    ribs = c.pick("5th to 7th", "6th to 8th", "7th to 9th")
    complications, extra = "None", []
    if c.complicated:
        complications = (
            f"Lower respiratory tract infection on day {rng.randint(3, 4)} (fever, productive cough, CRP {rng.randint(70, 140)} mg/L, "
            "no consolidation on X-ray), treated with oral antibiotics and chest physiotherapy."
        )
        extra = [("J22", "Lower respiratory tract infection (treated)")]
    antibiotic = c.free("Doxycycline", "Clarithromycin") if p.penicillin_allergy() else c.free("Amoxicillin–clavulanate", "Clarithromycin")
    return Admission(
        title=f"Fractured ribs, {side}",
        admitted=c.admitted,
        discharged=discharged,
        service="Thoracic Surgery",
        doctor=THORACIC,
        complaint=join(
            f"{c.opening()}. {c.pick('Fell from a ladder while picking fruit', 'Fell down the last few stairs at home', 'Slipped in the bath')}",
            f"and struck the {side} side of the chest. Sharp pain on breathing and coughing.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(pulse=(84, 102), rr=(18, 24), spo2=(94, 97)),
            f"Tender over the {side} lateral chest wall; no surgical emphysema; breath sounds present on both sides.",
        ),
        course=join(
            f"Chest X-ray{'' if p.story in NO_ABDOMINAL_IMAGING else ' and CT'}: fractures of the {side} {ribs} ribs laterally, no pneumothorax, haemothorax or lung contusion.",
            "Admitted for analgesia and breathing exercises: regular paracetamol, short-acting opioid for breakthrough pain,",
            "incentive spirometry and physiotherapy. Coughing effectively and walking around the ward before discharge.",
        ),
        admission_diagnoses=(("S22.4", f"Fractures of the {side} {ribs} ribs"),),
        discharge_diagnoses=(("S22.4", f"Multiple fractures of ribs, {side} {ribs}"), *extra, *c.chronic()),
        prescription=(
            "Paracetamol 1 g orally four times daily",
            f"{c.free('Tramadol')} 50 mg orally up to three times daily as needed for 7 days",
            *((f"{c.free('Naproxen')} 500 mg orally twice daily with food for 5 days",) if nsaid else ()),
            *((f"{antibiotic} {'100 mg twice daily' if antibiotic == 'Doxycycline' else '500 mg twice daily' if antibiotic == 'Clarithromycin' else '1 g twice daily'} orally for {rng.randint(3, 5)} more days",) if c.complicated else ()),
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Deep-breathing exercises every hour while awake; do not strap the chest.",
            "Return with fever, worsening breathlessness or coughing blood. Family doctor review in one week.",
        ),
        outcome="Improved",
        complications=complications,
    )


def vertigo(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("left", "right")
    other = "right" if side == "left" else "left"
    discharged = c.days(2, 3) if not c.complicated else c.days(3, 4)
    vascular = c.age >= 50 or p.has("I10", c.admitted) or p.diabetic(c.admitted) or p.smoker(c.admitted)
    complications, extra = "None", []
    if c.complicated:
        text, diagnosis = _hypokalaemia(c)
        complications, extra = text.replace("Hypokalaemia", "Hypokalaemia from vomiting"), [diagnosis]
    return Admission(
        title=f"Acute vestibular neuronitis, {side}",
        admitted=c.admitted,
        discharged=discharged,
        service="Neurology",
        doctor=NEUROLOGY,
        complaint=join(
            f"{c.opening()}. Woke with severe spinning vertigo, nausea and repeated vomiting, worse with any head movement; unable to stand.",
            "No hearing loss, tinnitus, headache, double vision, slurred speech, weakness or numbness.",
            c.pick("A cold the week before.", "Otherwise well beforehand.", "A sore throat and runny nose ten days earlier."),
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(pulse=(72, 92)),
            f"Horizontal-torsional nystagmus beating to the {other}, suppressed by fixation; abnormal head impulse test to the {side};",
            "no skew deviation (HINTS examination consistent with a peripheral cause). Hearing normal to whisper. No limb ataxia;",
            "cranial nerves otherwise normal. Unable to walk unaided.",
        ),
        course=join(
            "MRI of the brain with diffusion-weighted imaging, given the vascular risk factors: no infarct." if vascular else "",
            "Intravenous fluids, metoclopramide and dimenhydrinate for 48 hours, then early vestibular rehabilitation with the physiotherapist.",
            f"Vomiting stopped on day {rng.randint(1, 2)}; walking independently with mild unsteadiness before discharge.",
        ),
        admission_diagnoses=(("R42", "Acute vertigo"),),
        discharge_diagnoses=(("H81.2", f"Vestibular neuronitis, {side}"), *extra, *c.chronic()),
        prescription=("Dimenhydrinate 50 mg orally up to three times daily as needed, for no more than 3 days", *c.continuing(discharged)),
        recommendations=join(
            "Vestibular exercises three times a day as taught. Do not drive until the dizziness has settled.",
            "Neurology clinic in 4 weeks. Return at once with weakness, numbness, slurred speech or a new severe headache.",
        ),
        outcome="Improved",
        complications=complications,
    )


def childbirth(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    previous = 1 if "last pregnancy six years ago" in p.notes and p.story == "iron_deficiency" else rng.choice((0, 0, 1, 2))
    gravida = previous + 1
    weeks = f"{rng.randint(38, 40)}+{rng.randint(0, 6)}"
    discharged = c.days(1, 2) if not c.complicated else c.days(2, 3)
    baby = c.pick("girl", "boy")
    weight = rng.randint(2950, 3750)
    complications, extra = "None", []
    if c.complicated:
        loss = rng.randint(16, 22) * 50
        before, after = rng.uniform(11.8, 12.8), rng.uniform(8.9, 9.8)
        complications = (
            f"Postpartum haemorrhage of about {loss} mL from uterine atony, 30 minutes after delivery; controlled with uterine "
            f"massage, an oxytocin infusion and rectal misoprostol. Hb {_number(before)} g/dL before and {_number(after)} g/dL after; "
            "no transfusion needed."
        )
        extra = [("O72.1", "Postpartum haemorrhage from uterine atony (controlled)")]
    return Admission(
        title="Spontaneous vaginal delivery",
        admitted=c.admitted,
        discharged=discharged,
        service="Obstetrics and Gynaecology",
        doctor=OBSTETRICS,
        complaint=join(
            f"{c.age}-year-old woman, gravida {gravida} para {previous}, at {weeks} weeks, admitted in spontaneous labour.",
            "Uncomplicated pregnancy with normal screening and anomaly scans.",
        ),
        past_history=c.past(["Previous delivery: spontaneous vaginal birth." if previous == 1 else f"Previous deliveries: {previous} spontaneous vaginal births." if previous else "First pregnancy."]),
        examination=join(
            c.vitals(sbp=(108, 124), pulse=(78, 92)),
            f"Contractions every 3–4 minutes. Cephalic presentation; cervix {rng.randint(4, 6)} cm dilated. Cardiotocography reassuring.",
        ),
        course=join(
            f"Spontaneous vaginal delivery after a labour of {rng.randint(5, 11)} hours{c.pick(' with epidural analgesia', '')}:",
            f"live {baby}, {weight} g, Apgar {rng.randint(8, 9)} and {rng.randint(9, 10)}. Perineum intact. Placenta and membranes complete.",
            "Breastfeeding established. Mother and baby discharged together.",
        ),
        admission_diagnoses=(("O80", f"Spontaneous labour at {weeks} weeks"),),
        discharge_diagnoses=(("O80", "Single spontaneous delivery"), ("Z37.0", "Single live birth"), *extra, *c.chronic()),
        prescription=(
            "Paracetamol 1 g orally up to four times daily as needed",
            *(("Iron(III) hydroxide polymaltose 100 mg orally once daily for 3 months",) if c.complicated else ()),
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Postnatal check with the family doctor and midwife at 6 weeks, with a full blood count." if c.complicated
            else "Postnatal check with the family doctor and midwife at 6 weeks.",
            "Contraception discussed. Return with heavy bleeding, fever or calf pain.",
        ),
        outcome="Recovered",
        complications=complications,
    )


# ----------------------------------------------------------------- diagnostic procedures


def bleeding_ulcer(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    discharged = c.days(3, 4) if not c.complicated else c.days(4, 6)
    scope = c.admitted + timedelta(days=1)
    size = rng.randint(6, 12)
    nsaid_history = not p.no_nsaid(c.admitted) and p.story != "colorectal_cancer" and rng.random() < 0.5
    base = c.creatinine()
    hb, hb_low = rng.uniform(9.4, 10.8), 0.0
    hb_low = hb - rng.uniform(0.4, 0.9)
    complications, extra = "None", []
    if c.complicated:
        text, diagnosis = _aki(c, base, base * rng.uniform(1.5, 1.8))
        complications, extra = text, [diagnosis]
    return Admission(
        title="Upper gastrointestinal bleeding from a duodenal ulcer",
        admitted=c.admitted,
        discharged=discharged,
        service="Gastroenterology",
        doctor=KOC,
        complaint=join(
            f"{c.opening()}. {rng.randint(2, 3)} black, tarry stools over a day and dizziness on standing; {c.pick('burning upper abdominal pain for several weeks', 'no abdominal pain')}.",
            f"Took ibuprofen 400 mg three times a day for a week for back pain." if nsaid_history else "No anti-inflammatory or blood-thinning medicines.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(pulse=(100, 114), sbp=(98, 112)),
            "Pale. Epigastric tenderness, no guarding. Melaena on rectal examination.",
        ),
        course=join(
            f"Hb {_number(hb)} g/dL, urea raised, creatinine {_number(base * rng.uniform(1.05, 1.2), 2)} mg/dL; Glasgow-Blatchford score {rng.randint(7, 10)}.",
            "Intravenous fluids and a pantoprazole infusion. Gastroscopy the next morning (see the procedure report).",
            f"No further bleeding; Hb steady at {_number(hb_low)} g/dL; no transfusion needed. Eating normally from day {rng.randint(2, 3)}.",
            "Rapid urease test positive for Helicobacter pylori; eradication therapy started.",
        ),
        admission_diagnoses=(("K92.1", "Melaena"),),
        discharge_diagnoses=(
            ("K26.0", f"Duodenal ulcer with haemorrhage ({size} mm, clean base)"), ("B98.0", "Helicobacter pylori infection"),
            *extra, *c.chronic(),
        ),
        prescription=(
            "Pantoprazole 40 mg orally twice daily for 14 days, then once daily to complete 8 weeks",
            "Bismuth subcitrate 240 mg orally twice daily for 14 days",
            "Tetracycline 500 mg orally four times daily for 14 days",
            f"{c.free('Metronidazole')} 500 mg orally three times daily for 14 days",
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Avoid anti-inflammatory painkillers; paracetamol is safe.",
            "Urea breath test 4 weeks after finishing pantoprazole to confirm eradication. Full blood count with the family doctor in 2 weeks.",
        ),
        outcome="Improved",
        complications=complications,
        procedure=ProcedureReport(
            performed=scope,
            name="Gastroscopy (upper gastrointestinal endoscopy) with antral biopsy for rapid urease test",
            operation=False,
            pre_diagnosis="Upper gastrointestinal bleeding (melaena)",
            post_diagnosis=f"Duodenal ulcer, {size} mm, clean base (Forrest III); Helicobacter pylori positive",
            team=f"{KOC} (endoscopist)",
            anaesthesia="Conscious sedation (midazolam 2 mg intravenously) and lidocaine throat spray",
            wound_class="Not applicable",
            note=join(
                "Oesophagus normal. Stomach: some altered blood, mild antral erythema; no ulcer. Two antral biopsies for rapid urease test.",
                f"Duodenal bulb: {size} mm ulcer on the anterior wall with a clean base; no visible vessel, no adherent clot, no active bleeding.",
                "Second part of the duodenum normal. No endoscopic treatment needed.",
            ),
            blood_loss="None",
            specimen="Antral biopsies for rapid urease test: positive",
            body_site="Duodenum",
        ),
    )


def colonoscopy(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    count = rng.randint(1, 3)
    site = c.pick("sigmoid colon", "descending colon", "transverse colon")
    size = rng.randint(4, 9)  # small: hyperplastic polyps of 10 mm or more would need surveillance
    scope = c.admitted + timedelta(days=1)
    discharged = scope if not c.complicated else scope + timedelta(days=rng.randint(1, 2))
    held = [order for order in p.medicines(c.admitted) if name_of(order).lower() in ("metformin", "empagliflozin", "dapagliflozin")]
    polyps = "one polyp" if count == 1 else f"{count} polyps"
    plural = "s" if count > 1 else ""
    procedure_complications, extra = "None", []
    if c.complicated:
        procedure_complications = (
            f"Delayed bleeding from the polypectomy site {rng.randint(10, 20)} hours later: two passages of fresh red blood, "
            f"Hb {_number(rng.uniform(13.0, 13.8))} falling to {_number(rng.uniform(11.6, 12.4))} g/dL. Settled with observation; "
            "no repeat endoscopy or transfusion."
        )
        extra = [("T81.0", "Delayed post-polypectomy bleeding (settled)")]
    return Admission(
        title="Colonoscopy with polyp removal after a positive screening test",
        admitted=c.admitted,
        discharged=discharged,
        service="Gastroenterology",
        doctor=KOC,
        complaint=join(
            f"{c.opening()}. Positive faecal immunochemical test at bowel cancer screening; no symptoms, no rectal bleeding, weight steady.",
            "Admitted the day before for supervised bowel preparation" + (" because of the diabetes medicines." if held else "."),
        ),
        past_history=c.past(),
        examination=join(c.vitals(), "Abdomen soft, non-tender. Rectal examination normal."),
        course=join(
            "Bowel preparation completed overnight; colonoscopy the next morning (see the procedure report).",
            ("Held during the preparation and restarted with the first meal: " + ", ".join(name_of(order).lower() for order in held) + ".") if held else "",
            "Home the same afternoon." if not c.complicated else "Kept in after the bleeding, which stopped without treatment; eating normally before discharge.",
        ),
        admission_diagnoses=(("R19.5", "Positive faecal immunochemical test"),),
        discharge_diagnoses=(("K63.5", f"Hyperplastic polyp{plural} of the {site}, removed"), *extra, *c.chronic()),
        prescription=tuple(c.continuing(discharged)),
        recommendations=join(
            f"Histology: hyperplastic polyp{plural}, no dysplasia; no surveillance colonoscopy needed.",
            "Return to the national screening programme in 10 years. Return with heavy rectal bleeding, dizziness or abdominal pain.",
        ),
        outcome="Recovered",
        complications=procedure_complications,
        procedure=ProcedureReport(
            performed=scope,
            name="Colonoscopy with cold snare polypectomy",
            operation=False,
            pre_diagnosis="Positive faecal immunochemical test",
            post_diagnosis=f"{polyps.capitalize()} in the {site} ({size} mm{' largest' if count > 1 else ''}), removed",
            team=f"{KOC} (endoscopist)",
            anaesthesia=f"Deep sedation with propofol ({c.pick(*ANAESTHETISTS)})",
            wound_class="Not applicable",
            note=join(
                f"Bowel preparation good (Boston score {rng.randint(7, 9)}). Caecum reached, identified by the appendiceal orifice and",
                f"ileocaecal valve; terminal ileum normal. {polyps.capitalize()} in the {site}, sessile, up to {size} mm, removed by cold",
                "snare and retrieved. Remaining colon normal. Withdrawal time 9 minutes.",
            ),
            complications=procedure_complications,
            specimen=f"{polyps.capitalize()}, {site}: hyperplastic, no dysplasia",
            body_site="Colon",
        ),
    )


def angiography(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    performed = c.admitted + timedelta(days=1)
    discharged = performed + timedelta(days=rng.randint(0, 1)) if not c.complicated else performed + timedelta(days=1)
    held = [order for order in p.medicines(c.admitted) if name_of(order).lower() == "metformin"]
    restart = performed + timedelta(days=2)
    risks = [
        name for name, present in (
            ("hypertension", p.has("I10", c.admitted)), ("diabetes", p.diabetic(c.admitted)),
            ("raised cholesterol", p.has("E78", c.admitted)), ("smoking", p.smoker(c.admitted)),
            ("kidney disease", p.kidney_disease(c.admitted)),
            ("age", (c.age >= 60 and not p.female) or c.age >= 65),
        ) if present
    ]
    reason = ("risk factors (" + ", ".join(risks) + ")") if risks else "the typical description of the pain"
    procedure_complications, extra = "None", []
    if c.complicated:
        procedure_complications = (
            f"Haematoma of {rng.randint(3, 5)} cm at the right radial puncture site, controlled with compression; radial pulse "
            "present and the hand well perfused; kept overnight for observation."
        )
        extra = [("T81.0", "Radial puncture-site haematoma (resolved)")]
    return Admission(
        title="Chest pain; coronary angiography without significant stenosis",
        admitted=c.admitted,
        discharged=discharged,
        service="Cardiology",
        doctor=KARA,
        complaint=join(
            f"{c.opening()}. {c.pick('Two', 'Three')} episodes of central chest tightness at rest over {rng.randint(2, 4)} days, each lasting",
            f"{c.pick('10 to 20', 'about 15', '15 to 30')} minutes, {c.pick('spreading to the left arm', 'with sweating', 'spreading to the jaw')}; the last on the morning of admission.",
        ),
        past_history=c.past(),
        examination=join(c.vitals(), "Pain-free on arrival. Heart sounds normal, no murmur; chest clear; no leg swelling."),
        course=join(
            "ECG: sinus rhythm, no acute ST-segment changes.",
            f"High-sensitivity troponin T {rng.randint(5, 9)} and {rng.randint(6, 10)} ng/L at 0 and 3 hours (below the 99th percentile).",
            f"Because of {reason}, coronary angiography on day 2 (see the procedure report): no significant coronary stenosis.",
            "No further pain. Thought most likely oesophageal; a 4-week trial of a proton-pump inhibitor started.",
            "Intravenous fluids before and after the contrast study because of the kidney disease; creatinine unchanged the next day."
            if p.kidney_disease(c.admitted) else "",
            "Metformin withheld for 48 hours after the contrast study." if held else "",
        ),
        admission_diagnoses=(("R07.4", "Chest pain, suspected acute coronary syndrome"),),
        discharge_diagnoses=(("R07.4", "Non-cardiac chest pain; no significant coronary artery disease on angiography"), *extra, *c.chronic()),
        prescription=(
            "Pantoprazole 40 mg orally once daily before breakfast for 4 weeks",
            *c.continuing(discharged, hold=("metformin",), restart=restart),
        ),
        recommendations=join(
            "Keep the wrist dressing dry for 24 hours; no heavy lifting with the right arm for 3 days.",
            "Family doctor review in 4 weeks. Return at once if chest pain recurs at rest.",
        ),
        outcome="Recovered",
        complications=procedure_complications,
        procedure=ProcedureReport(
            performed=performed,
            name="Coronary angiography via the right radial artery",
            operation=False,
            pre_diagnosis="Chest pain, suspected acute coronary syndrome",
            post_diagnosis="No significant coronary artery stenosis",
            team=f"{KARA} (interventional cardiologist)",
            anaesthesia="Local anaesthesia (lidocaine 2%) at the puncture site",
            wound_class="Clean",
            note=join(
                "Right radial access with a 6F sheath; intra-arterial verapamil and heparin. Left main stem normal. Left anterior",
                f"descending, circumflex and right coronary arteries smooth{c.pick(', with minor wall irregularities', '')} and without",
                f"significant stenosis; right-dominant circulation. Contrast {rng.randint(60, 90)} mL. Sheath removed; radial compression band applied.",
            ),
            complications=procedure_complications,
            body_site="Coronary arteries",
        ),
    )


# ----------------------------------------------------------------- operations


def _course_antibiotic(c: Ctx, days: int) -> tuple[str, ...]:
    antibiotic = c.free("Clindamycin") if c.p.penicillin_allergy() else c.free("Cefalexin")
    dose = "300 mg orally three times daily" if antibiotic == "Clindamycin" else "500 mg orally four times daily"
    return (f"{antibiotic} {dose} for {days} days",)


def appendicectomy(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    performed = c.admitted + timedelta(days=rng.randint(0, 1))
    discharged = performed + timedelta(days=rng.randint(1, 2)) if not c.complicated else performed + timedelta(days=rng.randint(3, 5))
    allergic = p.penicillin_allergy()
    complications, extra, oral = "None", [], ()
    if c.complicated:
        kind = c.pick("wound", "ileus") if p.female or c.age < 50 else c.pick("wound", "ileus", "retention")
        if kind == "wound":
            complications = (
                "Superficial infection of the umbilical port wound on day 3: redness and a little pus; the swab grew Staphylococcus "
                "aureus. Treated with oral antibiotics and dressings."
            )
            extra = [("T81.4", "Superficial port-site infection (treated)")]
            oral = _course_antibiotic(c, 5)
        elif kind == "ileus":
            complications = "Paralytic ileus on days 1 to 3 (bloating, vomiting), managed with nil by mouth and intravenous fluids; settled without a tube."
            extra = [("K56.0", "Postoperative paralytic ileus (resolved)")]
        else:
            complications = "Urinary retention on the first night, catheterised for 24 hours; voided normally afterwards."
            extra = [("R33", "Postoperative urinary retention (resolved)")]
    prophylaxis = "intravenous ciprofloxacin and metronidazole" if allergic else "intravenous ceftriaxone and metronidazole"
    imaging = (
        "CT abdomen: thickened appendix of 11 mm with surrounding fat stranding; no abscess."
        if c.age >= 45
        else f"Ultrasound: non-compressible appendix of {rng.randint(8, 11)} mm with a little free fluid."
    )
    name = "Laparoscopic appendicectomy"
    return Admission(
        title="Acute appendicitis",
        admitted=c.admitted,
        discharged=discharged,
        service="General Surgery",
        doctor=YALCIN,
        complaint=join(
            f"{c.opening()}. {rng.randint(14, 30)} hours of pain that began around the navel and moved to the right lower abdomen,",
            "with loss of appetite, nausea and one episode of vomiting.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(temp=(37.5, 38.3), pulse=(88, 106)),
            "Tender in the right iliac fossa with guarding and rebound tenderness; Rovsing's sign positive.",
        ),
        course=join(
            f"WBC {_number(rng.uniform(12.5, 16.8))} ×10³/µL with neutrophilia, CRP {rng.randint(35, 120)} mg/L.",
            imaging,
            f"{name} on {day_text(performed)} (see the operation report), with {prophylaxis}.",
            "Eating and walking on the first day after surgery." if not c.complicated else "",
        ),
        admission_diagnoses=(("R10.3", "Right iliac fossa pain, suspected appendicitis"),),
        discharge_diagnoses=(("K35.8", "Acute appendicitis, not perforated"), *extra, *c.chronic()),
        prescription=(
            "Paracetamol 1 g orally up to four times daily as needed",
            *((f"{c.free('Ibuprofen')} 400 mg orally up to three times daily with food for 5 days",) if not p.no_nsaid(c.admitted) else ()),
            *oral,
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Wound check with the family doctor on day 7–10; absorbable sutures, no removal needed.",
            "No heavy lifting for 2 weeks. Histology reviewed: no further follow-up needed.",
        ),
        outcome="Recovered",
        complications=complications,
        procedure=ProcedureReport(
            performed=performed,
            name=name,
            operation=True,
            pre_diagnosis="Acute appendicitis",
            post_diagnosis="Acute suppurative appendicitis, not perforated",
            team=c.team(YALCIN),
            anaesthesia="General anaesthesia with endotracheal intubation",
            wound_class="Clean-contaminated",
            note=join(
                "Open (Hasson) entry at the umbilicus, 12 mm port; two 5 mm ports in the left iliac fossa and suprapubic region.",
                f"Inflamed, swollen appendix{c.pick(' with fibrinous exudate', '')}, not perforated; {c.pick('a little', 'about 20 mL of')} serous",
                "fluid in the pelvis, aspirated. Mesoappendix divided with diathermy; base secured with two endoloops and divided;",
                "appendix removed in a retrieval bag. Umbilical fascia closed; skin closed with absorbable subcuticular sutures.",
            ),
            blood_loss="Minimal (under 10 mL)",
            specimen="Appendix: acute suppurative appendicitis; no neoplasm",
            body_site="Appendix",
        ),
    )


def inguinal_hernia(c: Ctx) -> Admission:
    rng = c.rng
    side = c.pick("right", "left")
    discharged = c.admitted + timedelta(days=rng.randint(0, 1)) if not c.complicated else c.admitted + timedelta(days=rng.randint(1, 2))
    complications, extra = "None", []
    if c.complicated:
        if c.age >= 50:
            complications = "Urinary retention after the spinal anaesthetic; catheterised overnight and voided normally the next morning."
            extra = [("R33", "Postoperative urinary retention (resolved)")]
        else:
            complications = f"Scrotal bruising and a small {side} groin haematoma on day 1, managed with support and ice; no drainage needed."
            extra = [("T81.0", "Groin haematoma after hernia repair (resolved)")]
    sac = c.pick("indirect", "direct")
    name = f"Open {side} inguinal hernia repair with mesh"
    home = "" if c.complicated else "Home the same evening." if discharged == c.admitted else "Home the next morning."
    return Admission(
        title=f"{side.capitalize()} inguinal hernia",
        admitted=c.admitted,
        discharged=discharged,
        service="General Surgery",
        doctor=YALCIN,
        complaint=join(
            f"{c.opening()}, admitted electively for repair of a {side} inguinal hernia.",
            f"Groin swelling for {c.pick('about a year', 'two years', 'eighteen months')}, aching {'after long walks' if c.age >= 62 else 'at the end of the working day'}; always",
            "reducible, no episodes of obstruction.",
        ),
        past_history=c.past(),
        examination=join(c.vitals(), f"Reducible {side} inguinal hernia with a cough impulse, not extending into the scrotum. Other side normal."),
        course=join(
            f"{name} (Lichtenstein) under spinal anaesthesia on the day of admission (see the operation report).",
            "Walking and passing urine within six hours." if not c.complicated else "",
            home,
        ),
        admission_diagnoses=(("K40.9", f"{side.capitalize()} inguinal hernia"),),
        discharge_diagnoses=(("K40.9", f"Unilateral inguinal hernia, {side}, {sac}, without obstruction or gangrene"), *extra, *c.chronic()),
        prescription=("Paracetamol 1 g orally up to four times daily as needed", *c.continuing(discharged)),
        recommendations="No heavy lifting for 4 weeks; normal walking encouraged. Wound check on day 7. Surgical clinic in 6 weeks.",
        outcome="Recovered",
        complications=complications,
        procedure=ProcedureReport(
            performed=c.admitted,
            name=name,
            operation=True,
            pre_diagnosis=f"{side.capitalize()} inguinal hernia",
            post_diagnosis=f"{side.capitalize()} {sac} inguinal hernia",
            team=c.team(YALCIN),
            anaesthesia="Spinal anaesthesia",
            wound_class="Clean",
            note=join(
                f"{side.capitalize()} groin crease incision. External oblique opened; ilioinguinal nerve identified and preserved.",
                "Indirect sac dissected off the cord and reduced." if sac == "indirect" else "Direct bulge of the posterior wall reduced and imbricated.",
                "Posterior wall reinforced with a 6 × 11 cm polypropylene mesh, sutured to the inguinal ligament with continuous",
                "polypropylene and to the conjoint tendon; tails crossed around the cord. External oblique and skin closed with absorbable sutures.",
            ),
            body_site=f"{side.capitalize()} inguinal region",
            device="Polypropylene mesh 6 × 11 cm",
        ),
    )


def septoplasty(c: Ctx) -> Admission:
    side = c.pick("left", "right")
    discharged = c.admitted + timedelta(days=1) if not c.complicated else c.admitted + timedelta(days=2)
    complications, extra = "None", []
    if c.complicated:
        complications = "Nosebleed after the packs were removed on day 1; settled with a new pack for 24 hours; no further bleeding."
        extra = [("T81.0", "Postoperative nosebleed (settled)")]
    return Admission(
        title="Deviated nasal septum",
        admitted=c.admitted,
        discharged=discharged,
        service="Otorhinolaryngology",
        doctor=ENT,
        complaint=join(
            f"{c.opening()}, admitted electively. Long-standing {side}-sided nasal blockage, worse at night, with mouth breathing and",
            f"snoring; no better after three months of a steroid nasal spray. {c.pick('Broke the nose playing football as a teenager.', 'No nasal injury remembered.')}",
        ),
        past_history=c.past(),
        examination=join(c.vitals(), f"Septum deviated to the {side} with a bony spur touching the inferior turbinate. No polyps. Ears and throat normal."),
        course=join(
            "Septoplasty under general anaesthesia on the day of admission (see the operation report).",
            "Packs removed the next morning; breathing through the nose better." if not c.complicated else "",
        ),
        admission_diagnoses=(("J34.2", "Deviated nasal septum"),),
        discharge_diagnoses=(("J34.2", f"Deviated nasal septum to the {side}, corrected"), *extra, *c.chronic()),
        prescription=(
            "Saline nasal rinse twice daily for 2 weeks",
            "Paracetamol 1 g orally up to four times daily as needed",
            *c.continuing(discharged),
        ),
        recommendations="Do not blow the nose for a week; sneeze with the mouth open. ENT clinic in 2 weeks.",
        outcome="Recovered",
        complications=complications,
        procedure=ProcedureReport(
            performed=c.admitted,
            name="Septoplasty",
            operation=True,
            pre_diagnosis="Deviated nasal septum",
            post_diagnosis=f"Deviated nasal septum to the {side} with a bony spur",
            team=c.team(ENT),
            anaesthesia="General anaesthesia with endotracheal intubation",
            wound_class="Clean-contaminated",
            note=join(
                "Hemitransfixion incision; mucoperichondrial and mucoperiosteal flaps raised on both sides. Deviated part of the",
                "quadrilateral cartilage and the bony spur of the vomer removed; caudal strut preserved. Flaps re-approximated with",
                "a quilting suture; incision closed. Nasal packs on both sides.",
            ),
            specimen="Septal cartilage and bone, not sent for histology",
            body_site="Nasal septum",
        ),
    )


def carpal_tunnel(c: Ctx) -> Admission:
    rng = c.rng
    side = c.pick("right", "left")
    discharged = c.admitted if not c.complicated else c.admitted + timedelta(days=1)
    complications, extra = "None", []
    if c.complicated:
        complications = "Fainted briefly on standing after the procedure (vasovagal); observed overnight with a normal ECG and blood pressure."
        extra = [("R55", "Vasovagal faint after the procedure (resolved)")]
    name = f"Open {side} carpal tunnel release"
    return Admission(
        title=f"Carpal tunnel syndrome, {side}",
        admitted=c.admitted,
        discharged=discharged,
        service="Orthopaedics and Traumatology",
        doctor=ORTHOPAEDICS,
        complaint=join(
            f"{c.opening()}, admitted as a day case. {rng.randint(8, 18)} months of numbness and tingling in the {side} thumb, index and",
            "middle fingers, waking at night; no better with a night splint. Nerve conduction studies: moderate median nerve compression",
            "at the wrist.",
        ),
        past_history=c.past(),
        examination=join(c.vitals(), f"Positive Tinel's and Phalen's signs at the {side} wrist; no thenar wasting; thumb abduction strong."),
        course=join(f"{name} under local anaesthesia (see the operation report).", "Home the same day." if not c.complicated else ""),
        admission_diagnoses=(("G56.0", f"Carpal tunnel syndrome, {side}"),),
        discharge_diagnoses=(("G56.0", f"Carpal tunnel syndrome, {side}, released"), *extra, *c.chronic()),
        prescription=("Paracetamol 1 g orally up to four times daily as needed", *c.continuing(discharged)),
        recommendations=join(
            "Keep the hand raised for 48 hours and move the fingers often. Keep the dressing dry.",
            "Sutures out at the family doctor's on day 12. Hand clinic in 6 weeks.",
        ),
        outcome="Recovered",
        complications=complications,
        procedure=ProcedureReport(
            performed=c.admitted,
            name=name,
            operation=True,
            pre_diagnosis=f"Carpal tunnel syndrome, {side}",
            post_diagnosis=f"Carpal tunnel syndrome, {side}; median nerve compressed",
            team=c.team(ORTHOPAEDICS, anaesthetist=False),
            anaesthesia="Local anaesthesia (lidocaine 1% with adrenaline), no tourniquet",
            wound_class="Clean",
            note=join(
                "3 cm palmar incision in line with the radial border of the ring finger. Palmar fascia and transverse carpal ligament",
                "divided completely under direct vision. Median nerve flattened and reddened beneath the ligament; motor branch intact.",
                "Skin closed with interrupted nylon sutures; soft bulky dressing.",
            ),
            body_site=f"{side.capitalize()} wrist",
        ),
    )


def fracture_fixation(c: Ctx) -> Admission:
    rng, p = c.rng, c.p
    side = c.pick("right", "left")
    ankle = c.pick(True, False)
    performed = c.admitted + timedelta(days=rng.randint(1, 2) if ankle else rng.randint(0, 1))
    discharged = performed + timedelta(days=rng.randint(1, 2)) if not c.complicated else performed + timedelta(days=rng.randint(3, 4))
    complications, extra, oral = "None", [], ()
    if c.complicated:
        if ankle:
            complications = "Superficial infection of the lateral wound on day 3, treated with oral antibiotics; the plate was not involved."
            extra = [("T81.4", "Superficial wound infection after fixation (treated)")]
            oral = _course_antibiotic(c, 7)
        else:
            text, diagnosis = _phlebitis(c, 2)
            complications, extra = text, [diagnosis]
    if ankle:
        name = f"Open reduction and internal fixation of {side} ankle fracture"
        how = c.pick("Twisted the ankle stepping off a kerb", "Slipped on wet stairs", "Went over on the ankle on uneven ground")
        return Admission(
            title=f"Fracture of the {side} ankle (lateral malleolus)",
            admitted=c.admitted,
            discharged=discharged,
            service="Orthopaedics and Traumatology",
            doctor=ORTHOPAEDICS,
            complaint=f"{c.opening()}. {how}; immediate pain and swelling of the {side} ankle, unable to bear weight.",
            past_history=c.past(),
            examination=join(
                c.vitals(pulse=(80, 98)),
                f"Swelling and bruising over the {side} lateral malleolus, tender; skin intact; foot pulses and sensation normal.",
            ),
            course=join(
                f"X-ray: displaced Weber B fracture of the {side} lateral malleolus with lateral shift of the talus.",
                f"Backslab and elevation until the swelling settled; operation on {day_text(performed)} (see the operation report).",
                "Prophylactic enoxaparin while in plaster. Walking with crutches without putting weight on the leg before discharge.",
            ),
            admission_diagnoses=(("S82.6", f"Fracture of the {side} lateral malleolus"),),
            discharge_diagnoses=(("S82.6", f"Fracture of the {side} lateral malleolus (Weber B), fixed"), *extra, *c.chronic()),
            prescription=(
                "Enoxaparin 40 mg subcutaneously once daily for 6 weeks, while in plaster",
                "Paracetamol 1 g orally four times daily as needed",
                *oral,
                *c.continuing(discharged),
            ),
            recommendations=join(
                "No weight on the leg for 6 weeks; keep it raised. Fracture clinic in 2 weeks for the wound and an X-ray.",
                "The plate and screws stay in unless they cause trouble.",
            ),
            outcome="Improved",
            complications=complications,
            procedure=ProcedureReport(
                performed=performed,
                name=name,
                operation=True,
                pre_diagnosis=f"Displaced Weber B fracture of the {side} lateral malleolus",
                post_diagnosis="Same; syndesmosis stable on testing",
                team=c.team(ORTHOPAEDICS),
                anaesthesia="Spinal anaesthesia; thigh tourniquet",
                wound_class="Clean",
                note=join(
                    "Lateral approach; superficial peroneal nerve protected. Oblique fracture reduced and held with a lag screw, then",
                    "neutralised with a one-third tubular plate and screws. Syndesmosis stable on the hook test. Fluoroscopy confirmed",
                    "reduction and a congruent mortise. Wound closed in layers; below-knee backslab.",
                ),
                body_site=f"{side.capitalize()} ankle",
                device="One-third tubular plate with lag screw",
            ),
        )
    name = f"Open reduction and internal fixation of {side} distal radius fracture"
    how = c.pick("Slipped on a wet floor", "Tripped over a kerb", "Fell off a bicycle")
    return Admission(
        title=f"Fracture of the {side} distal radius",
        admitted=c.admitted,
        discharged=discharged,
        service="Orthopaedics and Traumatology",
        doctor=ORTHOPAEDICS,
        complaint=f"{c.opening()}. {how} onto an outstretched {side} hand; pain, swelling and deformity of the wrist.",
        past_history=c.past(),
        examination=join(
            c.vitals(pulse=(80, 98)),
            f"Dinner-fork deformity of the {side} wrist; skin intact; radial pulse present; sensation in the fingers normal.",
        ),
        course=join(
            f"X-ray: dorsally displaced, intra-articular fracture of the {side} distal radius with shortening.",
            f"Backslab and elevation; operation on {day_text(performed)} (see the operation report).",
            "Fingers moving well and the hand warm before discharge.",
        ),
        admission_diagnoses=(("S52.5", f"Fracture of the {side} distal radius"),),
        discharge_diagnoses=(("S52.5", f"Fracture of the lower end of the {side} radius, intra-articular, fixed"), *extra, *c.chronic()),
        prescription=("Paracetamol 1 g orally four times daily as needed", *c.continuing(discharged)),
        recommendations=join(
            "Keep the hand raised; move the fingers often. Fracture clinic in 2 weeks for the wound and an X-ray; hand therapy from then.",
            "The plate stays in unless it causes trouble.",
        ),
        outcome="Improved",
        complications=complications,
        procedure=ProcedureReport(
            performed=performed,
            name=name,
            operation=True,
            pre_diagnosis=f"Displaced intra-articular fracture of the {side} distal radius",
            post_diagnosis="Same",
            team=c.team(ORTHOPAEDICS),
            anaesthesia="Infraclavicular brachial plexus block with sedation; arm tourniquet",
            wound_class="Clean",
            note=join(
                "Volar (modified Henry) approach through the flexor carpi radialis sheath; pronator quadratus elevated. Fracture",
                "reduced under fluoroscopy and fixed with a volar locking plate and screws; joint surface restored. Pronator",
                "quadratus repaired; skin closed. Volar plaster slab.",
            ),
            body_site=f"{side.capitalize()} wrist (distal radius)",
            device="Volar locking plate (titanium)",
        ),
    )


# ----------------------------------------------------------------- the reports of two events the stories already hold


def knee_replacement(c: Ctx, procedure: dict) -> Admission:
    """The right total knee replacement already on p-1009's chart; its report adds no Procedure."""
    rng = c.rng
    performed = _performed(procedure)
    discharged = performed + timedelta(days=4)
    return Admission(
        title="Osteoarthritis of the right knee; total knee replacement",
        admitted=c.admitted,
        discharged=discharged,
        service="Orthopaedics and Traumatology",
        doctor=ORTHOPAEDICS,
        complaint=join(
            f"{c.opening()}, admitted electively for a right total knee replacement. Several years of right knee pain, now at night",
            "and limiting walking to a few hundred metres despite painkillers, physiotherapy and steroid injections.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(),
            "Right knee: varus deformity, crepitus, fixed flexion of 10°, flexion to 100°. Ligaments stable. Foot pulses normal.",
        ),
        course=join(
            "X-rays: advanced osteoarthritis of the right knee with loss of the medial joint space and osteophytes.",
            f"Right total knee replacement on {day_text(performed)} (see the operation report).",
            "Walking with a frame on day 1 and with crutches on day 3; flexion to 90° at discharge. Wound clean and dry.",
        ),
        admission_diagnoses=(("M17.1", "Primary osteoarthritis of the right knee"),),
        discharge_diagnoses=(("M17.1", "Primary osteoarthritis of the right knee, treated by total knee replacement"), *c.chronic()),
        prescription=(
            "Enoxaparin 40 mg subcutaneously once daily for 14 days",
            "Paracetamol 1 g orally four times daily",
            f"{c.free('Tramadol')} 50 mg orally up to three times daily as needed for 7 days",
            *c.continuing(discharged),
        ),
        recommendations=join(
            "Physiotherapy exercises daily; crutches for about 6 weeks. Clips out at the family doctor's on day 14.",
            "Orthopaedic clinic in 6 weeks with an X-ray.",
        ),
        outcome="Improved",
        procedure=ProcedureReport(
            performed=performed,
            name=procedure["code"]["text"] + " (cemented, posterior-stabilised)",
            operation=True,
            pre_diagnosis="Primary osteoarthritis of the right knee",
            post_diagnosis="Same; tricompartmental osteoarthritis",
            team=c.team(ORTHOPAEDICS),
            anaesthesia="Spinal anaesthesia with an adductor canal block",
            wound_class="Clean",
            note=join(
                "Thigh tourniquet. Midline incision and medial parapatellar arthrotomy. Bone cuts with intramedullary femoral and",
                "extramedullary tibial guides; balanced in flexion and extension. Cemented posterior-stabilised femoral and tibial",
                f"components with a polyethylene insert; patella not resurfaced. Layered closure; skin clips. Tourniquet time {rng.randint(70, 90)} minutes.",
            ),
            blood_loss=f"About {rng.randint(3, 6) * 50} mL",
            drains="One suction drain, removed on day 1",
            body_site="Right knee",
            device="Cemented total knee prosthesis",
        ),
    )


def ercp(c: Ctx, procedure: dict) -> Admission:
    """The ERCP already on p-2042's chart, done as a day case; its report adds no Procedure."""
    chart = c.p.chart

    def reported(title: str) -> date:
        found = next(item for item in chart.resources if item["resourceType"] == "DiagnosticReport" and item["code"]["text"] == title)
        return date.fromisoformat(found["effectiveDateTime"][:10])

    ultrasound, mrcp = reported("Ultrasound abdomen"), reported("MRCP")
    return Admission(
        title="Common bile duct stone; ERCP",
        admitted=c.admitted,
        discharged=c.admitted,
        service="Gastroenterology",
        doctor=KOC,
        complaint=join(
            f"{c.age}-year-old woman with three months of biliary-type pain and obstructive jaundice, now settling, admitted as a day case.",
            f"Ultrasound on {day_text(ultrasound)}: gallstones and a 9 mm common bile duct. MRCP on {day_text(mrcp)}: 7 mm stone in the",
            "distal common bile duct.",
        ),
        past_history=c.past(),
        examination=join(c.vitals(), "Mild scleral icterus. Abdomen soft, mildly tender in the right upper quadrant."),
        course=join(
            "ERCP in the morning (see the procedure report): biliary sphincterotomy and balloon extraction of the stone; duct clear.",
            "Comfortable afterwards, tolerating fluids, no abdominal pain. Home the same evening.",
        ),
        admission_diagnoses=(("K80.5", "Choledocholithiasis"),),
        discharge_diagnoses=(("K80.5", "Common bile duct stone, cleared at ERCP"), *c.chronic()),
        prescription=("Paracetamol 1 g orally up to four times daily as needed",),
        recommendations=join(
            "Referred to general surgery for laparoscopic cholecystectomy, ideally within 6–8 weeks. Low-fat diet meanwhile.",
            "Return at once with abdominal pain, fever or yellowing of the eyes.",
        ),
        outcome="Improved",
        procedure=ProcedureReport(
            performed=c.admitted,
            name=procedure["code"]["text"],
            operation=False,
            pre_diagnosis="Common bile duct stone on MRCP",
            post_diagnosis="Choledocholithiasis (7 mm distal common bile duct stone), cleared",
            team=f"{KOC} (endoscopist)",
            anaesthesia=f"Deep sedation with propofol ({c.pick(*ANAESTHETISTS)})",
            wound_class="Not applicable",
            note=join(
                "Normal papilla. Selective biliary cannulation. Cholangiogram: 7 mm filling defect in the distal common bile duct; duct",
                "9 mm. Biliary sphincterotomy; stone extracted with a balloon; occlusion cholangiogram shows a clear duct. No",
                "pancreatic duct cannulation. No immediate bleeding.",
            ),
            blood_loss="None",
            body_site="Common bile duct",
        ),
    )


# ----------------------------------------------------------------- choosing the episodes


@dataclass(frozen=True)
class Episode:
    name: str
    kind: str  # "medical", "diagnostic" or "operation"
    build: Callable[[Ctx], Admission]
    fits: Callable[[Patient, date], bool] = lambda p, day: True
    weight: Callable[[Patient, date], float] = lambda p, day: 1.0  # how common it is, against the others of its kind


# From when dexamethasone was standard for COVID-19 pneumonia needing oxygen, to the end of 2021.
COVID_FROM, COVID_TO = date(2020, 7, 1), date(2021, 12, 15)
# Their notes say which abdominal imaging came first (p-2041: "No prior imaging"; p-2042: gallstones first found in 2026).
NO_ABDOMINAL_IMAGING = ("colorectal_cancer", "gallstone_disease")

EPISODES = (
    Episode("pneumonia", "medical", pneumonia, weight=lambda p, day: 4.0 if p.age(day) >= 60 else 2.5),
    Episode("gastroenteritis", "medical", gastroenteritis, weight=lambda p, day: 3.0),
    Episode("pyelonephritis", "medical", pyelonephritis, weight=lambda p, day: 3.0 if p.female else 1.0),
    Episode("cellulitis", "medical", cellulitis, weight=lambda p, day: 1.5),
    Episode(
        "renal colic", "medical", renal_colic, lambda p, day: p.story not in NO_ABDOMINAL_IMAGING,
        weight=lambda p, day: 1.0 if p.female else 2.0,
    ),
    Episode("head injury", "medical", head_injury, weight=lambda p, day: 1.0),
    Episode("fracture", "medical", fracture_treated_without_surgery, lambda p, day: p.age(day) >= 50, weight=lambda p, day: 1.5),
    Episode("vertigo", "medical", vertigo, lambda p, day: p.age(day) >= 30, weight=lambda p, day: 0.6),
    Episode("bleeding ulcer", "diagnostic", bleeding_ulcer, lambda p, day: p.story not in ("colorectal_cancer", "iron_deficiency")),
    Episode(
        "colonoscopy", "diagnostic", colonoscopy,
        lambda p, day: p.age(day) >= 50 and p.story not in ("colorectal_cancer", "iron_deficiency"), weight=lambda p, day: 1.5,
    ),
    Episode(
        "angiography", "diagnostic", angiography,
        lambda p, day: p.age(day) >= 45 and p.story not in ("colorectal_cancer", "iron_deficiency", "heart_failure"),
    ),
    Episode("appendicectomy", "operation", appendicectomy, lambda p, day: p.age(day) <= 70, weight=lambda p, day: 2.0),
    Episode("inguinal hernia", "operation", inguinal_hernia, lambda p, day: not p.female, weight=lambda p, day: 2.5),
    Episode("septoplasty", "operation", septoplasty, lambda p, day: 18 <= p.age(day) <= 60),
    Episode("carpal tunnel", "operation", carpal_tunnel, lambda p, day: p.age(day) >= 30, weight=lambda p, day: 2.0 if p.female else 1.0),
    Episode("fracture fixation", "operation", fracture_fixation, weight=lambda p, day: 1.5),
)
COVID = Episode("covid", "medical", covid)
CHILDBIRTH = Episode("childbirth", "medical", childbirth)


def _childbirth_day(p: Patient, rng: random.Random, low: date, high: date) -> date | None:
    """A day for a birth that the notes allow, or None."""
    if not p.female or p.story in ("gallstone_disease", "colorectal_cancer"):
        return None
    born = p.chart.birth_date
    if p.story == "iron_deficiency":
        # Only where her first note says when her last pregnancy was.
        if "last pregnancy six years ago" not in p.notes:
            return None
        first = min(date.fromisoformat(item["date"][:10]) for item in p.chart.resources if item["resourceType"] == "DocumentReference")
        day = first - timedelta(days=6 * 365 + rng.randint(-60, 60))
        return day if low <= day <= high and 20 <= p.age(day) <= 42 else None
    start = max(low, date(born.year + 21, born.month, min(born.day, 28)))
    end = min(high, date(born.year + 40, born.month, min(born.day, 28)))
    if start > end or rng.random() < 0.4:
        return None
    return start + timedelta(days=rng.randint(0, (end - start).days))


def plan(p: Patient, rng: random.Random, low: date, high: date, fixed: list[date]) -> list[tuple[Episode, date, bool]]:
    """The episodes for one patient between `low` and `high`, each with its admission day and whether it carries a
    complication. `fixed` are the days of reports already decided, which the others keep clear of."""
    total = rng.randint(5, 7)
    chosen: list[tuple[Episode, date]] = []
    taken = list(fixed)

    def free(day: date) -> bool:
        return low <= day <= high and all(abs((day - other).days) >= 90 for other in taken)

    covid_low, covid_high = max(low, COVID_FROM), min(high, COVID_TO)
    if covid_low < covid_high and rng.random() < 0.55:
        day = covid_low + timedelta(days=rng.randint(0, (covid_high - covid_low).days))
        if free(day):
            chosen.append((COVID, day))
            taken.append(day)
    birth = _childbirth_day(p, rng, low, high)
    if birth and free(birth):
        chosen.append((CHILDBIRTH, birth))
        taken.append(birth)

    needed = total - len(fixed) - len(chosen)
    days: list[date] = []
    for _ in range(1000):
        if len(days) == needed:
            break
        day = low + timedelta(days=rng.randint(0, (high - low).days))
        if free(day):
            days.append(day)
            taken.append(day)

    operations = 0 if p.closed else rng.choice((0, 1, 1, 2))
    diagnostics = rng.choice((0, 1, 1))
    kinds = (["operation"] * operations + ["diagnostic"] * diagnostics + ["medical"] * len(days))[: len(days)]
    rng.shuffle(kinds)
    used: set[str] = set()
    for day, kind in zip(days, kinds):
        options = [item for item in EPISODES if item.kind == kind and item.name not in used and item.fits(p, day)]
        if not options:
            options = [item for item in EPISODES if item.kind == "medical" and item.name not in used and item.fits(p, day)]
        episode = rng.choices(options, weights=[item.weight(p, day) for item in options])[0]
        used.add(episode.name)
        chosen.append((episode, day))

    flags = [rng.random() < 0.3 for _ in chosen]
    if not any(flags):
        flags[rng.randrange(len(flags))] = True
    return sorted(((episode, day, flag) for (episode, day), flag in zip(chosen, flags)), key=lambda item: item[1])

