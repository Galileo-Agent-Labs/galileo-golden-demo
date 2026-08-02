"""Self-contained EHR data layer for the healthcare practitioner demo.

The chart-centric EHR frontend used to read every panel straight out of
Postgres.  For the demo we want the whole patient dataset to *travel with the
frontend* so the chart renders on a laptop with nothing running behind it — no
database, no network.  This module is that data layer.

It reads the three CSVs that already ship in ``domains/healthcare/docs``
(patient / medication / history) and deterministically enriches them into the
kind of dense record a real EHR shows: demographics, allergies, a problem
list, a vitals flowsheet with trends, lab panels with reference ranges and
abnormal flags, a care team, immunisations, coverage and location.

Everything is seeded off the patient id, so a given patient looks identical on
every rerun — no flicker, no "the labs changed when I clicked" surprises.

Public surface:
    load_roster()      -> [{"patient_id", "patient_name", ...}]  (sorted)
    get_chart(pid)     -> full chart dict consumed by ehr_theme
"""

from __future__ import annotations

import csv
import hashlib
import os
import random
from datetime import date, datetime, timedelta
from functools import lru_cache

# The clinical "now" for the demo.  The bundled data is dated into 2026, so we
# anchor age/refill/lab math to a fixed reference day rather than the wall
# clock — that keeps the demo stable and the numbers self-consistent.
TODAY = date(2026, 8, 1)

_DOCS = os.path.join(os.path.dirname(__file__), "docs")


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------
def _read_csv(name: str) -> list[dict]:
    """Read one of the relational CSVs, trimming the quoted/space-padded cells."""
    path = os.path.join(_DOCS, name)
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh, skipinitialspace=True):
            rows.append({
                (k or "").strip(): (v.strip() if isinstance(v, str) else v)
                for k, v in raw.items()
                if k is not None
            })
    return rows


@lru_cache(maxsize=1)
def _raw():
    return {
        "patients": _read_csv("relational_patient.csv"),
        "medications": _read_csv("relational_medication.csv"),
        "history": _read_csv("relational_history.csv"),
    }


def _rng(pid: str) -> random.Random:
    """A stable per-patient PRNG so enrichment is deterministic."""
    seed = int(hashlib.md5(pid.encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------
# Curated sex for the 30 seeded patients (clearly-gendered common first names)
# so pronouns/labels read naturally in the demo; anything else falls back to a
# deterministic coin-flip.
_SEX = {
    "P001": "M", "P002": "F", "P003": "M", "P004": "M", "P005": "F",
    "P006": "F", "P007": "M", "P008": "F", "P009": "M", "P010": "F",
    "P011": "M", "P012": "F", "P013": "M", "P014": "F", "P015": "M",
    "P016": "F", "P017": "M", "P018": "F", "P019": "M", "P020": "F",
    "P021": "M", "P022": "F", "P023": "M", "P024": "F", "P025": "M",
    "P026": "F", "P027": "M", "P028": "F", "P029": "M", "P030": "F",
}

# drug -> (problem label, ICD-10, managing specialty)
_DRUG_PROBLEM = {
    "Lisinopril": ("Essential hypertension", "I10", "Internal Medicine"),
    "Losartan": ("Essential hypertension", "I10", "Internal Medicine"),
    "Amlodipine": ("Essential hypertension", "I10", "Cardiology"),
    "Hydrochlorothiazide": ("Essential hypertension", "I10", "Internal Medicine"),
    "Metoprolol": ("Atrial fibrillation", "I48.91", "Cardiology"),
    "Metformin": ("Type 2 diabetes mellitus", "E11.9", "Endocrinology"),
    "Atorvastatin": ("Hyperlipidemia", "E78.5", "Internal Medicine"),
    "Levothyroxine": ("Hypothyroidism", "E03.9", "Endocrinology"),
    "Aspirin": ("ASCVD — secondary prevention", "I25.10", "Cardiology"),
    "Omeprazole": ("Gastroesophageal reflux disease", "K21.9", "Gastroenterology"),
    "Gabapentin": ("Peripheral neuropathy", "G62.9", "Neurology"),
    "Sertraline": ("Major depressive disorder", "F32.9", "Psychiatry"),
    "Warfarin": ("Atrial fibrillation — anticoagulated", "I48.20", "Cardiology"),
    "Albuterol": ("Asthma", "J45.909", "Pulmonology"),
    "Prednisone": ("Polymyalgia rheumatica", "M35.3", "Rheumatology"),
}

_ATTENDINGS = [
    "Priya Nadkarni, MD", "Daniel Okafor, MD", "Susan Reyes, MD",
    "Marcus Feld, MD", "Anne Whitlock, DO", "Louis Brandt, MD",
    "Grace Yun, MD", "Omar Haddad, MD",
]
_SPECIALISTS = {
    "Cardiology": ["Helen Vasquez, MD", "Rex Carmody, MD"],
    "Endocrinology": ["Iris Bhatt, MD", "Paul Steiner, MD"],
    "Pulmonology": ["Nadia Prosser, MD"],
    "Gastroenterology": ["Wen Li, MD"],
    "Neurology": ["Theodore Ash, MD"],
    "Psychiatry": ["Corinne Vaults, MD"],
    "Rheumatology": ["Gideon Marsh, MD"],
}
_RNS = ["T. Alvarez, RN", "M. Donnelly, RN", "K. Osei, RN", "B. Fontaine, RN"]

_PAYERS = [
    ("Blue Cross Blue Shield", "PPO"), ("Aetna", "HMO"),
    ("UnitedHealthcare", "PPO"), ("Cigna", "PPO"),
    ("Medicare Part B", "—"), ("Kaiser Permanente", "HMO"),
]

_ALLERGY_POOL = [
    ("Penicillin", "Hives / urticaria", "High"),
    ("Sulfa drugs", "Maculopapular rash", "Moderate"),
    ("Codeine", "Nausea, pruritus", "Low"),
    ("Latex", "Contact dermatitis", "Moderate"),
    ("Iodinated contrast", "Flushing, hypotension", "High"),
    ("Peanuts", "Anaphylaxis", "High"),
    ("Shellfish", "Facial swelling", "Moderate"),
]

_INPATIENT_UNITS = ["4 West · Med-Surg", "5 North · Telemetry", "3 East · Cardiac Step-Down", "6 West · General Medicine"]
_CLINICS = ["Evercrest Internal Medicine", "Evercrest Family Health", "Lakeside Primary Care"]


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------
def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt(d: date) -> str:
    return d.strftime("%b %d, %Y")


def _age_dob(rng: random.Random) -> tuple[int, str]:
    age = rng.randint(41, 87)
    # keep the birthday earlier in the year so age math is unambiguous
    dob = date(TODAY.year - age, rng.randint(1, 12), rng.randint(1, 28))
    return age, dob


def _meds_for(pid: str) -> list[dict]:
    meds = [m for m in _raw()["medications"] if m.get("patient_id") == pid and m.get("status") == "active"]
    meds.sort(key=lambda m: m.get("start_date", ""))
    return meds


def _history_for(pid: str) -> list[dict]:
    hist = [h for h in _raw()["history"] if h.get("patient_id") == pid]
    hist.sort(key=lambda h: h.get("event_date", ""), reverse=True)
    return hist


# Collapse clinically-overlapping problems (e.g. Metoprolol + Warfarin both
# imply atrial fibrillation) into a single family so the list reads like a
# reconciled chart rather than one row per drug.
_PROBLEM_FAMILY = {
    "Essential hypertension": "HTN",
    "Atrial fibrillation": "AFIB",
    "Atrial fibrillation — anticoagulated": "AFIB",
}
_FAMILY_PREFERRED = {"AFIB": "Atrial fibrillation — anticoagulated"}


def _problem_list(rng, med_names, dx_dates):
    seen_family, problems = {}, []
    for name in med_names:
        info = _DRUG_PROBLEM.get(name)
        if not info:
            continue
        label, icd, spec = info
        fam = _PROBLEM_FAMILY.get(label, label)
        if fam in seen_family:
            # Upgrade to the more specific label for this family if we hit it.
            idx = seen_family[fam]
            if _FAMILY_PREFERRED.get(fam) == label:
                problems[idx].update({"problem": label, "code": icd})
            continue
        seen_family[fam] = len(problems)
        problems.append({
            "problem": label,
            "code": icd,
            "since": dx_dates.get(name, _fmt(TODAY - timedelta(days=rng.randint(400, 3200)))),
            "status": "Active",
            "specialty": spec,
        })
    # a couple of near-universal chronic/again-common problems for density
    extras = [
        ("Vitamin D deficiency", "E55.9"),
        ("Overweight (BMI 27.6)", "E66.3"),
        ("Chronic low back pain", "M54.5"),
        ("Obstructive sleep apnea", "G47.33"),
        ("Osteoarthritis, knee", "M17.9"),
    ]
    rng.shuffle(extras)
    for label, icd in extras[: rng.randint(1, 2)]:
        problems.append({
            "problem": label, "code": icd,
            "since": _fmt(TODAY - timedelta(days=rng.randint(200, 2600))),
            "status": "Active", "specialty": "Internal Medicine",
        })
    return problems


def _allergies(rng):
    if rng.random() < 0.35:
        return []  # NKDA
    pool = _ALLERGY_POOL[:]
    rng.shuffle(pool)
    out = []
    for name, reaction, sev in pool[: rng.randint(1, 2)]:
        out.append({"allergen": name, "reaction": reaction, "severity": sev})
    return out


def _vitals(rng, hypertensive: bool, height_in: int, base_wt: float):
    """Return a flowsheet: newest-first columns of dated vital signs."""
    cols = []
    n = 6
    for i in range(n):
        d = TODAY - timedelta(days=int(i * rng.uniform(38, 62)))
        sys = rng.randint(150, 168) if hypertensive else rng.randint(116, 132)
        # trend blood pressure gently downward toward "now" for treated HTN
        sys -= (n - 1 - i) * (rng.randint(2, 5) if hypertensive else 0)
        dia = int(sys * rng.uniform(0.60, 0.66))
        wt = round(base_wt + rng.uniform(-2.5, 2.5) + (n - 1 - i) * rng.uniform(0.2, 0.8), 1)
        bmi = round((wt / (height_in ** 2)) * 703, 1)
        cols.append({
            "date": d,
            "BP": f"{sys}/{dia}",
            "sys": sys,
            "HR": rng.randint(60, 92),
            "RR": rng.randint(12, 18),
            "Temp": round(rng.uniform(97.6, 99.1), 1),
            "SpO2": rng.randint(95, 99),
            "Wt": wt,
            "BMI": bmi,
            "Pain": rng.randint(0, 4),
        })
    return cols  # newest-first


def _lab_row(name, value, unit, lo, hi, dec=1):
    if value < lo:
        flag = "L"
    elif value > hi:
        flag = "H"
    else:
        flag = ""
    return {
        "analyte": name,
        "value": round(value, dec),
        "unit": unit,
        "ref": f"{lo:g}–{hi:g}",
        "flag": flag,
    }


def _series(rng, start, end, n, lo, hi, dec=1):
    """A trend series oldest->newest between start and end, clamped-ish."""
    out = []
    for i in range(n):
        f = i / (n - 1)
        v = start + (end - start) * f + rng.uniform(-(hi - lo) * 0.04, (hi - lo) * 0.04)
        out.append(round(v, dec))
    return out


def _labs(rng, med_names):
    """Return lab panels (each: title, date, rows[]) plus trend series."""
    panels = []
    trends = {}
    d0 = TODAY - timedelta(days=rng.randint(6, 26))

    # CMP — everyone
    cr = rng.uniform(0.8, 1.4)
    egfr = max(38, int(140 - cr * 55 - rng.randint(0, 20)))
    panels.append({
        "title": "Comprehensive Metabolic Panel", "date": d0, "rows": [
            _lab_row("Sodium", rng.uniform(136, 143), "mmol/L", 135, 145, 0),
            _lab_row("Potassium", rng.uniform(3.6, 5.1), "mmol/L", 3.5, 5.0, 1),
            _lab_row("Chloride", rng.uniform(98, 107), "mmol/L", 98, 107, 0),
            _lab_row("CO2", rng.uniform(22, 29), "mmol/L", 22, 29, 0),
            _lab_row("BUN", rng.uniform(9, 24), "mg/dL", 7, 20, 0),
            _lab_row("Creatinine", cr, "mg/dL", 0.7, 1.3, 2),
            _lab_row("eGFR", egfr, "mL/min", 60, 120, 0),
            _lab_row("Glucose", rng.uniform(84, 118), "mg/dL", 70, 99, 0),
        ],
    })
    trends["Creatinine"] = _series(rng, cr + rng.uniform(0.0, 0.2), cr, 4, 0.7, 1.3, 2)

    # CBC — everyone
    panels.append({
        "title": "Complete Blood Count", "date": d0, "rows": [
            _lab_row("WBC", rng.uniform(4.2, 10.8), "K/uL", 4.0, 11.0, 1),
            _lab_row("Hemoglobin", rng.uniform(12.1, 16.4), "g/dL", 12.0, 17.0, 1),
            _lab_row("Hematocrit", rng.uniform(37, 49), "%", 36, 50, 0),
            _lab_row("Platelets", rng.uniform(150, 380), "K/uL", 150, 400, 0),
        ],
    })

    if "Metformin" in med_names:
        a1c = rng.uniform(6.8, 8.6)
        panels.append({
            "title": "Diabetes Panel", "date": d0, "rows": [
                _lab_row("HbA1c", a1c, "%", 4.0, 5.6, 1),
                _lab_row("Fasting glucose", rng.uniform(112, 168), "mg/dL", 70, 99, 0),
            ],
        })
        trends["HbA1c"] = _series(rng, a1c + rng.uniform(0.4, 1.2), a1c, 4, 4.0, 5.6, 1)

    if "Atorvastatin" in med_names:
        ldl = rng.uniform(78, 138)
        panels.append({
            "title": "Lipid Panel", "date": d0, "rows": [
                _lab_row("Total cholesterol", rng.uniform(160, 232), "mg/dL", 0, 200, 0),
                _lab_row("LDL", ldl, "mg/dL", 0, 100, 0),
                _lab_row("HDL", rng.uniform(38, 62), "mg/dL", 40, 200, 0),
                _lab_row("Triglycerides", rng.uniform(96, 210), "mg/dL", 0, 150, 0),
            ],
        })
        trends["LDL"] = _series(rng, ldl + rng.uniform(20, 55), ldl, 4, 0, 100, 0)

    if "Levothyroxine" in med_names:
        panels.append({
            "title": "Thyroid Function", "date": d0, "rows": [
                _lab_row("TSH", rng.uniform(0.6, 5.8), "mIU/L", 0.4, 4.0, 2),
                _lab_row("Free T4", rng.uniform(0.8, 1.7), "ng/dL", 0.8, 1.8, 1),
            ],
        })

    if "Warfarin" in med_names:
        inr = rng.uniform(1.8, 3.4)
        panels.insert(0, {
            "title": "Coagulation — INR", "date": TODAY - timedelta(days=rng.randint(1, 6)), "rows": [
                _lab_row("INR", inr, "", 2.0, 3.0, 1),
                _lab_row("PT", rng.uniform(22, 34), "sec", 11, 13.5, 1),
            ],
        })
        trends["INR"] = _series(rng, rng.uniform(1.6, 2.2), inr, 5, 2.0, 3.0, 1)

    return panels, trends


def _care_team(rng, specialties):
    team = [{"role": "Attending / PCP", "name": rng.choice(_ATTENDINGS)}]
    for spec in sorted(set(specialties)):
        pool = _SPECIALISTS.get(spec)
        if pool:
            team.append({"role": spec, "name": rng.choice(pool)})
    team.append({"role": "Primary RN", "name": rng.choice(_RNS)})
    return team


def _immunizations(rng, age):
    imm = [
        {"vaccine": "Influenza (quadrivalent)", "date": _fmt(date(2025, rng.randint(9, 11), rng.randint(1, 28)))},
        {"vaccine": "COVID-19 (2025–26 formula)", "date": _fmt(date(2025, rng.randint(9, 12), rng.randint(1, 28)))},
        {"vaccine": "Tdap", "date": _fmt(date(TODAY.year - rng.randint(1, 8), rng.randint(1, 12), rng.randint(1, 28)))},
    ]
    if age >= 65:
        imm.append({"vaccine": "Pneumococcal (PCV20)", "date": _fmt(date(TODAY.year - rng.randint(0, 3), rng.randint(1, 12), 15))})
        imm.append({"vaccine": "Zoster (Shingrix) ×2", "date": _fmt(date(TODAY.year - rng.randint(1, 4), rng.randint(1, 12), 10))})
    return imm


def _refills_remaining(rng, pid, med_name):
    # George Rivera's Lisinopril is the scripted "due for refill" hero case —
    # keep it deterministically at zero so it always shows REFILL DUE and lines
    # up with the copilot's "Refill his Lisinopril" flow.
    if pid == "P001" and med_name == "Lisinopril":
        return 0
    return rng.randint(0, 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_roster() -> list[dict]:
    """Roster rows: id, name, plus a few banner-friendly fields for the picker."""
    out = []
    for p in _raw()["patients"]:
        pid = p.get("patient_id", "")
        if not pid:
            continue
        rng = _rng(pid)
        age, _dob = _age_dob(rng)
        out.append({
            "patient_id": pid,
            "patient_name": p.get("patient_name", pid),
            "age": age,
            "sex": _SEX.get(pid, "M" if rng.random() < 0.5 else "F"),
            "type": p.get("patient_type", ""),
        })
    out.sort(key=lambda r: r["patient_id"])
    return out


@lru_cache(maxsize=64)
def get_chart(pid: str) -> dict:
    """Full, self-contained chart for one patient."""
    patient = next((p for p in _raw()["patients"] if p.get("patient_id") == pid), None)
    if not patient:
        return {"patient_id": pid, "found": False}

    rng = _rng(pid)
    name = patient.get("patient_name", pid)
    ptype = (patient.get("patient_type") or "").lower()
    sex = _SEX.get(pid, "M" if rng.random() < 0.5 else "F")
    age, dob = _age_dob(rng)

    meds_raw = _meds_for(pid)
    med_names = [m.get("medication", "") for m in meds_raw]
    history = _history_for(pid)

    # dx dates gleaned from the "Prescription" history rows where possible
    dx_dates = {}
    for h in history:
        if h.get("event_type") == "Prescription":
            for mn in med_names:
                if mn and mn.lower() in (h.get("detail", "").lower()):
                    try:
                        dx_dates[mn] = _fmt(datetime.strptime(h["event_date"], "%Y-%m-%d").date())
                    except Exception:
                        pass

    problems = _problem_list(rng, med_names, dx_dates)
    specialties = [p["specialty"] for p in problems if p.get("specialty") and p["specialty"] != "Internal Medicine"]

    hypertensive = any(n in ("Lisinopril", "Losartan", "Amlodipine", "Hydrochlorothiazide") for n in med_names)
    height_in = rng.randint(62, 74)
    base_wt = round(rng.uniform(150, 232), 1)
    vitals = _vitals(rng, hypertensive, height_in, base_wt)
    labs, trends = _labs(rng, med_names)

    # medications, enriched
    meds = []
    for m in meds_raw:
        mn = m.get("medication", "")
        refills = _refills_remaining(rng, pid, mn)
        try:
            start = datetime.strptime(m.get("start_date", ""), "%Y-%m-%d").date()
        except Exception:
            start = None
        meds.append({
            "medication": mn,
            "sig": m.get("dosage", ""),
            "start": _fmt(start) if start else m.get("start_date", ""),
            "start_iso": m.get("start_date", ""),
            "refills": refills,
            "prescriber": problems and next((p["specialty"] for p in problems if _DRUG_PROBLEM.get(mn) and _DRUG_PROBLEM[mn][0] == p["problem"]), "Internal Medicine") or "Internal Medicine",
            "route": "PO" if "mcg" not in m.get("dosage", "") or mn == "Levothyroxine" else "INH",
        })

    # encounters: reuse the seeded history, formatted
    encounters = []
    for h in history:
        try:
            d = datetime.strptime(h.get("event_date", ""), "%Y-%m-%d").date()
            dfmt = _fmt(d)
        except Exception:
            dfmt = h.get("event_date", "")
        encounters.append({
            "date": dfmt,
            "type": h.get("event_type", ""),
            "detail": h.get("detail", ""),
        })

    mrn = f"EMR-{pid[1:].zfill(6)}"
    payer, plan = rng.choice(_PAYERS)
    if ptype == "inpatient":
        location = rng.choice(_INPATIENT_UNITS)
        room = f"Rm {rng.randint(300, 640)}-{rng.choice('AB')}"
        loc_detail = f"{location} · {room}"
        status_word = "Admitted — Inpatient"
    else:
        loc_detail = rng.choice(_CLINICS) + " · Outpatient"
        status_word = "Outpatient"

    allergies = _allergies(rng)
    weight = vitals[0]["Wt"]
    bmi = vitals[0]["BMI"]

    return {
        "found": True,
        "patient_id": pid,
        "mrn": mrn,
        "name": name,
        "age": age,
        "sex": "Male" if sex == "M" else "Female",
        "sex_short": sex,
        "dob": _fmt(dob),
        "phone": patient.get("phone_number", ""),
        "address": patient.get("address", ""),
        "type": patient.get("patient_type", ""),
        "status_word": status_word,
        "location": loc_detail,
        "code_status": "DNR / DNI" if rng.random() < 0.12 else "Full Code",
        "language": rng.choice(["English", "English", "English", "Spanish", "Mandarin"]),
        "height_in": height_in,
        "weight_lb": weight,
        "bmi": bmi,
        "insurance": {"payer": payer, "plan": plan, "member": f"{rng.choice('AEUXK')}{rng.randint(100000000, 999999999)}", "group": f"GRP-{rng.randint(1000, 9999)}"},
        "allergies": allergies,
        "problems": problems,
        "medications": meds,
        "vitals": vitals,
        "labs": labs,
        "trends": trends,
        "care_team": _care_team(rng, specialties),
        "immunizations": _immunizations(rng, age),
        "encounters": encounters,
    }


if __name__ == "__main__":  # quick smoke test
    roster = load_roster()
    print(f"{len(roster)} patients")
    c = get_chart("P001")
    print(c["name"], c["mrn"], c["age"], c["sex"])
    print("problems:", [p["problem"] for p in c["problems"]])
    print("meds:", [m["medication"] for m in c["medications"]])
    print("labs:", [l["title"] for l in c["labs"]])
    print("trends:", list(c["trends"].keys()))
