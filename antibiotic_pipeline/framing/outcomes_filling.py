"""
F14: Fill the previously NaN outcomes (VFD-28, VaPFD-28, AKI worsening,
secondary infection) directly inside framing. Previously these were
placeholders to be filled "downstream" — but if the downstream step failed
or was skipped, the sensitivity grid silently dropped the outcome.

All outcomes are computed from time zero (decision_time) forward over a 28-day
window:

  VFD-28    : days alive AND off invasive ventilation in [T0, T0 + 28d]
              (death within the window contributes 0 days)
  VaPFD-28  : days alive AND off vasopressors in [T0, T0 + 28d]
  AKI worsening : KDIGO stage at any point in [T0, T0 + 7d] strictly higher
              than the stage at T0
  Secondary infection : positive blood culture in [T0 + 3d, T0 + 28d] that is
              not at the same site as a positive pre-T0 culture
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
from loguru import logger

from antibiotic_pipeline.constants import (
    COLNAME_AKI_WORSENING,
    COLNAME_CDIFF_28D,
    COLNAME_DECISION_TIME,
    COLNAME_HADM_ID,
    COLNAME_ICUSTAY_ID,
    COLNAME_PATIENT_ID,
    COLNAME_SECONDARY_INFECTION,
    COLNAME_VAPFD28,
    COLNAME_VFD28,
    DIR2DERIVED,
    DIR2RAW,
)

WINDOW_DAYS = 28

# F20: C. difficile is operationalised as a *new* oral-vancomycin or
# oral-metronidazole order during the follow-up window. MIMIC's
# microbiology table does not consistently code C. diff toxin assays,
# so the standard pharma-epi proxy (Bagdasarian et al. 2015) is to count
# initiation of CDI-directed therapy. Patients already on oral vanco /
# metronidazole at T0 are excluded from the numerator.
CDIFF_DRUG_PATTERN = (
    r"(vancomycin\s*(?:hcl)?\s*(?:oral|capsule|po)|"
    r"vancomycin\s*125|vancomycin\s*250|"
    r"metronidazole\s*(?:oral|capsule|po|tablet))"
)


def _hours_in_intervals_within(
    intervals: pd.DataFrame,
    t0_series: pd.Series,
    horizon_days: int = WINDOW_DAYS,
) -> pd.Series:
    """For each stay_id in t0_series.index, sum the overlap (in hours) between
    `intervals` (cols: stay_id, starttime, endtime) and the window
    [T0, T0 + horizon_days] for that stay."""
    if intervals.empty:
        return pd.Series(0.0, index=t0_series.index, name="hours")
    iv = intervals.copy()
    iv["starttime"] = pd.to_datetime(iv["starttime"])
    iv["endtime"] = pd.to_datetime(iv["endtime"])
    t0_df = t0_series.rename("T0").to_frame()
    t0_df["T_end"] = t0_df["T0"] + pd.Timedelta(days=horizon_days)
    merged = iv.merge(t0_df, left_on=COLNAME_ICUSTAY_ID, right_index=True, how="inner")
    if merged.empty:
        return pd.Series(0.0, index=t0_series.index, name="hours")
    overlap_start = merged[["starttime", "T0"]].max(axis=1)
    overlap_end = merged[["endtime", "T_end"]].min(axis=1)
    delta = (overlap_end - overlap_start).dt.total_seconds() / 3600.0
    delta = delta.clip(lower=0.0)
    merged["hours"] = delta
    hours = merged.groupby(COLNAME_ICUSTAY_ID)["hours"].sum()
    return hours.reindex(t0_series.index).fillna(0.0)


def _vent_or_vaso_free_days(
    population: pd.DataFrame,
    intervals: pd.DataFrame,
) -> pd.Series:
    """Days alive AND off the device in [T0, T0+28d].

    If the patient dies inside the window, free-days = 0 (standard CTSI defn).
    """
    pop = population.set_index(COLNAME_ICUSTAY_ID)
    t0 = pd.to_datetime(pop[COLNAME_DECISION_TIME])
    horizon = WINDOW_DAYS

    device_hours = _hours_in_intervals_within(intervals, t0, horizon)
    device_days = device_hours / 24.0

    days_alive = pd.Series(horizon, index=t0.index, dtype="float64")
    if "dod" in pop.columns:
        dod = pd.to_datetime(pop["dod"], errors="coerce")
        died_mask = dod.notnull() & ((dod - t0).dt.days <= horizon)
        days_alive[died_mask] = 0.0  # standard VFD-28: dead → 0 days

    free_days = (days_alive - device_days).clip(lower=0.0, upper=horizon)
    return free_days


def compute_vent_free_days(population: pd.DataFrame) -> pd.Series:
    vent = pl.scan_parquet(DIR2DERIVED / "ventilation.parquet")
    invasive = (
        vent.filter(pl.col("ventilation_status") == "InvasiveVent")
        .select([COLNAME_ICUSTAY_ID, "starttime", "endtime"])
        .collect()
        .to_pandas()
    )
    return _vent_or_vaso_free_days(population, invasive)


def compute_vaso_free_days(population: pd.DataFrame) -> pd.Series:
    vaso = pl.scan_parquet(DIR2DERIVED / "vasoactive_agent.parquet")
    intervals = (
        vaso.select([COLNAME_ICUSTAY_ID, "starttime", "endtime"]).collect().to_pandas()
    )
    return _vent_or_vaso_free_days(population, intervals)


def compute_aki_worsening(population: pd.DataFrame, lookahead_days: int = 7) -> pd.Series:
    """Binary: KDIGO AKI stage strictly higher anytime in [T0, T0+7d] than at T0."""
    kdigo = pl.scan_parquet(DIR2DERIVED / "kdigo_stages.parquet").select(
        [COLNAME_ICUSTAY_ID, "charttime", "aki_stage"]
    ).collect().to_pandas()
    kdigo["charttime"] = pd.to_datetime(kdigo["charttime"])

    pop = population[[COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]].copy()
    pop[COLNAME_DECISION_TIME] = pd.to_datetime(pop[COLNAME_DECISION_TIME])
    pop["T_end"] = pop[COLNAME_DECISION_TIME] + pd.Timedelta(days=lookahead_days)

    merged = kdigo.merge(pop, on=COLNAME_ICUSTAY_ID, how="inner")

    # Stage at T0 = latest reading on or before T0
    pre = merged[merged["charttime"] <= merged[COLNAME_DECISION_TIME]].copy()
    pre = pre.sort_values([COLNAME_ICUSTAY_ID, "charttime"])
    stage_t0 = pre.groupby(COLNAME_ICUSTAY_ID)["aki_stage"].last()

    # Max stage in (T0, T_end]
    post = merged[
        (merged["charttime"] > merged[COLNAME_DECISION_TIME])
        & (merged["charttime"] <= merged["T_end"])
    ]
    stage_post = post.groupby(COLNAME_ICUSTAY_ID)["aki_stage"].max()

    out = pd.Series(np.nan, index=population[COLNAME_ICUSTAY_ID].values)
    common = stage_t0.index.intersection(stage_post.index)
    out.loc[common] = (stage_post.loc[common] > stage_t0.loc[common]).astype(int)
    return out


def compute_secondary_infection(
    population: pd.DataFrame,
    lookahead_days_start: int = 3,
    lookahead_days_end: int = WINDOW_DAYS,
) -> pd.Series:
    """Binary: any new positive blood culture in [T0+3d, T0+28d] for the
    same hadm_id whose organism wasn't seen in the pre-T0 cultures.
    Conservative — if the patient has no microbiology event, marks 0
    (not NaN, since the absence-of-evidence here matches the clinical
    definition of "no documented secondary infection").
    """
    mb = pl.scan_parquet(DIR2RAW / "microbiologyevents.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "charttime", "spec_type_desc", "org_name"]
    ).filter(pl.col("org_name").is_not_null()).collect().to_pandas()
    mb["charttime"] = pd.to_datetime(mb["charttime"])
    mb["spec_type_desc"] = mb["spec_type_desc"].fillna("").str.lower()
    mb["org_name"] = mb["org_name"].fillna("").str.lower()
    mb = mb[mb["spec_type_desc"].str.contains("blood")]

    pop = population[[COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]].copy()
    pop[COLNAME_DECISION_TIME] = pd.to_datetime(pop[COLNAME_DECISION_TIME])
    pop["T_start"] = pop[COLNAME_DECISION_TIME] + pd.Timedelta(days=lookahead_days_start)
    pop["T_end"] = pop[COLNAME_DECISION_TIME] + pd.Timedelta(days=lookahead_days_end)

    merged = mb.merge(pop, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")
    pre_orgs = (
        merged[merged["charttime"] <= merged[COLNAME_DECISION_TIME]]
        .groupby(COLNAME_ICUSTAY_ID)["org_name"].apply(set)
    )
    post = merged[
        (merged["charttime"] >= merged["T_start"])
        & (merged["charttime"] <= merged["T_end"])
    ]

    out = pd.Series(0, index=population[COLNAME_ICUSTAY_ID].values, dtype="int8")
    for stay_id, group in post.groupby(COLNAME_ICUSTAY_ID):
        pre = pre_orgs.get(stay_id, set())
        new = set(group["org_name"]) - pre
        if new:
            out.loc[stay_id] = 1
    return out


def compute_cdiff(
    population: pd.DataFrame,
    lookahead_days: int = WINDOW_DAYS,
) -> pd.Series:
    """Binary: a new CDI-directed antibiotic order during [T0, T0+28d] that
    was *not* already active at T0."""
    pres = pl.scan_parquet(DIR2RAW / "prescriptions.parquet").select(
        [COLNAME_PATIENT_ID, COLNAME_HADM_ID, "starttime", "drug", "route"]
    )
    pres = (
        pres.with_columns([
            pl.col("drug").str.to_lowercase().alias("drug_lower"),
            pl.col("route").str.to_lowercase().alias("route_lower"),
        ])
        # Match oral vanco / metronidazole. IV vancomycin is excluded by the
        # route filter; oral metronidazole is the broader pattern.
        .filter(
            (pl.col("drug_lower").str.contains("vancomycin") & pl.col("route_lower").str.contains("po"))
            | (pl.col("drug_lower").str.contains("metronidazole") & pl.col("route_lower").str.contains("po"))
            | (pl.col("drug_lower").str.contains("metronidazole") & pl.col("route_lower").str.contains("oral"))
        )
        .select([COLNAME_PATIENT_ID, COLNAME_HADM_ID, "starttime", "drug_lower"])
        .collect()
        .to_pandas()
    )
    pres["starttime"] = pd.to_datetime(pres["starttime"])

    pop = population[[COLNAME_PATIENT_ID, COLNAME_HADM_ID, COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]].copy()
    pop[COLNAME_DECISION_TIME] = pd.to_datetime(pop[COLNAME_DECISION_TIME])
    pop["T_end"] = pop[COLNAME_DECISION_TIME] + pd.Timedelta(days=lookahead_days)

    merged = pres.merge(pop, on=[COLNAME_PATIENT_ID, COLNAME_HADM_ID], how="inner")

    # Exclude patients already on CDI therapy at T0 (3-day grace window).
    pre_mask = merged["starttime"] <= merged[COLNAME_DECISION_TIME] + pd.Timedelta(days=3)
    pre_on_cdi = set(merged.loc[pre_mask, COLNAME_ICUSTAY_ID].unique())

    post_mask = (
        (merged["starttime"] > merged[COLNAME_DECISION_TIME] + pd.Timedelta(days=3))
        & (merged["starttime"] <= merged["T_end"])
    )
    new_cdi = set(merged.loc[post_mask, COLNAME_ICUSTAY_ID].unique()) - pre_on_cdi

    out = pd.Series(0, index=population[COLNAME_ICUSTAY_ID].values, dtype="int8")
    out.loc[list(new_cdi)] = 1
    return out


def fill_all(population: pd.DataFrame) -> pd.DataFrame:
    """Fill VFD/VaPFD/AKI-worsening/secondary-infection into the population frame."""
    pop = population.copy()
    logger.info("F14: computing VFD-28")
    pop[COLNAME_VFD28] = compute_vent_free_days(pop).reindex(pop[COLNAME_ICUSTAY_ID].values).values
    logger.info("F14: computing VaPFD-28")
    pop[COLNAME_VAPFD28] = compute_vaso_free_days(pop).reindex(pop[COLNAME_ICUSTAY_ID].values).values
    logger.info("F14: computing AKI worsening (7d lookahead)")
    pop[COLNAME_AKI_WORSENING] = compute_aki_worsening(pop).reindex(pop[COLNAME_ICUSTAY_ID].values).values
    logger.info("F14: computing secondary infection")
    pop[COLNAME_SECONDARY_INFECTION] = compute_secondary_infection(pop).reindex(pop[COLNAME_ICUSTAY_ID].values).values
    logger.info("F20: computing C. difficile (proxy: new oral vanco / metronidazole)")
    pop[COLNAME_CDIFF_28D] = compute_cdiff(pop).reindex(pop[COLNAME_ICUSTAY_ID].values).values
    return pop
