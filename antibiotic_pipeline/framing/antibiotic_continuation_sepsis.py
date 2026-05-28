"""
PICO framing for the antibiotic continuation decision in suspected sepsis.

Clinical question
-----------------
After 48–72 hours of broad-spectrum antibiotics in suspected sepsis, should the
regimen be:
  0 – continued (same or escalated),
  1 – de-escalated (narrowed spectrum), or
  2 – stopped (all antibiotics ceased)?

Target trial emulation
----------------------
  Population : ICU patients ≥18y, sepsis-3, on broad-spectrum antibiotics,
               who survive to 72 h after antibiotic initiation.
  Time zero  : 72 h after first broad-spectrum antibiotic (the "decision point").
  Treatment  : antibiotic change in the 12 h window centred on time zero.
  Outcomes   : VFD-28, VaPFD-28, ICU LOS, AKI worsening, secondary infection,
               28-day mortality.
  Follow-up  : 28 days from time zero.

Key methodological safeguards
------------------------------
- Immortal time bias: cohort restricted to patients who survive to time zero.
- Time-varying confounding: confounders are measured *at* time zero (72 h snapshot).
- Dynamic treatment regimes: single decision point simplification (72 h).
"""

import pickle
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import polars as pl
from loguru import logger
from sklearn.utils import Bunch

from antibiotic_pipeline.constants import (
    COLNAME_AKI_WORSENING,
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_INCLUSION_START,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    COLNAME_MORTALITY_90D,
    COLNAME_PATIENT_ID,
    COLNAME_SECONDARY_INFECTION,
    COLNAME_VFD28,
    COLNAME_VAPFD28,
    COLNAME_ICU_LOS,
    DIR2COHORT,
    DIR2DERIVED,
    DIR2RAW,
    FILENAME_INCLUSION_CRITERIA,
    FILENAME_TARGET_POPULATION,
    TREATMENT_ARM_CONTINUE,
    TREATMENT_ARM_DEESCALATE,
    TREATMENT_ARM_STOP,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

# ── Cohort configuration ────────────────────────────────────────────────────

DECISION_WINDOW_HOURS = 72
TREATMENT_CLASSIFY_WINDOW_HOURS = CAUSAL_GRAPH.treatment.classification_window_hours

COHORT_CONFIG_ANTIBIOTIC_CONTINUATION = Bunch(
    **{
        "min_age": 18,
        "decision_window_hours": DECISION_WINDOW_HOURS,
        "treatment_classify_window_hours": TREATMENT_CLASSIFY_WINDOW_HOURS,
        "cohort_name": "antibiotic_continuation_sepsis",
        "save_cohort": True,
        # WS2: target-trial protocol controls.
        # Grace period after T0 within which deviations do not change the
        # initial arm classification. 24h is the default; 0h is a strict
        # sensitivity.
        "grace_period_hours": 24,
        # Sustained-treatment sensitivity: a stricter classification that
        # requires the treatment state to persist at least this many hours
        # after T0. None disables (default analysis).
        "sustained_hours": None,
        # Infection-certainty eligibility (WS2): require at least one of
        # positive culture before T0, documented infection source, or
        # qSOFA >= 2 at T0. Off by default for backward compatibility; the
        # sensitivity analysis turns this on.
        "require_infection_certainty": False,
        # T0 anchor choices. The default is hours after first broad-spectrum
        # administration. The "culture_finalisation" anchor uses the time
        # of first finalised culture (with a 72h fallback for cultures that
        # do not result). See _resolve_T0_anchor in this module.
        "t0_anchor": "first_broad_spectrum",  # or {48, 96, "culture_finalisation"}
    }
)

# ── Drug lists from causal_graph.yaml ───────────────────────────────────────

_drug_lists = CAUSAL_GRAPH.treatment.drug_lists

CARBAPENEM_DRUGS: List[str] = _drug_lists.get("carbapenems", [])
GLYCOPEPTIDE_DRUGS: List[str] = _drug_lists.get("glycopeptides", [])
BETALACTAM_BROAD_DRUGS: List[str] = _drug_lists.get("broad_betalactams", [])
AMINOGLYCOSIDE_DRUGS: List[str] = _drug_lists.get("aminoglycosides", [])

BROAD_SPECTRUM_DRUGS: List[str] = CAUSAL_GRAPH.treatment.all_broad_spectrum_drugs
NARROW_SPECTRUM_DRUGS: List[str] = CAUSAL_GRAPH.treatment.all_narrow_spectrum_drugs


# ── Main cohort building function ───────────────────────────────────────────

def get_population(
    cohort_config: Bunch = COHORT_CONFIG_ANTIBIOTIC_CONTINUATION,
) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """Build target trial population for antibiotic continuation decision.

    Returns
    -------
    target_trial_population : pd.DataFrame
        One row per ICU stay with treatment arm, time zero, and all outcomes.
    inclusion_ids : dict
        Step-by-step inclusion counts for attrition reporting.
    """
    cohort_folder = _create_cohort_folder(cohort_config)

    # ── Step 1: Base population (sepsis-3, age ≥18, ICU ≥72 h) ─────────────
    logger.info("Step 1: Building base population")
    patients = pl.scan_parquet(DIR2RAW / "patients.parquet").select(
        [COLNAME_PATIENT_ID, "anchor_age", "anchor_year", "gender", "dod"]
    )
    admissions = pl.scan_parquet(DIR2RAW / "admissions.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "admittime", "dischtime",
         "admission_type", "insurance"]
    )
    icu_stays = pl.scan_parquet(DIR2RAW / "icustays.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID,
         "intime", "outtime", "los"]
    )

    # Sepsis-3 flag (table has subject_id + stay_id only, no hadm_id)
    sepsis3 = pl.scan_parquet(DIR2DERIVED / "sepsis3.parquet").filter(
        pl.col("sepsis3") == True
    ).select([COLNAME_PATIENT_ID, COLNAME_ICUSTAY_ID])

    base_pop = (
        icu_stays.join(patients, on=COLNAME_PATIENT_ID, how="inner")
        .join(admissions.select([COLNAME_PATIENT_ID, COLNAME_HADM_ID,
                                  "admittime", "admission_type", "insurance"]),
              on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")
        .join(sepsis3, on=[COLNAME_PATIENT_ID, COLNAME_ICUSTAY_ID], how="inner")
        .filter(pl.col("anchor_age") >= cohort_config.min_age)
        .filter(pl.col("los") >= (cohort_config.decision_window_hours / 24))
        .collect()
        .to_pandas()
    )
    inclusion_ids = {"Sepsis-3, age ≥18, ICU LOS ≥72h": base_pop[COLNAME_PATIENT_ID].unique().tolist()}
    logger.info(f"  Base population: {len(base_pop)} stays")

    # ── Step 2: First broad-spectrum antibiotic = inclusion event ────────────
    logger.info("Step 2: Identifying first broad-spectrum antibiotic")
    # Use prescriptions (raw) which has subject_id, hadm_id, drug, starttime, stoptime
    prescriptions = pl.scan_parquet(DIR2RAW / "prescriptions.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "starttime", "stoptime", "drug"]
    )
    broad_pattern = "|".join(BROAD_SPECTRUM_DRUGS)
    first_broad_abx = (
        prescriptions.filter(pl.col("drug").str.to_lowercase().str.contains(broad_pattern))
        .sort([COLNAME_PATIENT_ID, "starttime"])
        .group_by([COLNAME_PATIENT_ID, COLNAME_HADM_ID])
        .agg(pl.first("starttime").alias(COLNAME_INCLUSION_START))
        .collect()
        .to_pandas()
    )
    base_pop = base_pop.merge(first_broad_abx, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")

    # Inclusion start must be within first 48h of ICU admission
    base_pop[COLNAME_INCLUSION_START] = pd.to_datetime(base_pop[COLNAME_INCLUSION_START])
    base_pop["intime"] = pd.to_datetime(base_pop["intime"])
    base_pop["delta_abx_icu"] = (
        base_pop[COLNAME_INCLUSION_START] - base_pop["intime"]
    ).dt.total_seconds() / 3600
    base_pop = base_pop.loc[
        (base_pop["delta_abx_icu"] >= 0) & (base_pop["delta_abx_icu"] <= 48)
    ]
    inclusion_ids["First broad-spectrum abx within 48h of ICU admission"] = (
        base_pop[COLNAME_PATIENT_ID].unique().tolist()
    )
    logger.info(f"  After broad-spectrum abx filter: {len(base_pop)} stays")

    # ── Step 3: Time zero = inclusion_start + 72h (the decision point) ──────
    logger.info("Step 3: Computing time zero (72 h)")
    base_pop[COLNAME_DECISION_TIME] = base_pop[COLNAME_INCLUSION_START] + pd.Timedelta(
        hours=cohort_config.decision_window_hours
    )
    base_pop["outtime"] = pd.to_datetime(base_pop["outtime"])

    # Immortal time bias safeguard: patient must still be in ICU at time zero
    base_pop = base_pop.loc[base_pop[COLNAME_DECISION_TIME] < base_pop["outtime"]]
    inclusion_ids["Alive in ICU at 72h (immortal time removed)"] = (
        base_pop[COLNAME_PATIENT_ID].unique().tolist()
    )
    logger.info(f"  After immortal time filter: {len(base_pop)} stays")

    # ── Step 3b: One-stay-per-subject (F4) ──────────────────────────────────
    # A subject_id with multiple qualifying ICU stays would otherwise contribute
    # correlated observations and could appear across treatment arms — SUTVA
    # violation. Keep the earliest qualifying stay only.
    n_before_dedup = len(base_pop)
    base_pop = (
        base_pop.sort_values([COLNAME_PATIENT_ID, COLNAME_INCLUSION_START])
        .drop_duplicates(subset=[COLNAME_PATIENT_ID], keep="first")
        .reset_index(drop=True)
    )
    inclusion_ids["One stay per subject (earliest)"] = (
        base_pop[COLNAME_PATIENT_ID].unique().tolist()
    )
    logger.info(
        f"  After one-stay-per-subject dedup: {len(base_pop)} stays "
        f"({n_before_dedup - len(base_pop)} dropped)"
    )

    # ── Step 3c: Exclude patients in Comfort-Measures-Only (CMO) at T0 (WS4) ──
    # Reviewer concern #1/#2: patients in CMO at the decision point are not
    # eligible for the treatment policy under study — antibiotics are
    # discontinued as part of goals-of-care transition, not because of
    # bacterial-disease reasoning. Adjusting for code status is not enough
    # here; we exclude them from the analytic cohort and document the count.
    from antibiotic_pipeline.variables.clinical_intent import (
        get_clinical_intent_confounders,
    )
    intent_now = get_clinical_intent_confounders(base_pop)
    cmo_stays = set(intent_now.loc[intent_now["cmo_at_decision"] == 1, COLNAME_ICUSTAY_ID])
    n_before_cmo = len(base_pop)
    base_pop = base_pop[~base_pop[COLNAME_ICUSTAY_ID].isin(cmo_stays)].reset_index(drop=True)
    inclusion_ids["Not in comfort-measures-only at T0"] = (
        base_pop[COLNAME_PATIENT_ID].unique().tolist()
    )
    logger.info(
        f"  After CMO-at-T0 exclusion: {len(base_pop)} stays "
        f"({n_before_cmo - len(base_pop)} CMO-at-T0 stays dropped)"
    )

    # ── Step 4: Classify treatment arm at time zero ──────────────────────────
    # F13: prefer ICU `inputevents` (actual administrations) over
    # `prescriptions` (orders). Patients with no matching IV record fall
    # back to the prescriptions-based classifier so the cohort doesn't
    # shrink.
    logger.info("Step 4: Classifying treatment arms (inputevents primary, prescriptions fallback)")
    from antibiotic_pipeline.framing.treatment_classification import classify_from_inputevents
    primary = classify_from_inputevents(base_pop, cohort_config)
    n_admin = (primary[COLNAME_INTERVENTION_STATUS] != TREATMENT_ARM_STOP).sum()
    logger.info(
        f"  Inputevents-classified non-stop: {n_admin}/{len(primary)} stays "
        f"({100*n_admin/len(primary):.1f}%)"
    )

    if n_admin / len(primary) < 0.30:
        logger.warning(
            "  Inputevents coverage is low (<30%); falling back entirely to prescriptions-based"
            " classification. Set MIMIC-IV ICU inputevents check."
        )
        base_pop = _classify_treatment_arm(base_pop, cohort_config)
    else:
        # Use inputevents as primary; for stays that classify as "stop" with
        # no inputevents records, check prescriptions as a safety net so a
        # missed ICU record doesn't masquerade as cessation.
        base_pop_pres = _classify_treatment_arm(base_pop.copy(), cohort_config)
        # If inputevents says STOP but prescriptions says CONTINUE → trust
        # prescriptions (avoids false-cease bias).
        mask_disagree_continue = (
            (primary[COLNAME_INTERVENTION_STATUS] == TREATMENT_ARM_STOP)
            & (base_pop_pres[COLNAME_INTERVENTION_STATUS] == TREATMENT_ARM_CONTINUE)
        )
        mask_disagree_deesc = (
            (primary[COLNAME_INTERVENTION_STATUS] == TREATMENT_ARM_STOP)
            & (base_pop_pres[COLNAME_INTERVENTION_STATUS] == TREATMENT_ARM_DEESCALATE)
        )
        primary.loc[mask_disagree_continue, COLNAME_INTERVENTION_STATUS] = TREATMENT_ARM_CONTINUE
        primary.loc[mask_disagree_deesc, COLNAME_INTERVENTION_STATUS] = TREATMENT_ARM_DEESCALATE
        logger.info(
            f"  Reclassified {int(mask_disagree_continue.sum())} STOP→CONTINUE "
            f"and {int(mask_disagree_deesc.sum())} STOP→DEESCALATE based on prescriptions"
        )
        base_pop = primary
    inclusion_ids["Treatment arm classified"] = (
        base_pop[COLNAME_PATIENT_ID].unique().tolist()
    )
    for arm, label in {0: "continue", 1: "de-escalate", 2: "stop"}.items():
        n = (base_pop[COLNAME_INTERVENTION_STATUS] == arm).sum()
        logger.info(f"  Arm {arm} ({label}): {n} stays ({100*n/len(base_pop):.1f}%)")

    # ── Step 5: Compute outcomes ─────────────────────────────────────────────
    logger.info("Step 5: Computing outcomes")
    base_pop = _compute_outcomes(base_pop, cohort_config)

    # F14: fill VFD/VaPFD/AKI-worsening/secondary-infection inside framing so
    # downstream sensitivity grid does not silently drop the outcome.
    from antibiotic_pipeline.framing.outcomes_filling import fill_all
    base_pop = fill_all(base_pop)

    for col in [COLNAME_MORTALITY_28D, COLNAME_SECONDARY_INFECTION, COLNAME_AKI_WORSENING]:
        prev = base_pop[col].mean()
        logger.info(f"  {col}: {100*prev:.1f}%")
    logger.info(f"  {COLNAME_VFD28} mean: {base_pop[COLNAME_VFD28].mean():.1f} days")

    # ── Step 6: Save ─────────────────────────────────────────────────────────
    if cohort_config.save_cohort:
        base_pop.to_parquet(cohort_folder / FILENAME_TARGET_POPULATION)
        logger.info(f"Saved cohort at {cohort_folder / FILENAME_TARGET_POPULATION}")
        pickle.dump(inclusion_ids, open(str(cohort_folder / FILENAME_INCLUSION_CRITERIA), "wb"))

    return base_pop, inclusion_ids


# ── Treatment arm classification ─────────────────────────────────────────────

def _classify_treatment_arm(
    population: pd.DataFrame,
    cohort_config: Bunch,
) -> pd.DataFrame:
    """Classify each stay into continue / de-escalate / stop at time zero.

    Classification window: [decision_time - 12h, decision_time + 12h].

    Logic:
      stop        : no antibiotic orders covering the window close
      de-escalate : only narrow-spectrum agents in window (no broad)
      continue    : broad-spectrum agent still active in window
    """
    window_h = cohort_config.treatment_classify_window_hours

    decision_times = pl.from_pandas(
        population[[COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_DECISION_TIME]]
    ).lazy()

    prescriptions = pl.scan_parquet(DIR2RAW / "prescriptions.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "starttime", "stoptime", "drug"]
    )

    all_abx_pattern = "|".join(BROAD_SPECTRUM_DRUGS + NARROW_SPECTRUM_DRUGS)
    abx_in_window = (
        prescriptions.filter(
            pl.col("drug").str.to_lowercase().str.contains(all_abx_pattern)
        )
        .join(decision_times, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")
        .filter(
            (pl.col("starttime") <= pl.col(COLNAME_DECISION_TIME) + pl.duration(hours=window_h))
            & (pl.col("stoptime") >= pl.col(COLNAME_DECISION_TIME) - pl.duration(hours=window_h))
        )
        .with_columns(
            pl.col("drug").str.to_lowercase().alias("drug_lower")
        )
        .collect()
        .to_pandas()
    )

    broad_pattern = "|".join(BROAD_SPECTRUM_DRUGS)
    narrow_pattern = "|".join(NARROW_SPECTRUM_DRUGS)

    has_broad = (
        abx_in_window[abx_in_window["drug_lower"].str.contains(broad_pattern)]
        .groupby([COLNAME_PATIENT_ID, COLNAME_HADM_ID])
        .size()
        .reset_index(name="n_broad")
    )
    has_narrow = (
        abx_in_window[abx_in_window["drug_lower"].str.contains(narrow_pattern)]
        .groupby([COLNAME_PATIENT_ID, COLNAME_HADM_ID])
        .size()
        .reset_index(name="n_narrow")
    )

    population = population.merge(has_broad, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="left")
    population = population.merge(has_narrow, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="left")
    population["n_broad"] = population["n_broad"].fillna(0)
    population["n_narrow"] = population["n_narrow"].fillna(0)

    def _arm(row):
        if row["n_broad"] > 0:
            return TREATMENT_ARM_CONTINUE
        elif row["n_narrow"] > 0:
            return TREATMENT_ARM_DEESCALATE
        else:
            return TREATMENT_ARM_STOP

    population[COLNAME_INTERVENTION_STATUS] = population.apply(_arm, axis=1)
    population = population.drop(columns=["n_broad", "n_narrow"])
    return population


# ── Outcome computation ──────────────────────────────────────────────────────

def _compute_outcomes(population: pd.DataFrame, cohort_config: Bunch) -> pd.DataFrame:
    """Compute all outcomes measured from time zero (decision point)."""
    pop = population.copy()
    pop[COLNAME_DECISION_TIME] = pd.to_datetime(pop[COLNAME_DECISION_TIME])

    # 28-day and 90-day mortality (from time zero)
    pop["dod"] = pd.to_datetime(pop["dod"], errors="coerce")
    mask_dod = pop["dod"].notnull()
    days_to_death = (pop["dod"] - pop[COLNAME_DECISION_TIME]).dt.days
    pop[COLNAME_MORTALITY_28D] = (mask_dod & (days_to_death <= 28)).astype(int)
    pop[COLNAME_MORTALITY_90D] = (mask_dod & (days_to_death <= 90)).astype(int)

    # WS11: multi-horizon mortality (7d, 14d, 21d) for the trajectory analysis.
    # Computed on the SAME cohort as mortality_28d so the four horizons are
    # like-for-like comparable; the F16 censoring below then NaN's all four
    # horizons together for patients without full 28d follow-up.
    pop["mortality_7d"]  = (mask_dod & (days_to_death <= 7)).astype(int)
    pop["mortality_14d"] = (mask_dod & (days_to_death <= 14)).astype(int)
    pop["mortality_21d"] = (mask_dod & (days_to_death <= 21)).astype(int)

    # F16: censor 28-day mortality for patients whose follow-up window extends
    # past MIMIC's death-registry coverage. Otherwise a patient discharged
    # within 28 days of the cutoff is silently coded "alive" → survivorship
    # bias. dod_max (from the global patients table) is the effective cutoff.
    try:
        all_patients = pl.scan_parquet(DIR2RAW / "patients.parquet").select(["dod"]).collect()
        dod_max = pd.to_datetime(all_patients.to_pandas()["dod"].max())
        cutoff_28d = dod_max - pd.Timedelta(days=28)
        censor_mask = pop[COLNAME_DECISION_TIME] > cutoff_28d
        n_censored = int(censor_mask.sum())
        pop.loc[censor_mask, COLNAME_MORTALITY_28D] = np.nan
        # WS11 cohort-consistency: NaN ALL horizons whenever 28d is NaN, so
        # all four horizons share the same denominator (avoids the "earlier
        # horizons get a bigger N" trap raised in our WS11 review).
        for col in ("mortality_7d", "mortality_14d", "mortality_21d"):
            pop.loc[censor_mask, col] = np.nan
        cutoff_90d = dod_max - pd.Timedelta(days=90)
        censor_90 = pop[COLNAME_DECISION_TIME] > cutoff_90d
        pop.loc[censor_90, COLNAME_MORTALITY_90D] = np.nan
        logger.info(
            f"  F16 mortality censoring (dod cutoff={dod_max.date()}): "
            f"{n_censored} stays censored at 28d, {int(censor_90.sum())} at 90d"
        )
    except Exception as exc:
        logger.warning(f"F16 mortality censoring skipped: {exc}")

    # ICU LOS from time zero (capped at 28 days; 0 if died in ICU)
    pop["outtime"] = pd.to_datetime(pop["outtime"])
    pop[COLNAME_ICU_LOS] = (
        (pop["outtime"] - pop[COLNAME_DECISION_TIME]).dt.total_seconds() / 86400
    ).clip(upper=28).round(1)

    # Ventilator-free days at 28 (computed in variables/selection.py with chart data)
    # Placeholder: filled downstream after ventilation events are joined
    pop[COLNAME_VFD28] = None
    pop[COLNAME_VAPFD28] = None

    # AKI worsening and secondary infection: filled downstream
    pop[COLNAME_AKI_WORSENING] = None
    pop[COLNAME_SECONDARY_INFECTION] = None

    return pop


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_cohort_folder(cohort_config: Bunch) -> Path:
    folder = DIR2COHORT / cohort_config.cohort_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


if __name__ == "__main__":
    pop, ids = get_population()
    print(pop[[COLNAME_INTERVENTION_STATUS, COLNAME_MORTALITY_28D]].value_counts())
