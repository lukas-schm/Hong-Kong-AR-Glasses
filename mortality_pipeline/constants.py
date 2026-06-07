"""
Single source of truth for the holistic intervention→mortality pipeline.

All paths are reused from ``antibiotic_pipeline.constants`` so the two pipelines
share one data root. The cohort is built from the bundled MIMIC-IV DuckDB, which
exposes the ``mimiciv_hosp``, ``mimiciv_icu`` and ``mimiciv_derived`` schemas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from antibiotic_pipeline.constants import (  # reuse the shared data root
    DIR2DATA,
    DIR2RESULTS,
    RANDOM_STATE,
)

# ── Storage ────────────────────────────────────────────────────────────────
DUCKDB_PATH = DIR2DATA / "mimic_derived.duckdb"
DIR2COHORT_MORTALITY = DIR2DATA / "cohort" / "intervention_mortality"
DIR2RESULTS_MORTALITY = DIR2RESULTS / "intervention_mortality"
COHORT_PARQUET = DIR2COHORT_MORTALITY / "icu_intervention_cohort.parquet"

MIN_AGE = 18
MIN_PS_SCORE = 0.02          # propensity clip for overlap / weight stability
N_CROSSFIT_FOLDS = 5
ALPHA = 0.05                 # 95% confidence intervals


# ── Outcomes ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Outcome:
    key: str
    label: str
    horizon_days: Optional[int]   # None = in-hospital (event-based, no fixed horizon)
    plain: str


MORTALITY_OUTCOMES: List[Outcome] = [
    Outcome("mortality_in_hospital", "In-hospital mortality", None,
            "died before leaving hospital"),
    Outcome("mortality_28d", "28-day mortality", 28,
            "died within 28 days of ICU admission"),
    Outcome("mortality_90d", "90-day mortality", 90,
            "died within 90 days of ICU admission"),
]
PRIMARY_OUTCOME = "mortality_in_hospital"


# ── Confounders (baseline, first 24 h of the ICU stay) ──────────────────────
@dataclass(frozen=True)
class Confounder:
    key: str
    group: str
    label: str
    kind: str = "continuous"   # continuous | binary


CONFOUNDERS: List[Confounder] = [
    # demographics
    Confounder("admission_age", "demographics", "Age"),
    Confounder("female", "demographics", "Female", "binary"),
    Confounder("emergency_admission", "demographics", "Emergency admission", "binary"),
    # illness severity (composite scores, first 24 h)
    Confounder("sofa", "severity", "SOFA score"),
    Confounder("sapsii", "severity", "SAPS-II score"),
    Confounder("oasis", "severity", "OASIS score"),
    Confounder("apsiii", "severity", "APACHE-III score"),
    # comorbidity burden
    Confounder("charlson_comorbidity_index", "comorbidity", "Charlson index"),
    # first-day vital signs
    Confounder("heart_rate_mean", "vitals", "Heart rate (mean)"),
    Confounder("mbp_mean", "vitals", "Mean arterial pressure"),
    Confounder("resp_rate_mean", "vitals", "Respiratory rate"),
    Confounder("temperature_mean", "vitals", "Temperature"),
    Confounder("spo2_mean", "vitals", "SpO2"),
    # first-day laboratory values
    Confounder("lactate_max", "labs", "Lactate (max)"),
    Confounder("creatinine_max", "labs", "Creatinine (max)"),
    Confounder("bun_max", "labs", "Blood urea nitrogen (max)"),
    Confounder("wbc_max", "labs", "White cell count (max)"),
    Confounder("platelets_min", "labs", "Platelets (min)"),
    Confounder("bilirubin_total_max", "labs", "Bilirubin (max)"),
    Confounder("hemoglobin_min", "labs", "Haemoglobin (min)"),
    Confounder("inr_max", "labs", "INR (max)"),
    Confounder("sodium_max", "labs", "Sodium (max)"),
    Confounder("potassium_max", "labs", "Potassium (max)"),
    Confounder("glucose_max", "labs", "Glucose (max)"),
    Confounder("pao2fio2ratio_min", "labs", "PaO2/FiO2 ratio (min)"),
    Confounder("ph_min", "labs", "Arterial pH (min)"),
]

CONFOUNDER_KEYS: List[str] = [c.key for c in CONFOUNDERS]
NUMERIC_CONFOUNDERS: List[str] = [c.key for c in CONFOUNDERS if c.kind == "continuous"]
BINARY_CONFOUNDERS: List[str] = [c.key for c in CONFOUNDERS if c.kind == "binary"]


# ── Intervention panel (the "different interventions" to compare) ───────────
@dataclass(frozen=True)
class Intervention:
    key: str                      # cohort column name (binary 0/1)
    label: str                    # short clinical label
    plain: str                    # plain-language description for HUD / monitor
    decision: str                 # the clinical decision this proxies
    caveat: str = ""              # known confounding-by-indication warning


INTERVENTIONS: List[Intervention] = [
    Intervention(
        key="intv_mechanical_ventilation",
        label="Invasive mechanical ventilation",
        plain="putting the patient on a breathing machine",
        decision="intubate & ventilate vs manage without invasive ventilation",
        caveat="strong confounding by indication — ventilated patients are far sicker",
    ),
    Intervention(
        key="intv_vasopressors",
        label="Vasopressors",
        plain="giving blood-pressure-supporting drugs",
        decision="start vasopressors vs fluids/observation for low blood pressure",
        caveat="markers of shock severity drive both treatment and death",
    ),
    Intervention(
        key="intv_rrt",
        label="Renal-replacement therapy",
        plain="starting dialysis for the kidneys",
        decision="initiate dialysis vs continue medical management of kidney failure",
        caveat="reserved for the most severe acute kidney injury",
    ),
    Intervention(
        key="intv_corticosteroids",
        label="Systemic corticosteroids",
        plain="giving steroid medication",
        decision="add corticosteroids vs standard care",
        caveat="prescribed for refractory shock and specific indications",
    ),
    Intervention(
        key="intv_antibiotics",
        label="Antibiotics",
        plain="giving antibiotics",
        decision="treat with antibiotics vs withhold",
        caveat="given to patients with (suspected) infection",
    ),
]
INTERVENTION_KEYS: List[str] = [i.key for i in INTERVENTIONS]


# ════════════════════════════════════════════════════════════════════════════
# TARGET-TRIAL DESIGN (P1+P2)  — pre-treatment baselines, equipoise, trajectory
# ════════════════════════════════════════════════════════════════════════════
DIR2TRIALS = DIR2DATA / "cohort" / "intervention_trials"
DIR2RESULTS_TRIALS = DIR2RESULTS / "intervention_trials"

# Confounders are aggregated over [icu_intime, icu_intime + BASELINE_WINDOW_HOURS]
# — a short *pre-exposure* window. Patients first treated inside this window are
# "prevalent users" and excluded, so the adjustment set is strictly baseline.
BASELINE_WINDOW_HOURS = 6

# Weekly grid (days) for the counterfactual survival trajectory.
WEEKLY_GRID_DAYS = [7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84]
TRAJECTORY_MAX_DAY = 90      # follow-up coverage is ~100% to ≥1y; 90d is safe


@dataclass(frozen=True)
class TrialConfig:
    """Per-intervention target-trial emulation parameters."""
    key: str                 # matches an Intervention.key
    start_source: str        # which exposure-onset extractor to use (see trials.py)
    grace_hours: int         # exposure must initiate within (baseline, grace] of t0
    equipoise: str           # equipoise sub-cohort name (see equipoise.py)
    exclude: str = ""        # extra exclusion rule key (e.g. 'esrd')
    rct_prior: str = ""      # external RCT context for the credibility/benchmark layer


TRIALS: List[TrialConfig] = [
    TrialConfig("intv_vasopressors", "vasoactive", grace_hours=24, equipoise="shock",
                rct_prior="No RCT of pressors-vs-none; vasopressin add-on neutral (VASST/VANISH)."),
    TrialConfig("intv_mechanical_ventilation", "invasive_vent", grace_hours=24, equipoise="resp_failure",
                rct_prior="No ethical RCT of ventilation-vs-none; extreme confounding by indication."),
    TrialConfig("intv_rrt", "rrt", grace_hours=72, equipoise="aki_23", exclude="esrd",
                rct_prior="Early-vs-late RRT neutral (AKIKI, IDEAL-ICU, STARRT-AKI); ELAIN single-centre benefit."),
    TrialConfig("intv_corticosteroids", "steroid", grace_hours=48, equipoise="septic_shock",
                rct_prior="Septic shock: ADRENAL neutral on mortality, APROCCHSS reduced 90d mortality."),
    TrialConfig("intv_antibiotics", "antibiotic", grace_hours=24, equipoise="suspected_infection",
                rct_prior="No RCT of abx-vs-none in infection; observational early-abx benefit (Surviving Sepsis)."),
]
TRIAL_BY_KEY = {t.key: t for t in TRIALS}


# ── Treatment-agnostic RAW pre-treatment confounders ────────────────────────
# Deliberately EXCLUDES SOFA/OASIS/APACHE composites, which embed organ-support
# (SOFA-cardiovascular = vasopressor dose; OASIS-mechvent = ventilation). These
# are raw physiology aggregated in the baseline window, plus fixed covariates.
@dataclass(frozen=True)
class RawConfounder:
    key: str
    group: str
    label: str
    agg: str            # 'min' | 'max' | 'mean' over the baseline window
    source: str         # derived table name ('' = already on the base row)
    column: str = ""    # source column (defaults to a sensible name)
    kind: str = "continuous"


RAW_CONFOUNDERS: List[RawConfounder] = [
    RawConfounder("admission_age", "demographics", "Age", "", "", kind="continuous"),
    RawConfounder("female", "demographics", "Female", "", "", kind="binary"),
    RawConfounder("emergency_admission", "demographics", "Emergency admission", "", "", kind="binary"),
    RawConfounder("charlson_comorbidity_index", "comorbidity", "Charlson index", "", ""),
    RawConfounder("gcs_min", "neuro", "GCS (min)", "min", "gcs", "gcs"),
    # vitals (mimiciv_derived.vitalsign)
    RawConfounder("heart_rate_max", "vitals", "Heart rate (max)", "max", "vitalsign", "heart_rate"),
    RawConfounder("mbp_min", "vitals", "Mean arterial pressure (min)", "min", "vitalsign", "mbp"),
    RawConfounder("sbp_min", "vitals", "Systolic BP (min)", "min", "vitalsign", "sbp"),
    RawConfounder("resp_rate_max", "vitals", "Respiratory rate (max)", "max", "vitalsign", "resp_rate"),
    RawConfounder("temperature_min", "vitals", "Temperature (min)", "min", "vitalsign", "temperature"),
    RawConfounder("spo2_min", "vitals", "SpO2 (min)", "min", "vitalsign", "spo2"),
    # blood gas (mimiciv_derived.bg)
    RawConfounder("lactate_max", "labs", "Lactate (max)", "max", "bg", "lactate"),
    RawConfounder("ph_min", "labs", "Arterial pH (min)", "min", "bg", "ph"),
    RawConfounder("pao2fio2_min", "labs", "PaO2/FiO2 (min)", "min", "bg", "pao2fio2ratio"),
    # chemistry
    RawConfounder("creatinine_max", "labs", "Creatinine (max)", "max", "chemistry", "creatinine"),
    RawConfounder("bun_max", "labs", "BUN (max)", "max", "chemistry", "bun"),
    RawConfounder("sodium_min", "labs", "Sodium (min)", "min", "chemistry", "sodium"),
    RawConfounder("potassium_max", "labs", "Potassium (max)", "max", "chemistry", "potassium"),
    RawConfounder("bicarbonate_min", "labs", "Bicarbonate (min)", "min", "chemistry", "bicarbonate"),
    RawConfounder("aniongap_max", "labs", "Anion gap (max)", "max", "chemistry", "aniongap"),
    RawConfounder("glucose_max", "labs", "Glucose (max)", "max", "chemistry", "glucose"),
    # CBC
    RawConfounder("wbc_max", "labs", "White cell count (max)", "max", "complete_blood_count", "wbc"),
    RawConfounder("platelet_min", "labs", "Platelets (min)", "min", "complete_blood_count", "platelet"),
    RawConfounder("hemoglobin_min", "labs", "Haemoglobin (min)", "min", "complete_blood_count", "hemoglobin"),
    # coagulation / liver
    RawConfounder("inr_max", "labs", "INR (max)", "max", "coagulation", "inr"),
    RawConfounder("bilirubin_max", "labs", "Bilirubin (max)", "max", "enzyme", "bilirubin_total"),
]
RAW_CONFOUNDER_KEYS: List[str] = [c.key for c in RAW_CONFOUNDERS]


# ── P3: stronger adjustment — goals-of-care, service, informative missingness ─
# These attack the dominant *unmeasured* ICU mortality confounders (code status,
# surgical vs medical), plus the fact-of-measurement (sicker patients get the
# lactate/ABG drawn). All are baseline / pre-treatment.
CODE_STATUS_ITEMID = 223758
CODE_STATUS_LIMITED_VALUES = (
    "DNR / DNI", "DNR (do not resuscitate)", "DNI (do not intubate)", "Comfort measures only",
)
SURGICAL_SERVICES = (
    "SURG", "CSURG", "NSURG", "TSURG", "VSURG", "PSURG", "ORTHO", "TRAUM", "GU", "ENT", "EYE", "DENT",
)
ELECTIVE_ADMISSION_TYPES = ("ELECTIVE", "SURGICAL SAME DAY ADMISSION")

P3_CONFOUNDERS: List[RawConfounder] = [
    RawConfounder("code_status_limited", "goals_of_care", "Code-status limitation (DNR/DNI/CMO)", "", "", kind="binary"),
    RawConfounder("surgical_admission", "service", "Surgical service", "", "", kind="binary"),
    RawConfounder("elective_admission", "service", "Elective admission", "", "", kind="binary"),
    RawConfounder("lactate_measured", "missingness", "Lactate measured (baseline)", "", "", kind="binary"),
    RawConfounder("abg_measured", "missingness", "Blood gas measured (baseline)", "", "", kind="binary"),
    RawConfounder("inr_measured", "missingness", "INR measured (baseline)", "", "", kind="binary"),
    RawConfounder("bilirubin_measured", "missingness", "Bilirubin measured (baseline)", "", "", kind="binary"),
]
P3_CONFOUNDER_KEYS: List[str] = [c.key for c in P3_CONFOUNDERS]

# Full adjustment set used by the target-trial estimators (P1 raw + P3 additions).
TRIAL_CONFOUNDERS: List[str] = RAW_CONFOUNDER_KEYS + P3_CONFOUNDER_KEYS


# ── Estimands ───────────────────────────────────────────────────────────────
ESTIMAND_ATE = "ATE"     # whole (sub)cohort
ESTIMAND_ATT = "ATT"     # effect on the treated
ESTIMAND_ATO = "ATO"     # overlap-weighted (clinical equipoise) — most stable
IPTW_TRUNC = 0.01        # truncate stabilised IPTW weights at the 1st/99th pctile


# ── Estimator labels (for the scoreboard) ──────────────────────────────────
METHOD_UNADJUSTED = "unadjusted"
METHOD_IPTW = "iptw"
METHOD_AIPW = "aipw"            # doubly-robust ATE, the headline causal estimate
METHOD_ATT = "att"             # doubly-robust effect on the treated
METHOD_ATO = "ato"            # overlap-weighted (equipoise) estimand
METHOD_TMLE = "tmle"          # targeted MLE — bounded, efficient doubly-robust (P5)
METHODS = [METHOD_UNADJUSTED, METHOD_IPTW, METHOD_AIPW, METHOD_ATT, METHOD_ATO]

__all__ = [
    "DUCKDB_PATH", "COHORT_PARQUET", "DIR2COHORT_MORTALITY", "DIR2RESULTS_MORTALITY",
    "MIN_AGE", "MIN_PS_SCORE", "N_CROSSFIT_FOLDS", "ALPHA", "RANDOM_STATE",
    "Outcome", "MORTALITY_OUTCOMES", "PRIMARY_OUTCOME",
    "Confounder", "CONFOUNDERS", "CONFOUNDER_KEYS", "NUMERIC_CONFOUNDERS", "BINARY_CONFOUNDERS",
    "Intervention", "INTERVENTIONS", "INTERVENTION_KEYS",
    "METHOD_UNADJUSTED", "METHOD_IPTW", "METHOD_AIPW", "METHODS",
]
