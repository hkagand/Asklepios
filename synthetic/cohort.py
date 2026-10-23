"""Synthetic patient stories for the Asklepios demo.

Each story runs in time order. Labs are drawn, the visit happens, the note
quotes results already stored on the chart, and orders placed at a visit are
fulfilled by the next draw. A few orders and referrals are deliberately never
fulfilled, so follow-up tracking has real gaps to find.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from catalog import CLINICIANS
from chart import PatientChart, add_workdays, at, day_text, workday

AYDIN = CLINICIANS["pr-aydin"]
SAHIN = CLINICIANS["pr-sahin"]
KARA = CLINICIANS["pr-kara"]
OZTURK = CLINICIANS["pr-ozturk"]
ARSLAN = CLINICIANS["pr-arslan"]
KOC = CLINICIANS["pr-koc"]
CELIK = CLINICIANS["pr-celik"]
KILIC = CLINICIANS["pr-kilic"]

METFORMIN = ("A10BA02", "metformin")
EMPAGLIFLOZIN = ("A10BK03", "empagliflozin")
DAPAGLIFLOZIN = ("A10BK01", "dapagliflozin")
LINAGLIPTIN = ("A10BH05", "linagliptin")
RAMIPRIL = ("C09AA05", "ramipril")
LOSARTAN = ("C09CA01", "losartan")
AMLODIPINE = ("C08CA01", "amlodipine")
ATORVASTATIN = ("C10AA05", "atorvastatin")
ROSUVASTATIN = ("C10AA07", "rosuvastatin")
LEVOTHYROXINE = ("H03AA01", "levothyroxine sodium")
FERROUS_SULFATE = ("B03AA07", "ferrous sulfate")
TRANEXAMIC_ACID = ("B02AA02", "tranexamic acid")
SACUBITRIL_VALSARTAN = ("C09DX04", "valsartan and sacubitril")
BISOPROLOL = ("C07AB07", "bisoprolol")
SPIRONOLACTONE = ("C03DA01", "spironolactone")
FUROSEMIDE = ("C03CA01", "furosemide")
OXALIPLATIN = ("L01XA03", "oxaliplatin")
FLUOROURACIL = ("L01BC02", "fluorouracil")
CALCIUM_FOLINATE = ("V03AF03", "calcium folinate")
PANITUMUMAB = ("L01FE02", "panitumumab")
ONDANSETRON = ("A04AA01", "ondansetron")
DOXYCYCLINE = ("J01AA02", "doxycycline")
MAGNESIUM_OXIDE = ("A12CC10", "magnesium oxide")

CLINIC_TIMES = (
    (9, 0), (9, 20), (9, 40), (10, 0), (10, 20), (10, 40), (11, 0),
    (11, 20), (13, 30), (13, 50), (14, 10), (14, 30), (14, 50), (15, 10),
)

PANEL_PHRASES = {
    "a1c": "HbA1c",
    "bmp": "basic metabolic panel",
    "cmp": "comprehensive metabolic panel",
    "lipid": "lipid panel",
    "cbc": "CBC",
    "cbc_diff": "CBC with differential",
    "uacr": "urine albumin/creatinine ratio",
    "ferritin": "ferritin",
    "thyroid": "TSH and free T4",
    "tpo": "anti-TPO antibodies",
    "ntprobnp": "NT-proBNP",
    "cea": "CEA",
    "mg": "magnesium",
}


# --------------------------------------------------------------------- values


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cbc(
    rng: random.Random,
    gender: str,
    *,
    hgb: float | None = None,
    mcv: float | None = None,
    plt: float | None = None,
) -> dict[str, float]:
    hgb = hgb if hgb is not None else rng.gauss(14.7 if gender == "male" else 13.2, 0.6)
    return {
        "hgb": hgb,
        "hct": hgb * 2.98 + rng.gauss(0, 0.5),
        "mcv": mcv if mcv is not None else rng.gauss(89, 2.5),
        "wbc": clamp(rng.gauss(6.7, 1.1), 4.4, 9.8),
        "plt": plt if plt is not None else clamp(rng.gauss(252, 45), 165, 380),
    }


def chemistry(
    rng: random.Random,
    *,
    cr: float,
    glu: float | None = None,
    k: float | None = None,
    co2: float | None = None,
    na: float | None = None,
    bun_ratio: tuple[float, float] = (12.0, 17.0),
    hepatic: bool = False,
    alt: float | None = None,
) -> dict[str, float]:
    na = na if na is not None else rng.gauss(140, 1.5)
    co2 = co2 if co2 is not None else rng.gauss(25.5, 1.2)
    values = {
        "na": na,
        "k": k if k is not None else rng.gauss(4.3, 0.2),
        "cl": na - co2 - rng.gauss(11.5, 1.0),
        "co2": co2,
        "bun": cr * rng.uniform(*bun_ratio),
        "cr": cr,
        "glu": glu if glu is not None else rng.gauss(91, 6),
        "ca": rng.gauss(9.4, 0.2),
    }
    if hepatic:
        alt = alt if alt is not None else clamp(rng.gauss(23, 6), 10, 45)
        values |= {
            "alb": rng.gauss(4.3, 0.2),
            "alt": alt,
            "ast": alt * rng.uniform(0.7, 0.9) + 5,
            "alp": clamp(rng.gauss(78, 15), 45, 120),
            "tbil": clamp(rng.gauss(0.6, 0.2), 0.3, 1.1),
        }
    return values


def lipids(*, ldl: float, hdl: float, tg: float) -> dict[str, float]:
    """Total cholesterol is derived so the calculated (Friedewald) LDL matches."""
    hdl, tg = round(hdl), round(tg)
    total = round(ldl + hdl + tg / 5)
    return {"chol": total, "hdl": hdl, "tg": tg, "ldl": total - hdl - tg / 5}


def fasting_glucose(rng: random.Random, a1c: float) -> float:
    return 28.7 * a1c - 46.7 - rng.uniform(6, 18)


# ---------------------------------------------------------------- note text


def sections(*parts: tuple[str, str | list[str]]) -> str:
    blocks = []
    for heading, content in parts:
        text = "\n".join(line for line in content if line) if isinstance(content, list) else content
        blocks.append(f"{heading.upper()}\n{text.strip()}")
    return "\n\n".join(blocks)


def numbered(items: list[str]) -> list[str]:
    return [f"{index}. {item}" for index, item in enumerate(items, 1)]


def bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def describe(panel_keys: list[str]) -> str:
    names = [PANEL_PHRASES[key] for key in panel_keys]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def months_between(earlier: date, later: date) -> int:
    return max(1, round((later - earlier).days / 30.4))


def direction(current: float, prior: float, tolerance: float) -> str:
    if current > prior + tolerance:
        return "up"
    if current < prior - tolerance:
        return "down"
    return "unchanged"


# -------------------------------------------------------------------- story


@dataclass
class Story:
    rng: random.Random
    anchor: date
    chart: PatientChart
    appointment: datetime
    variant: int = 0

    def years_ago(self, years: float) -> date:
        return self.anchor - timedelta(days=round(years * 365.25))

    def schedule(self, *, count: int, interval: int, jitter: int, last_gap: int) -> list[date]:
        """Past clinic days, oldest first, the latest `last_gap` days before the anchor."""
        days, day = [], self.anchor - timedelta(days=last_gap)
        for _ in range(count):
            days.append(workday(day, forward=False))
            day -= timedelta(days=interval + self.rng.randint(-jitter, jitter))
        return sorted(days)

    def clinic(self, day: date) -> datetime:
        hour, minute = self.rng.choice(CLINIC_TIMES)
        return at(workday(day, forward=False), hour, minute)

    def morning_draw(self, day: date) -> datetime:
        return at(workday(day, forward=False), 8, self.rng.choice((5, 12, 20, 34, 41, 50)))

    def before(self, day: date) -> datetime:
        """Pre-visit blood draw, two to five days ahead of a clinic day."""
        return self.morning_draw(day - timedelta(days=self.rng.randint(2, 5)))

    def pre_appointment(self) -> datetime:
        return self.morning_draw(self.appointment.date() - timedelta(days=self.rng.randint(2, 4)))

    def happened(self, moment: datetime) -> bool:
        return moment.date() < self.anchor

    def allergies(self, recorded: date) -> None:
        roll = self.rng.random()
        if roll < 0.15:
            self.chart.allergy("Penicillin", "Urticaria", recorded=recorded, criticality="high", severity="moderate")
        elif roll < 0.22:
            self.chart.allergy(
                "Sulfonamide antibiotics", "Maculopapular rash", recorded=recorded, criticality="low", severity="mild"
            )
        else:
            self.chart.no_known_allergies(recorded)


# ----------------------------------------------- type 2 diabetes, hypertension

ADHERENCE = (
    "Reports taking medications as prescribed.",
    "Admits to missing the evening metformin dose two or three times a week.",
    "Uses a weekly pill organiser and reports no missed doses.",
)
DIABETES_REVIEW = (
    "Denies polyuria, polydipsia, chest pain or visual change.",
    "No hypoglycaemic symptoms. No chest pain or claudication.",
    "No nocturia. No numbness or tingling in the feet.",
)
LIFESTYLE = (
    "Walking 20–30 minutes on most days.",
    "Diet less consistent lately because of shift work.",
    "Has cut down on bread and sugary drinks since the last visit.",
    "Little regular exercise; knee pain limits walking.",
)


def diabetes_hypertension(s: Story) -> None:
    c, rng, doc = s.chart, s.rng, AYDIN
    male = not c.female
    c.set_height(rng.gauss(173 if male else 160, 5))
    weight = rng.uniform(84, 102) if male else rng.uniform(71, 90)
    dm_onset = s.years_ago(rng.uniform(3, 9))
    htn_onset = dm_onset - timedelta(days=rng.randint(300, 1800))
    c.condition("I10", "Essential (primary) hypertension", onset=htn_onset, clinician=doc)
    c.condition("E11.9", "Type 2 diabetes mellitus without complications", onset=dm_onset, clinician=doc)
    s.allergies(htn_onset)
    ramipril = c.start_med(
        "Ramipril 5 mg tablet", "5 mg orally once daily", start=htn_onset, prescriber=doc, atc=RAMIPRIL,
        reason="Essential hypertension",
    )
    metformin = c.start_med(
        "Metformin 500 mg tablet", "500 mg orally twice daily with meals", start=dm_onset, prescriber=doc,
        atc=METFORMIN, reason="Type 2 diabetes mellitus",
    )
    metformin_dose, ramipril_dose = 500, 5
    amlodipine = statin = empagliflozin = None

    days = s.schedule(count=rng.randint(5, 7), interval=91, jitter=10, last_gap=rng.randint(84, 98))
    a1c, floor = rng.uniform(8.0, 8.9), rng.uniform(6.6, 7.0)
    relapse = rng.random() < 0.6
    sbp, dbp = rng.uniform(144, 152), rng.uniform(87, 93)
    cr = rng.uniform(0.82, 1.06) if male else rng.uniform(0.62, 0.84)
    ldl, tg = rng.uniform(136, 162), rng.uniform(165, 235)
    hdl = rng.uniform(37, 45) if male else rng.uniform(43, 52)
    uacr = rng.uniform(14, 62)
    eye_referral_visit = len(days) - 3 if s.variant in (0, 2) else None

    def values(key: str) -> dict[str, float]:
        if key == "a1c":
            return {"a1c": a1c}
        if key == "bmp":
            return chemistry(rng, cr=cr + rng.gauss(0, 0.04), glu=fasting_glucose(rng, a1c), k=rng.gauss(4.5, 0.2))
        if key == "lipid":
            return lipids(ldl=ldl * rng.uniform(0.96, 1.04), hdl=hdl + rng.gauss(0, 2), tg=tg * rng.uniform(0.9, 1.1))
        if key == "cbc":
            return cbc(rng, c.gender)
        return {"uacr": uacr * rng.uniform(0.85, 1.15)}

    planned = ["a1c", "bmp", "lipid", "cbc", "uacr"]
    orders: dict[str, dict] = {}
    pre = s.pre_appointment()
    changed: set[str] = set()
    for i, day in enumerate(days):
        last = i == len(days) - 1
        if i:
            if relapse and i >= len(days) - 2:
                a1c += rng.uniform(0.3, 0.55)
            else:
                a1c = max(floor, a1c - rng.uniform(0.3, 0.6))
        drawn = c.draw(s.before(day), {key: values(key) for key in planned}, orders=orders, requester=doc)
        start = s.clinic(day)
        visit = c.visit(start, doc, "Diabetes follow-up", "Type 2 diabetes mellitus; essential hypertension")
        bp_s, bp_d = round(sbp + rng.gauss(0, 3)), round(dbp + rng.gauss(0, 2))
        vitals = c.vitals(visit, sbp=bp_s, dbp=bp_d, hr=rng.gauss(76, 5), weight=weight + rng.gauss(0, 0.6))

        subjective = [
            f"{c.age_sex(start)} with type 2 diabetes since {dm_onset.year} and hypertension, attending for routine review."
            if i == 0
            else f"Returns for {months_between(days[i - 1], day)}-month diabetes and blood pressure review.",
            rng.choice(ADHERENCE),
        ]
        if "metformin" in changed:
            subjective.append("Loose stools for about two weeks after the metformin increase, now settled.")
        if "empagliflozin" in changed:
            subjective.append("Tolerating empagliflozin; no genital or urinary symptoms.")
        if "amlodipine" in changed:
            subjective.append("Mild ankle swelling in the evenings since starting amlodipine, not troublesome.")
        subjective += [rng.choice(DIABETES_REVIEW), rng.choice(LIFESTYLE)]
        changed = set()
        assessment: list[str] = []
        plan: list[str] = []
        next_panels = ["a1c", "bmp"]

        a1c_now = drawn["a1c"]
        prior = c.last("a1c", c.last("a1c", start)[0])
        trend = f", {direction(a1c_now, prior[1], 0.05)} from {c.fmt('a1c', prior[1])}" if prior else ""
        if a1c_now < 7.0:
            assessment.append(f"Type 2 diabetes — HbA1c {c.fmt('a1c', a1c_now)}{trend}; at individual target (< 7%).")
            plan.append("Continue current diabetes treatment.")
        elif metformin_dose == 500:
            assessment.append(f"Type 2 diabetes — HbA1c {c.fmt('a1c', a1c_now)}{trend}; above target.")
            metformin = c.change_med(
                metformin, when=start, text="Metformin 1000 mg tablet", dosage="1000 mg orally twice daily with meals",
                prescriber=doc, reason="Dose increased; HbA1c above target",
            )
            metformin_dose = 1000
            changed.add("metformin")
            plan.append("Increase metformin to 1000 mg twice daily with meals.")
        elif empagliflozin is None and (prior is None or a1c_now >= prior[1]):
            assessment.append(
                f"Type 2 diabetes — HbA1c {c.fmt('a1c', a1c_now)}{trend}; above target on maximum-dose metformin."
            )
            empagliflozin = c.start_med(
                "Empagliflozin 10 mg tablet", "10 mg orally once daily in the morning", start=start, prescriber=doc,
                atc=EMPAGLIFLOZIN, reason="Type 2 diabetes mellitus; HbA1c above target on metformin",
            )
            changed.add("empagliflozin")
            plan.append("Add empagliflozin 10 mg once daily. Counselled on hydration, genital hygiene and sick-day rules.")
        else:
            improving = prior is not None and a1c_now < prior[1]
            assessment.append(
                f"Type 2 diabetes — HbA1c {c.fmt('a1c', a1c_now)}{trend}; above target{' but improving' if improving else ''}."
            )
            plan.append("No change to diabetes medication today; diet and activity goals reviewed.")

        bp_meds = f"ramipril {ramipril_dose} mg" + (" and amlodipine 5 mg" if amlodipine else "")
        if bp_s >= 140 or bp_d >= 90:
            assessment.append(f"Hypertension — clinic BP {bp_s}/{bp_d} mmHg on {bp_meds}; above target (< 130/80).")
            if amlodipine is None:
                amlodipine = c.start_med(
                    "Amlodipine 5 mg tablet", "5 mg orally once daily", start=start, prescriber=doc, atc=AMLODIPINE,
                    reason="Essential hypertension",
                )
                sbp, dbp = sbp - rng.uniform(8, 12), dbp - rng.uniform(4, 6)
                changed.add("amlodipine")
                plan.append("Add amlodipine 5 mg once daily.")
            elif ramipril_dose == 5:
                ramipril = c.change_med(
                    ramipril, when=start, text="Ramipril 10 mg tablet", dosage="10 mg orally once daily",
                    prescriber=doc, reason="Dose increased; blood pressure above target",
                )
                ramipril_dose = 10
                sbp, dbp = sbp - rng.uniform(5, 8), dbp - rng.uniform(3, 5)
                plan.append("Increase ramipril to 10 mg once daily; potassium and creatinine with the next bloods.")
            else:
                plan.append("Home blood pressure readings for two weeks before the next visit.")
        elif bp_s >= 130 or bp_d >= 80:
            assessment.append(f"Hypertension — clinic BP {bp_s}/{bp_d} mmHg on {bp_meds}; slightly above target.")
            plan.append("Home blood pressure monitoring; bring readings to the next visit.")
        else:
            assessment.append(f"Hypertension — BP {bp_s}/{bp_d} mmHg on {bp_meds}; at target.")

        if "ldl" in drawn:
            ldl_now = drawn["ldl"]
            if statin is None and ldl_now >= 100:
                c.condition("E78.5", "Hyperlipidaemia, unspecified", onset=start.date(), text="Dyslipidaemia", clinician=doc)
                statin = c.start_med(
                    "Atorvastatin 20 mg tablet", "20 mg orally once daily at night", start=start, prescriber=doc,
                    atc=ATORVASTATIN, reason="Dyslipidaemia; type 2 diabetes",
                )
                ldl, tg = ldl * rng.uniform(0.55, 0.62), tg * rng.uniform(0.8, 0.9)
                assessment.append(
                    f"Dyslipidaemia — LDL {c.fmt('ldl', ldl_now)}; above target (< 100 mg/dL) for a person with diabetes."
                )
                plan.append("Start atorvastatin 20 mg at night.")
                next_panels.append("lipid")
            elif statin is not None:
                status = "at target" if ldl_now < 100 else "above target"
                assessment.append(f"Dyslipidaemia — LDL {c.fmt('ldl', ldl_now)} on atorvastatin 20 mg; {status}.")
        if drawn.get("uacr", 0) >= 30:
            assessment.append(f"Moderately increased albuminuria — urine ACR {c.fmt('uacr', drawn['uacr'])}.")
            plan.append("Continue ACE inhibitor; repeat urine ACR at the annual review.")
        if i == eye_referral_visit:
            c.order_service(
                "Ophthalmology referral — diabetic retinopathy screening", category="referral",
                ordered=start + timedelta(minutes=20), due=day + timedelta(days=42), requester=doc, encounter=visit,
                reason="Retinal screening, type 2 diabetes",
            )
            plan.append("Referral to ophthalmology for retinal screening; last screening more than two years ago.")

        next_day = s.appointment.date() if last else days[i + 1]
        if (i + 1) % 4 == 0:
            next_panels += [key for key in ("lipid", "cbc", "uacr") if key not in next_panels]
        planned = next_panels
        orders = c.order_many(
            planned, ordered=start + timedelta(minutes=20), due=pre.date() if last else next_day - timedelta(days=3),
            requester=doc, encounter=visit, reason="Diabetes monitoring",
        )
        plan.append(f"{describe(planned).capitalize()} before the next visit.")
        plan.append(f"Follow-up in {months_between(day, next_day)} months.")
        note_keys = [key for key in ("a1c", "glu", "cr", "egfr", "k", "ldl", "hdl", "tg", "uacr", "hgb") if key in drawn]
        c.note(
            when=start + timedelta(minutes=25), author=doc, title="Internal medicine progress note", encounter=visit,
            body=sections(
                ("Subjective", " ".join(subjective)),
                ("Objective", [vitals, c.labs_text(note_keys, before=start, compare=("a1c",))]),
                ("Assessment", numbered(assessment)),
                ("Plan", bullets(plan)),
            ),
        )

    c.appointment(s.appointment, doc, "Diabetes and blood pressure review")
    if s.happened(pre):
        a1c = a1c + rng.uniform(-0.2, 0.3) if relapse else max(floor, a1c - rng.uniform(0, 0.2))
        c.draw(pre, {key: values(key) for key in planned}, orders=orders, requester=doc)


# ------------------------------------------------------- chronic kidney disease

KIDNEY_REVIEW = (
    "No oedema or breathlessness. Nocturia once nightly.",
    "Feels well. Appetite normal. No urinary symptoms.",
    "Mild afternoon fatigue. No oedema, no itch.",
)


def chronic_kidney_disease(s: Story) -> None:
    c, rng, doc = s.chart, s.rng, OZTURK
    male = not c.female
    diabetic = s.variant % 2 == 0
    c.set_height(rng.gauss(171 if male else 158, 5))
    weight = rng.uniform(74, 92) if male else rng.uniform(62, 80)
    htn_onset = s.years_ago(rng.uniform(10, 18))
    ckd_onset = s.years_ago(rng.uniform(2.5, 5))
    cause = "diabetic kidney disease" if diabetic else "hypertensive nephrosclerosis"
    c.condition("I10", "Essential (primary) hypertension", onset=htn_onset, clinician=AYDIN)
    if diabetic:
        c.condition(
            "E11.2", "Type 2 diabetes mellitus with renal complications", onset=s.years_ago(rng.uniform(10, 16)),
            clinician=AYDIN,
        )
        c.start_med(
            "Linagliptin 5 mg tablet", "5 mg orally once daily", start=ckd_onset, prescriber=AYDIN, atc=LINAGLIPTIN,
            reason="Type 2 diabetes mellitus",
        )
    c.condition(
        "N18.3", "Chronic kidney disease, stage 3", onset=ckd_onset, text=f"Chronic kidney disease stage 3 ({cause})",
        clinician=doc,
    )
    s.allergies(htn_onset)
    losartan = c.start_med(
        "Losartan 50 mg tablet", "50 mg orally once daily", start=ckd_onset, prescriber=doc, atc=LOSARTAN,
        reason="Hypertension; albuminuric chronic kidney disease",
    )
    amlodipine = c.start_med(
        "Amlodipine 5 mg tablet", "5 mg orally once daily", start=htn_onset, prescriber=AYDIN, atc=AMLODIPINE,
        reason="Essential hypertension",
    )
    c.start_med(
        "Atorvastatin 20 mg tablet", "20 mg orally once daily at night", start=ckd_onset, prescriber=doc,
        atc=ATORVASTATIN, reason="Cardiovascular risk reduction in chronic kidney disease",
    )
    losartan_dose, amlodipine_dose = 50, 5
    dapagliflozin = bicarbonate = iron = None
    ferritin_requested = False

    days = s.schedule(count=rng.randint(4, 5), interval=126, jitter=10, last_gap=rng.randint(100, 120))
    cr = rng.uniform(1.42, 1.60) if male else rng.uniform(1.12, 1.26)
    slope = rng.uniform(0.03, 0.06)
    uacr = rng.uniform(180, 420)
    k, co2 = rng.uniform(4.6, 4.9), rng.uniform(21.8, 23.2)
    hgb = rng.uniform(12.4, 12.9) if male else rng.uniform(11.5, 11.9)
    a1c = rng.uniform(6.9, 7.5)
    sbp, dbp = rng.uniform(136, 146), rng.uniform(78, 86)
    ferritin = rng.uniform(48, 140)

    def values(key: str) -> dict[str, float]:
        if key == "bmp":
            return chemistry(
                rng, cr=cr + rng.gauss(0, 0.03), k=k + rng.gauss(0, 0.12), co2=co2 + rng.gauss(0, 0.5),
                glu=fasting_glucose(rng, a1c) if diabetic else None, bun_ratio=(15.0, 20.0),
            )
        if key == "cbc":
            return cbc(rng, c.gender, hgb=hgb, mcv=rng.gauss(88, 2))
        if key == "uacr":
            return {"uacr": uacr * rng.uniform(0.9, 1.1)}
        if key == "a1c":
            return {"a1c": a1c + rng.gauss(0, 0.15)}
        return {"ferritin": ferritin}

    base_panels = ["bmp", "cbc", "uacr"] + (["a1c"] if diabetic else [])
    planned = list(base_panels)
    orders: dict[str, dict] = {}
    pre = s.pre_appointment()
    changed: set[str] = set()
    for i, day in enumerate(days):
        last = i == len(days) - 1
        if i:
            cr += slope + rng.gauss(0, 0.02)
            hgb -= rng.uniform(0.1, 0.3)
            if bicarbonate is None:
                co2 -= rng.uniform(0.2, 0.8)
        drawn = c.draw(s.before(day), {key: values(key) for key in planned}, orders=orders, requester=doc)
        start = s.clinic(day)
        visit = c.visit(start, doc, "Nephrology follow-up", f"Chronic kidney disease stage 3 ({cause})")
        bp_s, bp_d = round(sbp + rng.gauss(0, 3)), round(dbp + rng.gauss(0, 2))
        vitals = c.vitals(visit, sbp=bp_s, dbp=bp_d, hr=rng.gauss(72, 5), weight=weight + rng.gauss(0, 0.5))

        egfr_now, uacr_now = drawn["egfr"], drawn["uacr"]
        egfr_prior = c.last("egfr", c.last("egfr", start)[0])
        g_stage = "G3a" if egfr_now >= 45 else "G3b"
        a_stage = "A3" if uacr_now > 300 else "A2" if uacr_now >= 30 else "A1"

        subjective = [
            f"{c.age_sex(start)} with CKD stage 3 attributed to {cause}, followed in nephrology clinic since {ckd_onset.year}."
            if i == 0
            else f"Routine {months_between(days[i - 1], day)}-month nephrology review.",
            rng.choice(KIDNEY_REVIEW),
            "Avoiding NSAIDs as advised.",
        ]
        if "dapagliflozin" in changed:
            subjective.append("Tolerating dapagliflozin; no urinary infections or dizziness.")
        if "bicarbonate" in changed:
            subjective.append("Taking sodium bicarbonate three times daily without stomach upset.")
        if "iron" in changed:
            subjective.append("Taking oral iron; mild constipation.")
        changed = set()

        trend = f", from {egfr_prior[1]} on {day_text(egfr_prior[0])}" if egfr_prior else ""
        assessment = [
            f"CKD {g_stage} {a_stage} ({cause}) — eGFR {egfr_now} mL/min/1.73m²{trend}; urine ACR {c.fmt('uacr', uacr_now)}."
        ]
        plan: list[str] = []
        next_panels = list(base_panels)
        if dapagliflozin is None:
            dapagliflozin = c.start_med(
                "Dapagliflozin 10 mg tablet", "10 mg orally once daily", start=start, prescriber=doc,
                atc=DAPAGLIFLOZIN, reason="Chronic kidney disease with albuminuria",
            )
            cr += rng.uniform(0.06, 0.1)
            uacr *= rng.uniform(0.65, 0.75)
            changed.add("dapagliflozin")
            plan.append("Start dapagliflozin 10 mg once daily for kidney protection; a small early fall in eGFR is expected.")
        elif uacr_now > 300 and drawn["k"] < 5.0 and losartan_dose == 50:
            losartan = c.change_med(
                losartan, when=start, text="Losartan 100 mg tablet", dosage="100 mg orally once daily",
                prescriber=doc, reason="Dose increased; persistent albuminuria",
            )
            losartan_dose = 100
            k += 0.2
            uacr *= rng.uniform(0.75, 0.85)
            plan.append("Increase losartan to 100 mg once daily; potassium and creatinine with the next bloods.")

        if drawn["k"] >= 5.1:
            assessment.append(f"Mild hyperkalaemia — K {c.fmt('k', drawn['k'])} on losartan.")
            plan.append("Low-potassium diet advice; avoid potassium supplements and salt substitutes.")
        if drawn["co2"] < 22:
            assessment.append(f"Low serum bicarbonate ({c.fmt('co2', drawn['co2'])}), consistent with metabolic acidosis of CKD.")
            if bicarbonate is None:
                bicarbonate = c.start_med(
                    "Sodium bicarbonate 500 mg tablet", "1000 mg orally three times daily", start=start,
                    prescriber=doc, reason="Metabolic acidosis of chronic kidney disease",
                )
                co2 += rng.uniform(2.5, 3.5)
                changed.add("bicarbonate")
                plan.append("Start sodium bicarbonate 1000 mg three times daily.")

        if drawn["hgb"] < (12.0 if c.female else 13.0):
            hb = c.fmt("hgb", drawn["hgb"])
            if "ferritin" in drawn:
                level = c.fmt("ferritin", drawn["ferritin"])
                if drawn["ferritin"] < 100 and iron is None:
                    iron = c.start_med(
                        "Ferrous sulfate 325 mg tablet", "325 mg orally every other day", start=start, prescriber=doc,
                        atc=FERROUS_SULFATE, reason="Iron deficiency in chronic kidney disease",
                    )
                    hgb += 0.4
                    changed.add("iron")
                    assessment.append(f"Anaemia of CKD with low iron stores — Hb {hb}, ferritin {level}.")
                    plan.append("Start oral iron (ferrous sulfate 325 mg every other day).")
                else:
                    assessment.append(f"Anaemia of CKD — Hb {hb}; ferritin {level}, iron replete.")
                    plan.append("No erythropoiesis-stimulating agent indicated at this haemoglobin; monitor.")
            elif not ferritin_requested:
                assessment.append(f"Anaemia — Hb {hb}, likely related to CKD.")
                plan.append("Ferritin with the next bloods.")
                next_panels.append("ferritin")
                ferritin_requested = True
            else:
                assessment.append(f"Anaemia of CKD — Hb {hb}.")

        if bp_s >= 130 or bp_d >= 80:
            assessment.append(f"Hypertension — BP {bp_s}/{bp_d} mmHg; above target (< 130/80).")
            if amlodipine_dose == 5:
                amlodipine = c.change_med(
                    amlodipine, when=start, text="Amlodipine 10 mg tablet", dosage="10 mg orally once daily",
                    prescriber=doc, reason="Dose increased; blood pressure above target",
                )
                amlodipine_dose = 10
                sbp, dbp = sbp - rng.uniform(5, 8), dbp - rng.uniform(3, 5)
                plan.append("Increase amlodipine to 10 mg once daily.")
            else:
                plan.append("Home blood pressure readings; bring them to the next visit.")
        else:
            assessment.append(f"Hypertension — BP {bp_s}/{bp_d} mmHg; at target.")
        if diabetic and "a1c" in drawn:
            assessment.append(f"Type 2 diabetes — HbA1c {c.fmt('a1c', drawn['a1c'])} on linagliptin.")

        next_day = s.appointment.date() if last else days[i + 1]
        planned = next_panels
        orders = c.order_many(
            planned, ordered=start + timedelta(minutes=20), due=pre.date() if last else next_day - timedelta(days=3),
            requester=doc, encounter=visit, reason="Chronic kidney disease monitoring",
        )
        plan.append(f"{describe(planned).capitalize()} before the next visit; follow-up in {months_between(day, next_day)} months.")
        note_keys = [key for key in ("cr", "egfr", "k", "co2", "hgb", "ferritin", "uacr", "a1c") if key in drawn]
        c.note(
            when=start + timedelta(minutes=25), author=doc, title="Nephrology progress note", encounter=visit,
            body=sections(
                ("Subjective", " ".join(subjective)),
                ("Objective", [vitals, c.labs_text(note_keys, before=start, compare=("egfr",))]),
                ("Assessment", numbered(assessment)),
                ("Plan", bullets(plan)),
            ),
        )

    c.appointment(s.appointment, doc, "Nephrology follow-up")
    if s.happened(pre):
        cr += slope / 2
        c.draw(pre, {key: values(key) for key in planned}, orders=orders, requester=doc)


# ------------------------------------------------------ iron deficiency anaemia


def iron_deficiency(s: Story) -> None:
    """Variant 0 never gets the gynaecology appointment or the final bloods."""
    c, rng, doc = s.chart, s.rng, AYDIN
    missed = s.variant == 0
    c.set_height(rng.gauss(162, 5))
    weight = rng.uniform(56, 74)
    s.allergies(s.years_ago(6))
    first = workday(s.anchor - timedelta(days=rng.randint(255, 280)), forward=False)
    second = workday(first + timedelta(days=rng.randint(42, 49)), forward=False)
    third = workday(second + timedelta(days=rng.randint(84, 95)), forward=False)
    review_draw = s.morning_draw(third + timedelta(days=90))

    hgb, mcv, ferritin, plt = rng.uniform(8.9, 10.0), rng.uniform(69, 74), rng.uniform(4, 8), rng.uniform(412, 466)

    # First visit: fatigue and heavy periods.
    drawn = c.draw(
        s.before(first),
        {
            "cbc": cbc(rng, c.gender, hgb=hgb, mcv=mcv, plt=plt),
            "ferritin": {"ferritin": ferritin},
            "thyroid": {"tsh": rng.uniform(1.1, 2.6), "ft4": rng.uniform(1.05, 1.35)},
        },
        requester=doc,
    )
    start = s.clinic(first)
    visit = c.visit(start, doc, "Problem visit", "Fatigue; heavy menstrual bleeding")
    vitals = c.vitals(visit, sbp=rng.gauss(112, 5), dbp=rng.gauss(70, 4), hr=rng.gauss(94, 4), weight=weight)
    c.condition("D50.0", "Iron deficiency anaemia secondary to blood loss (chronic)", onset=first, clinician=doc)
    c.condition(
        "N92.0", "Excessive and frequent menstruation with regular cycle", onset=first, text="Heavy menstrual bleeding",
        clinician=doc,
    )
    iron = c.start_med(
        "Ferrous sulfate 325 mg tablet", "325 mg orally every other day before breakfast", start=start, prescriber=doc,
        atc=FERROUS_SULFATE, reason="Iron deficiency anaemia",
    )
    referral = c.order_service(
        "Gynaecology referral — heavy menstrual bleeding, pelvic ultrasound", category="referral",
        ordered=start + timedelta(minutes=20), due=first + timedelta(days=28), requester=doc, encounter=visit,
        reason="Heavy menstrual bleeding with iron deficiency anaemia",
    )
    orders = c.order_many(
        ["cbc", "ferritin"], ordered=start + timedelta(minutes=20), due=second - timedelta(days=3), requester=doc,
        encounter=visit, reason="Response to oral iron",
    )
    assessment = [
        f"Iron deficiency anaemia — Hb {c.fmt('hgb', drawn['hgb'])}, MCV {c.fmt('mcv', drawn['mcv'])}, "
        f"ferritin {c.fmt('ferritin', drawn['ferritin'])}; most likely from heavy menstrual bleeding.",
        "Heavy menstrual bleeding — needs gynaecological assessment.",
    ]
    if drawn["plt"] > 400:
        assessment.append(f"Reactive thrombocytosis (platelets {c.fmt('plt', drawn['plt'])}).")
    assessment.append("Thyroid function normal.")
    c.note(
        when=start + timedelta(minutes=25), author=doc, title="Internal medicine progress note", encounter=visit,
        body=sections(
            (
                "Subjective",
                f"{c.age_sex(start)} with four months of tiredness, reduced exercise tolerance and heavy periods: "
                "seven-day periods with clots, changing pads every two hours on the heaviest days. No rectal bleeding or "
                "melaena, no weight loss, no dysphagia. Eats little red meat. No NSAID use. "
                + rng.choice(
                    (
                        "Drinks tea with every meal.",
                        "Two children; last pregnancy six years ago.",
                        "Works as a teacher and is struggling to finish the school day.",
                    )
                ),
            ),
            (
                "Objective",
                [
                    vitals,
                    "Conjunctival pallor. Heart sounds normal, no murmur. Abdomen soft, no masses.",
                    c.labs_text(["hgb", "mcv", "plt", "ferritin", "tsh"], before=start),
                ],
            ),
            ("Assessment", numbered(assessment)),
            (
                "Plan",
                bullets(
                    [
                        "Ferrous sulfate 325 mg every other day before breakfast, with water or orange juice; "
                        "avoid tea within an hour of the dose.",
                        "Gynaecology referral for assessment and pelvic ultrasound.",
                        "Coeliac serology if the response to iron is poor.",
                        "Repeat CBC and ferritin in 6 weeks.",
                    ]
                ),
            ),
        ),
    )

    # Second visit: early response.
    hgb += rng.uniform(1.3, 1.8)
    mcv += rng.uniform(4, 6)
    drawn = c.draw(
        s.before(second),
        {"cbc": cbc(rng, c.gender, hgb=hgb, mcv=mcv, plt=rng.uniform(320, 380)), "ferritin": {"ferritin": rng.uniform(12, 19)}},
        orders=orders, requester=doc,
    )
    start = s.clinic(second)
    visit = c.visit(start, doc, "Follow-up", "Iron deficiency anaemia")
    vitals = c.vitals(visit, sbp=rng.gauss(114, 5), dbp=rng.gauss(72, 4), hr=rng.gauss(84, 4), weight=weight + 0.4)
    if missed:
        gynaecology = "Has not yet received a gynaecology appointment."
    else:
        seen = workday(first + timedelta(days=rng.randint(20, 30)), forward=False)
        c.complete(referral)
        c.condition("D25.9", "Leiomyoma of uterus, unspecified", onset=seen, text="Uterine fibroid (intramural, 3 cm)", clinician=doc)
        c.start_med(
            "Tranexamic acid 500 mg tablet", "1 g orally three times daily on heavy days, up to 4 days per cycle",
            start=seen, prescriber=doc, atc=TRANEXAMIC_ACID, reason="Heavy menstrual bleeding (gynaecology advice)",
        )
        gynaecology = (
            f"Seen in gynaecology on {day_text(seen)}: pelvic ultrasound showed a 3 cm intramural fibroid; "
            "tranexamic acid advised for heavy days. Last period lighter."
        )
    orders = c.order_many(
        ["cbc", "ferritin"], ordered=start + timedelta(minutes=20), due=third - timedelta(days=3), requester=doc,
        encounter=visit, reason="Response to oral iron",
    )
    c.note(
        when=start + timedelta(minutes=20), author=doc, title="Internal medicine progress note", encounter=visit,
        body=sections(
            ("Subjective", f"Energy improving. Tolerating iron with mild constipation. {gynaecology}"),
            ("Objective", [vitals, c.labs_text(["hgb", "mcv", "ferritin"], before=start, compare=("hgb",))]),
            (
                "Assessment",
                numbered([f"Iron deficiency anaemia — responding to oral iron (Hb {c.fmt('hgb', drawn['hgb'])})."]),
            ),
            ("Plan", bullets(["Continue ferrous sulfate every other day.", "Repeat CBC and ferritin in 3 months."])),
        ),
    )

    # Third visit: haemoglobin recovered, stores still low.
    hgb, mcv = rng.uniform(12.2, 12.9), rng.uniform(82, 86)
    drawn = c.draw(
        s.before(third),
        {"cbc": cbc(rng, c.gender, hgb=hgb, mcv=mcv), "ferritin": {"ferritin": rng.uniform(24, 36)}},
        orders=orders, requester=doc,
    )
    start = s.clinic(third)
    visit = c.visit(start, doc, "Follow-up", "Iron deficiency anaemia")
    vitals = c.vitals(visit, sbp=rng.gauss(114, 5), dbp=rng.gauss(72, 4), hr=rng.gauss(76, 4), weight=weight + 0.8)
    orders = c.order_many(
        ["cbc", "ferritin"], ordered=start + timedelta(minutes=20), due=review_draw.date(), requester=doc,
        encounter=visit, reason="Iron stores after completing treatment",
    )
    c.note(
        when=start + timedelta(minutes=20), author=doc, title="Internal medicine progress note", encounter=visit,
        body=sections(
            ("Subjective", "Feels well and is back to usual activities. Periods " + ("unchanged." if missed else "lighter on tranexamic acid.")),
            ("Objective", [vitals, c.labs_text(["hgb", "mcv", "ferritin"], before=start, compare=("hgb", "ferritin"))]),
            (
                "Assessment",
                numbered(
                    [
                        f"Iron deficiency anaemia — Hb back in range ({c.fmt('hgb', drawn['hgb'])}); "
                        f"ferritin {c.fmt('ferritin', drawn['ferritin'])}, stores not yet replete."
                    ]
                ),
            ),
            (
                "Plan",
                bullets(
                    [
                        "Continue iron for a further 3 months, then stop.",
                        "CBC and ferritin in 3 months; review with the results.",
                    ]
                ),
            ),
        ),
    )

    c.appointment(s.appointment, doc, "Review of iron studies")
    if not missed and s.happened(review_draw):
        c.draw(
            review_draw,
            {"cbc": cbc(rng, c.gender, hgb=rng.uniform(13.0, 13.6), mcv=rng.uniform(86, 89)), "ferritin": {"ferritin": rng.uniform(48, 70)}},
            orders=orders, requester=doc,
        )


# --------------------------------------------------------------- hypothyroidism


def hypothyroidism(s: Story) -> None:
    c, rng, doc = s.chart, s.rng, ARSLAN
    c.set_height(rng.gauss(161 if c.female else 175, 5))
    weight = rng.uniform(64, 84) if c.female else rng.uniform(80, 95)
    s.allergies(s.years_ago(5))
    days = [workday(s.anchor - timedelta(days=rng.randint(430, 500)), forward=False)]
    for gap in (rng.randint(45, 56), rng.randint(45, 56), rng.randint(165, 185), rng.randint(165, 185)):
        following = workday(days[-1] + timedelta(days=gap), forward=False)
        if (s.anchor - following).days < 45:
            break
        days.append(following)
    tsh = [rng.uniform(8.8, 13.5), rng.uniform(4.8, 6.6), rng.uniform(1.4, 2.8), rng.uniform(1.6, 3.4), rng.uniform(4.4, 5.6)]
    ft4 = [rng.uniform(0.72, 0.86), rng.uniform(0.92, 1.05), rng.uniform(1.1, 1.35), rng.uniform(1.05, 1.3), rng.uniform(0.95, 1.1)]
    ldl, hdl, tg = rng.uniform(148, 172), rng.uniform(48, 58), rng.uniform(110, 160)
    family_history = rng.random() < 0.5
    levothyroxine = None
    orders: dict[str, dict] = {}
    pre = s.pre_appointment()

    for i, day in enumerate(days):
        last = i == len(days) - 1
        start = s.clinic(day)
        if i == 0:
            drawn = c.draw(
                s.before(day),
                {
                    "thyroid": {"tsh": tsh[0], "ft4": ft4[0]},
                    "tpo": {"tpo": rng.uniform(180, 650)},
                    "lipid": lipids(ldl=ldl, hdl=hdl, tg=tg),
                    "cbc": cbc(rng, c.gender),
                },
                requester=AYDIN,
            )
        else:
            panels = {"thyroid": {"tsh": tsh[i], "ft4": ft4[i]}}
            if i == 3:
                panels["lipid"] = lipids(ldl=ldl * rng.uniform(0.76, 0.82), hdl=hdl, tg=tg * 0.9)
            drawn = c.draw(s.before(day), panels, orders=orders, requester=doc)
        visit = c.visit(start, doc, "Endocrinology consultation" if i == 0 else "Endocrinology follow-up", "Hypothyroidism")
        vitals = c.vitals(
            visit, sbp=rng.gauss(122, 6), dbp=rng.gauss(76, 4), hr=rng.gauss(64 if i == 0 else 72, 4),
            weight=weight - (2.0 if i >= 2 else 0),
        )
        tsh_text = c.fmt("tsh", drawn["tsh"])
        ft4_text = c.fmt("ft4", drawn["ft4"])
        next_panels = ["thyroid"]
        if i == 0:
            c.condition(
                "E06.3", "Autoimmune thyroiditis", onset=day, text="Primary hypothyroidism due to Hashimoto thyroiditis",
                clinician=doc,
            )
            levothyroxine = c.start_med(
                "Levothyroxine 50 microgram tablet", "50 micrograms orally once daily, 30–60 minutes before breakfast",
                start=start, prescriber=doc, atc=LEVOTHYROXINE, reason="Primary hypothyroidism",
            )
            pregnancy = " Not pregnant and not planning pregnancy in the next year." if c.female and c.age_on(day) < 45 else ""
            subjective = (
                f"Referred by Dr. Elif Aydın with a raised TSH. {c.age_sex(start)} reporting a year of tiredness, "
                "4 kg weight gain, cold intolerance, constipation and dry skin. "
                + ("Mother has hypothyroidism. " if family_history else "No family history of thyroid disease. ")
                + "No neck swelling, dysphagia or voice change."
                + pregnancy
            )
            exam = "Thyroid diffusely enlarged and firm, non-tender, no discrete nodules. Slow-relaxing ankle reflexes."
            assessment = [
                f"Primary hypothyroidism due to Hashimoto thyroiditis — TSH {tsh_text}, free T4 {ft4_text}, "
                f"anti-TPO {c.fmt('tpo', drawn['tpo'])}.",
                f"LDL {c.fmt('ldl', drawn['ldl'])} — likely partly secondary to hypothyroidism; reassess when euthyroid.",
            ]
            plan = [
                "Start levothyroxine 50 micrograms once daily, 30–60 minutes before breakfast; "
                "separate from calcium or iron by 4 hours.",
                "TSH and free T4 in 6–8 weeks.",
                "Thyroid ultrasound not needed (no palpable nodules).",
            ]
        elif i == 1:
            levothyroxine = c.change_med(
                levothyroxine, when=start, text="Levothyroxine 75 microgram tablet",
                dosage="75 micrograms orally once daily, 30–60 minutes before breakfast", prescriber=doc,
                reason="Dose increased; TSH above target",
            )
            subjective, exam = "Energy a little better; still tired in the afternoons. Taking levothyroxine before breakfast.", ""
            assessment = [f"Hypothyroidism — TSH {tsh_text} on 50 micrograms; still above target."]
            plan = ["Increase levothyroxine to 75 micrograms once daily.", "TSH and free T4 in 6–8 weeks."]
        elif i == 2:
            subjective, exam = "Feels much better. Energy back to normal and weight down 2 kg.", ""
            assessment = [f"Hypothyroidism — TSH {tsh_text}, free T4 {ft4_text} on 75 micrograms; within target."]
            plan = ["Continue levothyroxine 75 micrograms.", "TSH and free T4 in 6 months."]
        elif i == 3:
            subjective, exam = "Well. No palpitations, tremor or heat intolerance.", ""
            assessment = [
                f"Hypothyroidism — TSH {tsh_text}; stable on replacement.",
                f"LDL {c.fmt('ldl', drawn['ldl'])}, lower now that she is euthyroid." if c.female
                else f"LDL {c.fmt('ldl', drawn['ldl'])}, lower now that he is euthyroid.",
            ]
            plan = ["Continue levothyroxine 75 micrograms.", "TSH and free T4 in 6 months."]
        else:
            subjective = (
                "Started a new job three months ago and now takes levothyroxine together with breakfast and coffee. "
                "Mild tiredness again."
            )
            exam = ""
            assessment = [
                f"Hypothyroidism — TSH {tsh_text}, mildly above range; most likely from taking levothyroxine with food and coffee."
            ]
            plan = [
                "Take levothyroxine on waking with water, 30–60 minutes before breakfast and coffee. No dose change.",
                "TSH and free T4 in 8 weeks.",
            ]
        orders = c.order_many(
            next_panels, ordered=start + timedelta(minutes=20),
            due=pre.date() if last else days[i + 1] - timedelta(days=3), requester=doc, encounter=visit,
            reason="Thyroid replacement monitoring",
        )
        keys = [key for key in ("tsh", "ft4", "tpo", "ldl", "hdl", "hgb") if key in drawn]
        c.note(
            when=start + timedelta(minutes=25), author=doc, encounter=visit,
            kind="consult" if i == 0 else "progress",
            title="Endocrinology consultation" if i == 0 else "Endocrinology progress note",
            body=sections(
                ("Subjective", subjective),
                ("Objective", [vitals, exam, c.labs_text(keys, before=start, compare=("tsh",) if i else ())]),
                ("Assessment", numbered(assessment)),
                ("Plan", bullets(plan)),
            ),
        )

    c.appointment(s.appointment, doc, "Thyroid follow-up")
    if s.happened(pre):
        c.draw(pre, {"thyroid": {"tsh": rng.uniform(1.8, 3.2), "ft4": rng.uniform(1.1, 1.3)}}, orders=orders, requester=doc)


# ---------------------------------------------------------------- heart failure


def heart_failure(s: Story) -> None:
    c, rng, doc = s.chart, s.rng, KARA
    male = not c.female
    c.set_height(rng.gauss(172 if male else 160, 5))
    dry = rng.uniform(76, 90) if male else rng.uniform(64, 76)
    htn_onset = s.years_ago(rng.uniform(6, 12))
    c.condition("I10", "Essential (primary) hypertension", onset=htn_onset, clinician=AYDIN)
    s.allergies(htn_onset)
    old_amlodipine = c.start_med(
        "Amlodipine 10 mg tablet", "10 mg orally once daily", start=htn_onset, prescriber=AYDIN, atc=AMLODIPINE,
        reason="Essential hypertension",
    )

    admit = workday(s.anchor - timedelta(days=rng.randint(330, 380)), forward=False)
    discharge = admit + timedelta(days=rng.randint(5, 7))
    arrival, leaving = at(admit, 14, 10), at(discharge, 11, 30)
    stay = c.visit(arrival, doc, "Emergency admission", "Acute decompensated heart failure", inpatient_until=leaving)
    admission_vitals = c.vitals(
        stay, sbp=rng.uniform(146, 158), dbp=rng.uniform(88, 94), hr=rng.uniform(102, 112), weight=dry + rng.uniform(5.5, 7.0)
    )
    c.draw(
        at(admit, 14, 40),
        {
            "cbc": cbc(rng, c.gender, hgb=rng.uniform(13.4, 14.2) if male else rng.uniform(12.3, 13.1)),
            "bmp": chemistry(rng, cr=rng.uniform(1.24, 1.34), na=rng.uniform(133, 135), k=rng.uniform(3.9, 4.2), bun_ratio=(17.0, 21.0)),
            "ntprobnp": {"ntprobnp": rng.uniform(3800, 5200)},
        },
        requester=doc,
    )
    ef = rng.choice((28, 30, 32))
    echo_time = at(workday(admit + timedelta(days=1), forward=True), 11, 0)
    c.report(
        "echo", "Transthoracic echocardiogram", performed=echo_time, issued=echo_time + timedelta(hours=2),
        interpreter=KARA,
        findings=(
            "FINDINGS\n"
            f"Left ventricle dilated (end-diastolic diameter {rng.randint(63, 68)} mm) with global hypokinesis. "
            f"LVEF {ef}% (biplane Simpson). Grade II diastolic dysfunction.\n"
            "Moderate functional mitral regurgitation. Aortic valve trileaflet, no stenosis.\n"
            "Right ventricle normal size, TAPSE 18 mm. Estimated pulmonary artery systolic pressure 42 mmHg.\n"
            "No pericardial effusion."
        ),
        conclusion=f"Dilated left ventricle with severely reduced systolic function (LVEF {ef}%). Moderate functional mitral regurgitation.",
    )
    c.condition(
        "I50.0", "Congestive heart failure", onset=admit, text=f"Heart failure with reduced ejection fraction (LVEF {ef}%)",
        clinician=doc,
    )
    c.condition(
        "I42.0", "Dilated cardiomyopathy", onset=admit,
        text="Non-ischaemic dilated cardiomyopathy (no obstructive coronary disease on angiography)", clinician=doc,
    )
    cr, ntprobnp = rng.uniform(1.16, 1.24), rng.uniform(2100, 2600)
    c.draw(
        s.morning_draw(discharge - timedelta(days=1)),
        {"bmp": chemistry(rng, cr=cr, na=rng.uniform(135, 137), k=4.4, bun_ratio=(18.0, 22.0)), "ntprobnp": {"ntprobnp": ntprobnp}},
        requester=doc,
    )
    c.stop_med(old_amlodipine, end=leaving, reason="Stopped: heart failure with reduced ejection fraction")
    sacubitril = c.start_med(
        "Sacubitril/valsartan 24/26 mg tablet", "24/26 mg orally twice daily", start=leaving, prescriber=doc,
        atc=SACUBITRIL_VALSARTAN, reason="Heart failure with reduced ejection fraction",
    )
    bisoprolol = c.start_med(
        "Bisoprolol 2.5 mg tablet", "2.5 mg orally once daily", start=leaving, prescriber=doc, atc=BISOPROLOL,
        reason="Heart failure with reduced ejection fraction",
    )
    c.start_med(
        "Spironolactone 25 mg tablet", "25 mg orally once daily", start=leaving, prescriber=doc, atc=SPIRONOLACTONE,
        reason="Heart failure with reduced ejection fraction",
    )
    c.start_med(
        "Dapagliflozin 10 mg tablet", "10 mg orally once daily", start=leaving, prescriber=doc, atc=DAPAGLIFLOZIN,
        reason="Heart failure with reduced ejection fraction",
    )
    furosemide = c.start_med(
        "Furosemide 40 mg tablet", "40 mg orally once daily in the morning", start=leaving, prescriber=doc,
        atc=FUROSEMIDE, reason="Fluid overload",
    )
    angiography = day_text(workday(admit + timedelta(days=3), forward=True))
    c.note(
        when=leaving, author=doc, kind="discharge", title="Discharge summary", encounter=stay,
        body=sections(
            ("Admission", f"{day_text(admit)} to {day_text(discharge)}, cardiology ward."),
            (
                "Presentation",
                f"{c.age_sex(arrival)} with hypertension, three weeks of progressive exertional breathlessness, "
                "three-pillow orthopnoea and ankle swelling. No chest pain.",
            ),
            (
                "Findings",
                [
                    f"On arrival: {admission_vitals} Raised JVP, bibasal crackles, pitting oedema to mid-shin.",
                    "ECG: sinus tachycardia, no acute ischaemic changes. Chest X-ray: cardiomegaly, upper lobe diversion, small bilateral effusions.",
                    c.labs_text(["hgb", "na", "k", "cr", "egfr", "ntprobnp"], before=arrival + timedelta(days=1)),
                    f"Echocardiogram {day_text(echo_time)}: dilated LV, LVEF {ef}%, moderate functional mitral regurgitation.",
                    f"Coronary angiography {angiography}: no obstructive coronary artery disease.",
                ],
            ),
            (
                "Diagnosis",
                numbered(
                    [
                        f"Acute decompensated heart failure; new heart failure with reduced ejection fraction (LVEF {ef}%).",
                        "Non-ischaemic dilated cardiomyopathy.",
                        "Hypertension.",
                    ]
                ),
            ),
            (
                "Course",
                "Intravenous furosemide with good diuresis. Guideline-directed medical therapy started and tolerated. "
                + c.labs_text(["cr", "k", "ntprobnp"], before=leaving),
            ),
            (
                "Discharge medication",
                bullets(
                    [
                        "Sacubitril/valsartan 24/26 mg twice daily (new)",
                        "Bisoprolol 2.5 mg once daily (new)",
                        "Spironolactone 25 mg once daily (new)",
                        "Dapagliflozin 10 mg once daily (new)",
                        "Furosemide 40 mg once daily (new)",
                        "Amlodipine stopped",
                    ]
                ),
            ),
            (
                "Follow-up",
                bullets(
                    [
                        "Cardiology clinic in 2 weeks with basic metabolic panel and NT-proBNP.",
                        "Daily weights; contact the heart failure nurse if weight rises by more than 2 kg in 3 days.",
                    ]
                ),
            ),
        ),
    )

    first = workday(discharge + timedelta(days=rng.randint(14, 18)), forward=False)
    days = [first]
    for gap in (rng.randint(42, 49), rng.randint(84, 91), rng.randint(84, 91)):
        days.append(workday(days[-1] + timedelta(days=gap), forward=False))
    final = workday(s.anchor - timedelta(days=rng.randint(38, 46)), forward=False)
    days = [day for day in days if (final - day).days >= 35] + [final]
    stable_ntprobnp = [rng.uniform(1500, 1800), rng.uniform(1050, 1300), rng.uniform(800, 1000), rng.uniform(760, 950)]
    stable_weight = [dry + 0.6, dry + 0.3, dry, dry - 0.2]
    potassium = 4.5
    echo: tuple[datetime, int] | None = None
    echo_reviewed = False
    orders = c.order_many(
        ["bmp", "ntprobnp"], ordered=leaving, due=first - timedelta(days=2), requester=doc, encounter=stay,
        reason="Post-discharge heart failure monitoring",
    )
    pre = s.pre_appointment()

    for i, day in enumerate(days):
        last = i == len(days) - 1
        step = min(i, 3)
        cr += rng.uniform(0.06, 0.1) if last else rng.uniform(0.0, 0.03)
        potassium = min(5.0, potassium + rng.uniform(0.05, 0.15))
        drawn = c.draw(
            s.before(day),
            {
                "bmp": chemistry(
                    rng, cr=cr, k=potassium, na=rng.uniform(134, 136) if last else rng.uniform(136, 139),
                    bun_ratio=(17.0, 22.0),
                ),
                "ntprobnp": {"ntprobnp": rng.uniform(1700, 2200) if last else stable_ntprobnp[step]},
            },
            orders=orders, requester=doc,
        )
        start = s.clinic(day)
        visit = c.visit(start, doc, "Heart failure clinic", "Heart failure with reduced ejection fraction")
        vitals = c.vitals(
            visit, sbp=rng.uniform(108, 118), dbp=rng.uniform(66, 72),
            hr=rng.uniform(70, 76) if last else max(62.0, 84 - 6 * i + rng.gauss(0, 2)),
            weight=dry + rng.uniform(2.3, 2.8) if last else stable_weight[step],
        )
        assessment: list[str] = []
        plan: list[str] = []
        if last:
            subjective = (
                "Weight up about 2.5 kg over ten days with ankle swelling and breathlessness on one flight of stairs. "
                "Two-pillow orthopnoea. Admits to more salty food at family gatherings. Taking all medication."
            )
            exam = "JVP 4 cm above the sternal angle. Fine bibasal crackles. Pitting oedema to mid-shin. ECG: sinus rhythm."
            assessment += [
                "Heart failure with reduced ejection fraction — mild congestion, NYHA class II–III; "
                "NT-proBNP higher than at the last visit.",
                "Likely precipitated by dietary salt; no evidence of infection or arrhythmia.",
            ]
            furosemide = c.change_med(
                furosemide, when=start, text="Furosemide 40 mg tablet",
                dosage="80 mg orally once daily for 7 days, then 40 mg once daily", prescriber=doc,
                reason="Dose temporarily increased; congestion",
            )
            week_check = s.morning_draw(day + timedelta(days=7))
            check = c.order(
                "bmp", ordered=start + timedelta(minutes=20), due=week_check.date(), requester=doc, encounter=visit,
                reason="Renal function and potassium after diuretic increase",
            )
            plan += [
                "Increase furosemide to 80 mg once daily for 7 days, then back to 40 mg.",
                "Basic metabolic panel in 1 week.",
                "Salt restriction and 1.5–2 L/day fluid limit reinforced.",
                "Heart failure nurse telephone review in 3 days.",
                "NT-proBNP and basic metabolic panel before the next visit.",
            ]
        else:
            subjective = rng.choice(
                (
                    "Breathing much improved; walks 500 m on the flat. Sleeps on one pillow. Weight stable on daily weighing.",
                    "No breathlessness at rest, comfortable on two flights of stairs. No dizziness. Weight stable.",
                    "Feels well. No orthopnoea, no ankle swelling. Mild fatigue after the beta-blocker increase, settling.",
                )
            )
            exam = "JVP not raised. Chest clear. No peripheral oedema."
            assessment.append("Heart failure with reduced ejection fraction — euvolaemic, NYHA class II.")
            if i == 0:
                bisoprolol = c.change_med(
                    bisoprolol, when=start, text="Bisoprolol 5 mg tablet", dosage="5 mg orally once daily",
                    prescriber=doc, reason="Dose up-titrated",
                )
                plan.append("Increase bisoprolol to 5 mg once daily.")
            elif i == 1:
                sacubitril = c.change_med(
                    sacubitril, when=start, text="Sacubitril/valsartan 49/51 mg tablet",
                    dosage="49/51 mg orally twice daily", prescriber=doc, reason="Dose up-titrated",
                )
                plan.append("Increase sacubitril/valsartan to 49/51 mg twice daily.")
            elif i == 2:
                bisoprolol = c.change_med(
                    bisoprolol, when=start, text="Bisoprolol 7.5 mg tablet", dosage="7.5 mg orally once daily",
                    prescriber=doc, reason="Dose up-titrated",
                )
                echo_order = c.order_service(
                    "Transthoracic echocardiogram", category="imaging", ordered=start + timedelta(minutes=20),
                    due=day + timedelta(days=60), requester=doc, encounter=visit,
                    reason="Reassess LVEF after optimisation of medical therapy",
                )
                echo = (at(workday(day + timedelta(days=rng.randint(52, 58)), forward=False), 10, 30), ef + rng.choice((6, 7, 8)))
                plan += ["Increase bisoprolol to 7.5 mg once daily.", "Repeat echocardiogram in about 2 months."]
            else:
                plan.append("No medication change; continue current doses.")
            plan.append("Continue daily weights; NT-proBNP and basic metabolic panel before the next visit.")
        if drawn["k"] >= 5.0:
            assessment.append(f"Potassium {c.fmt('k', drawn['k'])} on spironolactone and sacubitril/valsartan — at the upper limit; monitor.")
        if echo and not echo_reviewed and echo[0] < start:
            assessment.append(
                f"Echocardiogram {day_text(echo[0])}: LVEF {echo[1]}%, improved from {ef}%. "
                "Primary-prevention ICD not indicated at present."
            )
            echo_reviewed = True
        c.note(
            when=start + timedelta(minutes=25), author=doc, title="Cardiology progress note", encounter=visit,
            body=sections(
                ("Subjective", subjective),
                ("Objective", [vitals, exam, c.labs_text(["ntprobnp", "cr", "egfr", "k", "na"], before=start, compare=("ntprobnp", "cr"))]),
                ("Assessment", numbered(assessment)),
                ("Plan", bullets(plan)),
            ),
        )
        orders = c.order_many(
            ["bmp", "ntprobnp"], ordered=start + timedelta(minutes=20),
            due=pre.date() if last else days[i + 1] - timedelta(days=3), requester=doc, encounter=visit,
            reason="Heart failure monitoring",
        )
        if i == 2 and echo:
            c.report(
                "echo", "Transthoracic echocardiogram", performed=echo[0], issued=echo[0] + timedelta(hours=2),
                interpreter=KARA, order=echo_order,
                findings=(
                    "COMPARISON\n"
                    f"Echocardiogram {day_text(echo_time)}.\n\n"
                    "FINDINGS\n"
                    f"Left ventricle mildly dilated. LVEF {echo[1]}% (biplane Simpson), previously {ef}%.\n"
                    "Mild functional mitral regurgitation, previously moderate.\n"
                    "Right ventricle normal. No pericardial effusion."
                ),
                conclusion=f"Improved left ventricular systolic function, LVEF {echo[1]}% (previously {ef}%). Mild mitral regurgitation.",
            )
        if last:
            c.draw(
                week_check,
                {
                    "bmp": chemistry(
                        rng, cr=cr + rng.uniform(0.1, 0.14), k=4.9, na=rng.uniform(133, 135), bun_ratio=(21.0, 25.0)
                    )
                },
                orders={"bmp": check}, requester=doc,
            )

    c.appointment(s.appointment, doc, "Heart failure clinic")
    if s.happened(pre):
        c.draw(
            pre,
            {
                "bmp": chemistry(rng, cr=cr + 0.02, k=4.8, na=rng.uniform(135, 137), bun_ratio=(18.0, 22.0)),
                "ntprobnp": {"ntprobnp": rng.uniform(1100, 1400)},
            },
            orders=orders, requester=doc,
        )


# ------------------------------------------------- dyslipidaemia, health checks


def dyslipidaemia(s: Story) -> None:
    """Variant 1 also has fatty liver disease found at the first health check."""
    c, rng, doc = s.chart, s.rng, AYDIN
    male = not c.female
    fatty_liver = s.variant == 1
    smoker = s.variant in (0, 3)
    c.set_height(rng.gauss(174 if male else 161, 5))
    weight = (rng.uniform(80, 92) if male else rng.uniform(66, 78)) + (10 if fatty_liver else 0)
    s.allergies(s.years_ago(4))
    if smoker:
        c.condition("Z72.0", "Tobacco use", onset=s.years_ago(rng.uniform(15, 25)), text="Current smoker", clinician=doc)

    first = workday(s.anchor - timedelta(days=rng.randint(715, 740)), forward=False)
    lifestyle = workday(first + timedelta(days=rng.randint(88, 98)), forward=False)
    statin_check = workday(lifestyle + timedelta(days=rng.randint(56, 66)), forward=False)
    annual = workday(first + timedelta(days=rng.randint(358, 372)), forward=False)
    ldl = rng.uniform(164, 192)
    hdl = rng.uniform(38, 46) if male else rng.uniform(46, 56)
    tg = rng.uniform(170, 240) if fatty_liver else rng.uniform(110, 165)
    a1c = rng.uniform(5.7, 6.2) if fatty_liver else rng.uniform(5.2, 5.6)
    alt = rng.uniform(58, 76) if fatty_liver else rng.uniform(16, 32)
    family_history = rng.random() < 0.5

    # Annual health check.
    drawn = c.draw(
        s.before(first),
        {
            "cbc": cbc(rng, c.gender),
            "cmp": chemistry(rng, cr=rng.uniform(0.8, 1.0) if male else rng.uniform(0.6, 0.8), hepatic=True, alt=alt),
            "lipid": lipids(ldl=ldl, hdl=hdl, tg=tg),
            "a1c": {"a1c": a1c},
            "thyroid": {"tsh": rng.uniform(1.0, 2.8), "ft4": rng.uniform(1.0, 1.4)},
        },
        requester=doc,
    )
    start = s.clinic(first)
    visit = c.visit(start, doc, "Annual health check", "Preventive health check")
    vitals = c.vitals(visit, sbp=rng.uniform(126, 134), dbp=rng.uniform(78, 84), hr=rng.uniform(70, 80), weight=weight)
    bmi = round(weight / (c.height_cm / 100) ** 2, 1)
    assessment = [f"Hypercholesterolaemia — LDL {c.fmt('ldl', drawn['ldl'])}, total cholesterol {c.fmt('chol', drawn['chol'])}."]
    plan = [
        "Mediterranean-style diet with dietitian handout; at least 150 minutes a week of moderate activity.",
        "Repeat lipid panel in 3 months.",
    ]
    if smoker:
        assessment.append("Current smoker, about 20 cigarettes a day.")
        plan.append("Smoking cessation advice; referred to the hospital stop-smoking clinic.")
    if drawn["a1c"] >= 5.7:
        c.condition("R73.0", "Abnormal glucose tolerance test", onset=first, text="Prediabetes", clinician=doc)
        assessment.append(f"Prediabetes — HbA1c {c.fmt('a1c', drawn['a1c'])}.")
    if bmi >= 30:
        c.condition("E66.9", "Obesity, unspecified", onset=first, text=f"Obesity (BMI {bmi:.1f})", clinician=doc)
        assessment.append(f"Obesity (BMI {bmi:.1f}).")
    ultrasound = None
    if fatty_liver:
        assessment.append(
            f"Raised ALT ({c.fmt('alt', drawn['alt'])}) with high triglycerides — possible fatty liver disease."
        )
        ultrasound = c.order_service(
            "Abdominal ultrasound", category="imaging", ordered=start + timedelta(minutes=20),
            due=first + timedelta(days=21), requester=doc, encounter=visit, reason="Raised ALT; suspected fatty liver",
        )
        plan.append("Abdominal ultrasound; viral hepatitis serology if ultrasound is not diagnostic.")
    orders = c.order_many(
        ["lipid"] + (["cmp"] if fatty_liver else []), ordered=start + timedelta(minutes=20),
        due=lifestyle - timedelta(days=3), requester=doc, encounter=visit, reason="Lipids after lifestyle changes",
    )
    c.note(
        when=start + timedelta(minutes=25), author=doc, title="Annual health check", encounter=visit,
        body=sections(
            (
                "Subjective",
                f"{c.age_sex(start)} attending for an annual health check. No complaints. "
                + ("Father had a myocardial infarction at 54. " if family_history else "No family history of premature heart disease. ")
                + ("Smokes about 20 cigarettes a day. " if smoker else "Never smoked. ")
                + "Alcohol rarely.",
            ),
            (
                "Objective",
                [vitals, c.labs_text(["chol", "ldl", "hdl", "tg", "a1c", "alt", "cr", "egfr", "hgb", "tsh"], before=start)],
            ),
            ("Assessment", numbered(assessment)),
            ("Plan", bullets(plan)),
        ),
    )
    if ultrasound is not None:
        scan = at(workday(first + timedelta(days=rng.randint(12, 18)), forward=False), 13, 0)
        c.report(
            "imaging", "Abdominal ultrasound", performed=scan, issued=scan + timedelta(hours=3), interpreter=CELIK,
            order=ultrasound, loinc=("18748-4", "Diagnostic imaging study"),
            findings=(
                "FINDINGS\n"
                "Liver normal in size with diffusely increased echogenicity and attenuation of the posterior beam. "
                "No focal lesion. Smooth contour. Portal vein patent with normal flow.\n"
                "Gallbladder, bile ducts, pancreas, spleen and kidneys unremarkable."
            ),
            conclusion="Diffuse hepatic steatosis. No focal liver lesion.",
        )
        c.condition(
            "K76.0", "Fatty (change of) liver, not elsewhere classified", onset=scan.date(),
            text="Metabolic dysfunction-associated steatotic liver disease", clinician=doc,
        )

    # Lifestyle review: statin decision.
    ldl *= rng.uniform(0.91, 0.96)
    drawn = c.draw(
        s.before(lifestyle),
        {"lipid": lipids(ldl=ldl, hdl=hdl, tg=tg * 0.92)}
        | ({"cmp": chemistry(rng, cr=rng.uniform(0.8, 1.0) if male else rng.uniform(0.6, 0.8), hepatic=True, alt=alt * 0.9)} if fatty_liver else {}),
        orders=orders, requester=doc,
    )
    start = s.clinic(lifestyle)
    visit = c.visit(start, doc, "Follow-up", "Hypercholesterolaemia")
    vitals = c.vitals(visit, sbp=rng.uniform(124, 132), dbp=rng.uniform(76, 82), hr=rng.uniform(68, 78), weight=weight - 1.2)
    c.condition("E78.0", "Pure hypercholesterolaemia", onset=lifestyle, text="Hypercholesterolaemia", clinician=doc)
    c.start_med(
        "Rosuvastatin 10 mg tablet", "10 mg orally once daily", start=start, prescriber=doc, atc=ROSUVASTATIN,
        reason="Hypercholesterolaemia",
    )
    orders = c.order_many(
        ["lipid", "cmp"], ordered=start + timedelta(minutes=20), due=statin_check - timedelta(days=3), requester=doc,
        encounter=visit, reason="Response to statin; liver enzymes",
    )
    c.note(
        when=start + timedelta(minutes=20), author=doc, title="Internal medicine progress note", encounter=visit,
        body=sections(
            ("Subjective", "Has changed diet and walks three times a week. Lost about 1 kg." + (" Still smoking, cut down to 10 a day." if smoker else "")),
            ("Objective", [vitals, c.labs_text(["ldl", "chol", "hdl", "tg", "alt"], before=start, compare=("ldl",))]),
            (
                "Assessment",
                numbered([f"Hypercholesterolaemia — LDL {c.fmt('ldl', drawn['ldl'])} despite lifestyle changes; above target."]),
            ),
            (
                "Plan",
                bullets(
                    [
                        "Start rosuvastatin 10 mg once daily; discussed muscle symptoms to report.",
                        "Lipid panel and liver enzymes in 8 weeks.",
                    ]
                ),
            ),
        ),
    )

    # Statin check.
    ldl *= rng.uniform(0.55, 0.62)
    drawn = c.draw(
        s.before(statin_check),
        {
            "lipid": lipids(ldl=ldl, hdl=hdl + 2, tg=tg * 0.8),
            "cmp": chemistry(rng, cr=rng.uniform(0.8, 1.0) if male else rng.uniform(0.6, 0.8), hepatic=True, alt=alt * (0.75 if fatty_liver else 1.05)),
        },
        orders=orders, requester=doc,
    )
    start = s.clinic(statin_check)
    visit = c.visit(start, doc, "Follow-up", "Hypercholesterolaemia on statin")
    vitals = c.vitals(visit, sbp=rng.uniform(122, 130), dbp=rng.uniform(74, 80), hr=rng.uniform(66, 76), weight=weight - 2.0)
    orders = c.order_many(
        ["cbc", "cmp", "lipid", "a1c"], ordered=start + timedelta(minutes=20), due=annual - timedelta(days=3),
        requester=doc, encounter=visit, reason="Annual health check",
    )
    c.note(
        when=start + timedelta(minutes=20), author=doc, title="Internal medicine progress note", encounter=visit,
        body=sections(
            ("Subjective", "Taking rosuvastatin daily. No muscle aches."),
            ("Objective", [vitals, c.labs_text(["ldl", "hdl", "tg", "alt", "ast"], before=start, compare=("ldl",))]),
            (
                "Assessment",
                numbered(
                    [f"Hypercholesterolaemia — LDL {c.fmt('ldl', drawn['ldl'])} on rosuvastatin 10 mg; liver enzymes acceptable."]
                ),
            ),
            ("Plan", bullets(["Continue rosuvastatin 10 mg.", "Annual review with bloods in about 9 months."])),
        ),
    )

    # Second annual check.
    a1c += rng.uniform(-0.1, 0.2)
    drawn = c.draw(
        s.before(annual),
        {
            "cbc": cbc(rng, c.gender),
            "cmp": chemistry(rng, cr=rng.uniform(0.8, 1.0) if male else rng.uniform(0.6, 0.8), hepatic=True, alt=alt * (0.7 if fatty_liver else 1.0)),
            "lipid": lipids(ldl=ldl * rng.uniform(0.97, 1.05), hdl=hdl + 2, tg=tg * 0.82),
            "a1c": {"a1c": a1c},
        },
        orders=orders, requester=doc,
    )
    start = s.clinic(annual)
    visit = c.visit(start, doc, "Annual health check", "Preventive health check")
    vitals = c.vitals(visit, sbp=rng.uniform(122, 132), dbp=rng.uniform(74, 82), hr=rng.uniform(66, 76), weight=weight - 2.5)
    assessment = [f"Hypercholesterolaemia — LDL {c.fmt('ldl', drawn['ldl'])} on rosuvastatin; at target."]
    if drawn["a1c"] >= 5.7:
        assessment.append(f"Prediabetes — HbA1c {c.fmt('a1c', drawn['a1c'])}.")
    if fatty_liver:
        assessment.append(f"Steatotic liver disease — ALT {c.fmt('alt', drawn['alt'])}, improving with weight loss.")
    pre = s.pre_appointment()
    orders = c.order_many(
        ["cbc", "cmp", "lipid", "a1c"], ordered=start + timedelta(minutes=20), due=pre.date(), requester=doc,
        encounter=visit, reason="Annual health check",
    )
    c.note(
        when=start + timedelta(minutes=25), author=doc, title="Annual health check", encounter=visit,
        body=sections(
            ("Subjective", "Well. Keeping up with walking." + (" Has not managed to stop smoking." if smoker else "")),
            ("Objective", [vitals, c.labs_text(["ldl", "hdl", "tg", "a1c", "alt", "egfr", "hgb"], before=start, compare=("ldl", "a1c"))]),
            ("Assessment", numbered(assessment)),
            ("Plan", bullets(["Continue rosuvastatin 10 mg.", "Annual check with bloods in 12 months."])),
        ),
    )

    c.appointment(s.appointment, doc, "Annual health check")
    if s.happened(pre):
        c.draw(
            pre,
            {
                "cbc": cbc(rng, c.gender),
                "cmp": chemistry(rng, cr=rng.uniform(0.8, 1.0) if male else rng.uniform(0.6, 0.8), hepatic=True, alt=alt * (0.68 if fatty_liver else 1.0)),
                "lipid": lipids(ldl=ldl * rng.uniform(0.95, 1.05), hdl=hdl + 2, tg=tg * 0.8),
                "a1c": {"a1c": a1c + rng.uniform(-0.1, 0.15)},
            },
            orders=orders, requester=doc,
        )


# ------------------------------------------- P-2041: metastatic colon cancer

# Days relative to the anchor date:
# Hb, MCV, WBC, ANC, platelets, creatinine, ALT, AST, ALP, albumin, Mg, CEA.
HERO_LABS: dict[int, tuple] = {
    -258: (10.6, 76, 7.9, None, 388, 0.88, 36, 41, 162, 3.7, None, None),
    -234: (10.9, 78, 8.2, 5.6, 371, 0.90, 39, 44, 171, 3.6, None, 86.4),
    -220: (11.6, 81, 7.4, 4.8, 342, 0.86, 35, 40, 158, 3.7, 2.0, None),
    -192: (11.9, 83, 5.6, 3.1, 248, 0.92, 31, 34, 139, 3.8, 1.9, 41.2),
    -164: (12.1, 85, 5.1, 2.6, 214, 0.95, 29, 33, 121, 3.9, 1.7, 18.5),
    -136: (11.8, 86, 4.7, 2.3, 188, 0.91, 27, 30, 108, 4.0, 1.6, 9.6),
    -108: (11.6, 87, 4.4, 2.0, 171, 0.93, 26, 31, 102, 4.0, 1.5, 6.8),
    -80: (11.8, 86, 4.6, 2.2, 176, 0.90, 25, 28, 98, 4.0, 1.6, 5.4),
    -38: (11.4, 85, 4.5, 2.1, 168, 0.92, 24, 27, 96, 3.9, 1.5, 4.9),
    -8: (9.8, 80, 5.2, 2.9, 181, 0.94, 26, 29, 104, 3.7, 1.4, None),
}
CYCLE_DAYS = (-220, -206, -192, -178, -164, -150, -136, -122, -108, -94, -80, -66, -52, -38)


def _hero_point(offset: int) -> tuple:
    if offset in HERO_LABS:
        return HERO_LABS[offset]
    lower = max(key for key in HERO_LABS if key < offset)
    upper = min(key for key in HERO_LABS if key > offset)
    weight = (offset - lower) / (upper - lower)
    return tuple(
        None if a is None or b is None else a + (b - a) * weight for a, b in zip(HERO_LABS[lower], HERO_LABS[upper])
    )


def colorectal_cancer(s: Story) -> None:
    """Patient P-2041, the walkthrough case from the product brief.

    Hb falls from 11.4 to 9.8 g/dL over 30 days during a treatment break, the
    restaging CT ordered three weeks ago has no report, and the CEA drawn with
    the last bloods has no result.
    """
    c, rng = s.chart, s.rng

    def day(offset: int) -> date:
        return workday(s.anchor + timedelta(days=offset), forward=False)

    def labs(offset: int, *, full: bool, orders: dict[str, dict] | None = None, extra: dict | None = None) -> None:
        hgb, mcv, wbc, anc, plt, cr, alt, ast, alp, alb, mg, cea = _hero_point(offset)
        blood = {"hgb": hgb, "hct": hgb * 3.05, "mcv": mcv, "wbc": wbc, "plt": plt}
        panels: dict[str, dict[str, float]] = {}
        if anc is None:
            panels["cbc"] = blood
        else:
            panels["cbc_diff"] = blood | {"anc": anc}
        if full:
            chemistry_values = chemistry(rng, cr=cr, glu=rng.uniform(92, 108), k=rng.uniform(3.8, 4.3), hepatic=True, alt=alt)
            panels["cmp"] = chemistry_values | {"ast": ast, "alp": alp, "alb": alb, "tbil": rng.uniform(0.5, 0.8)}
        if mg is not None:
            panels["mg"] = {"mg": mg}
        if full and cea is not None:
            panels["cea"] = {"cea": cea}
        panels |= extra or {}
        requester = AYDIN if offset < -240 else SAHIN
        c.draw(at(day(offset), 8, rng.choice((10, 15, 20))), panels, orders=orders, requester=requester)

    def clinic_note(start: datetime, visit: dict, title: str, subjective: str, exam: str, keys: list[str],
                    compare: tuple[str, ...], assessment: list[str], plan: list[str], vitals: str) -> None:
        c.note(
            when=start + timedelta(minutes=30), author=SAHIN, title=title, encounter=visit,
            body=sections(
                ("Subjective", subjective),
                ("Objective", [vitals, exam, c.labs_text(keys, before=start, compare=compare)]),
                ("Assessment", numbered(assessment)),
                ("Plan", bullets(plan)),
            ),
        )

    c.set_height(175)
    htn_onset = s.years_ago(8.3)
    c.condition("I10", "Essential (primary) hypertension", onset=htn_onset, clinician=AYDIN)
    c.no_known_allergies(htn_onset)
    c.start_med(
        "Amlodipine 5 mg tablet", "5 mg orally once daily", start=htn_onset, prescriber=AYDIN, atc=AMLODIPINE,
        reason="Essential hypertension",
    )

    # Internal medicine: anaemia, bleeding and change in bowel habit.
    labs(-258, full=True, extra={"ferritin": {"ferritin": 9}})
    start = at(day(-258), 10, 40)
    visit = c.visit(start, AYDIN, "Problem visit", "Fatigue, change in bowel habit, rectal bleeding")
    vitals = c.vitals(visit, sbp=132, dbp=80, hr=92, weight=78.0)
    c.condition("D50.0", "Iron deficiency anaemia secondary to blood loss (chronic)", onset=day(-258), clinician=AYDIN)
    c.start_med(
        "Ferrous sulfate 325 mg tablet", "325 mg orally every other day before breakfast", start=start,
        prescriber=AYDIN, atc=FERROUS_SULFATE, reason="Iron deficiency anaemia",
    )
    referral = c.order_service(
        "Gastroenterology referral — urgent colonoscopy", category="referral", ordered=start + timedelta(minutes=20),
        due=day(-244), requester=AYDIN, encounter=visit, priority="urgent",
        reason="Iron deficiency anaemia, rectal bleeding and change in bowel habit",
    )
    c.note(
        when=start + timedelta(minutes=30), author=AYDIN, title="Internal medicine progress note", encounter=visit,
        body=sections(
            (
                "Subjective",
                f"{c.age_sex(start)} with hypertension, presenting with two months of fatigue and exertional breathlessness "
                "and a change in bowel habit (looser stools alternating with constipation). Has noticed dark red blood mixed "
                "with the stool on several occasions. Unintentional weight loss of about 4 kg over three months. No abdominal "
                "pain, fever or night sweats. No NSAID or anticoagulant use. Father was diagnosed with colon cancer at 70. "
                "No previous colonoscopy.",
            ),
            (
                "Objective",
                [
                    vitals,
                    "Conjunctival pallor. Abdomen soft and non-tender; no palpable mass or hepatomegaly. "
                    "Rectal examination: no palpable mass, brown stool on the glove.",
                    c.labs_text(["hgb", "mcv", "plt", "ferritin", "alp", "alt", "ast", "alb", "cr"], before=start),
                ],
            ),
            (
                "Assessment",
                numbered(
                    [
                        "Iron deficiency anaemia with rectal bleeding, change in bowel habit and weight loss — "
                        "colorectal cancer must be excluded.",
                        f"Raised alkaline phosphatase ({c.fmt('alp', c.value('alp', start))}), cause not yet established.",
                        "Hypertension, controlled on amlodipine.",
                    ]
                ),
            ),
            (
                "Plan",
                bullets(
                    [
                        "Urgent gastroenterology referral for colonoscopy.",
                        "Start ferrous sulfate 325 mg every other day.",
                        "Further imaging to be guided by colonoscopy findings.",
                        "Return urgently if bleeding increases, or with dizziness or chest pain.",
                    ]
                ),
            ),
        ),
    )

    # Diagnosis and staging.
    scope = at(day(-244), 9, 30)
    c.report(
        "endoscopy", "Colonoscopy", performed=scope, issued=scope + timedelta(hours=2), interpreter=KOC,
        order=referral, loinc=("18746-8", "Colonoscopy study"),
        findings=(
            "INDICATION\nIron deficiency anaemia, rectal bleeding, change in bowel habit.\n\n"
            "FINDINGS\n"
            "Good bowel preparation. Caecum reached, confirmed by the appendiceal orifice and ileocaecal valve.\n"
            "Ulcerated, friable, near-circumferential mass at 25–30 cm from the anal verge (sigmoid colon), partially "
            "obstructing; the scope passed with gentle pressure. Six biopsies taken; site tattooed distally.\n"
            "Two diminutive polyps (3 and 4 mm) in the ascending colon, removed by cold snare and retrieved.\n"
            "Remaining colonic mucosa normal."
        ),
        conclusion=(
            "Sigmoid colon mass, highly suspicious for malignancy; biopsied and tattooed. "
            "Two diminutive ascending colon polyps removed. Staging CT requested."
        ),
    )
    staging = c.order_service(
        "CT chest, abdomen and pelvis with IV contrast", category="imaging", ordered=scope + timedelta(hours=3),
        due=day(-238), requester=KOC, priority="urgent", reason="Staging of suspected sigmoid colon cancer",
    )
    c.report(
        "pathology", "Histopathology — colonic biopsies", performed=scope, issued=at(day(-240), 15, 10),
        interpreter=KILIC, loinc=("11526-1", "Pathology study"),
        findings=(
            "SPECIMENS\nA. Sigmoid colon mass at 25 cm, biopsies (6 fragments).\nB. Ascending colon polyps (2), cold snare.\n\n"
            "MICROSCOPY\n"
            "A. Colonic mucosa infiltrated by moderately differentiated adenocarcinoma forming irregular glands with "
            "intraluminal necrotic debris. Lymphovascular invasion cannot be assessed on biopsy material.\n"
            "B. Tubular adenomas with low-grade dysplasia, completely excised.\n\n"
            "IMMUNOHISTOCHEMISTRY (A)\nMismatch repair proteins MLH1, PMS2, MSH2 and MSH6: nuclear expression retained."
        ),
        conclusion=(
            "A. Sigmoid colon, biopsy: adenocarcinoma, moderately differentiated; mismatch repair proficient (pMMR). "
            "B. Ascending colon polyps: tubular adenomas with low-grade dysplasia."
        ),
    )
    baseline_ct = at(day(-238), 11, 0)
    c.report(
        "imaging", "CT chest, abdomen and pelvis with IV contrast", performed=baseline_ct,
        issued=baseline_ct + timedelta(hours=5), interpreter=CELIK, order=staging,
        loinc=("18748-4", "Diagnostic imaging study"),
        findings=(
            "TECHNIQUE\nPortal venous phase CT of the chest, abdomen and pelvis after IV contrast. No prior imaging.\n\n"
            "FINDINGS\n"
            "Colon: circumferential wall thickening of the sigmoid colon over 5.5 cm with pericolic fat stranding. "
            "Three pericolic lymph nodes, short axis up to 9 mm.\n"
            "Liver: three hypoattenuating lesions in keeping with metastases — segment VII 32 mm, segment IVa 21 mm, "
            "segment VI 14 mm. No biliary dilatation. Portal and hepatic veins patent.\n"
            "Chest: no pulmonary nodules. No mediastinal or hilar lymphadenopathy. No pleural effusion.\n"
            "Other: no ascites or peritoneal nodularity. No suspicious bone lesion."
        ),
        conclusion=(
            "Sigmoid colon tumour with regional nodal involvement and three liver metastases "
            "(largest 32 mm, segment VII). No extrahepatic metastatic disease."
        ),
    )
    c.condition(
        "C18.7", "Malignant neoplasm of sigmoid colon", onset=day(-240), text="Adenocarcinoma of the sigmoid colon",
        clinician=SAHIN, stage="Stage IVA (cT3 N1 M1a), liver-limited", note="pMMR / MSS; KRAS, NRAS and BRAF V600E wild-type.",
    )
    c.condition(
        "C78.7", "Secondary malignant neoplasm of liver and intrahepatic bile duct", onset=day(-238),
        text="Liver metastases (segments VII, IVa and VI)", clinician=SAHIN,
    )

    # Medical oncology consultation.
    labs(-234, full=True)
    start = at(day(-234), 11, 0)
    visit = c.visit(start, SAHIN, "New patient consultation", "Sigmoid adenocarcinoma with liver metastases", minutes=45)
    vitals = c.vitals(visit, sbp=134, dbp=82, hr=86, weight=76.8)
    molecular = c.order_service(
        "Molecular pathology: KRAS/NRAS exons 2–4, BRAF V600E, MSI", category="laboratory",
        ordered=start + timedelta(minutes=40), due=day(-227), requester=SAHIN, encounter=visit,
        reason="Metastatic colorectal adenocarcinoma — treatment selection",
    )
    c.note(
        when=start + timedelta(minutes=45), author=SAHIN, kind="consult", title="Medical oncology consultation",
        encounter=visit,
        body=sections(
            ("Reason for referral", "Newly diagnosed sigmoid adenocarcinoma with liver metastases; referred by Dr. Ayhan Koç (gastroenterology)."),
            (
                "History",
                [
                    f"{c.age_sex(start)}. Presented to Dr. Elif Aydın on {day_text(day(-258))} with iron deficiency anaemia, "
                    "rectal bleeding, change in bowel habit and 4 kg weight loss.",
                    f"Colonoscopy {day_text(scope)}: ulcerated, partially obstructing sigmoid mass at 25–30 cm.",
                    f"Histology {day_text(day(-240))}: moderately differentiated adenocarcinoma, mismatch repair proficient.",
                    f"Staging CT {day_text(baseline_ct)}: sigmoid primary with regional nodes; three liver metastases "
                    "(32, 21 and 14 mm; segments VII, IVa, VI); no extrahepatic disease.",
                    "Fatigue, otherwise independent; works part-time. ECOG performance status 1.",
                    "Comorbidities: hypertension. Medications: amlodipine 5 mg daily, ferrous sulfate 325 mg every other day. "
                    "No known allergies.",
                    "Social: married, retired teacher. Ex-smoker (20 pack-years, stopped 2010). No alcohol.",
                    "Family history: father had colon cancer at 70.",
                ],
            ),
            ("Examination", [vitals, "No palpable lymphadenopathy. Liver edge not palpable. No ascites."]),
            ("Results", c.labs_text(["hgb", "anc", "plt", "cr", "alp", "tbil", "alb", "cea"], before=start)),
            (
                "Assessment",
                "Adenocarcinoma of the sigmoid colon, stage IVA (cT3 N1 M1a) with liver-limited metastases. Left-sided "
                "primary, mismatch repair proficient. Bilobar liver disease, potentially convertible to resection "
                "depending on response.",
            ),
            (
                "Plan",
                bullets(
                    [
                        "Extended RAS (KRAS/NRAS exons 2–4), BRAF V600E and MSI testing on the biopsy — requested today.",
                        "Present at the multidisciplinary tumour board with hepatobiliary surgery and radiology.",
                        "Port-a-cath insertion.",
                        "Provisional plan: FOLFOX, adding an anti-EGFR antibody if RAS and BRAF are wild-type.",
                        "Discussed the diagnosis, the aim of treatment (disease control, possible conversion to surgery) "
                        "and the main side effects with the patient and his wife.",
                    ]
                ),
            ),
        ),
    )
    c.report(
        "molecular", "Molecular pathology — colorectal panel", performed=at(day(-231), 9, 0),
        issued=at(day(-227), 14, 30), interpreter=KILIC, order=molecular,
        loinc=("81247-9", "Master HL7 genetic variant reporting panel"),
        findings=(
            "SPECIMEN\nSigmoid colon biopsy (block A1); tumour content approximately 60%.\n\n"
            "METHODS\nNext-generation sequencing: KRAS exons 2, 3 and 4; NRAS exons 2, 3 and 4; BRAF exon 15. "
            "Microsatellite instability by PCR (five mononucleotide markers).\n\n"
            "RESULTS\nKRAS: no pathogenic variant detected.\nNRAS: no pathogenic variant detected.\n"
            "BRAF V600E: not detected.\nMSI: microsatellite stable (MSS)."
        ),
        conclusion="RAS wild-type, BRAF V600E not detected, microsatellite stable.",
    )
    board = at(day(-226), 14, 0)
    c.note(
        when=board, author=SAHIN, kind="consult", title="Multidisciplinary tumour board",
        body=sections(
            (
                "Attendees",
                "Medical oncology (Dr. Murat Şahin), hepatobiliary surgery, radiology (Dr. Burak Çelik), "
                "pathology (Dr. Deniz Kılıç), gastroenterology (Dr. Ayhan Koç).",
            ),
            (
                "Case",
                f"{c.age_sex(board)} with sigmoid adenocarcinoma, pMMR/MSS, RAS and BRAF wild-type. Three liver metastases "
                f"(32, 21 and 14 mm; segments VII, IVa, VI); no extrahepatic disease. ECOG 1. "
                f"CEA {c.fmt('cea', c.value('cea', board))}.",
            ),
            (
                "Discussion",
                "Bilobar liver involvement; upfront resection would leave an inadequate future liver remnant. "
                "Potentially convertible with a good response. Primary not clinically obstructing.",
            ),
            (
                "Recommendation",
                bullets(
                    [
                        "FOLFOX plus panitumumab.",
                        "Restaging CT after four cycles.",
                        "Re-present for surgical assessment if there is a response.",
                    ]
                ),
            ),
        ),
    )

    # Induction chemotherapy, every 14 days. Notes at alternate cycles.
    regimen = "Metastatic colorectal cancer (FOLFOX + panitumumab)"
    oxaliplatin = folinate = fluorouracil = panitumumab = ondansetron = doxycycline = None
    keys = ["hgb", "anc", "plt", "cr", "alt", "alp", "mg", "cea"]
    for cycle, offset in enumerate(CYCLE_DAYS, 1):
        noted = cycle in (1, 3, 5, 7, 9, 11, 14)
        labs(offset, full=noted)
        if not noted:
            continue
        start = at(day(offset), 10, 0)
        visit = c.visit(start, SAHIN, "Chemotherapy review", f"Cycle {cycle}, metastatic colorectal cancer")
        if cycle == 1:
            vitals = c.vitals(visit, sbp=130, dbp=80, hr=84, weight=76.5)
            oxaliplatin = c.start_med(
                "Oxaliplatin 85 mg/m² IV", "85 mg/m² IV over 2 hours on day 1, every 14 days", start=start,
                prescriber=SAHIN, atc=OXALIPLATIN, reason=regimen,
            )
            folinate = c.start_med(
                "Calcium folinate (leucovorin) 400 mg/m² IV", "400 mg/m² IV over 2 hours on day 1, every 14 days",
                start=start, prescriber=SAHIN, atc=CALCIUM_FOLINATE, reason=regimen,
            )
            fluorouracil = c.start_med(
                "Fluorouracil IV", "400 mg/m² IV bolus, then 2400 mg/m² continuous infusion over 46 hours, every 14 days",
                start=start, prescriber=SAHIN, atc=FLUOROURACIL, reason=regimen,
            )
            panitumumab = c.start_med(
                "Panitumumab 6 mg/kg IV", "6 mg/kg IV over 60 minutes on day 1, every 14 days", start=start,
                prescriber=SAHIN, atc=PANITUMUMAB, reason=regimen,
            )
            ondansetron = c.start_med(
                "Ondansetron 8 mg tablet", "8 mg orally twice daily for 2 days after each cycle, then as needed",
                start=start, prescriber=SAHIN, atc=ONDANSETRON, reason="Chemotherapy-induced nausea",
            )
            doxycycline = c.start_med(
                "Doxycycline 100 mg capsule", "100 mg orally twice daily", start=start, prescriber=SAHIN,
                atc=DOXYCYCLINE, reason="Pre-emptive prophylaxis of panitumumab skin toxicity",
            )
            clinic_note(
                start, visit, "Oncology treatment note — cycle 1",
                f"Port-a-cath inserted on {day_text(day(-224))} without complication. Fatigue unchanged. Loose stools "
                "two to three times daily with occasional small amounts of blood. Appetite fair; weight stable.",
                "ECOG 1. Port site clean. Abdomen soft, non-tender.", keys, (),
                [
                    "Liver-limited metastatic sigmoid adenocarcinoma, pMMR/MSS, RAS and BRAF wild-type. Fit for cycle 1.",
                ],
                [
                    "Cycle 1 FOLFOX + panitumumab today; written consent obtained.",
                    "Skin care: emollients, sunscreen and pre-emptive doxycycline 100 mg twice daily.",
                    "Ondansetron for 2 days after each cycle.",
                    "CBC, chemistry and magnesium before each cycle.",
                    "Restaging CT after cycle 4.",
                ],
                vitals,
            )
        elif cycle == 3:
            vitals = c.vitals(visit, sbp=126, dbp=78, hr=80, weight=75.2)
            c.condition(
                "L27.0", "Generalized skin eruption due to drugs and medicaments", onset=day(offset),
                text="Acneiform rash (panitumumab-associated)", clinician=SAHIN,
            )
            restaging_1 = c.order_service(
                "CT chest, abdomen and pelvis with IV contrast", category="imaging",
                ordered=start + timedelta(minutes=20), due=day(-174), requester=SAHIN, encounter=visit,
                reason="Restaging after 4 cycles of FOLFOX + panitumumab",
            )
            clinic_note(
                start, visit, "Oncology treatment note — cycle 3",
                "Cycles 1 and 2 given without delay. Acneiform rash on the face and upper chest, manageable with "
                "emollients and doxycycline. Cold-induced tingling in the fingers for 2–3 days after each oxaliplatin "
                "dose, resolving between cycles. Nausea controlled. Bowels settling; no further bleeding.",
                "Papulopustular rash on face and upper chest (grade 1). No peripheral neuropathy on examination.",
                keys, ("cea",),
                [
                    f"Metastatic sigmoid adenocarcinoma on FOLFOX + panitumumab — CEA {c.fmt('cea', c.value('cea', start))}, falling.",
                    "Panitumumab-related acneiform rash, grade 1.",
                    "Acute oxaliplatin cold dysaesthesia; no persistent neuropathy.",
                ],
                [
                    "Proceed with cycle 3 at full dose.",
                    "Restaging CT chest, abdomen and pelvis after cycle 4 (requested).",
                    "Continue skin prophylaxis.",
                ],
                vitals,
            )
            restaging_scan = at(day(-172), 12, 0)
            c.report(
                "imaging", "CT chest, abdomen and pelvis with IV contrast", performed=restaging_scan,
                issued=restaging_scan + timedelta(hours=5), interpreter=CELIK, order=restaging_1,
                loinc=("18748-4", "Diagnostic imaging study"),
                findings=(
                    f"COMPARISON\nCT {day_text(baseline_ct)}.\n\n"
                    "FINDINGS\n"
                    "Liver: the three metastases are smaller — segment VII 19 mm (previously 32 mm), segment IVa 12 mm "
                    "(21 mm), segment VI 8 mm (14 mm). No new hepatic lesion.\n"
                    "Colon: reduced sigmoid wall thickening; pericolic nodes now subcentimetric (largest 5 mm).\n"
                    "Chest: no pulmonary nodules.\n"
                    "Other: no ascites. No new lesions."
                ),
                conclusion="Partial response: sum of target lesion diameters 39 mm, from 67 mm (−42%, RECIST 1.1). No new disease.",
            )
        elif cycle == 5:
            vitals = c.vitals(visit, sbp=128, dbp=76, hr=78, weight=74.6)
            clinic_note(
                start, visit, "Oncology treatment note — cycle 5",
                "Rash worse after cycle 4 — itchy papulopustular eruption on the face, scalp and upper back. Cold "
                "dysaesthesia now lasts up to a week after each cycle, no functional impairment. Energy better.",
                f"Rash grade 2. Restaging CT {day_text(restaging_scan)}: partial response (sum of target lesions 39 mm "
                "from 67 mm); no new disease.",
                keys, ("cea",),
                [
                    f"Partial response on restaging CT; CEA {c.fmt('cea', c.value('cea', start))}.",
                    "Acneiform rash, grade 2.",
                    "Peripheral sensory neuropathy, grade 1.",
                ],
                [
                    "Proceed with cycle 5; panitumumab at full dose.",
                    "Continue doxycycline and emollients; dermatology review if the rash does not settle.",
                    "Re-present at tumour board for a surgical opinion.",
                ],
                vitals,
            )
        elif cycle == 7:
            vitals = c.vitals(visit, sbp=132, dbp=80, hr=76, weight=74.9)
            clinic_note(
                start, visit, "Oncology treatment note — cycle 7",
                "Rash improved. Tingling in the fingertips now persists between cycles but does not affect buttons or "
                "writing. Eating well; weight stable.",
                "Rash grade 1. Reduced light-touch sensation in the fingertips.",
                keys, ("cea",),
                [
                    f"Ongoing biochemical response; CEA {c.fmt('cea', c.value('cea', start))}.",
                    "Peripheral sensory neuropathy, grade 1, persistent between cycles.",
                    f"Tumour board {day_text(day(-157))}: liver metastases not yet resectable (bilobar); continue systemic "
                    "therapy and reassess after the next restaging CT.",
                ],
                ["Proceed with cycle 7.", "Reduce oxaliplatin if neuropathy reaches grade 2."],
                vitals,
            )
        elif cycle == 9:
            vitals = c.vitals(visit, sbp=134, dbp=82, hr=78, weight=75.3)
            c.condition(
                "G62.0", "Drug-induced polyneuropathy", onset=day(offset),
                text="Oxaliplatin-induced peripheral sensory neuropathy", clinician=SAHIN,
            )
            c.condition(
                "E83.4", "Disorders of magnesium metabolism", onset=day(offset),
                text="Hypomagnesaemia (panitumumab-associated)", clinician=SAHIN,
            )
            oxaliplatin = c.change_med(
                oxaliplatin, when=start, text="Oxaliplatin 65 mg/m² IV",
                dosage="65 mg/m² IV over 2 hours on day 1, every 14 days", prescriber=SAHIN,
                reason="Dose reduced for grade 2 sensory neuropathy",
            )
            c.start_med(
                "Magnesium oxide 400 mg tablet", "400 mg orally twice daily", start=start, prescriber=SAHIN,
                atc=MAGNESIUM_OXIDE, reason="Hypomagnesaemia",
            )
            restaging_2 = c.order_service(
                "CT chest, abdomen and pelvis with IV contrast", category="imaging",
                ordered=start + timedelta(minutes=20), due=day(-90), requester=SAHIN, encounter=visit,
                reason="Restaging after 10 cycles",
            )
            clinic_note(
                start, visit, "Oncology treatment note — cycle 9",
                "Numbness in the fingertips and toes is now constant; difficulty with buttons and dropping small objects. "
                "Night-time calf cramps. Rash mild.",
                "Reduced light-touch and vibration sense in fingers and toes. Rash grade 1.",
                keys, ("cea", "mg"),
                [
                    "Oxaliplatin-induced peripheral sensory neuropathy, grade 2.",
                    f"Hypomagnesaemia (Mg {c.fmt('mg', c.value('mg', start))}), panitumumab-related; likely contributing to cramps.",
                    f"CEA {c.fmt('cea', c.value('cea', start))}, continuing to fall.",
                ],
                [
                    "Reduce oxaliplatin to 65 mg/m² from this cycle.",
                    "Start magnesium oxide 400 mg twice daily.",
                    "Restaging CT after cycle 10 (requested).",
                    "Proceed with cycle 9.",
                ],
                vitals,
            )
            second_scan = at(day(-88), 12, 0)
            c.report(
                "imaging", "CT chest, abdomen and pelvis with IV contrast", performed=second_scan,
                issued=second_scan + timedelta(hours=5), interpreter=CELIK, order=restaging_2,
                loinc=("18748-4", "Diagnostic imaging study"),
                findings=(
                    f"COMPARISON\nCT {day_text(restaging_scan)} and {day_text(baseline_ct)}.\n\n"
                    "FINDINGS\n"
                    "Liver: further decrease — segment VII 15 mm (19 mm), segment IVa 9 mm (12 mm), segment VI 5 mm (8 mm). "
                    "No new hepatic lesion.\n"
                    "Colon: minimal residual sigmoid wall thickening.\n"
                    "Chest: no pulmonary nodules.\n"
                    "Other: no new lesions."
                ),
                conclusion="Continued partial response: sum of target lesions 29 mm (39 mm previously, 67 mm at baseline). No new disease.",
            )
        elif cycle == 11:
            vitals = c.vitals(visit, sbp=130, dbp=78, hr=74, weight=75.8)
            c.stop_med(oxaliplatin, end=start, reason="Discontinued for persistent grade 2 sensory neuropathy")
            clinic_note(
                start, visit, "Oncology treatment note — cycle 11",
                "Neuropathy unchanged despite the dose reduction, now also affecting balance on uneven ground. Cramps "
                "better on magnesium. Rash mild.",
                f"Grade 2 sensory neuropathy. Restaging CT {day_text(second_scan)}: continued partial response, "
                "sum of target lesions 29 mm; no new disease.",
                keys, ("cea",),
                [
                    f"Continued partial response; CEA {c.fmt('cea', c.value('cea', start))}.",
                    "Persistent grade 2 neuropathy on reduced-dose oxaliplatin.",
                    f"Hepatobiliary surgery review {day_text(day(-84))}: combined resection and ablation may be possible "
                    "if disease remains controlled; re-image in about 3 months and re-present.",
                ],
                [
                    "Stop oxaliplatin. Continue fluorouracil, leucovorin and panitumumab every 14 days as maintenance.",
                    "Continue magnesium oxide.",
                    "Next restaging CT in about 3 months, then re-present at tumour board.",
                ],
                vitals,
            )
        else:
            vitals = c.vitals(visit, sbp=136, dbp=84, hr=80, weight=76.1)
            clinic_note(
                start, visit, "Oncology treatment note — cycle 14",
                "Maintenance cycles 12 and 13 given on schedule. Mild fatigue. Neuropathy improving. Rash grade 1.",
                "Grade 1 sensory neuropathy. Rash grade 1.",
                keys, ("hgb", "cea"),
                [
                    f"Metastatic sigmoid adenocarcinoma on maintenance fluorouracil, leucovorin and panitumumab; "
                    f"CEA {c.fmt('cea', c.value('cea', start))}.",
                    f"Hypomagnesaemia — Mg {c.fmt('mg', c.value('mg', start))} on oral magnesium.",
                    "Neuropathy improving, grade 1.",
                ],
                ["Proceed with cycle 14.", "Continue magnesium oxide.", "Review in 2 weeks with a restaging plan."],
                vitals,
            )

    # Treatment break, restaging requested.
    start = at(day(-22), 11, 20)
    visit = c.visit(start, SAHIN, "Oncology follow-up", "Metastatic colorectal cancer — maintenance therapy review")
    vitals = c.vitals(visit, sbp=132, dbp=80, hr=82, weight=75.4)
    for medication in (fluorouracil, folinate, panitumumab):
        c.hold_med(medication, reason=f"Planned treatment break from {day_text(start)}")
    c.stop_med(doxycycline, end=start, reason="Not needed during treatment break")
    c.stop_med(ondansetron, end=start, reason="Not needed during treatment break")
    c.order_service(
        "CT chest, abdomen and pelvis with IV contrast", category="imaging", ordered=start + timedelta(minutes=20),
        due=day(-11), requester=SAHIN, encounter=visit, reason="Restaging before surgical re-assessment",
    )
    lab_orders = c.order_many(
        ["cbc_diff", "cmp", "mg", "cea"], ordered=start + timedelta(minutes=20), due=day(-8), requester=SAHIN,
        encounter=visit, reason="Bloods before restaging review",
    )
    c.note(
        when=start + timedelta(minutes=30), author=SAHIN, title="Oncology progress note", encounter=visit,
        body=sections(
            (
                "Subjective",
                "Due for cycle 15. Feels well but tired of treatment after seven months and asks whether a break is "
                "possible. Rash and neuropathy grade 1. No bleeding; normal bowel habit. Weight stable.",
            ),
            (
                "Objective",
                [vitals, "No hepatomegaly. Grade 1 rash on face.", c.labs_text(["hgb", "anc", "plt", "mg", "cea"], before=start)],
            ),
            (
                "Assessment",
                numbered(
                    [
                        f"Liver-limited metastatic sigmoid adenocarcinoma with continued partial response on CT "
                        f"{day_text(second_scan)}; CEA {c.fmt('cea', c.value('cea', start))}.",
                        "Patient request for a treatment break; reasonable while restaging and surgical options are assessed.",
                    ]
                ),
            ),
            (
                "Plan",
                bullets(
                    [
                        "Hold maintenance chemotherapy and panitumumab (planned treatment break).",
                        f"Restaging CT chest, abdomen and pelvis by {day_text(day(-11))}.",
                        f"CBC with differential, comprehensive metabolic panel, magnesium and CEA on {day_text(day(-8))}.",
                        f"Clinic review on {day_text(s.appointment)} with CT and blood results; re-present at tumour board "
                        "for surgical assessment.",
                        "Stop doxycycline and ondansetron during the break; continue magnesium oxide.",
                    ]
                ),
            ),
        ),
    )
    # Bloods drawn as planned; CEA not yet resulted and no CT report on file.
    labs(-8, full=True, orders=lab_orders)
    c.appointment(s.appointment, SAHIN, "Review restaging CT and blood results; decide on resuming treatment")


# ------------------------------------------------------------------- cohort


@dataclass(frozen=True)
class Template:
    story: Callable[[Story], None]
    sex: str | None
    ages: tuple[int, int]
    count: int


TEMPLATES = (
    Template(diabetes_hypertension, None, (48, 74), 5),
    Template(chronic_kidney_disease, None, (61, 82), 3),
    Template(heart_failure, "male", (58, 79), 2),
    Template(hypothyroidism, "female", (31, 66), 3),
    Template(iron_deficiency, "female", (27, 49), 2),
    Template(dyslipidaemia, None, (41, 63), 4),
)

# Business days from the anchor for each patient's next appointment.
APPOINTMENT_OFFSETS = (0, 3, 1, 0, 4, 2, 0, 5, 1, 3, 0, 6, 2, 4, 7, 1, 5, 8, 3)

FEMALE_NAMES = ("Ayşe", "Fatma", "Emine", "Zehra", "Hülya", "Derya", "Esra", "Gülsüm", "Meryem", "Sevgi", "Nurten", "Canan", "Filiz", "Seda")
MALE_NAMES = ("Ahmet", "Mustafa", "Ali", "Hüseyin", "İbrahim", "Osman", "Yusuf", "Ömer", "Kemal", "Halil", "Erkan", "Serkan", "Cengiz", "Levent")
FAMILY_NAMES = (
    "Yılmaz", "Kaya", "Çetin", "Doğan", "Polat", "Korkmaz", "Özkan", "Şimşek", "Kurt", "Güneş",
    "Aksoy", "Bulut", "Tekin", "Avcı", "Uçar", "Karaca", "Erdem", "Tunç", "Sarı", "Altun",
)
CITIES = ("Ankara", "İstanbul", "İzmir", "Bursa", "Konya", "Eskişehir", "Kayseri", "Antalya")


def build_cohort(anchor: date, seed: int = 2041) -> list[PatientChart]:
    rng = random.Random(seed)
    hero = PatientChart(
        number=2041, given="Mehmet", family="Yıldız", gender="male", birth_date=date(anchor.year - 63, 4, 12),
        city="Ankara", gp=AYDIN,
    )
    colorectal_cancer(Story(rng, anchor, hero, at(add_workdays(anchor, 0), 10, 30)))
    charts = [hero]
    used = {hero.name}

    jobs = [(template, variant) for template in TEMPLATES for variant in range(template.count)]
    rng.shuffle(jobs)
    for index, (template, variant) in enumerate(jobs):
        gender = template.sex or rng.choice(("female", "male"))
        names = FEMALE_NAMES if gender == "female" else MALE_NAMES
        given, family = rng.choice(names), rng.choice(FAMILY_NAMES)
        while f"{given} {family}" in used:
            given, family = rng.choice(names), rng.choice(FAMILY_NAMES)
        used.add(f"{given} {family}")
        age = rng.randint(*template.ages)
        chart = PatientChart(
            number=1001 + index, given=given, family=family, gender=gender,
            birth_date=date(anchor.year - age, rng.randint(1, 12), rng.randint(1, 28)), city=rng.choice(CITIES),
            gp=AYDIN,
        )
        hour, minute = CLINIC_TIMES[(index * 5) % len(CLINIC_TIMES)]
        appointment = at(add_workdays(anchor, APPOINTMENT_OFFSETS[index % len(APPOINTMENT_OFFSETS)]), hour, minute)
        template.story(Story(rng, anchor, chart, appointment, variant))
        charts.append(chart)
    return charts
