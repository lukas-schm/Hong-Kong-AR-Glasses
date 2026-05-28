"""
Causal-validity diagnostics for the antibiotic continuation pipeline.

Two checks, one entrypoint:

F7 — Positivity / overlap
    For each pairwise treatment comparison, fit a logistic propensity model
    via cross_val_predict, save per-row propensities, and report the share of
    rows inside the [MIN_PS_SCORE, 1 - MIN_PS_SCORE] common-support window.
    If overlap is poor, downstream ATEs are extrapolations and should not be
    trusted at face value.

F12 — Per-arm calibration
    For each treatment arm, fit a logistic mortality model via
    cross_val_predict, compute Brier score, calibration intercept/slope (via
    logistic regression of y on logit-predicted), and a 10-bin reliability
    summary. A T-Learner whose calibration differs sharply across arms gives
    misleading per-arm absolute risks.

Output
------
    data/diagnostics/overlap/<arm_a>v<arm_b>/propensity.parquet
    data/diagnostics/overlap/<arm_a>v<arm_b>/summary.json
    data/diagnostics/calibration/<arm>/predictions.parquet
    data/diagnostics/calibration/<arm>/summary.json

Usage
-----
    python -m antibiotic_pipeline.experiments.diagnostics
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_ICUSTAY_ID,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2COHORT,
    DIR2DATA,
    MIN_PS_SCORE,
    RANDOM_STATE,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

COHORT_NAME = "antibiotic_continuation_sepsis"
DIR2DIAG = DIR2DATA / "diagnostics"
PAIRWISE = [(0, 1), (0, 2), (1, 2)]
ARMS = [0, 1, 2]


def _load_features() -> tuple[pd.DataFrame, list[str]]:
    cohort = DIR2COHORT / COHORT_NAME
    pop = pd.read_parquet(cohort / "target_population.parquet")
    confounders = pd.read_parquet(cohort / "confounders.parquet")
    data = pop.merge(confounders, on=COLNAME_ICUSTAY_ID, how="inner")

    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in data.columns]
    indicator_cols = [
        f"{c}__missing" for c in feature_cols if f"{c}__missing" in data.columns
    ]
    feature_cols = feature_cols + indicator_cols
    logger.info(f"Diagnostics dataset: {len(data)} rows, {len(feature_cols)} features")
    return data, feature_cols


# ── F7: positivity / overlap ──────────────────────────────────────────────────

def run_overlap_diagnostics(out_dir: Path = DIR2DIAG / "overlap") -> Dict[str, dict]:
    data, feature_cols = _load_features()
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries: Dict[str, dict] = {}

    for arm_a, arm_b in PAIRWISE:
        mask = data[COLNAME_INTERVENTION_STATUS].isin([arm_a, arm_b])
        sub = data.loc[mask, feature_cols + [COLNAME_INTERVENTION_STATUS, COLNAME_MORTALITY_28D, COLNAME_ICUSTAY_ID]].copy()
        y_t = (sub[COLNAME_INTERVENTION_STATUS] == arm_b).astype(int).values

        if y_t.sum() < 30 or (len(y_t) - y_t.sum()) < 30:
            logger.warning(f"Skipping {arm_a}v{arm_b}: not enough rows per class")
            continue

        pipe = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        )
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
        ps = cross_val_predict(pipe, sub[feature_cols].values, y_t, cv=skf, method="predict_proba")[:, 1]

        within_support = ((ps >= MIN_PS_SCORE) & (ps <= 1 - MIN_PS_SCORE)).mean()
        n_clipped_low = int((ps < MIN_PS_SCORE).sum())
        n_clipped_high = int((ps > 1 - MIN_PS_SCORE).sum())

        out = pd.DataFrame({
            COLNAME_ICUSTAY_ID: sub[COLNAME_ICUSTAY_ID].values,
            "treatment_arm": sub[COLNAME_INTERVENTION_STATUS].values,
            "propensity_arm_b": ps,
            "mortality_28days": sub[COLNAME_MORTALITY_28D].values,
        })
        pair_dir = out_dir / f"{arm_a}v{arm_b}"
        pair_dir.mkdir(parents=True, exist_ok=True)
        out.to_parquet(pair_dir / "propensity.parquet")

        # Histogram (10 bins) per arm for quick plotting downstream.
        hist_a, edges = np.histogram(ps[y_t == 0], bins=10, range=(0, 1))
        hist_b, _ = np.histogram(ps[y_t == 1], bins=10, range=(0, 1))

        summary = {
            "arm_a": arm_a,
            "arm_b": arm_b,
            "n_a": int((y_t == 0).sum()),
            "n_b": int((y_t == 1).sum()),
            "overlap_pct": round(float(within_support) * 100, 2),
            "min_ps_floor": MIN_PS_SCORE,
            "n_below_floor": n_clipped_low,
            "n_above_ceiling": n_clipped_high,
            "ps_mean_arm_a": round(float(ps[y_t == 0].mean()), 4),
            "ps_mean_arm_b": round(float(ps[y_t == 1].mean()), 4),
            "histogram_edges": [round(float(e), 3) for e in edges.tolist()],
            "histogram_arm_a": hist_a.tolist(),
            "histogram_arm_b": hist_b.tolist(),
            "reliable_for_inference": bool(within_support >= 0.70),
        }
        with open(pair_dir / "summary.json", "w") as fh:
            json.dump(summary, fh, indent=2)
        summaries[f"{arm_a}v{arm_b}"] = summary

        verdict = "OK" if summary["reliable_for_inference"] else "POOR — interpret ATEs with caution"
        logger.info(
            f"  {arm_a}v{arm_b}: overlap={summary['overlap_pct']:.1f}% "
            f"(n_a={summary['n_a']}, n_b={summary['n_b']}) — {verdict}"
        )
    return summaries


# ── F12: per-arm calibration ──────────────────────────────────────────────────

def run_calibration_diagnostics(out_dir: Path = DIR2DIAG / "calibration") -> Dict[int, dict]:
    data, feature_cols = _load_features()
    y_mort = data[COLNAME_MORTALITY_28D].fillna(0).astype(int).values
    T = data[COLNAME_INTERVENTION_STATUS].values
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries: Dict[int, dict] = {}

    for arm in ARMS:
        mask = T == arm
        if mask.sum() < 100 or y_mort[mask].sum() < 10:
            logger.warning(f"Skipping arm {arm}: not enough rows or events")
            continue
        X = data.loc[mask, feature_cols].values
        y = y_mort[mask]

        pipe = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=1000, C=1.0, random_state=RANDOM_STATE),
        )
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
        p_oof = cross_val_predict(pipe, X, y, cv=skf, method="predict_proba")[:, 1]

        brier = float(brier_score_loss(y, p_oof))

        # Calibration intercept & slope via logistic regression of y on logit(p_oof).
        eps = 1e-6
        p_clip = np.clip(p_oof, eps, 1 - eps)
        logit_p = np.log(p_clip / (1 - p_clip))
        calib_lr = LogisticRegression(C=1e6, max_iter=1000).fit(logit_p.reshape(-1, 1), y)
        cal_intercept = float(calib_lr.intercept_[0])
        cal_slope = float(calib_lr.coef_[0, 0])

        # 10-bin reliability
        bins = np.linspace(0, 1, 11)
        bin_idx = np.clip(np.digitize(p_oof, bins) - 1, 0, 9)
        reliability = []
        for b in range(10):
            sel = bin_idx == b
            if sel.sum() == 0:
                reliability.append({"bin": b, "n": 0, "p_mean": None, "y_mean": None})
            else:
                reliability.append({
                    "bin": b,
                    "n": int(sel.sum()),
                    "p_mean": round(float(p_oof[sel].mean()), 4),
                    "y_mean": round(float(y[sel].mean()), 4),
                })

        arm_dir = out_dir / f"arm_{arm}"
        arm_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            COLNAME_ICUSTAY_ID: data.loc[mask, COLNAME_ICUSTAY_ID].values,
            "predicted_mortality": p_oof,
            "observed_mortality": y,
        }).to_parquet(arm_dir / "predictions.parquet")

        summary = {
            "arm": arm,
            "n": int(mask.sum()),
            "n_events": int(y.sum()),
            "event_rate": round(float(y.mean()), 4),
            "brier": round(brier, 4),
            "calibration_intercept": round(cal_intercept, 4),
            "calibration_slope": round(cal_slope, 4),
            "reliability": reliability,
            "interpretation": _calibration_verdict(cal_intercept, cal_slope),
        }
        with open(arm_dir / "summary.json", "w") as fh:
            json.dump(summary, fh, indent=2)
        summaries[arm] = summary

        logger.info(
            f"  arm {arm}: Brier={brier:.4f} | calib_intercept={cal_intercept:+.3f}, "
            f"slope={cal_slope:.3f} | event_rate={summary['event_rate']:.3f}"
        )
    return summaries


def _calibration_verdict(intercept: float, slope: float) -> str:
    # Perfect calibration: intercept ≈ 0, slope ≈ 1.
    if abs(intercept) < 0.2 and 0.8 <= slope <= 1.2:
        return "good"
    if abs(intercept) < 0.5 and 0.6 <= slope <= 1.4:
        return "moderate"
    return "poor — re-evaluate before clinical use"


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    logger.info("=== F7: overlap diagnostics ===")
    overlap = run_overlap_diagnostics()
    logger.info("=== F12: per-arm calibration ===")
    calib = run_calibration_diagnostics()
    bundle = {
        "overlap": overlap,
        "calibration": {str(k): v for k, v in calib.items()},
    }
    summary_path = DIR2DIAG / "diagnostics_summary.json"
    DIR2DIAG.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as fh:
        json.dump(bundle, fh, indent=2)
    logger.info(f"Diagnostics bundle saved at {summary_path}")


if __name__ == "__main__":
    main()
