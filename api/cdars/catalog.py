"""Reference catalogues for the CDARS warehouse.

Mirrors the standardised coding systems CDARS uses in practice:
  · HA clusters + hospitals (territory-wide public sector)
  · ICD-9-CM principal/secondary diagnosis codes
  · BNF drug sections for the pharmacy dispensing records
  · HA local laboratory test codes (no LOINC in the source warehouse)
  · specialties / encounter (episode) types

All bilingual where the real records are (English + Traditional Chinese,
zh-Hant-HK). Patients/keys are fictional.
"""
from __future__ import annotations

from typing import Dict, List, TypedDict


class Bi(TypedDict):
    en: str
    zh: str


def bi(en: str, zh: str) -> Bi:
    return {"en": en, "zh": zh}


# ── HA clusters (7) and a representative set of public hospitals ──────────────
# Every HA cluster is represented; CDARS draws from all public hospitals.
CLUSTERS: Dict[str, Bi] = {
    "HKEC": bi("Hong Kong East", "港島東聯網"),
    "HKWC": bi("Hong Kong West", "港島西聯網"),
    "KCC": bi("Kowloon Central", "九龍中聯網"),
    "KEC": bi("Kowloon East", "九龍東聯網"),
    "KWC": bi("Kowloon West", "九龍西聯網"),
    "NTEC": bi("New Territories East", "新界東聯網"),
    "NTWC": bi("New Territories West", "新界西聯網"),
}


class Hospital(TypedDict):
    code: str
    cluster: str
    name: Bi
    acute: bool


HOSPITALS: List[Hospital] = [
    {"code": "PYNEH", "cluster": "HKEC", "name": bi("Pamela Youde Nethersole Eastern Hospital", "東區尤德夫人那打素醫院"), "acute": True},
    {"code": "RH", "cluster": "HKEC", "name": bi("Ruttonjee Hospital", "律敦治醫院"), "acute": True},
    {"code": "QMH", "cluster": "HKWC", "name": bi("Queen Mary Hospital", "瑪麗醫院"), "acute": True},
    {"code": "GH", "cluster": "HKWC", "name": bi("Grantham Hospital", "葛量洪醫院"), "acute": False},
    {"code": "QEH", "cluster": "KCC", "name": bi("Queen Elizabeth Hospital", "伊利沙伯醫院"), "acute": True},
    {"code": "KWH", "cluster": "KCC", "name": bi("Kwong Wah Hospital", "廣華醫院"), "acute": True},
    {"code": "UCH", "cluster": "KEC", "name": bi("United Christian Hospital", "基督教聯合醫院"), "acute": True},
    {"code": "TKOH", "cluster": "KEC", "name": bi("Tseung Kwan O Hospital", "將軍澳醫院"), "acute": True},
    {"code": "PMH", "cluster": "KWC", "name": bi("Princess Margaret Hospital", "瑪嘉烈醫院"), "acute": True},
    {"code": "CMC", "cluster": "KWC", "name": bi("Caritas Medical Centre", "明愛醫院"), "acute": True},
    {"code": "PWH", "cluster": "NTEC", "name": bi("Prince of Wales Hospital", "威爾斯親王醫院"), "acute": True},
    {"code": "AHNH", "cluster": "NTEC", "name": bi("Alice Ho Miu Ling Nethersole Hospital", "雅麗氏何妙齡那打素醫院"), "acute": True},
    {"code": "TMH", "cluster": "NTWC", "name": bi("Tuen Mun Hospital", "屯門醫院"), "acute": True},
    {"code": "POH", "cluster": "NTWC", "name": bi("Pok Oi Hospital", "博愛醫院"), "acute": True},
    {"code": "TSWH", "cluster": "NTWC", "name": bi("Tin Shui Wai Hospital", "天水圍醫院"), "acute": True},
]

ACUTE_HOSPITALS: List[str] = [h["code"] for h in HOSPITALS if h["acute"]]


# ── Episode (encounter) types ────────────────────────────────────────────────
EPISODE_TYPES: Dict[str, Bi] = {
    "IP": bi("Inpatient", "住院"),
    "SOPC": bi("Specialist Outpatient", "專科門診"),
    "GOPC": bi("General Outpatient", "普通科門診"),
    "AE": bi("Accident & Emergency", "急症室"),
    "DH": bi("Day Hospital / Day Procedure", "日間醫院"),
}

SPECIALTIES: Dict[str, Bi] = {
    "ICU": bi("Intensive Care", "深切治療"),
    "MED": bi("Medicine", "內科"),
    "SUR": bi("Surgery", "外科"),
    "A&E": bi("Emergency Medicine", "急症科"),
    "FM": bi("Family Medicine", "家庭醫學"),
    "RESP": bi("Respiratory Medicine", "呼吸系統科"),
    "NEPH": bi("Nephrology", "腎科"),
    "ID": bi("Infectious Disease", "感染及傳染病科"),
}


# ── ICD-9-CM diagnosis catalogue (sepsis + common comorbidities) ─────────────
class Dx(TypedDict):
    code: str
    desc: Bi
    sepsis: bool


ICD9: List[Dx] = [
    {"code": "038.9", "desc": bi("Septicaemia, unspecified", "敗血症（未特指）"), "sepsis": True},
    {"code": "038.42", "desc": bi("Septicaemia due to E. coli", "大腸桿菌敗血症"), "sepsis": True},
    {"code": "038.43", "desc": bi("Septicaemia due to Pseudomonas", "綠膿桿菌敗血症"), "sepsis": True},
    {"code": "038.49", "desc": bi("Septicaemia due to other Gram-negative organism", "其他革蘭氏陰性菌敗血症"), "sepsis": True},
    {"code": "038.11", "desc": bi("Methicillin-susceptible Staph. aureus septicaemia", "甲氧西林敏感金黃葡萄球菌敗血症"), "sepsis": True},
    {"code": "995.91", "desc": bi("Sepsis", "敗血病"), "sepsis": True},
    {"code": "995.92", "desc": bi("Severe sepsis", "嚴重敗血病"), "sepsis": True},
    {"code": "785.52", "desc": bi("Septic shock", "感染性休克"), "sepsis": True},
    {"code": "486", "desc": bi("Pneumonia, organism unspecified", "肺炎（病原體未特指）"), "sepsis": False},
    {"code": "482.41", "desc": bi("Methicillin-susceptible S. aureus pneumonia", "金黃葡萄球菌肺炎"), "sepsis": False},
    {"code": "599.0", "desc": bi("Urinary tract infection, site not specified", "尿路感染"), "sepsis": False},
    {"code": "590.10", "desc": bi("Acute pyelonephritis", "急性腎盂腎炎"), "sepsis": False},
    {"code": "540.9", "desc": bi("Acute appendicitis without peritonitis", "急性闌尾炎"), "sepsis": False},
    {"code": "567.21", "desc": bi("Peritonitis (generalised)", "腹膜炎"), "sepsis": False},
    {"code": "584.9", "desc": bi("Acute kidney failure, unspecified", "急性腎衰竭"), "sepsis": False},
    {"code": "518.81", "desc": bi("Acute respiratory failure", "急性呼吸衰竭"), "sepsis": False},
    {"code": "250.00", "desc": bi("Type 2 diabetes mellitus", "二型糖尿病"), "sepsis": False},
    {"code": "401.9", "desc": bi("Essential hypertension", "原發性高血壓"), "sepsis": False},
    {"code": "496", "desc": bi("Chronic obstructive pulmonary disease", "慢性阻塞性肺病"), "sepsis": False},
    {"code": "427.31", "desc": bi("Atrial fibrillation", "心房顫動"), "sepsis": False},
    {"code": "428.0", "desc": bi("Congestive heart failure", "充血性心臟衰竭"), "sepsis": False},
    {"code": "585.6", "desc": bi("End-stage renal disease", "末期腎病"), "sepsis": False},
]

ICD9_BY_CODE: Dict[str, Dx] = {d["code"]: d for d in ICD9}
SEPSIS_CODES: List[str] = [d["code"] for d in ICD9 if d["sepsis"]]


# ── BNF drug catalogue (pharmacy dispensing records) ─────────────────────────
class Drug(TypedDict):
    bnf: str
    code: str          # HA drug code
    name: Bi
    cls: str           # 'broad' | 'narrow' | 'pressor' | 'other'


DRUGS: List[Drug] = [
    {"bnf": "5.1.2.3", "code": "MER1G", "name": bi("Meropenem 1 g inj", "美羅培南 1克注射"), "cls": "broad"},
    {"bnf": "5.1.2.3", "code": "IMI500", "name": bi("Imipenem-Cilastatin 500 mg inj", "亞胺培南-西司他丁 500毫克注射"), "cls": "broad"},
    {"bnf": "5.1.1.3", "code": "TZP45", "name": bi("Piperacillin-Tazobactam 4.5 g inj", "哌拉西林-他唑巴坦 4.5克注射"), "cls": "broad"},
    {"bnf": "5.1.2", "code": "CRO2G", "name": bi("Ceftriaxone 2 g inj", "頭孢曲松 2克注射"), "cls": "narrow"},
    {"bnf": "5.1.2", "code": "CXM750", "name": bi("Cefuroxime 750 mg inj", "頭孢呋辛 750毫克注射"), "cls": "narrow"},
    {"bnf": "5.1.1.3", "code": "AMC12", "name": bi("Amoxicillin-Clavulanate 1.2 g inj", "阿莫西林-克拉維酸 1.2克注射"), "cls": "narrow"},
    {"bnf": "5.1.1.1", "code": "AMP1G", "name": bi("Ampicillin 1 g inj", "氨苄西林 1克注射"), "cls": "narrow"},
    {"bnf": "5.1.5", "code": "AZI500", "name": bi("Azithromycin 500 mg inj", "阿奇霉素 500毫克注射"), "cls": "narrow"},
    {"bnf": "5.1.7", "code": "VAN1G", "name": bi("Vancomycin 1 g inj", "萬古霉素 1克注射"), "cls": "narrow"},
    {"bnf": "2.7.1", "code": "NORAD", "name": bi("Noradrenaline inj", "去甲腎上腺素注射"), "cls": "pressor"},
    {"bnf": "2.7.1", "code": "ADREN", "name": bi("Adrenaline inj", "腎上腺素注射"), "cls": "pressor"},
    {"bnf": "9.2.2", "code": "ALB20", "name": bi("Human Albumin 20% inj", "人血白蛋白 20% 注射"), "cls": "other"},
]

DRUG_BY_CODE: Dict[str, Drug] = {d["code"]: d for d in DRUGS}
BROAD_DRUGS: List[str] = [d["code"] for d in DRUGS if d["cls"] == "broad"]
NARROW_DRUGS: List[str] = [d["code"] for d in DRUGS if d["cls"] == "narrow"]

BNF_SECTIONS: Dict[str, Bi] = {
    "5.1.1.1": bi("Benzylpenicillin & penicillins", "青霉素類"),
    "5.1.1.3": bi("Broad-spectrum penicillins", "廣譜青霉素"),
    "5.1.2": bi("Cephalosporins & other beta-lactams", "頭孢菌素及其他β-內酰胺"),
    "5.1.2.3": bi("Carbapenems", "碳青霉烯類"),
    "5.1.5": bi("Macrolides", "大環內酯類"),
    "5.1.7": bi("Glycopeptide antibiotics", "糖肽類抗生素"),
    "2.7.1": bi("Inotropic sympathomimetics", "強心擬交感神經藥"),
    "9.2.2": bi("Fluids & electrolytes (IV)", "靜脈輸液及電解質"),
}


# ── HA local laboratory test catalogue (source names + units) ────────────────
class LabDef(TypedDict):
    code: str          # HA local test code
    name: Bi
    unit: str
    ref_low: float
    ref_high: float


LAB_DEFS: List[LabDef] = [
    {"code": "WBC", "name": bi("White cell count", "白血球計數"), "unit": "x10^9/L", "ref_low": 4.0, "ref_high": 11.0},
    {"code": "CRP", "name": bi("C-reactive protein", "C反應蛋白"), "unit": "mg/L", "ref_low": 0.0, "ref_high": 5.0},
    {"code": "LACT", "name": bi("Lactate (arterial)", "動脈乳酸"), "unit": "mmol/L", "ref_low": 0.5, "ref_high": 2.0},
    {"code": "PCT", "name": bi("Procalcitonin", "降鈣素原"), "unit": "ng/mL", "ref_low": 0.0, "ref_high": 0.5},
    {"code": "CREA", "name": bi("Creatinine", "肌酸酐"), "unit": "umol/L", "ref_low": 49.0, "ref_high": 106.0},
    {"code": "BILI", "name": bi("Bilirubin (total)", "總膽紅素"), "unit": "umol/L", "ref_low": 4.0, "ref_high": 23.0},
    {"code": "PLT", "name": bi("Platelet count", "血小板計數"), "unit": "x10^9/L", "ref_low": 150.0, "ref_high": 400.0},
    {"code": "HGB", "name": bi("Haemoglobin", "血紅蛋白"), "unit": "g/dL", "ref_low": 11.5, "ref_high": 17.0},
]

LAB_BY_CODE: Dict[str, LabDef] = {d["code"]: d for d in LAB_DEFS}


def lab_flag(code: str, value: float) -> str:
    """HA-style abnormal flag (H/HH/L/LL or '')."""
    d = LAB_BY_CODE.get(code)
    if not d:
        return ""
    if value > d["ref_high"]:
        return "HH" if value > d["ref_high"] * 2 else "H"
    if value < d["ref_low"]:
        return "LL" if value < d["ref_low"] * 0.5 else "L"
    return ""


# ── Microbiology organisms ───────────────────────────────────────────────────
ORGANISMS: Dict[str, Bi] = {
    "ECOLI": bi("Escherichia coli", "大腸桿菌"),
    "KPNEU": bi("Klebsiella pneumoniae", "克雷伯氏肺炎桿菌"),
    "SAUR": bi("Staphylococcus aureus", "金黃葡萄球菌"),
    "PAER": bi("Pseudomonas aeruginosa", "綠膿桿菌"),
    "NG": bi("No growth", "無生長"),
    "PEND": bi("Pending", "待定"),
}


def cluster_of(hospital_code: str) -> str:
    for h in HOSPITALS:
        if h["code"] == hospital_code:
            return h["cluster"]
    return "KCC"
