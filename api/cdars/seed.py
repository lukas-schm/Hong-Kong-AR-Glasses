"""Deterministic synthetic seeding of the CDARS warehouse.

Two layers:
  1. A territory-wide retrospective cohort (1995–2026, all clusters) of
     sepsis / serious-infection episodes, with *confounded* treatment and
     outcome generation so cohort statistics are clinically sensible
     (sicker patients are continued on broad-spectrum and die more; the
     causal benefit of de-escalation is concentrated in lower-severity,
     culture-positive patients).
  2. Six current ICU admissions with dense longitudinal records (labs,
     vitals, micro, prescriptions, notes) and an identity-vault entry so
     they can be re-identified into the eHRSS view for the live demo.

All data is fictional. The four canonical index patients keep the same
reference keys, HKIDs and feature snapshots used elsewhere in the app.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List

from . import catalog as cat
from .db import Database

SEED = 20260607
HISTORIC_N = 2200
NOW = datetime(2026, 6, 6)


# ─────────────────────────────────────────────────────────────────────────────
# Six current ICU admissions (re-identifiable in this demo)
# ─────────────────────────────────────────────────────────────────────────────
def _state(**kw: Any) -> Dict[str, Any]:
    base = dict(
        sofa=0, sapsii=0, lactate=0, vaso=0, ventilation=0, aki=0, dialysis=0,
        pct=0, crp=0, wbc=0, temperature=37.0, culture_result="pending",
        source_identified=0, pathogen_identified=0, antibiotic_days=3,
        age=65, female=0, comorbidity=2, immunocompromised=0,
        heart_rate=80, resp_rate=16, spo2=98, map=80, urine_output=1200,
        weight=65, active_treatment_id="continue",
    )
    base.update(kw)
    return base


ACTIVE: List[Dict[str, Any]] = [
    {
        "reference_key": "10394722", "hkid": "K523678(A)",
        "name_en": "CHAN, Tai Man", "name_zh": "陳大文", "ccc": "7115 1129 2429",
        "dob": "1954-03-12", "sex": "M", "hospital": "QEH", "specialty": "ICU",
        "ward_en": "ICU · Bed 7", "ward_zh": "深切治療部 · 7號床",
        "subtitle_en": "72y · Male · Severe sepsis · ICU Day 3",
        "subtitle_zh": "72歲 · 男 · 嚴重敗血症 · 深切治療部第3日",
        "tags_en": ["Culture pending", "High SOFA", "Ventilated"],
        "tags_zh": ["培養待定", "SOFA 偏高", "使用呼吸機"],
        "dx": [("995.92", 1), ("486", 2), ("584.9", 3), ("401.9", 4)],
        "rx": [("MER1G", "1 g", "IV", "q8h", "active"),
               ("NORAD", "0.4 µg/kg/min", "IV infusion", "continuous", "active")],
        "labs": [("WBC", 18.7), ("CRP", 312), ("LACT", 4.8), ("PCT", 8.6),
                 ("CREA", 188), ("PLT", 96)],
        "micro": [("Blood", "PEND", "pending")],
        "allergy": [("ALG-PCN", "Penicillin", "青霉素", "Rash", "皮疹")],
        "state": _state(sofa=11, sapsii=58, lactate=4.8, vaso=1, ventilation=1, aki=2,
                        pct=8.6, crp=312, wbc=18.7, temperature=39.2, culture_result="pending",
                        antibiotic_days=3, age=72, female=0, comorbidity=6,
                        heart_rate=118, resp_rate=27, spo2=90, map=58, urine_output=540,
                        weight=68, active_treatment_id="continue"),
        "arm": "continue",
        "cached": {"continue": 41, "deescalate": 47, "cease": 62, "rec": "continue"},
        "rec_en": "Continue broad-spectrum: culture pending, high severity, de-escalation premature.",
        "rec_zh": "建議繼續廣譜抗生素：培養結果待定、病情嚴重，現階段降階為時尚早。",
    },
    {
        "reference_key": "10741055", "hkid": "P117465(3)",
        "name_en": "WONG, Siu Ying", "name_zh": "黃小英", "ccc": "7806 1420 5391",
        "dob": "1961-08-29", "sex": "F", "hospital": "PWH", "specialty": "ICU",
        "ward_en": "ICU · Bed 3", "ward_zh": "深切治療部 · 3號床",
        "subtitle_en": "64y · Female · Sepsis · ICU Day 3",
        "subtitle_zh": "64歲 · 女 · 敗血症 · 深切治療部第3日",
        "tags_en": ["Culture-positive (E. coli)", "UTI source", "Improving"],
        "tags_zh": ["培養陽性（大腸桿菌）", "尿路感染源", "病情好轉"],
        "dx": [("038.42", 1), ("599.0", 2), ("250.00", 3)],
        "rx": [("TZP45", "4.5 g", "IV", "q8h", "active")],
        "labs": [("WBC", 14.2), ("CRP", 187), ("LACT", 2.1), ("PCT", 12.4),
                 ("CREA", 121), ("PLT", 178)],
        "micro": [("Blood", "ECOLI", "positive"), ("Urine", "ECOLI", "positive")],
        "allergy": [],
        "state": _state(sofa=6, sapsii=34, lactate=2.1, vaso=0, ventilation=0, aki=1,
                        pct=12.4, crp=187, wbc=14.2, temperature=38.4, culture_result="positive",
                        source_identified=1, pathogen_identified=1, antibiotic_days=3,
                        age=64, female=1, comorbidity=3, heart_rate=88, resp_rate=18,
                        spo2=96, map=72, urine_output=1100, weight=58,
                        active_treatment_id="deescalate"),
        "arm": "deescalate",
        "cached": {"continue": 14, "deescalate": 11, "cease": 26, "rec": "deescalate"},
        "rec_en": "De-escalation to culture-guided narrow-spectrum reduces mortality by 3 pp vs. continuation.",
        "rec_zh": "根據培養結果降階至窄譜抗生素，較繼續廣譜治療可降低死亡率3個百分點。",
    },
    {
        "reference_key": "10852916", "hkid": "R876026(0)",
        "name_en": "LEE, Ka Ho", "name_zh": "李家豪", "ccc": "2621 1367 5072",
        "dob": "1972-01-04", "sex": "M", "hospital": "QMH", "specialty": "ICU",
        "ward_en": "ICU · Bed 11", "ward_zh": "深切治療部 · 11號床",
        "subtitle_en": "54y · Male · Suspected sepsis · ICU Day 3",
        "subtitle_zh": "54歲 · 男 · 疑似敗血症 · 深切治療部第3日",
        "tags_en": ["Culture-negative", "PCT declining", "No vasopressors"],
        "tags_zh": ["培養陰性", "降鈣素原下降", "無需升壓藥"],
        "dx": [("038.9", 1), ("496", 2)],
        "rx": [("CRO2G", "2 g", "IV", "daily", "active")],
        "labs": [("WBC", 10.1), ("CRP", 62), ("LACT", 1.4), ("PCT", 0.8),
                 ("CREA", 88), ("PLT", 233)],
        "micro": [("Blood", "NG", "negative")],
        "allergy": [],
        "state": _state(sofa=4, sapsii=26, lactate=1.4, vaso=0, ventilation=0, aki=0,
                        pct=0.8, crp=62, wbc=10.1, temperature=37.2, culture_result="negative",
                        antibiotic_days=3, age=54, female=0, comorbidity=2,
                        heart_rate=82, resp_rate=16, spo2=98, map=78, urine_output=1450,
                        weight=75, active_treatment_id="cease"),
        "arm": "cease",
        "cached": {"continue": 9, "deescalate": 8, "cease": 7, "rec": "cease"},
        "rec_en": "Antibiotic cessation appears safe: culture-negative, low PCT, improving clinical status.",
        "rec_zh": "停用抗生素屬安全：培養陰性、降鈣素原偏低、臨床狀況持續好轉。",
    },
    {
        "reference_key": "10238847", "hkid": "D224458(7)",
        "name_en": "CHEUNG, Mei Ling", "name_zh": "張美玲", "ccc": "1728 5019 3781",
        "dob": "1945-05-17", "sex": "F", "hospital": "TMH", "specialty": "ICU",
        "ward_en": "ICU · Bed 2", "ward_zh": "深切治療部 · 2號床",
        "subtitle_en": "81y · Female · Sepsis · ICU Day 3",
        "subtitle_zh": "81歲 · 女 · 敗血症 · 深切治療部第3日",
        "tags_en": ["Culture-positive (Klebsiella)", "Respiratory source", "Moderate severity"],
        "tags_zh": ["培養陽性（克雷伯氏菌）", "呼吸道感染源", "中度嚴重"],
        "dx": [("038.49", 1), ("486", 2), ("427.31", 3)],
        "rx": [("MER1G", "1 g", "IV", "q8h", "active"),
               ("NORAD", "0.2 µg/kg/min", "IV infusion", "continuous", "active")],
        "labs": [("WBC", 16.4), ("CRP", 142), ("LACT", 2.6), ("PCT", 15.2),
                 ("CREA", 134), ("PLT", 155)],
        "micro": [("Blood", "KPNEU", "positive"), ("Sputum", "KPNEU", "positive")],
        "allergy": [("ALG-SUL", "Sulfonamides", "磺胺類", "Urticaria", "蕁麻疹")],
        "state": _state(sofa=7, sapsii=41, lactate=2.6, vaso=1, ventilation=0, aki=1,
                        pct=15.2, crp=142, wbc=16.4, temperature=38.9, culture_result="positive",
                        source_identified=1, pathogen_identified=1, antibiotic_days=3,
                        age=81, female=1, comorbidity=4, heart_rate=96, resp_rate=22,
                        spo2=93, map=65, urine_output=890, weight=52,
                        active_treatment_id="deescalate"),
        "arm": "deescalate",
        "cached": {"continue": 19, "deescalate": 15, "cease": 34, "rec": "deescalate"},
        "rec_en": "De-escalation guided by culture sensitivity reduces mortality by 4 pp.",
        "rec_zh": "根據藥敏結果降階治療，可降低死亡率4個百分點。",
    },
    {
        "reference_key": "10567204", "hkid": "Y641203(8)",
        "name_en": "NG, Chi Keung", "name_zh": "吳志強", "ccc": "0710 1807 1730",
        "dob": "1956-11-23", "sex": "M", "hospital": "UCH", "specialty": "ICU",
        "ward_en": "ICU · Bed 5", "ward_zh": "深切治療部 · 5號床",
        "subtitle_en": "69y · Male · Pneumonia + sepsis · ICU Day 2",
        "subtitle_zh": "69歲 · 男 · 肺炎併敗血症 · 深切治療部第2日",
        "tags_en": ["Culture pending", "Pulmonary source", "COPD"],
        "tags_zh": ["培養待定", "肺部感染源", "慢阻肺"],
        "dx": [("486", 1), ("995.91", 2), ("496", 3), ("518.81", 4)],
        "rx": [("TZP45", "4.5 g", "IV", "q8h", "active"),
               ("NORAD", "0.1 µg/kg/min", "IV infusion", "continuous", "active")],
        "labs": [("WBC", 15.8), ("CRP", 224), ("LACT", 3.1), ("PCT", 5.2),
                 ("CREA", 142), ("PLT", 121)],
        "micro": [("Blood", "PEND", "pending"), ("Sputum", "PEND", "pending")],
        "allergy": [],
        "state": _state(sofa=8, sapsii=44, lactate=3.1, vaso=1, ventilation=1, aki=1,
                        pct=5.2, crp=224, wbc=15.8, temperature=38.7, culture_result="pending",
                        source_identified=1, antibiotic_days=2, age=69, female=0,
                        comorbidity=5, heart_rate=104, resp_rate=24, spo2=91, map=66,
                        urine_output=720, weight=64, active_treatment_id="continue"),
        "arm": "continue",
        "cached": {"continue": 24, "deescalate": 29, "cease": 41, "rec": "continue"},
        "rec_en": "Continue broad-spectrum: source identified but cultures pending and patient ventilated.",
        "rec_zh": "建議繼續廣譜抗生素：感染源已確認，但培養待定且病人需呼吸機支援。",
    },
    {
        "reference_key": "10683391", "hkid": "M772158(4)",
        "name_en": "LAU, Yuk Lan", "name_zh": "劉玉蘭", "ccc": "0491 3768 5366",
        "dob": "1949-02-08", "sex": "F", "hospital": "PMH", "specialty": "ICU",
        "ward_en": "ICU · Bed 9", "ward_zh": "深切治療部 · 9號床",
        "subtitle_en": "77y · Female · Septic shock · ICU Day 1",
        "subtitle_zh": "77歲 · 女 · 感染性休克 · 深切治療部第1日",
        "tags_en": ["Septic shock", "On dialysis", "Immunocompromised"],
        "tags_zh": ["感染性休克", "需透析", "免疫力低"],
        "dx": [("785.52", 1), ("995.92", 2), ("584.9", 3), ("585.6", 4)],
        "rx": [("MER1G", "1 g", "IV", "q8h", "active"),
               ("VAN1G", "1 g", "IV", "q12h", "active"),
               ("NORAD", "0.6 µg/kg/min", "IV infusion", "continuous", "active"),
               ("ADREN", "0.1 µg/kg/min", "IV infusion", "continuous", "active")],
        "labs": [("WBC", 21.3), ("CRP", 287), ("LACT", 5.6), ("PCT", 22.0),
                 ("CREA", 412), ("PLT", 74)],
        "micro": [("Blood", "PEND", "pending")],
        "allergy": [],
        "state": _state(sofa=13, sapsii=64, lactate=5.6, vaso=1, ventilation=1, aki=3,
                        dialysis=1, pct=22.0, crp=287, wbc=21.3, temperature=39.5,
                        culture_result="pending", antibiotic_days=1, age=77, female=1,
                        comorbidity=5, immunocompromised=1, heart_rate=124, resp_rate=29,
                        spo2=88, map=54, urine_output=320, weight=59,
                        active_treatment_id="continue"),
        "arm": "continue",
        "cached": {"continue": 48, "deescalate": 55, "cease": 70, "rec": "continue"},
        "rec_en": "Continue broad-spectrum: septic shock, immunocompromised, cultures pending — do not narrow.",
        "rec_zh": "建議繼續廣譜抗生素：感染性休克、免疫力低、培養待定 — 不宜收窄。",
    },
]

STATE_COLS = [
    "sofa", "sapsii", "lactate", "vaso", "ventilation", "aki", "dialysis",
    "pct", "crp", "wbc", "temperature", "culture_result", "source_identified",
    "pathogen_identified", "antibiotic_days", "age", "female", "comorbidity",
    "immunocompromised", "heart_rate", "resp_rate", "spo2", "map",
    "urine_output", "weight", "active_treatment_id",
]


# ─────────────────────────────────────────────────────────────────────────────
def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def seed(db: Database, force: bool = False) -> Dict[str, int]:
    """Populate the warehouse. Idempotent unless force=True."""
    if db.is_seeded() and not force:
        return _summary(db)
    if force:
        # Children before the parent `patient` table (FK constraints).
        for tbl in ("identity_vault", "episode", "diagnosis",
                    "prescription", "procedure", "allergy", "lab_result",
                    "micro_result", "vital_sign", "clinical_note",
                    "patient_state", "abx_course", "active_meta", "audit_log",
                    "patient"):
            db.execute(f"DELETE FROM {tbl}")

    rng = random.Random(SEED)
    _seed_active(db)
    _seed_historic(db, rng)
    db.audit("system", "seed", channel="portal",
             detail=f"warehouse seeded: {db.count('patient')} patients")
    return _summary(db)


def _seed_active(db: Database) -> None:
    for p in ACTIVE:
        rk = p["reference_key"]
        age = int(p["state"]["age"])
        birth_year = int(p["dob"][:4])
        db.execute(
            "INSERT INTO patient (reference_key, sex, birth_year, age, dod, active) "
            "VALUES (?,?,?,?,?,1)",
            (rk, p["sex"], birth_year, age, None),
        )
        db.execute(
            "INSERT INTO identity_vault "
            "(reference_key, hkid, name_en, name_zh, ccc, dob, hospital, ward_en, ward_zh) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (rk, p["hkid"], p["name_en"], p["name_zh"], p["ccc"], p["dob"],
             p["hospital"], p["ward_en"], p["ward_zh"]),
        )

        # Index ICU episode (still admitted) + a prior outpatient encounter.
        adm = NOW - timedelta(days=int(NOW.day % 3) + 1)
        day_match = {"Day 1": 1, "Day 2": 2, "Day 3": 3}
        for k, v in day_match.items():
            if k.lower() in p["subtitle_en"].lower():
                adm = NOW - timedelta(days=v - 1)
        ep_id = f"E{rk}A"
        cluster = cat.cluster_of(p["hospital"])
        db.execute(
            "INSERT INTO episode (episode_id, reference_key, episode_type, admission_date, "
            "discharge_date, cluster, hospital, specialty, ward) VALUES (?,?,?,?,?,?,?,?,?)",
            (ep_id, rk, "IP", _iso(adm), None, cluster, p["hospital"], "ICU", p["ward_en"]),
        )
        prior = adm - timedelta(days=180)
        db.execute(
            "INSERT INTO episode (episode_id, reference_key, episode_type, admission_date, "
            "discharge_date, cluster, hospital, specialty, ward) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"E{rk}P", rk, "SOPC", _iso(prior), _iso(prior), cluster, p["hospital"], "MED", None),
        )

        for code, rank in p["dx"]:
            db.execute(
                "INSERT INTO diagnosis (episode_id, reference_key, code, rank, dx_date) "
                "VALUES (?,?,?,?,?)", (ep_id, rk, code, rank, _iso(adm)))

        for drug_code, dose, route, freq, status in p["rx"]:
            drug = cat.DRUG_BY_CODE[drug_code]
            db.execute(
                "INSERT INTO prescription (episode_id, reference_key, bnf, drug_code, dose, "
                "route, frequency, start_date, end_date, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ep_id, rk, drug["bnf"], drug_code, dose, route, freq, _iso(adm), None, status))

        # Labs at a few timepoints (latest carries the snapshot value).
        for code, value in p["labs"]:
            for h, scale in ((36, 1.18), (24, 1.1), (12, 1.04), (0, 1.0)):
                v = round(value * scale, 1)
                db.execute(
                    "INSERT INTO lab_result (episode_id, reference_key, test_code, value, unit, "
                    "flag, collected) VALUES (?,?,?,?,?,?,?)",
                    (ep_id, rk, code, v, cat.LAB_BY_CODE[code]["unit"],
                     cat.lab_flag(code, v), _ts(NOW - timedelta(hours=h))))

        for specimen, organism, result in p["micro"]:
            resulted = None if result == "pending" else _ts(NOW - timedelta(hours=18))
            db.execute(
                "INSERT INTO micro_result (episode_id, reference_key, specimen, organism, "
                "result, collected, resulted) VALUES (?,?,?,?,?,?,?)",
                (ep_id, rk, specimen, organism, result, _ts(adm), resulted))

        for code, sub_en, sub_zh, rx_en, rx_zh in p["allergy"]:
            db.execute(
                "INSERT INTO allergy (reference_key, code, substance_en, substance_zh, "
                "reaction_en, reaction_zh) VALUES (?,?,?,?,?,?)",
                (rk, code, sub_en, sub_zh, rx_en, rx_zh))

        st = p["state"]
        for h in (12, 8, 4, 0):
            jitter = h / 12.0
            db.execute(
                "INSERT INTO vital_sign (episode_id, reference_key, taken, hr, rr, sbp, map, "
                "spo2, temp) VALUES (?,?,?,?,?,?,?,?,?)",
                (ep_id, rk, _ts(NOW - timedelta(hours=h)),
                 round(st["heart_rate"] + jitter * 6, 0),
                 round(st["resp_rate"] + jitter * 2, 0),
                 round(st["map"] * 1.4 + jitter * 4, 0),
                 round(st["map"] + jitter * 3, 0),
                 round(st["spo2"] - jitter * 2, 0),
                 round(st["temperature"] + jitter * 0.3, 1)))

        cols = ", ".join(STATE_COLS)
        ph = ", ".join("?" for _ in STATE_COLS)
        db.execute(
            f"INSERT INTO patient_state (reference_key, {cols}, updated_at) "
            f"VALUES (?, {ph}, ?)",
            (rk, *[st[c] for c in STATE_COLS], _ts(NOW))),

        db.execute(
            "INSERT INTO abx_course (reference_key, decision_date, arm, days_on_abx, "
            "mortality_28d, sofa, lactate, culture, age, sex, cluster) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (rk, _iso(adm), p["arm"], int(st["antibiotic_days"]), None,
             st["sofa"], st["lactate"], st["culture_result"], age, p["sex"], cluster))

        meta = {
            "subtitle": {"en": p["subtitle_en"], "zh": p["subtitle_zh"]},
            "tags": [{"en": e, "zh": z} for e, z in zip(p["tags_en"], p["tags_zh"])],
            "recommendation": {"en": p["rec_en"], "zh": p["rec_zh"]},
            "cached": p["cached"],
        }
        db.execute("INSERT INTO active_meta (reference_key, meta) VALUES (?,?)",
                   (rk, json.dumps(meta, ensure_ascii=False)))

        # Initial system note documenting the admission.
        db.execute(
            "INSERT INTO clinical_note (episode_id, reference_key, author, note_time, lang, "
            "text, source) VALUES (?,?,?,?,?,?,?)",
            (ep_id, rk, "System", _ts(adm), "en",
             f"ICU admission. {p['subtitle_en']}. Started {cat.DRUG_BY_CODE[p['rx'][0][0]]['name']['en']}.",
             "system"))


def _seed_historic(db: Database, rng: random.Random) -> None:
    """Confounded territory-wide retrospective cohort, 1995–2026."""
    sepsis_dx = cat.SEPSIS_CODES + ["486", "599.0", "590.10", "567.21"]
    # Recent years are over-represented (CDARS grew over time).
    years = list(range(1995, 2027))
    year_w = [1.0 + (y - 1995) * 0.12 for y in years]

    patients, episodes, diags, courses, labs, micros = [], [], [], [], [], []
    for i in range(HISTORIC_N):
        rk = f"{20000000 + i * 37 % 79999999:08d}"
        sex = rng.choice(["M", "F"])
        age = int(min(95, max(18, rng.gauss(68, 14))))
        cluster = rng.choice(list(cat.CLUSTERS))
        hosp = rng.choice([h["code"] for h in cat.HOSPITALS if h["cluster"] == cluster])

        # Severity & infection certainty (the confounders).
        sofa = int(min(20, max(0, rng.gauss(7, 4))))
        lactate = round(max(0.5, rng.gauss(2.6, 1.8)), 1)
        shock = lactate >= 4 or sofa >= 12
        culture = rng.choices(["positive", "negative", "pending"], weights=[0.42, 0.38, 0.20])[0]
        low_sev = sofa <= 6 and lactate < 3 and not shock

        # Treatment assignment confounded by severity & culture (observational).
        if shock or sofa >= 12:
            arm = rng.choices(["continue", "deescalate", "cease"], weights=[0.78, 0.18, 0.04])[0]
        elif low_sev and culture == "positive":
            arm = rng.choices(["continue", "deescalate", "cease"], weights=[0.30, 0.55, 0.15])[0]
        elif low_sev and culture == "negative":
            arm = rng.choices(["continue", "deescalate", "cease"], weights=[0.28, 0.30, 0.42])[0]
        else:
            arm = rng.choices(["continue", "deescalate", "cease"], weights=[0.55, 0.32, 0.13])[0]

        # Outcome: baseline risk from severity; arm modifies it with effect
        # heterogeneity (de-escalation helps low-severity culture-positive,
        # harms high-severity / culture-pending).
        risk = 0.04 + 0.028 * sofa + 0.05 * (lactate - 2) + 0.12 * shock + 0.004 * (age - 60)
        if arm == "deescalate":
            risk += -0.06 if (low_sev and culture == "positive") else 0.03
        elif arm == "cease":
            risk += -0.04 if (low_sev and culture == "negative") else 0.14
        risk = min(0.95, max(0.01, risk))
        died = rng.random() < risk

        adm_year = rng.choices(years, weights=year_w)[0]
        adm = datetime(adm_year, rng.randint(1, 12), rng.randint(1, 28),
                       rng.randint(0, 23), rng.randint(0, 59))
        los = max(1, int(rng.gauss(16 if sofa > 8 else 8, 6)))
        dischg = adm + timedelta(days=los)
        dod = None
        if died:
            dd = adm + timedelta(days=rng.randint(2, 28))
            dod = _iso(dd)

        dx = rng.choices(sepsis_dx, weights=[3 if c in cat.SEPSIS_CODES else 1 for c in sepsis_dx])[0]
        etype = rng.choices(["IP", "AE", "SOPC", "GOPC"], weights=[0.82, 0.1, 0.05, 0.03])[0]
        spec = "ICU" if (sofa >= 6 and etype == "IP") else rng.choice(["MED", "RESP", "ID", "A&E"])
        ep_id = f"E{rk}"

        patients.append((rk, sex, adm_year - age, age, dod, 0))
        episodes.append((ep_id, rk, etype, _iso(adm),
                         None if dod and etype == "IP" and rng.random() < 0.3 else _iso(dischg),
                         cluster, hosp, spec, "ICU" if spec == "ICU" else None))
        diags.append((ep_id, rk, dx, 1, _iso(adm)))
        # one representative lab for the line-listing
        if culture == "positive" or rng.random() < 0.5:
            labs.append((ep_id, rk, "LACT", lactate, "mmol/L", cat.lab_flag("LACT", lactate), _ts(adm)))
        else:
            crp = round(max(2, rng.gauss(150, 70)), 0)
            labs.append((ep_id, rk, "CRP", crp, "mg/L", cat.lab_flag("CRP", crp), _ts(adm)))
        org = {"positive": rng.choice(["ECOLI", "KPNEU", "SAUR", "PAER"]),
               "negative": "NG", "pending": "PEND"}[culture]
        micros.append((ep_id, rk, "Blood", org, culture, _ts(adm),
                       None if culture == "pending" else _ts(adm + timedelta(days=2))))
        courses.append((rk, _iso(adm), arm, int(rng.randint(1, 7)),
                        1 if died else 0, sofa, lactate, culture, age, sex, cluster))

    db.executemany(
        "INSERT INTO patient (reference_key, sex, birth_year, age, dod, active) VALUES (?,?,?,?,?,?)",
        patients)
    db.executemany(
        "INSERT INTO episode (episode_id, reference_key, episode_type, admission_date, "
        "discharge_date, cluster, hospital, specialty, ward) VALUES (?,?,?,?,?,?,?,?,?)",
        episodes)
    db.executemany(
        "INSERT INTO diagnosis (episode_id, reference_key, code, rank, dx_date) VALUES (?,?,?,?,?)",
        diags)
    db.executemany(
        "INSERT INTO lab_result (episode_id, reference_key, test_code, value, unit, flag, collected) "
        "VALUES (?,?,?,?,?,?,?)", labs)
    db.executemany(
        "INSERT INTO micro_result (episode_id, reference_key, specimen, organism, result, "
        "collected, resulted) VALUES (?,?,?,?,?,?,?)", micros)
    db.executemany(
        "INSERT INTO abx_course (reference_key, decision_date, arm, days_on_abx, mortality_28d, "
        "sofa, lactate, culture, age, sex, cluster) VALUES (?,?,?,?,?,?,?,?,?,?,?)", courses)


def _summary(db: Database) -> Dict[str, int]:
    return {
        "patients": db.count("patient"),
        "active": db.count("patient", "active = 1"),
        "episodes": db.count("episode"),
        "diagnoses": db.count("diagnosis"),
        "abx_courses": db.count("abx_course"),
        "deaths": db.count("patient", "dod IS NOT NULL"),
    }


if __name__ == "__main__":
    from .db import get_db

    s = seed(get_db(), force=True)
    print("CDARS seeded:", s)
