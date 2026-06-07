"""
P2 (part 1) — clinical-equipoise sub-cohorts.

Restricting each intervention to the population in which the treatment decision is
genuinely uncertain is the single biggest lever for positivity/overlap: it removes
patients who would essentially never (or always) receive the treatment, so the
propensity is bounded away from 0/1 and the doubly-robust estimate becomes
trustworthy. Masks are computed from the **baseline-window** physiology and the
auxiliary signals already on the trial table, so they are pre-treatment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _lt(s: pd.Series, thr: float) -> pd.Series:
    """NaN-safe 'less than' (missing → not flagged)."""
    return s.lt(thr).fillna(False)


def _ge(s: pd.Series, thr: float) -> pd.Series:
    return s.ge(thr).fillna(False)


def shock(df: pd.DataFrame) -> pd.Series:
    """Hypotension or hyperlactataemia — vasopressor candidates."""
    return _lt(df["mbp_min"], 65) | _ge(df["lactate_max"], 2.0)


def resp_failure(df: pd.DataFrame) -> pd.Series:
    """Hypoxaemia (P/F < 300, or SpO2 < 92 when no ABG) — ventilation candidates."""
    return _lt(df["pao2fio2_min"], 300) | _lt(df["spo2_min"], 92)


def aki_23(df: pd.DataFrame) -> pd.Series:
    """KDIGO stage ≥ 2 acute kidney injury — RRT candidates."""
    return _ge(df["aki_stage_max"], 2)


def septic_shock(df: pd.DataFrame) -> pd.Series:
    """Sepsis-3 with shock — corticosteroid candidates."""
    return df["sepsis3"].astype(bool) & shock(df)


def suspected_infection(df: pd.DataFrame) -> pd.Series:
    """Documented suspicion of infection — antibiotic candidates."""
    return df["suspected_infection"].astype(bool)


_MASKS = {
    "shock": shock,
    "resp_failure": resp_failure,
    "aki_23": aki_23,
    "septic_shock": septic_shock,
    "suspected_infection": suspected_infection,
}


def equipoise_mask(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in _MASKS:
        raise KeyError(f"Unknown equipoise cohort '{name}'. Have: {list(_MASKS)}")
    return _MASKS[name](df)
