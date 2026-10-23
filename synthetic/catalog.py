"""Terminology, units and reference ranges used by the synthetic cohort.

Reference ranges are typical adult values for a general hospital laboratory.
They only drive the H/L flags a laboratory system would attach to a result.
"""

from __future__ import annotations

from dataclasses import dataclass

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
ICD10 = "http://hl7.org/fhir/sid/icd-10"
ATC = "http://www.whocc.no/atc"
SNOMED = "http://snomed.info/sct"


@dataclass(frozen=True)
class Analyte:
    loinc: str
    display: str
    name: str
    short: str
    unit: str
    ucum: str
    decimals: int
    low: float | None = None
    high: float | None = None
    female: tuple[float | None, float | None] | None = None

    def reference_range(self, gender: str) -> tuple[float | None, float | None]:
        if gender == "female" and self.female is not None:
            return self.female
        return self.low, self.high


ANALYTES: dict[str, Analyte] = {
    "hgb": Analyte("718-7", "Hemoglobin [Mass/volume] in Blood", "Hemoglobin", "Hb", "g/dL", "g/dL", 1, 13.5, 17.5, (12.0, 15.5)),
    "hct": Analyte("4544-3", "Hematocrit [Volume Fraction] of Blood by Automated count", "Hematocrit", "Hct", "%", "%", 1, 41.0, 53.0, (36.0, 46.0)),
    "mcv": Analyte("787-2", "MCV [Entitic volume] by Automated count", "MCV", "MCV", "fL", "fL", 0, 80, 100),
    "wbc": Analyte("6690-2", "Leukocytes [#/volume] in Blood by Automated count", "White blood cells", "WBC", "10³/µL", "10*3/uL", 1, 4.0, 11.0),
    "anc": Analyte("751-8", "Neutrophils [#/volume] in Blood by Automated count", "Neutrophils, absolute", "ANC", "10³/µL", "10*3/uL", 2, 1.8, 7.7),
    "plt": Analyte("777-3", "Platelets [#/volume] in Blood by Automated count", "Platelets", "platelets", "10³/µL", "10*3/uL", 0, 150, 400),
    "na": Analyte("2951-2", "Sodium [Moles/volume] in Serum or Plasma", "Sodium", "Na", "mmol/L", "mmol/L", 0, 136, 145),
    "k": Analyte("2823-3", "Potassium [Moles/volume] in Serum or Plasma", "Potassium", "K", "mmol/L", "mmol/L", 1, 3.5, 5.1),
    "cl": Analyte("2075-0", "Chloride [Moles/volume] in Serum or Plasma", "Chloride", "Cl", "mmol/L", "mmol/L", 0, 98, 107),
    "co2": Analyte("2028-9", "Carbon dioxide, total [Moles/volume] in Serum or Plasma", "Bicarbonate (total CO₂)", "bicarbonate", "mmol/L", "mmol/L", 0, 22, 29),
    "bun": Analyte("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma", "Urea nitrogen (BUN)", "BUN", "mg/dL", "mg/dL", 0, 7, 20),
    "cr": Analyte("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "Creatinine", "creatinine", "mg/dL", "mg/dL", 2, 0.70, 1.30, (0.60, 1.10)),
    "egfr": Analyte(
        "98979-8",
        "Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine-based formula (CKD-EPI 2021)",
        "eGFR (CKD-EPI 2021)",
        "eGFR",
        "mL/min/1.73m²",
        "mL/min/{1.73_m2}",
        0,
        60,
        None,
    ),
    "glu": Analyte("2345-7", "Glucose [Mass/volume] in Serum or Plasma", "Glucose", "glucose", "mg/dL", "mg/dL", 0, 70, 99),
    "ca": Analyte("17861-6", "Calcium [Mass/volume] in Serum or Plasma", "Calcium", "calcium", "mg/dL", "mg/dL", 1, 8.6, 10.3),
    "alb": Analyte("1751-7", "Albumin [Mass/volume] in Serum or Plasma", "Albumin", "albumin", "g/dL", "g/dL", 1, 3.5, 5.0),
    "alt": Analyte("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "ALT", "ALT", "U/L", "U/L", 0, 7, 55),
    "ast": Analyte("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "AST", "AST", "U/L", "U/L", 0, 8, 48),
    "alp": Analyte("6768-6", "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma", "Alkaline phosphatase", "ALP", "U/L", "U/L", 0, 40, 130),
    "tbil": Analyte("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", "Bilirubin, total", "bilirubin", "mg/dL", "mg/dL", 1, 0.1, 1.2),
    "chol": Analyte("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "Cholesterol, total", "total cholesterol", "mg/dL", "mg/dL", 0, None, 200),
    "hdl": Analyte("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "HDL cholesterol", "HDL", "mg/dL", "mg/dL", 0, 40, None, (50, None)),
    "ldl": Analyte("13457-7", "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation", "LDL cholesterol (calculated)", "LDL", "mg/dL", "mg/dL", 0, None, 130),
    "tg": Analyte("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma", "Triglycerides", "triglycerides", "mg/dL", "mg/dL", 0, None, 150),
    "a1c": Analyte("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "Hemoglobin A1c", "HbA1c", "%", "%", 1, 4.0, 5.6),
    "tsh": Analyte("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma", "TSH", "TSH", "mIU/L", "m[IU]/L", 2, 0.40, 4.00),
    "ft4": Analyte("3024-7", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma", "Free T4", "free T4", "ng/dL", "ng/dL", 2, 0.90, 1.70),
    "tpo": Analyte("8099-4", "Thyroperoxidase Ab [Units/volume] in Serum or Plasma", "Anti-TPO antibodies", "anti-TPO", "IU/mL", "[IU]/mL", 0, None, 34),
    "ferritin": Analyte("2276-4", "Ferritin [Mass/volume] in Serum or Plasma", "Ferritin", "ferritin", "ng/mL", "ng/mL", 0, 24, 336, (11, 307)),
    "ntprobnp": Analyte("33762-6", "Natriuretic peptide.B prohormone N-Terminal [Mass/volume] in Serum or Plasma", "NT-proBNP", "NT-proBNP", "pg/mL", "pg/mL", 0, None, 125),
    "uacr": Analyte("9318-7", "Albumin/Creatinine [Mass Ratio] in Urine", "Urine albumin/creatinine ratio", "urine ACR", "mg/g", "mg/g", 0, None, 30),
    "cea": Analyte("2039-6", "Carcinoembryonic Ag [Mass/volume] in Serum or Plasma", "CEA", "CEA", "ng/mL", "ng/mL", 1, None, 5.0),
    "mg": Analyte("19123-9", "Magnesium [Mass/volume] in Serum or Plasma", "Magnesium", "Mg", "mg/dL", "mg/dL", 1, 1.7, 2.2),
}


@dataclass(frozen=True)
class Panel:
    name: str
    analytes: tuple[str, ...]
    loinc: str | None = None
    display: str | None = None
    turnaround_hours: float = 3.0


_BMP = ("na", "k", "cl", "co2", "bun", "cr", "egfr", "glu", "ca")


def _single(key: str, turnaround_hours: float = 6.0) -> Panel:
    analyte = ANALYTES[key]
    return Panel(analyte.name, (key,), analyte.loinc, analyte.display, turnaround_hours)


PANELS: dict[str, Panel] = {
    "cbc": Panel("Complete blood count", ("hgb", "hct", "mcv", "wbc", "plt"), "58410-2", "CBC panel - Blood by Automated count", 2.0),
    "cbc_diff": Panel(
        "CBC with differential",
        ("hgb", "hct", "mcv", "wbc", "anc", "plt"),
        "57021-8",
        "CBC W Auto Differential panel - Blood",
        2.0,
    ),
    "bmp": Panel("Basic metabolic panel", _BMP, "51990-0", "Basic metabolic panel - Blood"),
    "cmp": Panel(
        "Comprehensive metabolic panel",
        _BMP + ("alb", "alt", "ast", "alp", "tbil"),
        "24323-8",
        "Comprehensive metabolic 2000 panel - Serum or Plasma",
    ),
    "lipid": Panel("Lipid panel", ("chol", "hdl", "ldl", "tg"), "24331-1", "Lipid 1996 panel - Serum or Plasma", 4.0),
    "thyroid": Panel("Thyroid function", ("tsh", "ft4"), turnaround_hours=6.0),
    "a1c": _single("a1c"),
    "tpo": _single("tpo", 48.0),
    "ferritin": _single("ferritin", 8.0),
    "ntprobnp": _single("ntprobnp", 4.0),
    "uacr": _single("uacr"),
    "cea": _single("cea", 24.0),
    "mg": _single("mg", 3.0),
}


@dataclass(frozen=True)
class Vital:
    loinc: str
    display: str
    name: str
    unit: str
    ucum: str
    decimals: int


VITALS: dict[str, Vital] = {
    "bp": Vital("85354-9", "Blood pressure panel with all children optional", "Blood pressure", "mmHg", "mm[Hg]", 0),
    "sbp": Vital("8480-6", "Systolic blood pressure", "Systolic blood pressure", "mmHg", "mm[Hg]", 0),
    "dbp": Vital("8462-4", "Diastolic blood pressure", "Diastolic blood pressure", "mmHg", "mm[Hg]", 0),
    "hr": Vital("8867-4", "Heart rate", "Heart rate", "/min", "/min", 0),
    "weight": Vital("29463-7", "Body weight", "Body weight", "kg", "kg", 1),
    "height": Vital("8302-2", "Body height", "Body height", "cm", "cm", 0),
    "bmi": Vital("39156-5", "Body mass index (BMI) [Ratio]", "BMI", "kg/m²", "kg/m2", 1),
}


@dataclass(frozen=True)
class Clinician:
    id: str
    given: str
    family: str
    specialty: str

    @property
    def display(self) -> str:
        return f"Dr. {self.given} {self.family}"


CLINICIANS: dict[str, Clinician] = {
    c.id: c
    for c in (
        Clinician("pr-aydin", "Elif", "Aydın", "Internal Medicine"),
        Clinician("pr-sahin", "Murat", "Şahin", "Medical Oncology"),
        Clinician("pr-kara", "Zeynep", "Kara", "Cardiology"),
        Clinician("pr-ozturk", "Can", "Öztürk", "Nephrology"),
        Clinician("pr-arslan", "Selin", "Arslan", "Endocrinology"),
        Clinician("pr-koc", "Ayhan", "Koç", "Gastroenterology"),
        Clinician("pr-celik", "Burak", "Çelik", "Radiology"),
        Clinician("pr-kilic", "Deniz", "Kılıç", "Pathology"),
    )
}
