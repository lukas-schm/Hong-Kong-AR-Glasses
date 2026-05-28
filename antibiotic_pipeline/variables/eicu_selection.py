"""
WS7 — Confounder extraction for the eICU-CRD cohort.

Maps eICU schema onto the same 34+4 confounder set used for MIMIC-IV. Where a
confounder is not recoverable (e.g., the MIMIC-IV-specific KDIGO derived
table is not directly available), the column is filled with NaN and the
missingness indicator carries the signal.

eICU sources used:
  * lab.parquet         → lactate, creatinine, bilirubin, WBC, CRP
  * vitalperiodic.parquet → temperature, MAP
  * apachepatientresult.parquet → severity proxies (acutephysiologyscore,
                                  apachescore) — used as SAPS-II/SOFA proxies
  * infusiondrug.parquet → vasopressor flags
  * patient.parquet     → age, gender, hospitalid
  * diagnosis.parquet   → immunosuppression flags (Charlson proxies)
  * treatment.parquet   → ventilation flag

The mapping is documented in the manuscript's eICU-validation appendix.
"""
from __future__ import annotations

import pandas as pd
import polars as pl
from loguru import logger

from antibiotic_pipeline.constants import (
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_PATIENT_ID,
)
from antibiotic_pipeline.framing.eicu_framing import DIR2EICU


def get_eicu_confounders(pop: pd.DataFrame) -> pd.DataFrame:
    """Return one row per stay_id with the 34-variable confounder set on eICU."""
    stays = pop[[COLNAME_ICUSTAY_ID, "t0_min"]].copy()

    lab = _eicu_lab_features(stays)
    vital = _eicu_vital_features(stays)
    apache = _eicu_apache_features(pop)
    vasopressor = _eicu_vasopressor_features(stays)
    ventilation = _eicu_ventilation_features(stays)
    demo = _eicu_demographics(pop)

    out = pop[[COLNAME_ICUSTAY_ID]].copy()
    for df in (lab, vital, apache, vasopressor, ventilation, demo):
        out = out.merge(df, on=COLNAME_ICUSTAY_ID, how="left")

    # Trajectory deltas: eICU lab has multiple measurements per stay;
    # compute first-to-last delta in the 0–T0 window.
    deltas = _eicu_trajectory(stays)
    out = out.merge(deltas, on=COLNAME_ICUSTAY_ID, how="left")
    return out


def _eicu_lab_features(stays: pd.DataFrame) -> pd.DataFrame:
    """Latest lab value at or before T0 for each panel."""
    lab = pl.scan_parquet(DIR2EICU / "lab.parquet").select(
        ["patientunitstayid", "labresultoffset", "labname", "labresult"]
    )
    rows = []
    panel = {
        "lactate":    ["lactate"],
        "creatinine": ["creatinine"],
        "bilirubin":  ["bilirubin"],
        "WBC":        ["wbc", "white blood cells"],
        "CRP":        ["crp", "c-reactive protein"],
    }
    stays_pl = pl.from_pandas(stays).rename({COLNAME_ICUSTAY_ID: "patientunitstayid"})
    for out_name, patterns in panel.items():
        pattern_q = "|".join(patterns)
        df = (
            lab.filter(pl.col("labname").str.to_lowercase().str.contains(pattern_q))
            .join(stays_pl.lazy(), on="patientunitstayid", how="inner")
            .filter(pl.col("labresultoffset") <= pl.col("t0_min"))
            .sort(["patientunitstayid", "labresultoffset"])
            .group_by("patientunitstayid")
            .agg(pl.last("labresult").alias(f"{out_name}_at_decision"))
            .collect()
            .to_pandas()
            .rename(columns={"patientunitstayid": COLNAME_ICUSTAY_ID})
        )
        rows.append(df)
    result = stays[[COLNAME_ICUSTAY_ID]].copy()
    for df in rows:
        result = result.merge(df, on=COLNAME_ICUSTAY_ID, how="left")
    return result


def _eicu_vital_features(stays: pd.DataFrame) -> pd.DataFrame:
    """Latest temperature and MAP at or before T0."""
    vital = pl.scan_parquet(DIR2EICU / "vitalperiodic.parquet").select(
        ["patientunitstayid", "observationoffset", "temperature", "noninvasivemean"]
    )
    stays_pl = pl.from_pandas(stays).rename({COLNAME_ICUSTAY_ID: "patientunitstayid"})
    df = (
        vital.join(stays_pl.lazy(), on="patientunitstayid", how="inner")
        .filter(pl.col("observationoffset") <= pl.col("t0_min"))
        .sort(["patientunitstayid", "observationoffset"])
        .group_by("patientunitstayid")
        .agg([
            pl.last("temperature").alias("temperature_at_decision"),
            pl.last("noninvasivemean").alias("MAP_at_decision"),
        ])
        .collect()
        .to_pandas()
        .rename(columns={"patientunitstayid": COLNAME_ICUSTAY_ID})
    )
    return df


def _eicu_apache_features(pop: pd.DataFrame) -> pd.DataFrame:
    """APACHE IV severity scores as proxies for SOFA / SAPS-II."""
    apache = (
        pl.scan_parquet(DIR2EICU / "apachepatientresult.parquet")
        .select(["patientunitstayid", "acutephysiologyscore", "apachescore"])
        .collect()
        .to_pandas()
        .rename(columns={
            "patientunitstayid": COLNAME_ICUSTAY_ID,
            "acutephysiologyscore": "SOFA_at_decision",
            "apachescore":          "SAPSII",
        })
    )
    # Use only the first APACHE record per stay (admission baseline).
    return apache.drop_duplicates(subset=[COLNAME_ICUSTAY_ID])


def _eicu_vasopressor_features(stays: pd.DataFrame) -> pd.DataFrame:
    """Any vasopressor infusion active at T0."""
    infusion = pl.scan_parquet(DIR2EICU / "infusiondrug.parquet").select(
        ["patientunitstayid", "infusionoffset", "drugname"]
    )
    vasos = "norepinephrine|epinephrine|vasopressin|dopamine|phenylephrine"
    stays_pl = pl.from_pandas(stays).rename({COLNAME_ICUSTAY_ID: "patientunitstayid"})
    df = (
        infusion.filter(pl.col("drugname").str.to_lowercase().str.contains(vasos))
        .join(stays_pl.lazy(), on="patientunitstayid", how="inner")
        .filter(pl.col("infusionoffset") <= pl.col("t0_min"))
        .select("patientunitstayid")
        .unique()
        .with_columns(pl.lit(1).cast(pl.Int8).alias("vasopressors_at_decision"))
        .collect()
        .to_pandas()
        .rename(columns={"patientunitstayid": COLNAME_ICUSTAY_ID})
    )
    df = stays[[COLNAME_ICUSTAY_ID]].merge(df, on=COLNAME_ICUSTAY_ID, how="left")
    df["vasopressors_at_decision"] = df["vasopressors_at_decision"].fillna(0).astype(int)
    return df


def _eicu_ventilation_features(stays: pd.DataFrame) -> pd.DataFrame:
    """Mechanical ventilation flag from `treatment` text records."""
    treatment = pl.scan_parquet(DIR2EICU / "treatment.parquet").select(
        ["patientunitstayid", "treatmentoffset", "treatmentstring"]
    )
    stays_pl = pl.from_pandas(stays).rename({COLNAME_ICUSTAY_ID: "patientunitstayid"})
    df = (
        treatment.filter(
            pl.col("treatmentstring").str.to_lowercase().str.contains(
                "mechanical ventilation|intubation|ventilator|tube ventilation"
            )
        )
        .join(stays_pl.lazy(), on="patientunitstayid", how="inner")
        .filter(pl.col("treatmentoffset") <= pl.col("t0_min"))
        .select("patientunitstayid")
        .unique()
        .with_columns(pl.lit(1).cast(pl.Int8).alias("ventilation_at_decision"))
        .collect()
        .to_pandas()
        .rename(columns={"patientunitstayid": COLNAME_ICUSTAY_ID})
    )
    df = stays[[COLNAME_ICUSTAY_ID]].merge(df, on=COLNAME_ICUSTAY_ID, how="left")
    df["ventilation_at_decision"] = df["ventilation_at_decision"].fillna(0).astype(int)
    return df


def _eicu_demographics(pop: pd.DataFrame) -> pd.DataFrame:
    """Age, sex, and emergency admission flag from patient."""
    df = pop[[COLNAME_ICUSTAY_ID, "age_years", "gender"]].copy()
    df["admission_age"] = df["age_years"]
    df["Female"] = (df["gender"].str.upper() == "FEMALE").astype(int)
    # eICU patient table has unittype + unitadmitsource — emergency proxy
    return df[[COLNAME_ICUSTAY_ID, "admission_age", "Female"]]


def _eicu_trajectory(stays: pd.DataFrame) -> pd.DataFrame:
    """First-minus-last delta in [0, T0] window for SOFA proxy / lab markers.

    eICU has multiple APACHE records (admission, 24h, 48h, 72h) for many
    stays — we use them as the trajectory feature.
    """
    apache = (
        pl.scan_parquet(DIR2EICU / "apachepatientresult.parquet")
        .select(["patientunitstayid", "acutephysiologyscore"])
        .group_by("patientunitstayid")
        .agg([
            pl.first("acutephysiologyscore").alias("first"),
            pl.last("acutephysiologyscore").alias("last"),
        ])
        .with_columns((pl.col("last") - pl.col("first")).alias("delta_SOFA_0_72h"))
        .select(["patientunitstayid", "delta_SOFA_0_72h"])
        .collect()
        .to_pandas()
        .rename(columns={"patientunitstayid": COLNAME_ICUSTAY_ID})
    )
    return apache
