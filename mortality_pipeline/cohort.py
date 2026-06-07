"""
Cohort builder for the holistic intervention→mortality analysis.

One row per adult **first ICU stay**. Columns:

  * keys / timing          subject_id, hadm_id, stay_id, icu_intime, los_icu …
  * baseline confounders   measured over the first 24 h (severity scores,
                           vitals, labs, comorbidity, demographics)
  * intervention panel     binary 0/1 flags — did the patient receive each major
                           ICU intervention during the stay
  * mortality outcomes     in-hospital, 28-day, 90-day (with right-censoring at
                           the death-registry coverage horizon)

Everything is pulled from the bundled MIMIC-IV DuckDB in a single query; the few
derived quantities (sex, emergency flag, censored mortality) are computed in
pandas afterwards so the logic is auditable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    COHORT_PARQUET,
    CONFOUNDER_KEYS,
    DIR2COHORT_MORTALITY,
    DUCKDB_PATH,
    INTERVENTION_KEYS,
    MIN_AGE,
)

# Systemic corticosteroids — names that are unambiguously systemic; topical /
# ophthalmic / rectal / inhaled formulations are excluded by the NOT-regex.
_STEROID_RX = r"hydrocortisone|methylprednisolone|dexamethasone|prednisone|prednisolone|fludrocortisone"
_STEROID_EXCLUDE_RX = r"cream|ophth|rectal|suppos|oint|otic|nasal|topical|lotion|%"

_COHORT_SQL = f"""
WITH base AS (
    SELECT
        d.subject_id, d.hadm_id, d.stay_id,
        d.gender, d.admission_age, d.race,
        d.icu_intime, d.icu_outtime, d.los_icu, d.los_hospital,
        d.hospital_expire_flag, d.dod,
        a.admission_type
    FROM mimiciv_derived.icustay_detail d
    LEFT JOIN mimiciv_hosp.admissions a USING (hadm_id)
    WHERE d.admission_age >= {MIN_AGE}
      AND d.first_icu_stay = TRUE
),
-- ── intervention exposures (distinct stay_id sets) ───────────────────────────
vent AS (
    SELECT DISTINCT stay_id FROM mimiciv_derived.ventilation
    WHERE ventilation_status IN ('InvasiveVent', 'Tracheostomy')
),
vaso AS (
    SELECT DISTINCT stay_id FROM mimiciv_derived.vasoactive_agent
    WHERE greatest(
        coalesce(norepinephrine, 0), coalesce(epinephrine, 0),
        coalesce(dopamine, 0), coalesce(phenylephrine, 0),
        coalesce(vasopressin, 0)
    ) > 0
),
rrt AS (
    SELECT DISTINCT stay_id FROM mimiciv_derived.rrt WHERE dialysis_active = 1
    UNION
    SELECT DISTINCT stay_id FROM mimiciv_derived.crrt
),
abx AS (
    SELECT DISTINCT stay_id FROM mimiciv_derived.antibiotic WHERE stay_id IS NOT NULL
),
steroid AS (
    SELECT DISTINCT b.stay_id
    FROM base b
    JOIN mimiciv_hosp.prescriptions p
      ON p.hadm_id = b.hadm_id
     AND p.starttime <= b.icu_outtime
     AND coalesce(p.stoptime, p.starttime) >= b.icu_intime
    WHERE regexp_matches(lower(p.drug), '{_STEROID_RX}')
      AND NOT regexp_matches(lower(p.drug), '{_STEROID_EXCLUDE_RX}')
),
-- ── baseline confounders (first 24 h) ────────────────────────────────────────
sofa AS (SELECT stay_id, sofa FROM mimiciv_derived.first_day_sofa),
saps AS (SELECT stay_id, max(sapsii) AS sapsii FROM mimiciv_derived.sapsii GROUP BY 1),
oas  AS (SELECT stay_id, max(oasis)  AS oasis  FROM mimiciv_derived.oasis  GROUP BY 1),
aps  AS (SELECT stay_id, max(apsiii) AS apsiii FROM mimiciv_derived.apsiii GROUP BY 1),
char AS (SELECT hadm_id, max(charlson_comorbidity_index) AS charlson_comorbidity_index
         FROM mimiciv_derived.charlson GROUP BY 1),
vit  AS (
    SELECT stay_id, heart_rate_mean, mbp_mean, resp_rate_mean,
           temperature_mean, spo2_mean
    FROM mimiciv_derived.first_day_vitalsign
),
lab  AS (
    SELECT stay_id, creatinine_max, bun_max, wbc_max, platelets_min,
           bilirubin_total_max, hemoglobin_min, inr_max,
           sodium_max, potassium_max, glucose_max
    FROM mimiciv_derived.first_day_lab
),
bg   AS (
    SELECT stay_id, lactate_max, pao2fio2ratio_min, ph_min
    FROM mimiciv_derived.first_day_bg
)
SELECT
    b.*,
    -- interventions → 0/1
    (vent.stay_id    IS NOT NULL)::INT AS intv_mechanical_ventilation,
    (vaso.stay_id    IS NOT NULL)::INT AS intv_vasopressors,
    (rrt.stay_id     IS NOT NULL)::INT AS intv_rrt,
    (steroid.stay_id IS NOT NULL)::INT AS intv_corticosteroids,
    (abx.stay_id     IS NOT NULL)::INT AS intv_antibiotics,
    -- confounders
    sofa.sofa, saps.sapsii, oas.oasis, aps.apsiii,
    char.charlson_comorbidity_index,
    vit.heart_rate_mean, vit.mbp_mean, vit.resp_rate_mean,
    vit.temperature_mean, vit.spo2_mean,
    bg.lactate_max, lab.creatinine_max, lab.bun_max, lab.wbc_max,
    lab.platelets_min, lab.bilirubin_total_max, lab.hemoglobin_min,
    lab.inr_max, lab.sodium_max, lab.potassium_max, lab.glucose_max,
    bg.pao2fio2ratio_min, bg.ph_min
FROM base b
LEFT JOIN vent     ON vent.stay_id    = b.stay_id
LEFT JOIN vaso     ON vaso.stay_id    = b.stay_id
LEFT JOIN rrt      ON rrt.stay_id     = b.stay_id
LEFT JOIN steroid  ON steroid.stay_id = b.stay_id
LEFT JOIN abx      ON abx.stay_id     = b.stay_id
LEFT JOIN sofa     ON sofa.stay_id    = b.stay_id
LEFT JOIN saps     ON saps.stay_id    = b.stay_id
LEFT JOIN oas      ON oas.stay_id     = b.stay_id
LEFT JOIN aps      ON aps.stay_id     = b.stay_id
LEFT JOIN char     ON char.hadm_id    = b.hadm_id
LEFT JOIN vit      ON vit.stay_id     = b.stay_id
LEFT JOIN lab      ON lab.stay_id     = b.stay_id
LEFT JOIN bg       ON bg.stay_id      = b.stay_id
"""


def build_cohort(
    duckdb_path: Path = DUCKDB_PATH,
    save: bool = True,
) -> pd.DataFrame:
    """Assemble the analysis cohort and (optionally) cache it as parquet."""
    if not duckdb_path.exists():
        raise FileNotFoundError(
            f"MIMIC-IV DuckDB not found at {duckdb_path}. "
            "Set it up (data/build_derived.py) before running the pipeline."
        )

    logger.info(f"Building ICU intervention cohort from {duckdb_path.name}")
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        df = con.execute(_COHORT_SQL).fetch_df()
    finally:
        con.close()
    logger.info(f"  Base adult first-ICU-stay population: {len(df):,} stays")

    df = _derive_features(df)
    df = _derive_mortality(df)

    # Report exposure prevalence and outcome rates so the run log is self-describing.
    for key in INTERVENTION_KEYS:
        logger.info(f"  exposure {key:<32} {df[key].mean()*100:5.1f}%  (n={int(df[key].sum()):,})")
    logger.info(f"  in-hospital mortality: {df['mortality_in_hospital'].mean()*100:.1f}%")

    _check_confounders(df)

    if save:
        DIR2COHORT_MORTALITY.mkdir(parents=True, exist_ok=True)
        df.to_parquet(COHORT_PARQUET)
        logger.info(f"  saved cohort → {COHORT_PARQUET}")
    return df


def _derive_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["female"] = (df["gender"] == "F").astype(int)
    adm = df["admission_type"].fillna("").str.upper()
    df["emergency_admission"] = adm.str.contains("EMER|URGENT", regex=True).astype(int)
    return df


def _derive_mortality(df: pd.DataFrame) -> pd.DataFrame:
    """Compute in-hospital / 28-day / 90-day mortality from ICU admission.

    Right-censoring: the death registry only covers deaths up to ``dod_max``.
    A patient with no recorded death whose horizon extends *past* that coverage
    cannot be confirmed alive, so the horizon outcome is set to NaN rather than
    silently coded as a survivor (avoids survivorship bias). In-hospital
    mortality is fully observed within the admission and never censored.
    """
    df = df.copy()
    df["icu_intime"] = pd.to_datetime(df["icu_intime"])
    df["dod"] = pd.to_datetime(df["dod"], errors="coerce")

    df["mortality_in_hospital"] = df["hospital_expire_flag"].astype("Int64").astype(float)

    dod_max = df["dod"].max()
    days_to_death = (df["dod"] - df["icu_intime"]).dt.days
    for horizon, col in [(28, "mortality_28d"), (90, "mortality_90d")]:
        died = df["dod"].notna() & (days_to_death <= horizon)
        out = died.astype(float)
        # censor: alive-but-unconfirmed beyond registry coverage
        uncertain = df["dod"].isna() & (df["icu_intime"] + pd.Timedelta(days=horizon) > dod_max)
        out[uncertain] = np.nan
        df[col] = out
        n_cens = int(uncertain.sum())
        logger.info(f"  {col}: {np.nanmean(out)*100:.1f}%  ({n_cens:,} right-censored)")
    return df


def _check_confounders(df: pd.DataFrame) -> None:
    missing = [c for c in CONFOUNDER_KEYS if c not in df.columns]
    if missing:
        raise KeyError(f"Confounders missing from cohort: {missing}")
    miss = (df[CONFOUNDER_KEYS].isna().mean() * 100).sort_values(ascending=False)
    worst = miss[miss > 0].head(6)
    if len(worst):
        logger.info("  confounder missingness (top): "
                    + ", ".join(f"{k} {v:.0f}%" for k, v in worst.items()))


def load_cohort(rebuild: bool = False) -> pd.DataFrame:
    """Load the cached cohort, building it on first use or when ``rebuild``."""
    if COHORT_PARQUET.exists() and not rebuild:
        logger.info(f"Loading cached cohort ← {COHORT_PARQUET}")
        return pd.read_parquet(COHORT_PARQUET)
    return build_cohort(save=True)


if __name__ == "__main__":
    cohort = build_cohort()
    print(cohort[INTERVENTION_KEYS + ["mortality_in_hospital"]].mean().round(3))
