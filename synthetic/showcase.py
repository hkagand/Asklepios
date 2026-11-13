"""Showcase patients: fixed stories whose epicrisis reports carry the history a doctor would ask about.

Each patient has two parts that share one timeline, worked out from the anchor: the story (`thyroid_cancer`,
`coronary_disease`), which writes the problem list, medication orders, outpatient notes, results and the next
appointment, and the reports (`thyroid_cancer_reports`, `coronary_disease_reports`), added after it with the patient's
own epicrisis random numbers. The showcase patients get no background reports.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from chart import PatientChart, at, day_text, workday
from cohort import (
    ARSLAN, ATORVASTATIN, BISOPROLOL, CELIK, KARA, KOC, LEVOTHYROXINE, Story, bullets, cbc, chemistry, lipids, numbered,
    sections,
)
from epicrisis import Admission, ProcedureReport, add
from epicrisis_catalogue import (
    ENT, ORTHOPAEDICS, YALCIN, Ctx, Patient, cellulitis, join, name_of, pneumonia, renal_colic, vertigo,
)

# Patient ids of the showcase patients, for the checks (evals/epicrisis.py).
SHOWCASE = ("p-2043", "p-2044", "p-2045")

ENDOCRINOLOGIST = "Dr. Selin Arslan"
RADIOLOGIST = "Dr. Burak Çelik"
NUCLEAR_MEDICINE = "Dr. Hande Akyürek"


def _month(day: date) -> str:
    """"Mar 2019"."""
    return day_text(day).split(" ", 1)[1]


# ------------------------------------------------------------------ p-2043, papillary thyroid carcinoma


@dataclass(frozen=True)
class ThyroidTimeline:
    pneumonia: date  # admitted, before the thyroid story began
    goitre: date  # the neck ultrasound that found the multinodular goitre, eight years before the anchor
    aspiration: date  # day case: fine-needle aspiration of the right lobe nodule
    surgery: date  # admitted and operated: total thyroidectomy
    surgery_home: date
    calcium_stopped: date  # oral calcium and calcitriol stopped after a normal calcium check
    radioiodine: date  # admitted for remnant ablation, four weeks off thyroid hormone
    radioiodine_home: date  # levothyroxine started
    voice_recovered: date  # repeat laryngoscopy: normal cord movement
    dose_change: date  # levothyroxine 125 -> 100 micrograms after an excellent response
    vertigo: date
    cholecystitis: date
    node: date  # day case: fine-needle aspiration of a right neck lymph node
    wrist: date
    visits: tuple[date, date, date]  # endocrinology clinic with Dr. Selin Arslan


def thyroid_timeline(anchor: date) -> ThyroidTimeline:
    def back(days: int) -> date:
        return workday(anchor - timedelta(days=days), forward=False)

    def after(day: date, days: int) -> date:
        return workday(day + timedelta(days=days), forward=True)

    goitre = back(2922)
    aspiration = after(goitre, 23)
    surgery = after(aspiration, 48)
    surgery_home = surgery + timedelta(days=4)
    radioiodine = after(surgery, 28)
    radioiodine_home = radioiodine + timedelta(days=3)
    return ThyroidTimeline(
        pneumonia=back(3390), goitre=goitre, aspiration=aspiration, surgery=surgery, surgery_home=surgery_home,
        calcium_stopped=after(surgery_home, 14), radioiodine=radioiodine, radioiodine_home=radioiodine_home,
        voice_recovered=after(surgery, 95), dose_change=after(radioiodine_home, 400), vertigo=back(2350),
        cholecystitis=back(1900), node=back(1310), wrist=back(1000), visits=(back(640), back(390), back(125)),
    )


LEVOTHYROXINE_TIMING = "orally once daily, 30–60 minutes before breakfast"


def thyroid_cancer(s: Story) -> None:
    """Patient P-2043: a multinodular goitre found eight years ago; papillary thyroid carcinoma treated by total
    thyroidectomy and radioiodine.

    The problem list and levothyroxine orders follow from her epicrisis reports (thyroid_cancer_reports); the last two
    years hold three endocrinology visits with Dr. Selin Arslan, each with thyroid function results, and the next one
    is booked. Her notes keep to the thyroid: her other admissions are told by the reports alone.
    """
    c, rng, doc = s.chart, s.rng, ARSLAN
    t = thyroid_timeline(s.anchor)
    c.set_height(162)

    c.condition(
        "C73", "Malignant neoplasm of thyroid gland", onset=t.surgery, clinician=doc,
        text="Papillary thyroid carcinoma, treated", stage="pT2 NX M0, ATA intermediate risk",
        note=(
            f"Total thyroidectomy on {day_text(t.surgery)} and radioiodine remnant ablation on {day_text(t.radioiodine)}. "
            "Excellent response; no evidence of disease since."
        ),
    )
    c.condition(
        "E89.0", "Postprocedural hypothyroidism", onset=t.surgery, clinician=doc,
        text="Hypothyroidism after total thyroidectomy",
    )
    first = c.start_med(
        "Levothyroxine 125 microgram tablet", f"125 micrograms {LEVOTHYROXINE_TIMING}", start=t.radioiodine_home,
        prescriber=doc, atc=LEVOTHYROXINE, reason="Thyroid hormone replacement after total thyroidectomy",
    )
    c.change_med(
        first, when=at(t.dose_change, 10, 0), text="Levothyroxine 100 microgram tablet",
        dosage=f"100 micrograms {LEVOTHYROXINE_TIMING}", prescriber=doc,
        reason="Dose reduced; excellent response to treatment, TSH target relaxed to 0.5–2.0 mIU/L",
    )

    history = [
        f"Multinodular goitre found on a neck ultrasound in {_month(t.goitre)}; fine-needle aspiration of the dominant "
        f"24 mm right lobe nodule on {day_text(t.aspiration)} was suspicious for papillary carcinoma (Bethesda V).",
        f"Total thyroidectomy on {day_text(t.surgery)} (Dr. Kerem Yalçın): papillary thyroid carcinoma, 24 mm, right "
        "lobe, with a tall-cell component; pT2 NX.",
        "After the operation: transient hypocalcaemia, treated with calcium and calcitriol for two weeks; calcium "
        f"normal without supplements since {_month(t.calcium_stopped)}. Right vocal cord paresis with a hoarse voice, "
        f"recovered by {_month(t.voice_recovered)} (normal laryngoscopy).",
        f"Radioiodine remnant ablation (I-131, 3.7 GBq) on {day_text(t.radioiodine)}; post-therapy scan showed uptake in "
        "the thyroid bed only.",
        f"Excellent response at one year; levothyroxine reduced to 100 micrograms in {_month(t.dose_change)}.",
        f"Fine-needle aspiration of a 9 mm right level III neck lymph node on {day_text(t.node)}: benign, reactive "
        "lymph node.",
    ]
    summary = (
        f"Papillary thyroid carcinoma treated by total thyroidectomy ({t.surgery.year}) and radioiodine "
        f"({t.radioiodine.year}); no evidence of disease since."
    )
    tsh = [rng.uniform(1.2, 1.7), rng.uniform(0.8, 1.1), rng.uniform(1.1, 1.5)]
    ft4 = [rng.uniform(1.25, 1.4), rng.uniform(1.35, 1.5), rng.uniform(1.25, 1.4)]
    weight = rng.uniform(66, 70)
    orders: dict[str, dict] = {}
    pre_visit = workday(s.appointment.date() - timedelta(days=4), forward=False)
    c.no_known_allergies(t.visits[0])

    for i, day in enumerate(t.visits):
        last = i == len(t.visits) - 1
        panels = {"thyroid": {"tsh": tsh[i], "ft4": ft4[i]}}
        if i == 0:
            panels["bmp"] = chemistry(rng, cr=0.74)
        c.draw(s.before(day), panels, orders=orders, requester=doc)
        start = s.clinic(day)
        visit = c.visit(start, doc, "Endocrinology follow-up", "Papillary thyroid carcinoma, treated; post-surgical hypothyroidism")
        vitals = c.vitals(visit, sbp=rng.gauss(124, 5), dbp=rng.gauss(78, 3), hr=rng.gauss(72, 4), weight=weight + 0.6 * i)
        labs = c.labs_text(["tsh", "ft4", "ca"] if i == 0 else ["tsh", "ft4"], before=start, compare=("tsh",) if i else ())
        next_day = pre_visit if last else t.visits[i + 1]
        orders = {
            "thyroid": c.order(
                "thyroid", ordered=start + timedelta(minutes=20), due=pre_visit if last else next_day - timedelta(days=3),
                requester=doc, encounter=visit, reason="Thyroid replacement monitoring after thyroidectomy",
            )
        }
        exam = "Healed low collar incision. No palpable mass in the thyroid bed and no cervical lymph nodes. Voice normal."
        tsh_text = c.fmt("tsh", c.value("tsh", start))
        if i == 0:
            ultrasound = c.order_service(
                "Ultrasound neck — thyroid bed and cervical lymph nodes", category="imaging",
                ordered=start + timedelta(minutes=20), due=next_day - timedelta(days=14), requester=doc, encounter=visit,
                reason="Surveillance after papillary thyroid carcinoma",
            )
            parts = [
                ("Subjective", "Annual review. Feels well. No neck swelling, difficulty swallowing, palpitations or tremor. "
                 "Takes levothyroxine 100 micrograms on waking with water, 30–60 minutes before breakfast."),
                ("Thyroid history", bullets(history)),
                ("Objective", [vitals, exam, labs]),
                (
                    "Assessment",
                    numbered([
                        "Papillary thyroid carcinoma, treated — no clinical evidence of recurrence.",
                        f"Post-surgical hypothyroidism — TSH {tsh_text} on levothyroxine 100 micrograms; within the "
                        "target of 0.5–2.0 mIU/L. Calcium normal.",
                    ]),
                ),
                (
                    "Plan",
                    bullets([
                        "Continue levothyroxine 100 micrograms once daily.",
                        "Neck ultrasound of the thyroid bed and lymph nodes before the next visit.",
                        "TSH and free T4 before the next visit.",
                        "Review in 8 months.",
                    ]),
                ),
            ]
        elif i == 1:
            scanned = at(workday(day - timedelta(days=12), forward=False), 11, 0)
            c.report(
                "imaging", "Ultrasound neck", performed=scanned, issued=scanned + timedelta(hours=2), interpreter=CELIK,
                order=ultrasound,
                findings=(
                    "Thyroid bed: no residual tissue or mass after total thyroidectomy.\nCervical lymph nodes: small oval "
                    "nodes with a fatty hilum at levels II and III on both sides, the largest 7 mm on the right; no "
                    "microcalcification, cystic change or abnormal blood flow.\nThe right level III node aspirated in "
                    f"{_month(t.node)} is no longer seen as enlarged."
                ),
                conclusion="No sonographic evidence of recurrence in the thyroid bed or cervical lymph nodes.",
            )
            parts = [
                ("Subjective", "Well. Energy good, weight steady. Takes levothyroxine 100 micrograms before breakfast."),
                ("Objective", [vitals, exam, labs, f"Neck ultrasound {day_text(scanned)}: no evidence of recurrence in the thyroid bed or cervical lymph nodes."]),
                (
                    "Assessment",
                    numbered([
                        f"{summary} Neck ultrasound clear.",
                        f"Post-surgical hypothyroidism — TSH {tsh_text} on levothyroxine 100 micrograms; within target.",
                    ]),
                ),
                (
                    "Plan",
                    bullets([
                        "Continue levothyroxine 100 micrograms once daily.",
                        "TSH and free T4 before the next visit.",
                        "Review in 9 months.",
                    ]),
                ),
            ]
        else:
            parts = [
                ("Subjective", "Well, no new symptoms. Voice normal. Takes levothyroxine 100 micrograms before breakfast."),
                ("Objective", [vitals, exam, labs]),
                (
                    "Assessment",
                    numbered([
                        summary,
                        f"Post-surgical hypothyroidism — TSH {tsh_text} on levothyroxine 100 micrograms; within target.",
                    ]),
                ),
                (
                    "Plan",
                    bullets([
                        "Continue levothyroxine 100 micrograms once daily.",
                        "TSH and free T4 a few days before the next visit.",
                        f"Endocrinology follow-up on {day_text(s.appointment)}.",
                    ]),
                ),
            ]
        c.note(
            when=start + timedelta(minutes=25), author=doc, title="Endocrinology progress note", encounter=visit,
            body=sections(*parts),
        )

    c.appointment(s.appointment, doc, "Thyroid cancer follow-up")


def _levothyroxine(p: Patient, day: date) -> str:
    """"Levothyroxine 100 micrograms once daily, 30–60 minutes before breakfast" from the order active on the day."""
    order = next(order for order in p.medicines(day) if name_of(order).lower() == "levothyroxine")
    return f"{name_of(order)} {order['dosageInstruction'][0]['text'].replace(' orally', '')}"


def thyroid_cancer_reports(chart: PatientChart, anchor: date, seed: int) -> list[dict]:
    """P-2043's eight epicrisis reports, added oldest first; returns the DocumentReferences. Two unrelated admissions
    (pneumonia, vestibular neuronitis) come from the background catalogue; the rest are written for her."""
    rng = random.Random(f"epicrisis:{chart.pid}:{seed}")
    p = Patient.of(chart, thyroid_cancer.__name__, 0, False)
    t = thyroid_timeline(anchor)

    # Her operations, for the past history the catalogue's builders write.
    operations = [
        (t.surgery, "total thyroidectomy"), (t.cholecystitis + timedelta(days=1), "laparoscopic cholecystectomy"),
        (t.wrist + timedelta(days=1), "open reduction and internal fixation of left distal radius fracture"),
    ]

    def ctx(day: date) -> Ctx:
        return Ctx(p, rng, day, False, operations)

    thyroidectomy = f"total thyroidectomy ({t.surgery.year})"
    cholecystectomy = f"laparoscopic cholecystectomy ({t.cholecystitis.year})"
    pneumonia_line = f"Community-acquired pneumonia in {_month(t.pneumonia)}, treated in this hospital."
    thyroid_lines = [
        f"Papillary thyroid carcinoma (pT2 NX): {thyroidectomy}; radioiodine remnant ablation in {_month(t.radioiodine)}; "
        "no evidence of disease since.",
        f"After the thyroidectomy, transient hypocalcaemia (calcium normal without supplements since {_month(t.calcium_stopped)}) "
        f"and a right vocal cord paresis that recovered fully (normal laryngoscopy in {_month(t.voice_recovered)}).",
    ]
    # The catalogue's builders name the cancer as treated history, not as a discharge diagnosis.
    p.treated["C73"] = ("treated papillary thyroid carcinoma", thyroid_lines[0])

    def regular(day: date) -> str:
        return f"Regular medicines: {_levothyroxine(p, day).lower()}. No known drug allergies."

    admissions: list[Admission] = []

    # 1. Pneumonia, before any of the thyroid story.
    admissions.append(pneumonia(ctx(t.pneumonia)))

    # 2. Fine-needle aspiration of the thyroid nodule.
    c = ctx(t.aspiration)
    admissions.append(Admission(
        title="Thyroid nodule: fine-needle aspiration",
        admitted=t.aspiration,
        discharged=t.aspiration,
        service="Endocrinology",
        doctor=ENDOCRINOLOGIST,
        complaint=join(
            f"{c.age}-year-old woman with a painless swelling on the right side of the neck, noticed a few months ago.",
            f"A neck ultrasound on {day_text(t.goitre)}, requested by her family doctor, showed a multinodular goitre: several",
            "small nodules in both lobes and a dominant 24 mm solid, hypoechoic nodule in the right lobe with",
            "microcalcifications (TI-RADS 5). TSH normal. Admitted as a day case for fine-needle aspiration.",
        ),
        past_history=join(
            pneumonia_line, "No other illnesses. No regular medicines. No known drug allergies.",
            "No radiation to the head or neck. No family history of thyroid cancer. Never smoked.",
        ),
        examination=join(
            c.vitals(),
            "Multinodular goitre; a firm 2.5 cm nodule in the right lobe that moves with swallowing. No palpable cervical",
            "lymph nodes. Voice normal; no stridor.",
        ),
        course=join(
            f"TSH {rng.uniform(1.4, 1.9):.2f} mIU/L, free T4 {rng.uniform(1.15, 1.3):.2f} ng/dL, calcium {rng.uniform(9.2, 9.6):.1f} mg/dL.",
            "Ultrasound-guided fine-needle aspiration of the dominant right lobe nodule (see the procedure report); the",
            "on-site check confirmed an adequate sample. Observed for two hours: no bleeding or neck swelling.",
            "Home the same afternoon. Cytology to follow.",
        ),
        admission_diagnoses=(("E04.2", "Nontoxic multinodular goitre"),),
        discharge_diagnoses=(("E04.2", "Nontoxic multinodular goitre with a dominant right lobe nodule (TI-RADS 5); cytology pending"),),
        prescription=("Paracetamol 500 mg orally up to four times daily as needed for neck discomfort",),
        recommendations=join(
            "Endocrinology clinic (Dr. Selin Arslan) in one week for the cytology result.",
            "Return at once with neck swelling, difficulty breathing or difficulty swallowing.",
        ),
        outcome="Unchanged",
        procedure=ProcedureReport(
            performed=t.aspiration,
            name="Ultrasound-guided fine-needle aspiration of a right thyroid nodule",
            operation=False,
            pre_diagnosis="Dominant 24 mm right thyroid lobe nodule, TI-RADS 5, in a multinodular goitre",
            post_diagnosis="Same; adequate sample on the on-site check; cytology pending",
            team=f"{RADIOLOGIST} (radiologist); {ENDOCRINOLOGIST} (endocrinologist)",
            anaesthesia="Local anaesthesia (lidocaine 1%)",
            wound_class="Clean",
            note=join(
                "Supine with the neck extended. Under ultrasound guidance, three passes with a 25-gauge needle into the solid,",
                "calcified part of the right lobe nodule; smears and a liquid-based sample prepared. Pressure for 10 minutes;",
                "no haematoma on the final scan.",
            ),
            blood_loss="None",
            specimen="Fine-needle aspirate of the right thyroid nodule, for cytology",
            body_site="Thyroid, right lobe",
        ),
    ))

    # 3. Total thyroidectomy, with transient hypocalcaemia and a right vocal cord paresis.
    c = ctx(t.surgery)
    calcium_low = 7.4
    complications = join(
        f"Transient hypocalcaemia from day 1: corrected calcium lowest {calcium_low} mg/dL with PTH 9 pg/mL, tingling around",
        "the mouth and in the fingertips. Treated with intravenous calcium gluconate, then oral calcium carbonate and",
        "calcitriol; calcium 8.8 mg/dL without symptoms at discharge.",
        "Right vocal cord paresis: hoarse, breathy voice from day 1; laryngoscopy on day 2 showed the right vocal cord",
        "fixed near the midline with good compensation by the left; no stridor and no aspiration. Referred for voice therapy.",
    )
    admissions.append(Admission(
        title="Papillary thyroid carcinoma: total thyroidectomy",
        admitted=t.surgery,
        discharged=t.surgery_home,
        service="General Surgery",
        doctor=YALCIN,
        complaint=join(
            f"{c.age}-year-old woman with a multinodular goitre found on ultrasound in {_month(t.goitre)}. Fine-needle aspiration",
            f"of the dominant 24 mm right lobe nodule on {day_text(t.aspiration)} was suspicious for papillary thyroid carcinoma",
            "(Bethesda V). Seen in the surgical clinic and admitted on the day of surgery for a total thyroidectomy.",
            "Laryngoscopy before the operation: both vocal cords moving normally. Voice normal.",
        ),
        past_history=join(
            pneumonia_line,
            f"Fine-needle aspiration of the right thyroid nodule on {day_text(t.aspiration)} (day case).",
            "No regular medicines. No known drug allergies. Never smoked.",
        ),
        examination=join(
            c.vitals(),
            "Multinodular goitre with a firm dominant nodule in the right lobe. No palpable cervical lymph nodes. Voice normal.",
        ),
        course=join(
            f"Total thyroidectomy on {day_text(t.surgery)} (see the operation report); the right recurrent laryngeal nerve",
            "lost its monitoring signal at the end of the right-sided dissection although it was seen to be intact.",
            f"Day 1: hoarse, breathy voice, and tingling around the mouth with a corrected calcium of {calcium_low} mg/dL and",
            "PTH 9 pg/mL. Given intravenous calcium gluconate, then oral calcium carbonate and calcitriol; calcium 8.4 mg/dL on",
            "day 2, 8.6 mg/dL on day 3 and 8.8 mg/dL on day 4, with no further symptoms.",
            f"Flexible laryngoscopy on day 2 ({ENT}, ENT): right vocal cord paresis, cord fixed near the midline, good",
            "compensation by the left cord; airway adequate. Swallow assessment normal.",
            "Wound clean and dry. Histology on day 4: papillary thyroid carcinoma, classic type with a tall-cell component",
            "(about 20%), 24 mm, right lobe; no extrathyroidal extension; margins clear; vascular invasion in two vessels;",
            "background multinodular goitre in both lobes; pT2 NX. Discussed with the thyroid team: intermediate risk;",
            "radioiodine remnant ablation advised.",
        ),
        admission_diagnoses=(("E04.2", "Multinodular goitre with a right lobe nodule suspicious for papillary carcinoma (Bethesda V)"),),
        discharge_diagnoses=(
            ("C73", "Papillary thyroid carcinoma, right lobe, pT2 NX, after total thyroidectomy"),
            ("E89.2", "Postprocedural hypoparathyroidism, transient: hypocalcaemia, improving"),
            ("J38.0", "Right vocal cord paresis after thyroidectomy"),
            ("E89.0", "Postprocedural hypothyroidism (thyroid hormone deferred until after radioiodine)"),
        ),
        prescription=(
            "Calcium carbonate 1000 mg orally three times daily with meals for 2 weeks; stop after a normal calcium check",
            "Calcitriol 0.25 micrograms orally twice daily for 2 weeks",
            "Paracetamol 1 g orally up to four times daily as needed",
        ),
        recommendations=join(
            "Calcium check in one week at the endocrinology clinic (Dr. Selin Arslan); come back at once with tingling,",
            "cramps or muscle spasms. Wound review in the surgical clinic in 10 days.",
            "Voice therapy; repeat laryngoscopy in three months.",
            "Thyroid hormone is deliberately not started: radioiodine remnant ablation is planned in about four weeks, off",
            "thyroid hormone, with a low-iodine diet for the two weeks before it.",
        ),
        outcome="Improved",
        complications=complications,
        procedure=ProcedureReport(
            performed=t.surgery,
            name="Total thyroidectomy",
            operation=True,
            pre_diagnosis="Multinodular goitre; right lobe nodule suspicious for papillary thyroid carcinoma (Bethesda V)",
            post_diagnosis="Same",
            team=c.team(YALCIN),
            anaesthesia="General anaesthesia; endotracheal tube with nerve-monitoring electrodes",
            wound_class="Clean",
            note=join(
                "Low transverse collar incision; subplatysmal flaps; strap muscles separated in the midline.",
                "Left lobe first: middle thyroid vein divided; superior pole vessels taken on the gland, sparing the external",
                "branch of the superior laryngeal nerve; left recurrent laryngeal nerve identified and followed to the larynx",
                "with a normal monitoring signal; both left parathyroid glands preserved on their blood supply.",
                "Right lobe: the dominant nodule was firm and close to the ligament of Berry. Right recurrent laryngeal nerve",
                "identified and followed; both right parathyroid glands preserved. After the lobe was freed the right nerve",
                "signal fell from 780 to 60 µV; the nerve was seen to be intact and was not divided. Left signal normal at the end.",
                "Haemostasis checked at raised airway pressure. Strap muscles and platysma closed; subcuticular skin suture.",
            ),
            blood_loss="About 50 mL",
            complications=join(
                "Loss of the right recurrent laryngeal nerve monitoring signal with an intact nerve, followed by a right vocal",
                "cord paresis with hoarseness; transient hypocalcaemia from day 1 (see COMPLICATIONS DURING ADMISSION).",
            ),
            specimen="Total thyroidectomy specimen (both lobes and isthmus), oriented, for histology",
            body_site="Thyroid",
        ),
    ))

    # 4. Radioiodine remnant ablation; levothyroxine started on discharge.
    c = ctx(t.radioiodine)
    admissions.append(Admission(
        title="Radioiodine remnant ablation after total thyroidectomy",
        admitted=t.radioiodine,
        discharged=t.radioiodine_home,
        service="Nuclear Medicine",
        doctor=NUCLEAR_MEDICINE,
        complaint=join(
            f"{c.age}-year-old woman admitted for radioiodine (I-131) remnant ablation four weeks after a total thyroidectomy on",
            f"{day_text(t.surgery)} for papillary thyroid carcinoma (pT2 NX, tall-cell component; intermediate risk). Off thyroid",
            "hormone since the operation and on a low-iodine diet for two weeks. Tired and feels the cold. Voice still hoarse",
            f"but improving with voice therapy. No tingling since the calcium tablets were stopped on {day_text(t.calcium_stopped)}.",
        ),
        past_history=join(
            f"Total thyroidectomy on {day_text(t.surgery)}, complicated by transient hypocalcaemia (calcium and calcitriol for",
            "two weeks) and a right vocal cord paresis.", pneumonia_line,
            "No regular medicines. No known drug allergies. Not breastfeeding.",
        ),
        examination=join(
            c.vitals(pulse=(58, 66)),
            "Healed collar incision. Mildly hoarse voice; no stridor. No palpable cervical lymph nodes.",
        ),
        course=join(
            f"TSH {rng.uniform(62, 85):.1f} mIU/L; stimulated thyroglobulin {rng.uniform(1.4, 2.6):.1f} ng/mL with negative",
            "anti-thyroglobulin antibodies; calcium 9.3 mg/dL off supplements. Urine pregnancy test negative.",
            f"Given 3.7 GBq (100 mCi) of I-131 by mouth on {day_text(t.radioiodine)} in a shielded room. Mild neck tightness on",
            "day 2, eased by paracetamol. Post-therapy whole-body scan on day 3: uptake in the thyroid bed only; no uptake in",
            "the neck lymph nodes or elsewhere. Dose rate at 1 m below the release limit before discharge.",
            "Levothyroxine started on the day of discharge.",
        ),
        admission_diagnoses=(("C73", "Papillary thyroid carcinoma, after total thyroidectomy"),),
        discharge_diagnoses=(
            ("C73", "Papillary thyroid carcinoma, after total thyroidectomy and radioiodine remnant ablation"),
            ("E89.0", "Postprocedural hypothyroidism"),
            ("J38.0", "Right vocal cord paresis after thyroidectomy, improving"),
        ),
        prescription=(
            f"{_levothyroxine(p, t.radioiodine_home)}: start today",
            "Paracetamol 1 g orally up to four times daily as needed",
        ),
        recommendations=join(
            "Radiation precautions for 7 days: sleep alone, keep at least 1 m from adults and 2 m from children and pregnant",
            "women; no pregnancy for 6 months.",
            "TSH and free T4 at the endocrinology clinic (Dr. Selin Arslan) in 6 weeks; TSH target 0.1–0.5 mIU/L for the",
            "first year. Neck ultrasound and stimulated thyroglobulin at one year. Continue voice therapy.",
        ),
        outcome="Improved",
    ))

    # 5. Vestibular neuronitis.
    admissions.append(vertigo(ctx(t.vertigo)))

    # 6. Acute cholecystitis: laparoscopic cholecystectomy.
    c = ctx(t.cholecystitis)
    performed = t.cholecystitis + timedelta(days=1)
    discharged = performed + timedelta(days=2)
    admissions.append(Admission(
        title="Acute calculous cholecystitis: laparoscopic cholecystectomy",
        admitted=t.cholecystitis,
        discharged=discharged,
        service="General Surgery",
        doctor=YALCIN,
        complaint=join(
            f"{c.age}-year-old woman with two days of constant right upper abdominal pain spreading to the right shoulder,",
            "fever and vomiting, after several shorter attacks of pain following fatty meals over the last year.",
        ),
        past_history=join(*thyroid_lines, pneumonia_line, regular(t.cholecystitis), f"Previous operations: {thyroidectomy}."),
        examination=join(
            c.vitals(temp=(37.9, 38.6), pulse=(92, 106)),
            "Tender in the right upper quadrant with a positive Murphy's sign; no jaundice. Healed collar scar. Voice normal.",
        ),
        course=join(
            f"WBC {rng.uniform(13.0, 15.5):.1f} ×10³/µL, CRP {rng.randint(80, 120)} mg/L, bilirubin 0.9 mg/dL, ALT {rng.randint(40, 60)} U/L,",
            "lipase normal. Ultrasound: gallstones with a stone impacted in the gallbladder neck, a thickened gallbladder wall",
            "(6 mm) and a little fluid around it; common bile duct 5 mm.",
            "Intravenous ceftriaxone and metronidazole. Laparoscopic cholecystectomy the next day (see the operation report);",
            "normal vocal cord movement seen at intubation. Eating on day 1 after the operation; afebrile; antibiotics stopped.",
            "Levothyroxine continued throughout.",
        ),
        admission_diagnoses=(("K81.0", "Acute cholecystitis"),),
        discharge_diagnoses=(
            ("K80.0", "Calculus of gallbladder with acute cholecystitis"),
            ("E89.0", "Postprocedural hypothyroidism"),
        ),
        prescription=("Paracetamol 1 g orally up to four times daily as needed", *c.continuing(discharged)),
        recommendations=join(
            "Surgical clinic in 2 weeks with the histology. Normal diet; no lifting over 5 kg for 2 weeks.",
            "Return with fever, worsening pain or yellow eyes.",
        ),
        outcome="Recovered",
        procedure=ProcedureReport(
            performed=performed,
            name="Laparoscopic cholecystectomy",
            operation=True,
            pre_diagnosis="Acute calculous cholecystitis",
            post_diagnosis="Same; oedematous gallbladder with a stone impacted in the neck",
            team=c.team(YALCIN),
            anaesthesia="General anaesthesia",
            wound_class="Clean-contaminated",
            note=join(
                "Open (Hasson) entry at the umbilicus; three further ports. Oedematous, inflamed gallbladder with omentum",
                "adherent to it; decompressed with a needle. Calot's triangle dissected to the critical view of safety.",
                "Cystic duct and artery clipped and divided. Gallbladder removed from the liver bed with diathermy and taken out",
                "in a bag through the umbilical port. Haemostasis checked; fascia at the umbilicus closed.",
            ),
            blood_loss="Minimal",
            specimen="Gallbladder with stones, for histology",
            body_site="Gallbladder",
        ),
    ))

    # 7. Fine-needle aspiration of a neck lymph node on surveillance: benign.
    c = ctx(t.node)
    scan = workday(t.node - timedelta(days=12), forward=False)
    admissions.append(Admission(
        title="Neck lymph node: fine-needle aspiration",
        admitted=t.node,
        discharged=t.node,
        service="Endocrinology",
        doctor=ENDOCRINOLOGIST,
        complaint=join(
            f"{c.age}-year-old woman under surveillance after papillary thyroid carcinoma. A routine neck ultrasound on",
            f"{day_text(scan)} showed a 9 mm oval lymph node at right level III with an unclear fatty hilum; the thyroid bed was",
            "clear. Thyroglobulin undetectable on levothyroxine, with negative antibodies. She had a sore throat and a cold two",
            "weeks before the scan. Admitted as a day case for fine-needle aspiration.",
        ),
        past_history=join(
            *thyroid_lines, pneumonia_line, regular(t.node), f"Previous operations: {thyroidectomy}; {cholecystectomy}.",
        ),
        examination=join(c.vitals(), "Healed collar scar. No palpable mass in the thyroid bed or neck. Voice normal."),
        course=join(
            "Ultrasound-guided fine-needle aspiration of the right level III lymph node with a needle washout for",
            "thyroglobulin (see the procedure report). No bleeding or swelling on observation. On-site check: plentiful",
            "lymphoid cells of mixed types, no thyroid or malignant cells. Washout thyroglobulin below 0.2 ng/mL, reported the",
            "same afternoon. Home the same day. Final cytology to follow.",
        ),
        admission_diagnoses=(("R59.0", "Localised enlarged lymph node, right neck, level III"),),
        discharge_diagnoses=(
            ("R59.0", "Localised enlarged lymph node, right neck, level III: reactive on the on-site check; washout thyroglobulin undetectable"),
            ("C73", "Papillary thyroid carcinoma, treated; no evidence of disease"),
            ("E89.0", "Postprocedural hypothyroidism"),
        ),
        prescription=tuple(c.continuing(t.node)),
        recommendations=join(
            "Endocrinology clinic (Dr. Selin Arslan) in two weeks for the final cytology.",
        ),
        outcome="Unchanged",
        procedure=ProcedureReport(
            performed=t.node,
            name="Ultrasound-guided fine-needle aspiration of a right neck lymph node (level III)",
            operation=False,
            pre_diagnosis="9 mm right level III cervical lymph node with an unclear hilum, after papillary thyroid carcinoma",
            post_diagnosis="Same; benign-looking reactive lymph node on the on-site check; washout thyroglobulin undetectable",
            team=f"{RADIOLOGIST} (radiologist); {ENDOCRINOLOGIST} (endocrinologist)",
            anaesthesia="Local anaesthesia (lidocaine 1%)",
            wound_class="Clean",
            note=join(
                "Under ultrasound guidance, three passes with a 25-gauge needle into the right level III node; smears and a",
                "liquid-based sample prepared, and the needle rinsed in 1 mL of saline for thyroglobulin. Pressure for 5 minutes;",
                "no haematoma.",
            ),
            blood_loss="None",
            specimen="Fine-needle aspirate of the right level III lymph node, for cytology; needle washout for thyroglobulin",
            body_site="Right neck, level III lymph node",
        ),
    ))

    # 8. Fracture of the left distal radius, fixed with a plate.
    c = ctx(t.wrist)
    performed = t.wrist + timedelta(days=1)
    discharged = performed + timedelta(days=1)
    admissions.append(Admission(
        title="Fracture of the left distal radius",
        admitted=t.wrist,
        discharged=discharged,
        service="Orthopaedics and Traumatology",
        doctor=ORTHOPAEDICS,
        complaint=join(
            f"{c.age}-year-old woman who tripped on a kerb and fell onto her outstretched left hand; pain, swelling",
            "and deformity of the left wrist. No head injury. Right-handed.",
        ),
        past_history=join(
            *thyroid_lines,
            f"Fine-needle aspiration of a right neck lymph node in {_month(t.node)}: benign, reactive lymph node.",
            pneumonia_line, regular(t.wrist), f"Previous operations: {thyroidectomy}; {cholecystectomy}.",
        ),
        examination=join(
            c.vitals(pulse=(80, 96)),
            "Dinner-fork deformity of the left wrist; skin intact; radial pulse present; sensation in the fingers normal.",
        ),
        course=join(
            "X-ray: dorsally displaced, intra-articular fracture of the left distal radius with shortening.",
            f"Backslab and elevation; operation on {day_text(performed)} (see the operation report). Fingers moving well and",
            "the hand warm before discharge. Levothyroxine continued.",
        ),
        admission_diagnoses=(("S52.5", "Fracture of the left distal radius"),),
        discharge_diagnoses=(
            ("S52.5", "Fracture of the lower end of the left radius, intra-articular, fixed"),
            ("E89.0", "Postprocedural hypothyroidism"),
        ),
        prescription=("Paracetamol 1 g orally four times daily as needed", *c.continuing(discharged)),
        recommendations=join(
            "Keep the hand raised; move the fingers often. Fracture clinic in 2 weeks for the wound and an X-ray; hand therapy",
            "from then. The plate stays in unless it causes trouble.",
        ),
        outcome="Improved",
        procedure=ProcedureReport(
            performed=performed,
            name="Open reduction and internal fixation of left distal radius fracture",
            operation=True,
            pre_diagnosis="Displaced intra-articular fracture of the left distal radius",
            post_diagnosis="Same",
            team=c.team(ORTHOPAEDICS),
            anaesthesia="Infraclavicular brachial plexus block with sedation; arm tourniquet",
            wound_class="Clean",
            note=join(
                "Volar (modified Henry) approach through the flexor carpi radialis sheath; pronator quadratus elevated. Fracture",
                "reduced under fluoroscopy and fixed with a volar locking plate and screws; joint surface restored. Pronator",
                "quadratus repaired; skin closed. Volar plaster slab.",
            ),
            body_site="Left wrist (distal radius)",
            device="Volar locking plate (titanium)",
        ),
    ))

    return [add(chart, admission) for admission in sorted(admissions, key=lambda item: item.admitted)]


# ------------------------------------------------------------------ p-2044, coronary artery disease with two stents

CARDIOLOGIST = "Dr. Zeynep Kara"
GASTROENTEROLOGIST = "Dr. Ayhan Koç"
ASPIRIN = ("B01AC06", "acetylsalicylic acid")
CLOPIDOGREL = ("B01AC04", "clopidogrel")
PANTOPRAZOLE = ("A02BC02", "pantoprazole")


@dataclass(frozen=True)
class CoronaryTimeline:
    mi: date  # admitted: inferior ST-elevation myocardial infarction, primary stent to the right coronary artery
    mi_home: date
    stent: date  # admitted: planned (elective) stent to the left anterior descending artery
    stent_home: date
    cellulitis: date
    bleed: date  # admitted: bleeding duodenal ulcer on aspirin and clopidogrel; clopidogrel stopped this day
    bleed_home: date  # pantoprazole started, for as long as he takes aspirin
    hernia: date  # admitted and operated: open right inguinal hernia repair with mesh, on aspirin
    colic: date
    chest_pain: date  # admitted; coronary angiography the next day: both stents patent
    pneumonia: date
    visits: tuple[date, date, date]  # cardiology clinic with Dr. Zeynep Kara


def coronary_timeline(anchor: date) -> CoronaryTimeline:
    def back(days: int) -> date:
        return workday(anchor - timedelta(days=days), forward=False)

    def after(day: date, days: int) -> date:
        return workday(day + timedelta(days=days), forward=True)

    mi = back(2922)
    stent = after(mi, 110)
    bleed = after(stent, 285)
    return CoronaryTimeline(
        mi=mi, mi_home=mi + timedelta(days=5), stent=stent, stent_home=stent + timedelta(days=1),
        cellulitis=after(stent, 130), bleed=bleed, bleed_home=bleed + timedelta(days=5),
        hernia=back(1820), colic=back(1240), chest_pain=back(735), pneumonia=back(430),
        visits=(back(640), back(375), back(118)),
    )


def coronary_disease(s: Story) -> None:
    """Patient P-2044: an inferior heart attack eight years ago treated by a stent, a second, planned stent, and a
    bleeding duodenal ulcer on aspirin and clopidogrel, after which clopidogrel was stopped for good.

    The problem list and medication orders follow from his epicrisis reports (coronary_disease_reports); the last two
    years hold three cardiology visits with Dr. Zeynep Kara, each with lipid, kidney and blood count results, and the
    next one is booked. His notes keep to the heart and the bleed: his other admissions are told by the reports alone,
    apart from the pneumonia he had just before the second visit.
    """
    c, rng, doc = s.chart, s.rng, KARA
    t = coronary_timeline(s.anchor)
    c.set_height(174)

    c.condition(
        "I25.1", "Atherosclerotic heart disease", onset=t.mi, clinician=doc, text="Coronary artery disease",
        note=(
            f"Drug-eluting stents: right coronary artery on {day_text(t.mi)} (primary PCI for an inferior myocardial "
            f"infarction) and left anterior descending artery on {day_text(t.stent)} (elective). Both stents patent on "
            f"coronary angiography in {_month(t.chest_pain)}."
        ),
    )
    c.condition(
        "I25.2", "Old myocardial infarction", onset=t.mi, clinician=doc,
        text=f"Previous inferior ST-elevation myocardial infarction ({_month(t.mi)})",
    )
    c.condition(
        "Z87.1", "Personal history of diseases of the digestive system", onset=t.bleed, clinician=KOC,
        text="Previous bleeding duodenal ulcer on aspirin and clopidogrel",
        note=(
            f"Endoscopic haemostasis and two units of red cells on {day_text(t.bleed)}; Helicobacter pylori negative. "
            "Clopidogrel stopped for good; aspirin continued with long-term pantoprazole. No anti-inflammatory painkillers."
        ),
    )
    c.no_known_allergies(t.mi)
    stent_reason = "Coronary artery disease with stents; secondary prevention"
    c.start_med("Aspirin 100 mg tablet", "100 mg orally once daily", start=t.mi, prescriber=doc, atc=ASPIRIN, reason=stent_reason)
    clopidogrel = c.start_med(
        "Clopidogrel 75 mg tablet", "75 mg orally once daily", start=t.mi, prescriber=doc, atc=CLOPIDOGREL,
        reason="Dual antiplatelet therapy after coronary stenting",
    )
    c.stop_med(clopidogrel, end=t.bleed, reason="Stopped for good: bleeding duodenal ulcer on aspirin and clopidogrel")
    c.start_med(
        "Atorvastatin 80 mg tablet", "80 mg orally once daily at night", start=t.mi, prescriber=doc, atc=ATORVASTATIN,
        reason=stent_reason,
    )
    c.start_med(
        "Bisoprolol 5 mg tablet", "5 mg orally once daily", start=t.mi, prescriber=doc, atc=BISOPROLOL,
        reason="After myocardial infarction",
    )
    c.start_med(
        "Pantoprazole 40 mg tablet", "40 mg orally once daily, 30 minutes before breakfast", start=t.bleed_home,
        prescriber=KOC, atc=PANTOPRAZOLE, reason="Bleeding duodenal ulcer; protection while on aspirin",
    )

    history = [
        f"Inferior ST-elevation myocardial infarction on {day_text(t.mi)}: primary PCI with a drug-eluting stent to the "
        "right coronary artery; right femoral puncture-site haematoma, managed with compression.",
        f"Planned (elective) drug-eluting stent to the left anterior descending artery on {day_text(t.stent)}.",
        f"Bleeding duodenal ulcer on aspirin and clopidogrel on {day_text(t.bleed)}: endoscopic haemostasis and two units "
        "of red cells; Helicobacter pylori negative. Clopidogrel stopped for good; aspirin alone since, with pantoprazole.",
        f"Open right inguinal hernia repair with mesh in {_month(t.hernia)}, with aspirin continued throughout.",
        f"Chest pain admission in {_month(t.chest_pain)}: troponin normal; coronary angiography showed both stents patent "
        "and no new stenosis; chest wall pain.",
        f"Ex-smoker since the infarction in {t.mi.year}.",
    ]
    medicines = (
        "Takes aspirin 100 mg once daily, atorvastatin 80 mg at night, bisoprolol 5 mg once daily and pantoprazole 40 mg "
        "before breakfast."
    )
    exam = "Heart sounds normal, no murmur. Chest clear. No ankle swelling. Right radial pulse normal."
    ldl = [rng.uniform(47, 53), rng.uniform(45, 51), rng.uniform(46, 52)]
    hgb = [rng.uniform(14.0, 14.6), rng.uniform(13.8, 14.4), rng.uniform(14.1, 14.7)]
    weight = rng.uniform(82, 85)
    orders: dict[str, dict] = {}
    pre_visit = workday(s.appointment.date() - timedelta(days=4), forward=False)

    for i, day in enumerate(t.visits):
        last = i == len(t.visits) - 1
        panels = {
            "lipid": lipids(ldl=ldl[i], hdl=rng.uniform(42, 48), tg=rng.uniform(105, 140)),
            "bmp": chemistry(rng, cr=rng.uniform(0.92, 1.02)),
            "cbc": cbc(rng, "male", hgb=hgb[i]),
        }
        c.draw(s.before(day), panels, orders=orders, requester=doc)
        start = s.clinic(day)
        visit = c.visit(start, doc, "Cardiology follow-up", "Coronary artery disease with two stents; previous ulcer bleed")
        vitals = c.vitals(visit, sbp=rng.gauss(126, 4), dbp=rng.gauss(76, 3), hr=rng.gauss(62, 3), weight=weight + 0.4 * i)
        labs = c.labs_text(["ldl", "hdl", "tg", "hgb", "cr", "egfr", "k"], before=start, compare=("ldl", "hgb") if i else ())
        next_day = pre_visit if last else t.visits[i + 1]
        orders = c.order_many(
            ["lipid", "bmp", "cbc"], ordered=start + timedelta(minutes=20),
            due=pre_visit if last else next_day - timedelta(days=3), requester=doc, encounter=visit,
            reason="Secondary prevention after coronary stenting; aspirin with a previous ulcer bleed",
        )
        ldl_text, hgb_text = c.fmt("ldl", c.value("ldl", start)), c.fmt("hgb", c.value("hgb", start))
        assessment = numbered([
            f"Coronary artery disease with stents to the right coronary artery ({t.mi.year}) and the left anterior "
            f"descending artery ({t.stent.year}) — no angina. LDL {ldl_text} on atorvastatin 80 mg, at target (below 55 mg/dL).",
            f"Previous bleeding duodenal ulcer on dual antiplatelet therapy ({t.bleed.year}) — no further bleeding on "
            f"aspirin alone with pantoprazole. Hb {hgb_text}.",
        ])
        plan = [
            "Continue aspirin 100 mg once daily for life, always with pantoprazole 40 mg once daily; no second antiplatelet medicine.",
            "Continue atorvastatin 80 mg at night and bisoprolol 5 mg once daily.",
            "No anti-inflammatory painkillers (NSAIDs): previous ulcer bleed on antiplatelet therapy.",
        ]
        if i == 0:
            subjective = (
                f"Review after the chest pain admission in {_month(t.chest_pain)}, when coronary angiography showed both stents "
                "patent. No chest pain since; walks 40 minutes on most days without symptoms. No black stools or "
                f"indigestion. {medicines}"
            )
            parts = [("Subjective", subjective), ("Cardiac history", bullets(history))]
            plan += ["Lipid panel, basic metabolic panel and CBC before the next visit.", "Review in 9 months."]
        elif i == 1:
            subjective = (
                f"Admitted with community-acquired pneumonia in {_month(t.pneumonia)}; recovered fully. No chest pain or "
                f"breathlessness on exertion. No black stools. {medicines}"
            )
            parts = [("Subjective", subjective)]
            plan += ["Lipid panel, basic metabolic panel and CBC before the next visit.", "Review in 8 months."]
        else:
            subjective = f"Well. No chest pain, palpitations or breathlessness. No black stools or indigestion. {medicines}"
            parts = [("Subjective", subjective)]
            plan += [
                "Lipid panel, basic metabolic panel and CBC a few days before the next visit.",
                f"Cardiology follow-up on {day_text(s.appointment)}.",
            ]
        parts += [("Objective", [vitals, exam, labs]), ("Assessment", assessment), ("Plan", bullets(plan))]
        c.note(
            when=start + timedelta(minutes=25), author=doc, title="Cardiology progress note", encounter=visit,
            body=sections(*parts),
        )

    c.appointment(s.appointment, doc, "Coronary artery disease follow-up")


def _order_line(p: Patient, name: str, day: date) -> str:
    """"Aspirin 100 mg orally once daily" from the order active on the day."""
    order = next(order for order in p.medicines(day) if name_of(order).lower() == name)
    return f"{name_of(order)} {order['dosageInstruction'][0]['text']}"


def coronary_disease_reports(chart: PatientChart, anchor: date, seed: int) -> list[dict]:
    """P-2044's eight epicrisis reports, added oldest first; returns the DocumentReferences. Three unrelated admissions
    (cellulitis, renal colic, pneumonia) come from the background catalogue; the rest are written for him."""
    rng = random.Random(f"epicrisis:{chart.pid}:{seed}")
    p = Patient.of(chart, coronary_disease.__name__, 0, False)
    t = coronary_timeline(anchor)
    # The catalogue's builders name the infarction and the ulcer bleed as history, not as discharge diagnoses.
    p.treated = {
        "I25.2": (
            "a previous inferior myocardial infarction",
            f"Inferior ST-elevation myocardial infarction on {day_text(t.mi)}: primary stent to the right coronary artery "
            "(complicated by a right groin haematoma), then a planned stent to the left anterior descending artery on "
            f"{day_text(t.stent)}.",
        ),
        "Z87.1": (
            "a previous bleeding duodenal ulcer",
            f"Bleeding duodenal ulcer on aspirin and clopidogrel in {_month(t.bleed)}: endoscopic haemostasis and two units "
            "of red cells; Helicobacter pylori negative; clopidogrel stopped for good, aspirin continued with long-term "
            "pantoprazole; no anti-inflammatory painkillers.",
        ),
    }
    p.habits = f"Ex-smoker (30 pack-years, stopped after the heart attack in {t.mi.year}). Alcohol rarely."

    # His operations, for the past history the catalogue's builders write.
    operations = [
        (t.mi, "primary PCI with a drug-eluting stent to the right coronary artery"),
        (t.stent, "elective PCI with a drug-eluting stent to the left anterior descending artery"),
        (t.hernia, "open right inguinal hernia repair with mesh"),
    ]

    def ctx(day: date) -> Ctx:
        return Ctx(p, rng, day, False, operations)

    def line(name: str, day: date, note: str = "continue") -> str:
        return f"{_order_line(p, name, day)}: {note}"

    def regular(day: date) -> str:
        names = ("aspirin", "clopidogrel", "atorvastatin", "bisoprolol")
        return "; ".join(_order_line(p, name, day).replace(" orally", "").lower() for name in names)

    admissions: list[Admission] = []

    # 1. Inferior ST-elevation myocardial infarction: primary stent, with a groin haematoma.
    c = ctx(t.mi)
    size = rng.randint(5, 7)
    haematoma = (
        f"Right femoral puncture-site haematoma ({size} cm) on day 1 after the primary stent; ultrasound showed no false "
        "aneurysm or arteriovenous fistula. Managed with compression and bed rest for 12 hours; Hb 14.6 g/dL before and "
        "13.1 g/dL after; no transfusion. Antiplatelet medicines continued."
    )
    admissions.append(Admission(
        title="Inferior ST-elevation myocardial infarction: primary stent to the right coronary artery",
        admitted=t.mi,
        discharged=t.mi_home,
        service="Cardiology",
        doctor=CARDIOLOGIST,
        complaint=join(
            f"{c.age}-year-old man, a smoker, brought in by ambulance with 90 minutes of crushing central chest pain spreading",
            "to the jaw and left arm, with sweating and nausea, which began at rest in the early morning. No previous heart",
            "trouble. The ambulance ECG showed ST elevation in leads II, III and aVF; aspirin 300 mg was given on the way.",
        ),
        past_history=join(
            "No known illnesses; had not seen a doctor for some years. No regular medicines. No known drug allergies.",
            "Smokes about 20 cigarettes a day (30 pack-years). Alcohol rarely.",
            "Father had a heart attack at 70.",
        ),
        examination=join(
            c.vitals(pulse=(54, 62), sbp=(108, 122), spo2=(95, 97)),
            "Pale, sweating, in pain. Heart sounds normal, no murmur; chest clear; no leg swelling.",
        ),
        course=join(
            "Taken straight to the catheter laboratory: clopidogrel 600 mg and heparin. The right radial artery went into",
            "spasm, so the right femoral artery was used. Angiography: occluded mid right coronary artery (the culprit), an",
            "80% stenosis of the mid left anterior descending artery (LAD) and minor disease of the circumflex artery.",
            "Primary PCI with a drug-eluting stent to the right coronary artery (see the operation report); door-to-balloon",
            f"time {rng.randint(48, 58)} minutes. Pain gone and ST elevation resolved by the end of the procedure.",
            f"Peak high-sensitivity troponin T {rng.randint(2800, 4200)} ng/L. Left ventriculography: inferior hypokinesia,",
            "overall left ventricular function preserved.",
            f"Day 1: a {size} cm haematoma at the right femoral puncture site (see COMPLICATIONS DURING ADMISSION).",
            "Started aspirin, clopidogrel, atorvastatin and bisoprolol. Stop-smoking counselling. Walking on the ward",
            "without pain from day 3. Heart team decision: the LAD stenosis to be treated with a planned (elective) stent in",
            "about three months, on dual antiplatelet therapy.",
        ),
        admission_diagnoses=(("I21.1", "Acute inferior ST-elevation myocardial infarction"),),
        discharge_diagnoses=(
            ("I21.1", "Acute inferior ST-elevation myocardial infarction, treated by primary PCI with a drug-eluting stent to the right coronary artery"),
            ("I25.1", "Coronary artery disease: 80% stenosis of the mid left anterior descending artery, for elective stenting"),
            ("T81.0", "Right femoral puncture-site haematoma after coronary intervention, managed with compression"),
        ),
        complications=haematoma,
        prescription=(
            line("aspirin", t.mi_home, "new; for life"),
            line("clopidogrel", t.mi_home, "new; together with aspirin for 12 months; do not stop without asking cardiology"),
            line("atorvastatin", t.mi_home, "new"),
            line("bisoprolol", t.mi_home, "new"),
        ),
        recommendations=join(
            "Stop smoking: referred to the stop-smoking clinic. Cardiac rehabilitation programme. No driving for 4 weeks.",
            "Cardiology clinic (Dr. Zeynep Kara) in 4 weeks. Planned admission in about three months for elective",
            "stenting of the LAD. Return with chest pain, or with swelling, pain or bleeding in the right groin.",
        ),
        outcome="Improved",
        procedure=ProcedureReport(
            performed=t.mi,
            name="Primary percutaneous coronary intervention with a drug-eluting stent to the right coronary artery",
            operation=True,
            pre_diagnosis="Acute inferior ST-elevation myocardial infarction",
            post_diagnosis=(
                "Occluded mid right coronary artery (culprit), stented; 80% stenosis of the mid left anterior descending "
                "artery, left for a planned procedure"
            ),
            team=f"{CARDIOLOGIST} (interventional cardiologist)",
            anaesthesia="Local anaesthesia (lidocaine 2%) at the puncture site; intravenous fentanyl",
            wound_class="Clean",
            note=join(
                "Right radial access abandoned after severe spasm; right femoral access with a 6F sheath. Heparin 70 units/kg.",
                "Left system: 80% stenosis of the mid LAD; circumflex with minor irregularities. Right coronary artery",
                "occluded in its mid segment (TIMI 0 flow). Lesion crossed with a guidewire, aspiration of thrombus,",
                "predilatation, then a 3.5 × 28 mm drug-eluting stent deployed and post-dilated; TIMI 3 flow, no residual",
                f"stenosis. Contrast {rng.randint(160, 200)} mL. Femoral sheath removed with manual compression.",
            ),
            complications="Right femoral puncture-site haematoma on day 1, managed with compression (see COMPLICATIONS DURING ADMISSION).",
            body_site="Right coronary artery",
            device="Drug-eluting stent 3.5 × 28 mm",
        ),
    ))

    # 2. Planned (elective) stent to the left anterior descending artery.
    c = ctx(t.stent)
    admissions.append(Admission(
        title="Coronary artery disease: elective stent to the left anterior descending artery",
        admitted=t.stent,
        discharged=t.stent_home,
        service="Cardiology",
        doctor=CARDIOLOGIST,
        complaint=join(
            f"{c.age}-year-old man admitted electively for a planned stent to the left anterior descending artery (LAD).",
            f"Inferior myocardial infarction on {day_text(t.mi)}, treated by a primary stent to the right coronary artery; an",
            "80% stenosis of the mid LAD was left for this planned procedure. Since then mild chest tightness on brisk",
            "uphill walking, gone with rest. Stopped smoking after the infarction. Takes aspirin and clopidogrel without",
            "missed doses.",
        ),
        past_history=join(
            f"Inferior ST-elevation myocardial infarction on {day_text(t.mi)}; the primary stent was complicated by a right",
            "femoral puncture-site haematoma, managed with compression.",
            f"Regular medicines: {regular(t.stent)}. No known drug allergies.",
            f"Previous operations: primary PCI with a drug-eluting stent to the right coronary artery ({t.mi.year}).",
            f"Ex-smoker since {_month(t.mi)} (30 pack-years).",
        ),
        examination=join(c.vitals(pulse=(56, 64)), "Heart sounds normal; chest clear. Right groin healed, no bruit. Right radial pulse normal."),
        course=join(
            "Elective PCI via the right radial artery on the day of admission (see the operation report): drug-eluting stent",
            "to the mid LAD. The right coronary artery stent widely patent. No problem at the radial puncture site; ECG",
            "unchanged and troponin not raised after the procedure. Home the next morning.",
        ),
        admission_diagnoses=(("I25.1", "Coronary artery disease: stenosis of the mid left anterior descending artery, for elective stenting"),),
        discharge_diagnoses=(
            ("I25.1", "Coronary artery disease: elective drug-eluting stent to the left anterior descending artery; right coronary artery stent patent"),
            ("I25.2", "Old inferior myocardial infarction"),
        ),
        prescription=(
            line("aspirin", t.stent_home, "continue for life"),
            line("clopidogrel", t.stent_home, "continue together with aspirin for 12 months from today"),
            line("atorvastatin", t.stent_home),
            line("bisoprolol", t.stent_home),
        ),
        recommendations=join(
            f"Dual antiplatelet therapy (aspirin and clopidogrel) planned for 12 months, until {_month(t.stent + timedelta(days=365))};",
            "then aspirin alone. Keep the wrist dressing dry for 24 hours; no heavy lifting with the right arm for 3 days.",
            "Cardiology clinic (Dr. Zeynep Kara) in 6 weeks. Continue cardiac rehabilitation.",
        ),
        outcome="Improved",
        procedure=ProcedureReport(
            performed=t.stent,
            name="Elective percutaneous coronary intervention with a drug-eluting stent to the left anterior descending artery",
            operation=True,
            pre_diagnosis="Coronary artery disease: 80% stenosis of the mid left anterior descending artery; old inferior myocardial infarction",
            post_diagnosis="Same; stented, no residual stenosis; right coronary artery stent patent",
            team=f"{CARDIOLOGIST} (interventional cardiologist)",
            anaesthesia="Local anaesthesia (lidocaine 2%) at the puncture site",
            wound_class="Clean",
            note=join(
                "Right radial access with a 6F sheath; intra-arterial verapamil and heparin. Right coronary artery stent widely",
                "patent. Mid LAD stenosis of 80% crossed with a guidewire, predilated, and a 3.0 × 23 mm drug-eluting stent",
                f"deployed and post-dilated; TIMI 3 flow, no residual stenosis. Contrast {rng.randint(110, 150)} mL. Sheath",
                "removed; radial compression band applied.",
            ),
            body_site="Left anterior descending coronary artery",
            device="Drug-eluting stent 3.0 × 23 mm",
        ),
    ))

    # 3. Cellulitis, on aspirin and clopidogrel.
    admissions.append(cellulitis(ctx(t.cellulitis)))

    # 4. Bleeding duodenal ulcer on aspirin and clopidogrel: endoscopy, transfusion; clopidogrel stopped for good.
    c = ctx(t.bleed)
    hb_in, hb_after, hb_out = rng.uniform(7.2, 7.6), rng.uniform(9.2, 9.5), rng.uniform(9.6, 9.9)
    admissions.append(Admission(
        title="Upper gastrointestinal bleeding from a duodenal ulcer on aspirin and clopidogrel",
        admitted=t.bleed,
        discharged=t.bleed_home,
        service="Gastroenterology",
        doctor=GASTROENTEROLOGIST,
        complaint=join(
            f"{c.age}-year-old man with coronary artery disease and two stents, on aspirin and clopidogrel, admitted with two",
            "days of black, tarry stools and a faint on standing on the morning of admission. Vague upper abdominal",
            "discomfort for two weeks. No vomiting of blood. No anti-inflammatory painkillers.",
        ),
        past_history=join(
            p.treated["I25.2"][1], f"Cellulitis of the leg in {_month(t.cellulitis)}, treated in this hospital.",
            f"Regular medicines: {regular(t.bleed - timedelta(days=1))}. No known drug allergies.",
            "Previous operations: " + "; ".join(f"{text} ({when.year})" for when, text in operations if when < t.bleed) + ".",
            p.habits,
        ),
        examination=join(
            c.vitals(pulse=(108, 118), sbp=(92, 102)),
            "Pale, cool hands. Epigastric tenderness, no guarding. Melaena on rectal examination.",
        ),
        course=join(
            f"Hb {hb_in:.1f} g/dL (14.3 g/dL at the last check), urea raised, creatinine {rng.uniform(1.05, 1.2):.2f} mg/dL;",
            f"platelets normal; INR 1.0. Glasgow-Blatchford score {rng.randint(12, 14)}. Aspirin and clopidogrel withheld.",
            "Intravenous fluids, transfusion of two units of red cells, and intravenous pantoprazole (80 mg, then an infusion",
            "for 72 hours). Gastroscopy within 12 hours (see the procedure report): a 14 mm ulcer in the posterior duodenal",
            "bulb with a non-bleeding visible vessel, treated with adrenaline injection and two clips. Antral biopsies:",
            "no Helicobacter pylori on histology.",
            f"No further bleeding: Hb {hb_after:.1f} g/dL after the transfusion and {hb_out:.1f} g/dL at discharge. Eating",
            "normally from day 2.",
            f"Cardiology opinion ({CARDIOLOGIST}): the infarction was 13 months ago and the elective LAD stent more than 9",
            f"months ago, so clopidogrel was stopped for good on {day_text(t.bleed)}; aspirin restarted on day 3, with",
            "long-term pantoprazole.",
        ),
        admission_diagnoses=(("K92.1", "Melaena"), ("D62", "Acute posthaemorrhagic anaemia")),
        discharge_diagnoses=(
            ("K26.0", "Duodenal ulcer with haemorrhage, posterior bulb, 14 mm, Forrest IIa, on aspirin and clopidogrel; treated endoscopically; Helicobacter pylori negative"),
            ("D62", "Acute posthaemorrhagic anaemia, transfused two units of red cells"),
            ("I25.1", "Coronary artery disease with stents to the right coronary and left anterior descending arteries"),
        ),
        prescription=(
            line("pantoprazole", t.bleed_home, "new; for as long as aspirin is taken"),
            line("aspirin", t.bleed_home, f"continue (restarted on {day_text(t.bleed + timedelta(days=2))})"),
            line("atorvastatin", t.bleed_home),
            line("bisoprolol", t.bleed_home),
        ),
        recommendations=join(
            "Clopidogrel stopped permanently: do not restart it unless a cardiologist advises. Aspirin 100 mg once daily",
            "continues for life, always with pantoprazole. No anti-inflammatory painkillers; paracetamol is safe.",
            "Full blood count with the family doctor in 2 weeks. Cardiology clinic (Dr. Zeynep Kara) in 4 weeks.",
            "Return at once with black stools, vomiting blood or fainting.",
        ),
        outcome="Improved",
        procedure=ProcedureReport(
            performed=t.bleed,
            name="Gastroscopy with endoscopic haemostasis of a duodenal ulcer (adrenaline injection and clips)",
            operation=False,
            pre_diagnosis="Upper gastrointestinal bleeding (melaena) on aspirin and clopidogrel",
            post_diagnosis="Duodenal ulcer, posterior bulb, 14 mm, with a non-bleeding visible vessel (Forrest IIa); haemostasis achieved",
            team=f"{GASTROENTEROLOGIST} (endoscopist)",
            anaesthesia="Conscious sedation (midazolam 2 mg intravenously) and lidocaine throat spray",
            wound_class="Not applicable",
            note=join(
                "Oesophagus normal. Stomach: altered blood in the fundus, washed clear; no gastric ulcer. Two antral biopsies",
                "for histology. Duodenal bulb: 14 mm ulcer on the posterior wall with a raised, non-bleeding visible vessel.",
                "Injected with 8 mL of adrenaline 1:10,000 around the vessel, then two through-the-scope clips placed across",
                "it. No bleeding at the end. Second part of the duodenum normal.",
            ),
            blood_loss="None",
            specimen="Antral biopsies for histology: no Helicobacter pylori",
            body_site="Duodenum",
        ),
    ))

    # 5. Right inguinal hernia repaired with mesh, aspirin continued throughout.
    c = ctx(t.hernia)
    discharged = t.hernia + timedelta(days=1)
    admissions.append(Admission(
        title="Right inguinal hernia: open repair with mesh on aspirin",
        admitted=t.hernia,
        discharged=discharged,
        service="General Surgery",
        doctor=YALCIN,
        complaint=join(
            f"{c.opening()}, admitted electively for repair of a right inguinal hernia: groin swelling for about a year,",
            "aching after long walks, always reducible, no episodes of obstruction.",
        ),
        past_history=c.past(),
        examination=join(c.vitals(pulse=(56, 66)), "Reducible right inguinal hernia with a cough impulse, not extending into the scrotum. Left side normal."),
        course=join(
            f"Antiplatelet plan agreed before admission with cardiology ({CARDIOLOGIST}): aspirin 100 mg continued without a",
            "break through the operation because of the two coronary stents. No other antiplatelet medicine is taken:",
            f"clopidogrel was stopped for good after the duodenal ulcer bleed in {_month(t.bleed)}. Pantoprazole continued.",
            "Open right inguinal hernia repair with mesh (Lichtenstein) under spinal anaesthesia on the day of admission,",
            "on aspirin (see the operation report); careful haemostasis, no drain. No wound haematoma. Walking and passing",
            "urine within six hours. Home the next morning.",
        ),
        admission_diagnoses=(("K40.9", "Right inguinal hernia"),),
        discharge_diagnoses=(("K40.9", "Unilateral inguinal hernia, right, indirect, without obstruction or gangrene, repaired"), *c.chronic()),
        prescription=("Paracetamol 1 g orally up to four times daily as needed", *c.continuing(discharged)),
        recommendations=join(
            "Aspirin continues without a break; no anti-inflammatory painkillers because of the previous ulcer bleed.",
            "No heavy lifting for 4 weeks; normal walking encouraged. Wound check on day 7; surgical clinic in 6 weeks.",
            "Return with spreading groin bruising or swelling.",
        ),
        outcome="Recovered",
        procedure=ProcedureReport(
            performed=t.hernia,
            name="Open right inguinal hernia repair with mesh",
            operation=True,
            pre_diagnosis="Right inguinal hernia",
            post_diagnosis="Right indirect inguinal hernia",
            team=c.team(YALCIN),
            anaesthesia="Spinal anaesthesia, on aspirin 100 mg as agreed with cardiology",
            wound_class="Clean",
            note=join(
                "Right groin crease incision. External oblique opened; ilioinguinal nerve identified and preserved. Indirect sac",
                "dissected off the cord and reduced. Posterior wall reinforced with a 6 × 11 cm polypropylene mesh, sutured to",
                "the inguinal ligament and the conjoint tendon; tails crossed around the cord. Careful haemostasis with",
                "diathermy. External oblique and skin closed with absorbable sutures.",
            ),
            body_site="Right inguinal region",
            device="Polypropylene mesh 6 × 11 cm",
        ),
    ))

    # 6. Renal colic.
    admissions.append(renal_colic(ctx(t.colic)))

    # 7. Chest pain: coronary angiography showed both stents patent.
    c = ctx(t.chest_pain)
    performed = t.chest_pain + timedelta(days=1)
    admissions.append(Admission(
        title="Chest pain; coronary angiography with both stents patent",
        admitted=t.chest_pain,
        discharged=performed,
        service="Cardiology",
        doctor=CARDIOLOGIST,
        complaint=join(
            f"{c.opening()}. Three episodes over a week of central chest tightness spreading to the left arm, the last at rest",
            "for about 20 minutes on the morning of admission; worried it felt like his heart attack. No breathlessness or",
            "sweating. Takes his medicines without missed doses.",
        ),
        past_history=c.past(),
        examination=join(
            c.vitals(pulse=(58, 66)),
            "Pain-free on arrival. Heart sounds normal, no murmur; chest clear; no leg swelling. Right radial pulse normal.",
        ),
        course=join(
            "ECG: sinus rhythm, Q waves in the inferior leads from the old infarction, no new changes.",
            f"High-sensitivity troponin T {rng.randint(6, 9)} and {rng.randint(7, 10)} ng/L at 0 and 3 hours (below the 99th percentile).",
            "Because of the two stents and the description of the pain, coronary angiography on day 2 (see the procedure",
            "report): both stents patent, no in-stent restenosis and no new significant stenosis.",
            "On review the left 4th and 5th costal cartilages were tender and pressing there reproduced the pain: chest wall",
            "pain. Paracetamol and local heat; no anti-inflammatory painkillers because of the previous ulcer bleed. Regular",
            "medicines unchanged.",
        ),
        admission_diagnoses=(("R07.4", "Chest pain, suspected acute coronary syndrome"),),
        discharge_diagnoses=(
            ("R07.4", "Chest wall pain (costochondral); no new coronary disease on angiography"),
            ("I25.1", "Coronary artery disease: right coronary and left anterior descending artery stents patent"),
        ),
        prescription=("Paracetamol 1 g orally up to four times daily as needed", *c.continuing(performed)),
        recommendations=join(
            "Keep the wrist dressing dry for 24 hours; no heavy lifting with the right arm for 3 days.",
            "Cardiology clinic (Dr. Zeynep Kara) in three months. Return at once with chest pain at rest lasting more than 15 minutes.",
        ),
        outcome="Recovered",
        procedure=ProcedureReport(
            performed=performed,
            name="Coronary angiography via the right radial artery",
            operation=False,
            pre_diagnosis="Chest pain, suspected acute coronary syndrome, after stents to the right coronary and left anterior descending arteries",
            post_diagnosis="Both stents patent without restenosis; no new significant coronary stenosis",
            team=f"{CARDIOLOGIST} (interventional cardiologist)",
            anaesthesia="Local anaesthesia (lidocaine 2%) at the puncture site",
            wound_class="Clean",
            note=join(
                "Right radial access with a 6F sheath; intra-arterial verapamil and heparin. Left main stem normal. Stent in the",
                "mid left anterior descending artery patent with no restenosis. Circumflex artery with a 30% plaque. Stent in",
                f"the mid right coronary artery patent with no restenosis. Contrast {rng.randint(60, 90)} mL. Sheath removed;",
                "radial compression band applied.",
            ),
            body_site="Coronary arteries",
        ),
    ))

    # 8. Pneumonia.
    admissions.append(pneumonia(ctx(t.pneumonia)))

    return [add(chart, admission) for admission in sorted(admissions, key=lambda item: item.admitted)]
