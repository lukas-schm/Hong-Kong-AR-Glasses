"""
Constants for the sepsis treatment-timing pipeline.

Reuses path constants from ``antibiotic_pipeline.constants`` so both pipelines
read the same parquet tables.
"""

from sklearn.utils import Bunch

# Reuse shared paths / id columns / outcome names from the antibiotic pipeline.
from antibiotic_pipeline.constants import (  # noqa: F401  (re-exported)
    DIR2DATA,
    DIR2DERIVED,
    DIR2RAW,
    COLNAME_PATIENT_ID,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_MORTALITY_28D,
    COLNAME_AKI_WORSENING,
    COLNAME_ICU_LOS,
    BINARY_OUTCOMES,
    MIN_PS_SCORE,
    RANDOM_STATE,
)

# ── Output locations ─────────────────────────────────────────────────────────
DIR2TIMING = DIR2DATA / "timing"                 # cached panels per decision
DIR2TIMING_RESULTS = DIR2DATA / "results" / "timing"   # curve tables + AR json

# ── Landmark grid (the "multiple time points") ───────────────────────────────
# Hours since decision onset at which we estimate "treat now vs wait".
# Dense early (where the decision is clinically live), sparse later.
LANDMARK_GRID = [1, 2, 3, 4, 6, 8, 12, 24]

# Initiation window: a patient untreated at landmark t is "treated" if treatment
# starts within [t, t + EXPOSURE_WINDOW_H). Swept in the rigor path.
EXPOSURE_WINDOW_H = 3.0

# Follow-up horizon for the primary mortality outcome, measured from onset.
FOLLOWUP_DAYS = 28

# Minimum at-risk / treated counts for a landmark to be estimated (positivity).
MIN_AT_RISK = 100
MIN_PER_ARM = 20

# ── Cohort eligibility ───────────────────────────────────────────────────────
MIN_AGE = 18

# ── Treatment-arm coding for the timing exposure ─────────────────────────────
# At each landmark the exposure is binary: 0 = not (yet) treated in the window,
# 1 = treated within the initiation window.
EXPOSURE_WAIT = 0
EXPOSURE_TREAT_NOW = 1
EXPOSURE_LABELS = {EXPOSURE_WAIT: "Wait", EXPOSURE_TREAT_NOW: "Treat now"}
COLNAME_EXPOSURE = "treat_now"
COLNAME_ONSET = "onset_time"          # decision onset t0 (absolute timestamp)
COLNAME_LANDMARK_TIME = "landmark_time"  # onset + landmark hours (absolute)

# ── Outcomes used in the curve (primary first) ───────────────────────────────
TIMING_OUTCOMES = [
    COLNAME_MORTALITY_28D,   # primary
    COLNAME_AKI_WORSENING,
    COLNAME_ICU_LOS,
]
PRIMARY_OUTCOME = COLNAME_MORTALITY_28D

# ── CATE heterogeneity features (for "for patients like this" tiles) ──────────
TIMING_CATE_FEATURES = [
    "admission_age",
    "SOFA_at_landmark",
    "lactate_at_landmark",
    "immunosuppressed",
]

# ── Crystalloid fluid itemids (MIMIC-IV inputevents) ─────────────────────────
# Resuscitation crystalloids. VERIFY against derived/ d_items before a real run;
# these are the standard MIMIC-IV bolus/maintenance crystalloid items.
CRYSTALLOID_ITEMIDS = [
    225158,  # NaCl 0.9%
    225828,  # Lactated Ringers
    225825,  # D5NS
    225823,  # D5 1/2NS
    220949,  # Dextrose 5%
    225159,  # NaCl 0.45%
]
# Aggressive-resuscitation threshold (Surviving Sepsis): >=30 mL/kg crystalloid.
FLUID_AGGRESSIVE_ML_PER_KG = 30.0
DEFAULT_WEIGHT_KG = 80.0  # fallback when patient weight is missing

# ── Vasopressor of interest ──────────────────────────────────────────────────
# Column in derived/vasoactive_agent.parquet used as the pressor exposure.
PRESSOR_COLUMN = "norepinephrine"
SHOCK_MAP_THRESHOLD = 65.0    # MAP < 65 mmHg = hypotension
SHOCK_LACTATE_THRESHOLD = 4.0  # lactate >= 4 mmol/L = hypoperfusion

# ── Decision configurations ──────────────────────────────────────────────────
# Each decision defines: how onset t0 is anchored, and which exposure builder
# (in framing/exposures.py) flags "treated by landmark".
DECISION_ANTIBIOTICS = Bunch(
    key="antibiotics",
    label="Antibiotic timing",
    onset_anchor="suspected_infection",   # sepsis3.suspected_infection_time
    exposure="antibiotic",
    description="Time from suspected infection to first broad-spectrum antibiotic.",
)
DECISION_FLUIDS = Bunch(
    key="fluids",
    label="Fluid resuscitation timing",
    onset_anchor="shock",                 # first MAP<65 or lactate>=4
    exposure="fluids",
    description="Time from shock onset to aggressive crystalloid (>=30 mL/kg).",
)
DECISION_PRESSORS = Bunch(
    key="pressors",
    label="Vasopressor timing",
    onset_anchor="shock",
    exposure="pressors",
    description="Time from shock onset to norepinephrine initiation.",
)

DECISIONS = {
    DECISION_ANTIBIOTICS.key: DECISION_ANTIBIOTICS,
    DECISION_FLUIDS.key: DECISION_FLUIDS,
    DECISION_PRESSORS.key: DECISION_PRESSORS,
}
