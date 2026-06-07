"""Bilingual (English + written Cantonese / zh-Hant-HK) parsing helpers.

Drives the deterministic planner: which writable field a clinician dictated,
which drug, which simulated intervention, and which kind of question.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

CJK = re.compile(r"[一-鿿]")


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ""))


def includes_any(text: str, lower: str, keys: List[str]) -> bool:
    return any((k in text) if has_cjk(k) else (k in lower) for k in keys)


def first_number(text: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else None


# ── Writable record fields (voice charting → patient_state) ──────────────────
# key → (display, unit, [match terms EN + zh])
FIELD_LEXICON: List[Dict] = [
    {"key": "sofa", "label": "SOFA", "unit": "/24", "match": ["sofa"]},
    {"key": "sapsii", "label": "SAPS II", "unit": "", "match": ["saps"]},
    {"key": "lactate", "label": "Lactate", "unit": "mmol/L", "match": ["lactate", "乳酸"]},
    {"key": "map", "label": "MAP", "unit": "mmHg", "match": ["map", "blood pressure", "血壓", "動脈壓"]},
    {"key": "heart_rate", "label": "Heart rate", "unit": "/min", "match": ["heart rate", "pulse", "心率", "心跳"]},
    {"key": "resp_rate", "label": "Resp rate", "unit": "/min", "match": ["respiratory rate", "resp rate", "呼吸率", "呼吸"]},
    {"key": "spo2", "label": "SpO₂", "unit": "%", "match": ["spo2", "oxygen", "saturation", "血氧"]},
    {"key": "temperature", "label": "Temperature", "unit": "°C", "match": ["temperature", "temp", "體溫"]},
    {"key": "wbc", "label": "WBC", "unit": "x10⁹/L", "match": ["wbc", "white cell", "白血球"]},
    {"key": "crp", "label": "CRP", "unit": "mg/L", "match": ["crp", "c反應"]},
    {"key": "pct", "label": "Procalcitonin", "unit": "ng/mL", "match": ["procalcitonin", "pct", "降鈣素"]},
    {"key": "urine_output", "label": "Urine output", "unit": "mL/24h", "match": ["urine", "尿量", "尿"]},
    {"key": "antibiotic_days", "label": "Antibiotic days", "unit": "d", "match": ["antibiotic day", "abx day", "抗生素日"]},
]

WRITE_TRIGGERS = ["set ", "record", "chart", "update", "log ", "is now", "note that",
                  "改為", "記低", "記錄", "設定", "更新", "輸入", "寫低"]


def parse_write(text: str, lower: str) -> Optional[Dict]:
    is_write = includes_any(text, lower, WRITE_TRIGGERS)
    if not is_write:
        return None
    field = next((f for f in FIELD_LEXICON
                  if includes_any(text, lower, f["match"])), None)
    if not field:
        return None
    num = first_number(text)
    if num is None:
        return None
    return {"key": field["key"], "label": field["label"], "unit": field["unit"], "value": num}


# ── Vital / data queries ─────────────────────────────────────────────────────
VITAL_QUERIES: List[Dict] = [
    {"field": "sofa", "label": {"en": "SOFA score", "zh": "SOFA 評分"}, "unit": {"en": "/24", "zh": "/24"},
     "match": ["sofa"]},
    {"field": "lactate", "label": {"en": "Lactate", "zh": "乳酸"}, "unit": {"en": "mmol/L", "zh": "mmol/L"},
     "match": ["lactate", "乳酸"]},
    {"field": "map", "label": {"en": "MAP", "zh": "平均動脈壓"}, "unit": {"en": "mmHg", "zh": "mmHg"},
     "match": ["blood pressure", "map", "血壓"]},
    {"field": "heart_rate", "label": {"en": "Heart rate", "zh": "心率"}, "unit": {"en": "/min", "zh": "/分鐘"},
     "match": ["heart rate", "pulse", "心率", "心跳"]},
    {"field": "temperature", "label": {"en": "Temperature", "zh": "體溫"}, "unit": {"en": "°C", "zh": "°C"},
     "match": ["temperature", "temp", "體溫"]},
    {"field": "spo2", "label": {"en": "SpO₂", "zh": "血氧"}, "unit": {"en": "%", "zh": "%"},
     "match": ["oxygen", "spo2", "saturation", "血氧"]},
    {"field": "wbc", "label": {"en": "WBC", "zh": "白血球"}, "unit": {"en": "x10⁹/L", "zh": "x10⁹/L"},
     "match": ["white cell", "wbc", "白血球"]},
    {"field": "crp", "label": {"en": "CRP", "zh": "C反應蛋白"}, "unit": {"en": "mg/L", "zh": "mg/L"},
     "match": ["crp", "c反應"]},
]


# ── Simulated interventions (scored, not written) ────────────────────────────
INTERVENTIONS: List[Dict] = [
    {"id": "albumin", "match": ["albumin", "白蛋白"],
     "delta": {"map": 5, "urine_output": 150},
     "describe": {"en": "Giving albumin (simulated MAP +5, urine +150 mL/24h)",
                  "zh": "俾白蛋白（模擬 MAP +5、尿量 +150 mL/24h）"},
     "caveat": {"en": "Albumin is not a node in the causal graph — modelled via expected haemodynamic response.",
                "zh": "白蛋白並非因果圖節點 — 透過預期血流動力學反應模擬。"}},
    {"id": "fluids", "match": ["fluid", "bolus", "crystalloid", "輸液", "補液", "俾水", "生理鹽水"],
     "delta": {"map": 6, "lactate": -0.4, "urine_output": 200},
     "describe": {"en": "Fluid bolus (simulated MAP +6, lactate −0.4, urine +200 mL/24h)",
                  "zh": "輸液（模擬 MAP +6、乳酸 −0.4、尿量 +200 mL/24h）"}},
    {"id": "vasopressor", "match": ["vasopressor", "pressor", "noradrenaline", "norepinephrine", "升壓藥", "升壓", "去甲腎"],
     "delta": {"vaso": 1, "map": 10},
     "describe": {"en": "Starting/escalating vasopressors (simulated vaso ON, MAP +10)",
                  "zh": "開始／加大升壓藥（模擬升壓藥開啟、MAP +10）"}},
    {"id": "ventilation", "match": ["ventilat", "intubat", "呼吸機", "插喉"],
     "delta": {"ventilation": 1, "spo2": 5},
     "describe": {"en": "Mechanical ventilation (simulated vent ON, SpO₂ +5%)",
                  "zh": "機械通氣（模擬呼吸機開啟、血氧 +5%）"}},
]


# ── Antibiotic actions (written to the record) ───────────────────────────────
# Each maps an utterance to a prescription change + the analytic arm.
ABX_ACTIONS: List[Dict] = [
    {"id": "deescalate", "arm": "deescalate",
     "match": ["de-escalate", "deescalate", "narrow", "step down", "降階", "收窄"],
     "prescription": {"action": "switch", "drug": "CRO2G", "dose": "2 g", "frequency": "daily"},
     "describe": {"en": "De-escalating to narrow-spectrum (Ceftriaxone)",
                  "zh": "降階至窄譜抗生素（頭孢曲松）"}},
    {"id": "cease", "arm": "cease",
     "match": ["stop antibiotic", "cease antibiotic", "stop abx", "cease", "停抗生素", "停藥", "停用抗生素"],
     "prescription": {"action": "stop", "drug": "*"},
     "describe": {"en": "Ceasing antibiotics", "zh": "停用抗生素"}},
    {"id": "continue", "arm": "continue",
     "match": ["continue antibiotic", "keep antibiotic", "broad-spectrum", "繼續抗生素", "繼續廣譜"],
     "prescription": None,
     "describe": {"en": "Continuing broad-spectrum antibiotics", "zh": "繼續廣譜抗生素"}},
]

# Named-drug starts (e.g. "start vancomycin").
DRUG_LEXICON: List[Tuple[List[str], str, str, str]] = [
    (["meropenem", "美羅培南"], "MER1G", "1 g", "q8h"),
    (["piperacillin", "tazobactam", "tazocin", "哌拉西林"], "TZP45", "4.5 g", "q8h"),
    (["ceftriaxone", "頭孢曲松"], "CRO2G", "2 g", "daily"),
    (["cefuroxime", "頭孢呋辛"], "CXM750", "750 mg", "q8h"),
    (["vancomycin", "萬古霉素"], "VAN1G", "1 g", "q12h"),
    (["amoxicillin", "augmentin", "clavulanate", "阿莫西林"], "AMC12", "1.2 g", "q8h"),
    (["azithromycin", "阿奇霉素"], "AZI500", "500 mg", "daily"),
]

START_TRIGGERS = ["start ", "give ", "add ", "commence", "begin ", "開始", "加用", "俾"]


def parse_drug_start(text: str, lower: str) -> Optional[Dict]:
    if not includes_any(text, lower, START_TRIGGERS):
        return None
    for terms, code, dose, freq in DRUG_LEXICON:
        if includes_any(text, lower, terms):
            return {"action": "start", "drug": code, "dose": dose, "frequency": freq, "route": "IV"}
    return None


# ── Intent keyword banks ─────────────────────────────────────────────────────
SHOW_ALL = ["all patient", "patient list", "every patient", "show patients", "list patients",
            "who is in", "worklist", "所有病人", "全部病人", "病人名單", "邊個病人"]
MORTALITY_Q = ["mortality", "risk of death", "prognosis", "outlook", "死亡率", "風險", "預後"]
RECOMMEND_Q = ["recommend", "what should", "best option", "should i", "建議", "應該點", "點做好"]
COHORT_Q = ["how many", "cohort", "territory", "across hong kong", "similar patient", "past patient",
            "historically", "幾多", "隊列", "全港", "相似病人", "以往", "過往"]
SIMILAR_Q = ["similar patient", "past patient", "people like", "相似病人", "相似個案", "類似病人"]
