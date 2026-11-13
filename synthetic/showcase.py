"""Showcase patients: fixed stories whose epicrisis reports carry the history a doctor would ask about.

Each patient has two parts that share one timeline, worked out from the anchor: the story (`thyroid_cancer`), which
writes the problem list, medication orders, outpatient notes, results and the next appointment, and the reports
(`thyroid_cancer_reports`), added after it with the patient's own epicrisis random numbers. The showcase patients get
no background reports.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from chart import PatientChart, at, day_text, workday
from cohort import ARSLAN, CELIK, LEVOTHYROXINE, Story, bullets, chemistry, numbered, sections
from epicrisis import Admission, ProcedureReport, add
from epicrisis_catalogue import ENT, ORTHOPAEDICS, YALCIN, Ctx, Patient, _join, _name_of, pneumonia, vertigo

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
    order = next(order for order in p.medicines(day) if _name_of(order).lower() == "levothyroxine")
    return f"{_name_of(order)} {order['dosageInstruction'][0]['text'].replace(' orally', '')}"


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
        complaint=_join(
            f"{c.age}-year-old woman with a painless swelling on the right side of the neck, noticed a few months ago.",
            f"A neck ultrasound on {day_text(t.goitre)}, requested by her family doctor, showed a multinodular goitre: several",
            "small nodules in both lobes and a dominant 24 mm solid, hypoechoic nodule in the right lobe with",
            "microcalcifications (TI-RADS 5). TSH normal. Admitted as a day case for fine-needle aspiration.",
        ),
        past_history=_join(
            pneumonia_line, "No other illnesses. No regular medicines. No known drug allergies.",
            "No radiation to the head or neck. No family history of thyroid cancer. Never smoked.",
        ),
        examination=_join(
            c.vitals(),
            "Multinodular goitre; a firm 2.5 cm nodule in the right lobe that moves with swallowing. No palpable cervical",
            "lymph nodes. Voice normal; no stridor.",
        ),
        course=_join(
            f"TSH {rng.uniform(1.4, 1.9):.2f} mIU/L, free T4 {rng.uniform(1.15, 1.3):.2f} ng/dL, calcium {rng.uniform(9.2, 9.6):.1f} mg/dL.",
            "Ultrasound-guided fine-needle aspiration of the dominant right lobe nodule (see the procedure report); the",
            "on-site check confirmed an adequate sample. Observed for two hours: no bleeding or neck swelling.",
            "Home the same afternoon. Cytology to follow.",
        ),
        admission_diagnoses=(("E04.2", "Nontoxic multinodular goitre"),),
        discharge_diagnoses=(("E04.2", "Nontoxic multinodular goitre with a dominant right lobe nodule (TI-RADS 5); cytology pending"),),
        prescription=("Paracetamol 500 mg orally up to four times daily as needed for neck discomfort",),
        recommendations=_join(
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
            note=_join(
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
    complications = _join(
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
        complaint=_join(
            f"{c.age}-year-old woman with a multinodular goitre found on ultrasound in {_month(t.goitre)}. Fine-needle aspiration",
            f"of the dominant 24 mm right lobe nodule on {day_text(t.aspiration)} was suspicious for papillary thyroid carcinoma",
            "(Bethesda V). Seen in the surgical clinic and admitted on the day of surgery for a total thyroidectomy.",
            "Laryngoscopy before the operation: both vocal cords moving normally. Voice normal.",
        ),
        past_history=_join(
            pneumonia_line,
            f"Fine-needle aspiration of the right thyroid nodule on {day_text(t.aspiration)} (day case).",
            "No regular medicines. No known drug allergies. Never smoked.",
        ),
        examination=_join(
            c.vitals(),
            "Multinodular goitre with a firm dominant nodule in the right lobe. No palpable cervical lymph nodes. Voice normal.",
        ),
        course=_join(
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
        recommendations=_join(
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
            note=_join(
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
            complications=_join(
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
        complaint=_join(
            f"{c.age}-year-old woman admitted for radioiodine (I-131) remnant ablation four weeks after a total thyroidectomy on",
            f"{day_text(t.surgery)} for papillary thyroid carcinoma (pT2 NX, tall-cell component; intermediate risk). Off thyroid",
            "hormone since the operation and on a low-iodine diet for two weeks. Tired and feels the cold. Voice still hoarse",
            f"but improving with voice therapy. No tingling since the calcium tablets were stopped on {day_text(t.calcium_stopped)}.",
        ),
        past_history=_join(
            f"Total thyroidectomy on {day_text(t.surgery)}, complicated by transient hypocalcaemia (calcium and calcitriol for",
            "two weeks) and a right vocal cord paresis.", pneumonia_line,
            "No regular medicines. No known drug allergies. Not breastfeeding.",
        ),
        examination=_join(
            c.vitals(pulse=(58, 66)),
            "Healed collar incision. Mildly hoarse voice; no stridor. No palpable cervical lymph nodes.",
        ),
        course=_join(
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
        recommendations=_join(
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
        complaint=_join(
            f"{c.age}-year-old woman with two days of constant right upper abdominal pain spreading to the right shoulder,",
            "fever and vomiting, after several shorter attacks of pain following fatty meals over the last year.",
        ),
        past_history=_join(*thyroid_lines, pneumonia_line, regular(t.cholecystitis), f"Previous operations: {thyroidectomy}."),
        examination=_join(
            c.vitals(temp=(37.9, 38.6), pulse=(92, 106)),
            "Tender in the right upper quadrant with a positive Murphy's sign; no jaundice. Healed collar scar. Voice normal.",
        ),
        course=_join(
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
            ("C73", "Papillary thyroid carcinoma, treated; no evidence of disease"),
            ("E89.0", "Postprocedural hypothyroidism"),
        ),
        prescription=("Paracetamol 1 g orally up to four times daily as needed", *c.continuing(discharged)),
        recommendations=_join(
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
            note=_join(
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
        complaint=_join(
            f"{c.age}-year-old woman under surveillance after papillary thyroid carcinoma. A routine neck ultrasound on",
            f"{day_text(scan)} showed a 9 mm oval lymph node at right level III with an unclear fatty hilum; the thyroid bed was",
            "clear. Thyroglobulin undetectable on levothyroxine, with negative antibodies. She had a sore throat and a cold two",
            "weeks before the scan. Admitted as a day case for fine-needle aspiration.",
        ),
        past_history=_join(
            *thyroid_lines, pneumonia_line, regular(t.node), f"Previous operations: {thyroidectomy}; {cholecystectomy}.",
        ),
        examination=_join(c.vitals(), "Healed collar scar. No palpable mass in the thyroid bed or neck. Voice normal."),
        course=_join(
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
        recommendations=_join(
            "Endocrinology clinic (Dr. Selin Arslan) in two weeks for the final cytology. Neck ultrasound again in one year.",
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
            note=_join(
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
        complaint=_join(
            f"{c.age}-year-old woman who slipped on an icy pavement and fell onto her outstretched left hand; pain, swelling",
            "and deformity of the left wrist. No head injury. Right-handed.",
        ),
        past_history=_join(
            *thyroid_lines,
            f"Fine-needle aspiration of a right neck lymph node in {_month(t.node)}: benign, reactive lymph node.",
            pneumonia_line, regular(t.wrist), f"Previous operations: {thyroidectomy}; {cholecystectomy}.",
        ),
        examination=_join(
            c.vitals(pulse=(80, 96)),
            "Dinner-fork deformity of the left wrist; skin intact; radial pulse present; sensation in the fingers normal.",
        ),
        course=_join(
            "X-ray: dorsally displaced, intra-articular fracture of the left distal radius with shortening.",
            f"Backslab and elevation; operation on {day_text(performed)} (see the operation report). Fingers moving well and",
            "the hand warm before discharge. Levothyroxine continued.",
        ),
        admission_diagnoses=(("S52.5", "Fracture of the left distal radius"),),
        discharge_diagnoses=(
            ("S52.5", "Fracture of the lower end of the left radius, intra-articular, fixed"),
            ("C73", "Papillary thyroid carcinoma, treated; no evidence of disease"),
            ("E89.0", "Postprocedural hypothyroidism"),
        ),
        prescription=("Paracetamol 1 g orally four times daily as needed", *c.continuing(discharged)),
        recommendations=_join(
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
            note=_join(
                "Volar (modified Henry) approach through the flexor carpi radialis sheath; pronator quadratus elevated. Fracture",
                "reduced under fluoroscopy and fixed with a volar locking plate and screws; joint surface restored. Pronator",
                "quadratus repaired; skin closed. Volar plaster slab.",
            ),
            body_site="Left wrist (distal radius)",
            device="Volar locking plate (titanium)",
        ),
    ))

    return [add(chart, admission) for admission in sorted(admissions, key=lambda item: item.admitted)]
