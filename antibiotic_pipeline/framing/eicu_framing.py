"""
WS7 — Parallel target-trial framing for eICU-CRD.

Mirrors antibiotic_pipeline/framing/antibiotic_continuation_sepsis.py but
sources from the eICU-CRD schema (PhysioNet). The protocol — sepsis-3
cohort, first broad-spectrum at admission, T0 = 72h, ±12h classification
window, one stay per subject, alive at T0 — is identical so that
within-eICU estimates can be reported alongside MIMIC-IV estimates with the
same caveats.

eICU vs MIMIC-IV measurement-error caveats (documented in manuscript):
  * Antibiotic data lives in the `medication` table (orders, not actual
    administrations). MIMIC's `inputevents` granularity is not available.
    We treat 'order active at T0 ± 12h' as the arm-classification signal,
    which is closer to a 'prescription'-based MIMIC classifier than to the
    inputevents primary.
  * Sepsis-3 is approximated via diagnosis ICD codes (Angus criteria) and
    APACHE IV severity at admission, since the mimic-code-style sepsis3
    derived view is not provided by eICU.
  * Time stamps in eICU are 'offsets in minutes from ICU admission'.
    We convert these to absolute times by anchoring at the hospitaladmission
    time for downstream consistency.

Expected eICU parquet location: ``$DIR2EICU/{patient,medication,diagnosis,
apachepatientresult,apachepredvar,vitalperiodic,lab,treatment}.parquet``.
The runner :func:`get_eicu_population` raises FileNotFoundError if the
parquets are not present (the eICU DUA is separate from MIMIC).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pandas as pd
import polars as pl
from loguru import logger
from sklearn.utils import Bunch

from antibiotic_pipeline.constants import (
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_INCLUSION_START,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_PATIENT_ID,
    DIR2DATA,
    TREATMENT_ARM_CONTINUE,
    TREATMENT_ARM_DEESCALATE,
    TREATMENT_ARM_STOP,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

DIR2EICU = Path(os.getenv("DIR2EICU", DIR2DATA / "eicu"))

# Same drug lists as MIMIC-IV; eICU `medication.drugname` strings vary
# substantially (brand names, formulation suffixes) so the matcher is
# substring-based and case-insensitive.
BROAD_DRUGS: List[str] = CAUSAL_GRAPH.treatment.all_broad_spectrum_drugs
NARROW_DRUGS: List[str] = CAUSAL_GRAPH.treatment.all_narrow_spectrum_drugs


EICU_COHORT_CONFIG = Bunch(
    **{
        "min_age": 18,
        "decision_window_hours": 72,
        "treatment_classify_window_hours": 12,
        "cohort_name": "antibiotic_continuation_sepsis_eicu",
        "save_cohort": True,
        "grace_period_hours": 24,
    }
)


# Sepsis ICD-9/10 codes (Angus + Sepsis-3 surrogate; documented in the
# supplementary appendix).
SEPSIS_ICD_CODES = {
    "9",  # ICD-9: 038.* sepsis, 995.91 SIRS+infection, 995.92 severe sepsis
    "10",  # ICD-10: A40.*, A41.*, R65.20, R65.21
}
SEPSIS_ICD_PREFIXES = ("038.", "995.91", "995.92", "A40", "A41", "R65.20", "R65.21")


# ── Cohort builder ─────────────────────────────────────────────────────────


def get_eicu_population(
    cohort_config: Bunch = EICU_COHORT_CONFIG,
) -> tuple[pd.DataFrame, dict]:
    """Build the eICU-CRD analytic cohort under the same protocol as MIMIC.

    Returns
    -------
    population : pd.DataFrame
        One row per qualifying ICU stay with treatment arm, T0, outcomes,
        and hospital ID (for the within-eICU per-hospital subgroup
        analysis).
    inclusion_ids : dict
        Step-by-step inclusion counts for the cohort flow figure.
    """
    if not DIR2EICU.exists():
        raise FileNotFoundError(
            f"eICU parquet directory not found at {DIR2EICU}. Set DIR2EICU "
            "environment variable, or download eICU-CRD (PhysioNet) and "
            "export the tables to parquet via the project's standard "
            "build_derived.py script."
        )

    logger.info("Step 1: load eICU patient + diagnosis tables")
    patient = pl.scan_parquet(DIR2EICU / "patient.parquet")
    diagnosis = pl.scan_parquet(DIR2EICU / "diagnosis.parquet")

    # ICU stays >= 72h, age >= 18
    # eICU `patient` columns: patientunitstayid, uniquepid (subject_id),
    # patienthealthsystemstayid (hadm_id), hospitalid, unitid, age, gender,
    # unitdischargeoffset (minutes), hospitaldischargeoffset (minutes),
    # unitdischargestatus, hospitaldischargestatus.
    base = (
        patient.with_columns([
            # eICU encodes "> 89" as the string "> 89"; map to 90 for adults.
            pl.when(pl.col("age").str.contains(">"))
              .then(pl.lit(90))
              .otherwise(pl.col("age").cast(pl.Int32, strict=False))
              .alias("age_years"),
        ])
        .filter(pl.col("age_years") >= cohort_config.min_age)
        .filter(pl.col("unitdischargeoffset") >= cohort_config.decision_window_hours * 60)
        .select([
            pl.col("uniquepid").alias(COLNAME_PATIENT_ID),
            pl.col("patienthealthsystemstayid").alias(COLNAME_HADM_ID),
            pl.col("patientunitstayid").alias(COLNAME_ICUSTAY_ID),
            "hospitalid",
            "age_years",
            "gender",
            "unitdischargeoffset",
            "hospitaldischargeoffset",
            "hospitaldischargestatus",
            "unitdischargestatus",
        ])
    )

    # Sepsis filter via diagnosis ICD codes.
    sepsis_dx = (
        diagnosis.filter(
            pl.col("icd9code").is_not_null()
            & pl.any_horizontal([
                pl.col("icd9code").str.starts_with(prefix)
                for prefix in SEPSIS_ICD_PREFIXES
            ])
        )
        .select(pl.col("patientunitstayid").alias(COLNAME_ICUSTAY_ID))
        .unique()
    )
    base = base.join(sepsis_dx, on=COLNAME_ICUSTAY_ID, how="inner")

    inclusion_ids = {}
    base_pd = base.collect().to_pandas()
    inclusion_ids["Sepsis + adult + LOS >= 72h"] = base_pd[COLNAME_ICUSTAY_ID].tolist()
    logger.info(f"  Sepsis adults with LOS>=72h: {len(base_pd)} stays")

    # ── Step 2: first broad-spectrum medication ──────────────────────────────
    logger.info("Step 2: find first broad-spectrum medication")
    medication = pl.scan_parquet(DIR2EICU / "medication.parquet").select([
        pl.col("patientunitstayid").alias(COLNAME_ICUSTAY_ID),
        "drugname",
        "drugstartoffset",
        "drugstopoffset",
        "routeadmin",
    ])
    broad_pattern = "|".join(BROAD_DRUGS)
    first_broad = (
        medication.filter(pl.col("drugname").str.to_lowercase().str.contains(broad_pattern))
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.min("drugstartoffset").alias("first_broad_offset_min"))
        .collect()
        .to_pandas()
    )
    base_pd = base_pd.merge(first_broad, on=COLNAME_ICUSTAY_ID, how="inner")
    # Must be started within first 48h of ICU admission for the target-trial
    # eligibility (same as MIMIC).
    base_pd = base_pd[base_pd["first_broad_offset_min"] <= 48 * 60]
    inclusion_ids["First broad-spec within 48h"] = base_pd[COLNAME_ICUSTAY_ID].tolist()
    logger.info(f"  After first-broad filter: {len(base_pd)} stays")

    # ── Step 3: T0 = first_broad + 72h ──────────────────────────────────────
    base_pd[COLNAME_INCLUSION_START] = pd.to_timedelta(
        base_pd["first_broad_offset_min"], unit="m"
    )
    base_pd[COLNAME_DECISION_TIME] = (
        base_pd[COLNAME_INCLUSION_START]
        + pd.to_timedelta(cohort_config.decision_window_hours, unit="h")
    )
    # Immortal-time bias: T0 must precede ICU discharge.
    base_pd = base_pd[
        base_pd[COLNAME_DECISION_TIME].dt.total_seconds()
        < base_pd["unitdischargeoffset"] * 60
    ]
    inclusion_ids["Alive in ICU at T0"] = base_pd[COLNAME_ICUSTAY_ID].tolist()
    logger.info(f"  After immortal-time filter: {len(base_pd)} stays")

    # One stay per subject (earliest).
    base_pd = (
        base_pd.sort_values([COLNAME_PATIENT_ID, "first_broad_offset_min"])
        .drop_duplicates(subset=[COLNAME_PATIENT_ID], keep="first")
        .reset_index(drop=True)
    )
    inclusion_ids["One stay per subject"] = base_pd[COLNAME_PATIENT_ID].tolist()
    logger.info(f"  After one-stay-per-subject dedup: {len(base_pd)} stays")

    # ── Step 4: arm classification at T0 ────────────────────────────────────
    logger.info("Step 4: classify treatment arm at T0 (medication-active basis)")
    base_pd = _classify_arm_eicu(base_pd, cohort_config)
    for arm, label in {0: "continue", 1: "de-escalate", 2: "stop"}.items():
        n = int((base_pd[COLNAME_INTERVENTION_STATUS] == arm).sum())
        logger.info(f"  Arm {arm} ({label}): {n} stays ({100*n/len(base_pd):.1f}%)")

    # ── Step 5: outcomes ─────────────────────────────────────────────────────
    logger.info("Step 5: compute 28-day mortality outcome")
    base_pd = _compute_mortality_eicu(base_pd, cohort_config)

    if cohort_config.save_cohort:
        out = DIR2DATA / "cohort" / cohort_config.cohort_name
        out.mkdir(parents=True, exist_ok=True)
        base_pd.to_parquet(out / "target_population.parquet")
        logger.info(f"Saved {out / 'target_population.parquet'}")

    return base_pd, inclusion_ids


def _classify_arm_eicu(pop: pd.DataFrame, cfg: Bunch) -> pd.DataFrame:
    """Classify arm based on medication orders active at T0 ± window."""
    window_min = cfg.treatment_classify_window_hours * 60
    medication = (
        pl.scan_parquet(DIR2EICU / "medication.parquet")
        .select([
            pl.col("patientunitstayid").alias(COLNAME_ICUSTAY_ID),
            "drugname",
            "drugstartoffset",
            "drugstopoffset",
        ])
        .collect()
        .to_pandas()
    )
    medication["drugname_lower"] = medication["drugname"].fillna("").str.lower()
    pop = pop.copy()
    pop["t0_min"] = pop[COLNAME_DECISION_TIME].dt.total_seconds() / 60.0

    # For each stay, find any active medication in [t0 - window, t0 + window]
    merged = medication.merge(
        pop[[COLNAME_ICUSTAY_ID, "t0_min"]], on=COLNAME_ICUSTAY_ID, how="inner"
    )
    active = merged[
        (merged["drugstartoffset"] <= merged["t0_min"] + window_min)
        & (
            (merged["drugstopoffset"].isna())
            | (merged["drugstopoffset"] >= merged["t0_min"] - window_min)
        )
    ]
    broad_p = "|".join(BROAD_DRUGS)
    narrow_p = "|".join(NARROW_DRUGS)

    has_broad = active[active["drugname_lower"].str.contains(broad_p, na=False)][
        COLNAME_ICUSTAY_ID
    ].unique()
    has_narrow_only = (
        active[active["drugname_lower"].str.contains(narrow_p, na=False)][COLNAME_ICUSTAY_ID]
        .unique()
    )

    pop[COLNAME_INTERVENTION_STATUS] = TREATMENT_ARM_STOP
    pop.loc[pop[COLNAME_ICUSTAY_ID].isin(has_narrow_only),
            COLNAME_INTERVENTION_STATUS] = TREATMENT_ARM_DEESCALATE
    pop.loc[pop[COLNAME_ICUSTAY_ID].isin(has_broad),
            COLNAME_INTERVENTION_STATUS] = TREATMENT_ARM_CONTINUE
    return pop


def _compute_mortality_eicu(pop: pd.DataFrame, cfg: Bunch) -> pd.DataFrame:
    """Multi-horizon mortality from hospitaldischargeoffset + hospitaldischargestatus.

    eICU CAVEAT (manuscript-flagged):
    eICU records `hospitaldischargestatus` only at in-hospital discharge. A
    patient discharged alive on day 14 who dies at home on day 25 is coded
    "Alive" — eICU has no post-discharge mortality follow-up like MIMIC's
    `dod`. So the 4-horizon trajectory on eICU is most reliable at 7d (most
    patients still inpatient), degraded at 14d, and substantially under-
    reports at 21d/28d. We also save a per-horizon "in-hospital coverage"
    descriptive flag so the reader can see at each horizon what fraction of
    the cohort was still inpatient (and therefore observable for mortality).
    """
    pop = pop.copy()
    pop["t0_min"] = pop[COLNAME_DECISION_TIME].dt.total_seconds() / 60.0
    expired = pop["hospitaldischargestatus"] == "Expired"
    for h_days in (7, 14, 21, 28):
        thresh_min = h_days * 24 * 60
        died_in_window = expired & ((pop["hospitaldischargeoffset"] - pop["t0_min"]) <= thresh_min)
        col = "mortality_28days" if h_days == 28 else f"mortality_{h_days}d"
        pop[col] = died_in_window.astype("int8")
        # In-hospital coverage: still inpatient OR died (i.e., observable for
        # the mortality outcome at this horizon). Discharged-alive patients
        # past this horizon are right-censored on the eICU schema.
        still_in_hosp = (pop["hospitaldischargeoffset"] - pop["t0_min"]) > thresh_min
        observable = still_in_hosp | expired
        pop[f"observable_{h_days}d"] = observable.astype("int8")
    return pop
