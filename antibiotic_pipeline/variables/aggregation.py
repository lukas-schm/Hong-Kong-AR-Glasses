"""
Standardised feature aggregation for the antibiotic continuation pipeline.

All aggregation functions operate on Polars LazyFrames and respect the
temporal ordering enforced by the causal graph (measure at or before time zero).

Aggregation strategies (as specified in causal_graph.yaml):
  last_before_decision      Latest measurement ≤ decision_time
  first_in_stay             First measurement after ICU intime
  active_at_decision        Interval overlaps with decision_time (binary flag)
  any_before_decision       Any matching row before decision_time (binary flag)
  last_minus_first_in_window (last - first) in [inclusion_start, decision_time]
  duration_before_decision  Sum of interval durations before decision_time (days)
  static                    Join directly on stay/patient ID (no time filter)
"""

from typing import Optional

import pandas as pd
import polars as pl

from antibiotic_pipeline.constants import (
    COLNAME_DECISION_TIME,
    COLNAME_ICUSTAY_ID,
    COLNAME_INCLUSION_START,
    COLNAME_PATIENT_ID,
    COLNAME_HADM_ID,
)
from antibiotic_pipeline.definitions.loader import ConfounderDef

# ── Public dispatch function ──────────────────────────────────────────────────

def aggregate_feature(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    time_col: str = "charttime",
    start_col: str = "starttime",
    end_col: str = "endtime",
) -> pd.DataFrame:
    """Aggregate a single feature from source_lf according to config.aggregation.

    Parameters
    ----------
    stays : pl.DataFrame
        Cohort with COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME, COLNAME_INCLUSION_START.
    source_lf : pl.LazyFrame
        Lazy scan of the source table (parquet or CSV.GZ).
    config : ConfounderDef
        Feature definition from the causal graph.
    time_col : str
        Column name for point-in-time measurements.
    start_col / end_col : str
        Column names for interval-based events (ventilation, vasopressors, etc.).

    Returns
    -------
    pd.DataFrame with [stay_id, <config.variable>]
    """
    fn = _AGGREGATION_DISPATCH.get(config.aggregation)
    if fn is None:
        raise ValueError(
            f"Unknown aggregation '{config.aggregation}' for variable "
            f"'{config.variable}'. "
            f"Valid: {list(_AGGREGATION_DISPATCH)}"
        )
    return fn(stays, source_lf, config, time_col=time_col,
               start_col=start_col, end_col=end_col)


# ── Aggregation implementations ───────────────────────────────────────────────

def _last_before_decision(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    time_col: str = "charttime",
    **_,
) -> pd.DataFrame:
    """Latest measurement value at or before decision_time."""
    val_col = config.source_column or "value"
    result = (
        source_lf
        .join(stays.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
              on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))
        .sort([COLNAME_ICUSTAY_ID, time_col])
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.last(val_col).alias(config.variable))
        .collect()
        .to_pandas()
    )
    return result[[COLNAME_ICUSTAY_ID, config.variable]]


def _first_in_stay(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    time_col: str = "charttime",
    **_,
) -> pd.DataFrame:
    """First measurement after ICU intime (e.g. SAPSII computed on day 1)."""
    val_col = config.source_column or "value"
    result = (
        source_lf
        .join(stays.lazy().select([COLNAME_ICUSTAY_ID]),
              on=COLNAME_ICUSTAY_ID, how="inner")
        .sort([COLNAME_ICUSTAY_ID, time_col])
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.first(val_col).alias(config.variable))
        .collect()
        .to_pandas()
    )
    return result[[COLNAME_ICUSTAY_ID, config.variable]]


def _active_at_decision(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    start_col: str = "starttime",
    end_col: str = "endtime",
    **_,
) -> pd.DataFrame:
    """Binary: 1 if any interval overlaps with decision_time."""
    active = (
        source_lf
        .join(stays.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
              on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(
            (pl.col(start_col) <= pl.col(COLNAME_DECISION_TIME))
            & (pl.col(end_col) >= pl.col(COLNAME_DECISION_TIME))
        )
        .select(COLNAME_ICUSTAY_ID)
        .unique()
        .with_columns(pl.lit(1).alias(config.variable))
        .collect()
        .to_pandas()
    )
    result = stays.select(COLNAME_ICUSTAY_ID).to_pandas().merge(
        active, on=COLNAME_ICUSTAY_ID, how="left"
    )
    result[config.variable] = result[config.variable].fillna(0).astype(int)
    return result[[COLNAME_ICUSTAY_ID, config.variable]]


def _any_before_decision(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    time_col: str = "charttime",
    **_,
) -> pd.DataFrame:
    """Binary: 1 if any matching row exists before decision_time.

    Applies config.filter_sql as a polars filter expression where possible.
    For complex SQL filters, the caller should pre-filter the LazyFrame.
    """
    lf = source_lf.join(
        stays.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]),
        on=COLNAME_ICUSTAY_ID, how="inner"
    ).filter(pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))

    present = (
        lf
        .select(COLNAME_ICUSTAY_ID)
        .unique()
        .with_columns(pl.lit(1).alias(config.variable))
        .collect()
        .to_pandas()
    )
    result = stays.select(COLNAME_ICUSTAY_ID).to_pandas().merge(
        present, on=COLNAME_ICUSTAY_ID, how="left"
    )
    result[config.variable] = result[config.variable].fillna(0).astype(int)
    return result[[COLNAME_ICUSTAY_ID, config.variable]]


def _last_minus_first_in_window(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    time_col: str = "charttime",
    **_,
) -> pd.DataFrame:
    """Delta: (last value − first value) in window [inclusion_start, decision_time]."""
    val_col = config.source_column or "value"
    delta_col = config.variable

    result = (
        source_lf
        .join(stays.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_INCLUSION_START,
                                   COLNAME_DECISION_TIME]),
              on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(
            (pl.col(time_col) >= pl.col(COLNAME_INCLUSION_START))
            & (pl.col(time_col) <= pl.col(COLNAME_DECISION_TIME))
        )
        .sort([COLNAME_ICUSTAY_ID, time_col])
        .group_by(COLNAME_ICUSTAY_ID)
        .agg([
            pl.first(val_col).alias("_first"),
            pl.last(val_col).alias("_last"),
        ])
        .with_columns(
            (pl.col("_last") - pl.col("_first")).alias(delta_col)
        )
        .select([COLNAME_ICUSTAY_ID, delta_col])
        .collect()
        .to_pandas()
    )
    return result


def _duration_before_decision(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    start_col: str = "starttime",
    end_col: str = "stoptime",
    **_,
) -> pd.DataFrame:
    """Total duration (days) of intervals before decision_time."""
    result = (
        source_lf
        .join(stays.lazy().select([COLNAME_ICUSTAY_ID, COLNAME_INCLUSION_START,
                                   COLNAME_DECISION_TIME]),
              on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(
            (pl.col(start_col) >= pl.col(COLNAME_INCLUSION_START))
            & (pl.col(start_col) <= pl.col(COLNAME_DECISION_TIME))
        )
        .with_columns(
            pl.min_horizontal(pl.col(end_col), pl.col(COLNAME_DECISION_TIME))
            .alias("_clipped_end")
        )
        .with_columns(
            ((pl.col("_clipped_end") - pl.col(start_col)).dt.total_seconds() / 86400)
            .clip(lower_bound=0)
            .alias("_interval_days")
        )
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.sum("_interval_days").alias(config.variable))
        .collect()
        .to_pandas()
    )
    base = stays.select(COLNAME_ICUSTAY_ID).to_pandas()
    result = base.merge(result, on=COLNAME_ICUSTAY_ID, how="left")
    result[config.variable] = result[config.variable].fillna(0)
    return result[[COLNAME_ICUSTAY_ID, config.variable]]


def _static(
    stays: pl.DataFrame,
    source_lf: pl.LazyFrame,
    config: ConfounderDef,
    **_,
) -> pd.DataFrame:
    """Join directly by stay_id (no time filter) — for static attributes."""
    val_col = config.source_column or config.variable
    join_col = COLNAME_ICUSTAY_ID
    # Some static tables join on hadm_id or subject_id
    if val_col in ("anchor_age", "gender", "dod"):
        join_col = COLNAME_PATIENT_ID
    elif val_col in ("admission_type", "insurance"):
        join_col = COLNAME_HADM_ID

    available_cols = [join_col, val_col]

    result = (
        source_lf
        .select([c for c in source_lf.columns if c in available_cols + [COLNAME_ICUSTAY_ID,
                                                                          COLNAME_PATIENT_ID,
                                                                          COLNAME_HADM_ID]])
        .join(
            stays.lazy().select(list({COLNAME_ICUSTAY_ID, COLNAME_PATIENT_ID,
                                      COLNAME_HADM_ID, join_col})),
            on=join_col, how="inner"
        )
        .select([COLNAME_ICUSTAY_ID, val_col])
        .unique(subset=[COLNAME_ICUSTAY_ID])
        .collect()
        .to_pandas()
    )
    if val_col != config.variable:
        result = result.rename(columns={val_col: config.variable})
    return result[[COLNAME_ICUSTAY_ID, config.variable]]


# ── Dispatch table ────────────────────────────────────────────────────────────

_AGGREGATION_DISPATCH = {
    "last_before_decision":      _last_before_decision,
    "first_in_stay":             _first_in_stay,
    "active_at_decision":        _active_at_decision,
    "any_before_decision":       _any_before_decision,
    "last_minus_first_in_window": _last_minus_first_in_window,
    "duration_before_decision":  _duration_before_decision,
    "static":                    _static,
}


# ── Outcome helpers ───────────────────────────────────────────────────────────

def compute_free_days(
    population: pd.DataFrame,
    event_lf: pl.LazyFrame,
    outcome_col: str,
    mortality_col: str,
    follow_days: int = 28,
    start_col: str = "starttime",
    end_col: str = "endtime",
) -> pd.DataFrame:
    """Compute ventilator-free or vasopressor-free days.

    Returns 0 if patient died within follow_days; else follow_days minus
    total days spent on the event (ventilation/vasopressors) after time zero.
    """
    stays_lf = pl.from_pandas(
        population[[COLNAME_ICUSTAY_ID, COLNAME_DECISION_TIME]]
    ).lazy()

    follow_end = pl.col(COLNAME_DECISION_TIME) + pl.duration(days=follow_days)
    overlap_days = (
        event_lf
        .join(stays_lf, on=COLNAME_ICUSTAY_ID, how="inner")
        .filter(
            (pl.col(start_col) < follow_end)
            & (pl.col(end_col) > pl.col(COLNAME_DECISION_TIME))
        )
        .with_columns([
            pl.max_horizontal(pl.col(start_col), pl.col(COLNAME_DECISION_TIME))
            .alias("_overlap_start"),
            pl.min_horizontal(pl.col(end_col), follow_end)
            .alias("_overlap_end"),
        ])
        .with_columns(
            ((pl.col("_overlap_end") - pl.col("_overlap_start")).dt.total_seconds() / 86400)
            .clip(lower_bound=0)
            .alias("_days_on")
        )
        .group_by(COLNAME_ICUSTAY_ID)
        .agg(pl.sum("_days_on"))
        .collect()
        .to_pandas()
        .rename(columns={"_days_on": "_event_days"})
    )

    pop = population.merge(overlap_days, on=COLNAME_ICUSTAY_ID, how="left")
    pop["_event_days"] = pop["_event_days"].fillna(0)
    pop[outcome_col] = (
        (1 - pop[mortality_col]) * (follow_days - pop["_event_days"]).clip(lower=0)
    ).round(1)
    return pop.drop(columns=["_event_days"])
