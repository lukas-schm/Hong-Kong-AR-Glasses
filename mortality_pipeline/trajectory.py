"""
Weekly counterfactual **survival trajectory** for each intervention.

Instead of one effect per horizon, we estimate the doubly-robust risk difference
``RD(t) = P[death by t | treat] − P[death by t | control]`` on a weekly grid
``t ∈ {7,14,…,84} d`` from the baseline landmark t0, plus the counterfactual
survival curves ``S₁(t), S₀(t)``. This reveals the *shape* of the effect — does
it grow, attenuate, or reverse over the patient's trajectory.

All-cause mortality is followed via the death registry (coverage ≈100% to ≥1 y in
this extract), so discharge-alive is **not** a competing risk and administrative
censoring before 90 d is ≈0. We still drop (IPCW-style) anyone whose follow-up
ends before t and log the censored fraction, so the design is correct if the grid
is later extended past registry coverage.

Estimation reuses the cross-fit AIPW engine: the propensity is fit once per
intervention and reused across all weeks; the outcome surface is re-fit per week.
"""
from __future__ import annotations

import json
from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    DIR2RESULTS_TRIALS,
    INTERVENTIONS,
    N_CROSSFIT_FOLDS,
    TRIAL_CONFOUNDERS,
    TRIALS,
    WEEKLY_GRID_DAYS,
)
from mortality_pipeline.estimators import (
    add_evalue, aipw_ate, crossfit_nuisances, crossfit_propensity,
)
from mortality_pipeline.trials import load_trial

_INTV = {i.key: i for i in INTERVENTIONS}
TRAJECTORY_PARQUET = DIR2RESULTS_TRIALS / "trajectory.parquet"
MONITOR_TRAJECTORY_JSON = DIR2RESULTS_TRIALS / "monitor_trajectory.json"


def run_trajectory(
    interventions: Optional[List[str]] = None,
    cohort: str = "equipoise",
    weeks: Optional[List[int]] = None,
    learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS,
    rebuild: bool = False,
    save: bool = True,
) -> pd.DataFrame:
    cfgs = [c for c in TRIALS if (interventions is None or c.key in interventions)]
    weeks = weeks or WEEKLY_GRID_DAYS
    conf = TRIAL_CONFOUNDERS
    rows = []

    for cfg in cfgs:
        df = load_trial(cfg.key, rebuild=rebuild)
        cdf = df[df["equipoise"] == 1] if cohort == "equipoise" else df
        if cdf["treated"].sum() < 50 or (cdf["treated"] == 0).sum() < 50:
            logger.warning(f"  {cfg.key}/{cohort}: too few in an arm; skipping trajectory")
            continue
        X = cdf[conf]
        A = cdf["treated"].to_numpy(int)
        died = cdf["died"].to_numpy(int)
        ttd = cdf["days_to_death"].to_numpy(float)
        fup = cdf["followup_days"].to_numpy(float)
        e = crossfit_propensity(X, A, learner=learner, n_folds=n_folds)
        logger.info(f"▶ Trajectory {cfg.key} [{cohort}] n={len(cdf):,} treated={int(A.sum()):,}")

        for t in weeks:
            died_by = (died == 1) & (ttd <= t)
            censored = (died == 0) & (fup < t)         # follow-up ends before t
            keep = ~censored
            if keep.sum() < 100:
                continue
            Yt = died_by[keep].astype(float)
            r = add_evalue(aipw_ate(A[keep], Yt, crossfit_nuisances(
                X[keep], A[keep], Yt, learner=learner, n_folds=n_folds,
                precomputed_e=e[keep])))
            ey1 = r.get("counterfactual_risk_treated", np.nan)
            ey0 = r.get("counterfactual_risk_control", np.nan)
            rows.append({
                "intervention": cfg.key, "cohort": cohort, "week": t // 7, "day": t,
                "rd_pp": round(r["ate_pct"], 3),
                "ci_low": round(r["ci_low"] * 100, 3), "ci_high": round(r["ci_high"] * 100, 3),
                "p_value": r["p_value"],
                "risk_treated": round(float(ey1), 4), "risk_control": round(float(ey0), 4),
                "surv_treated": round(1 - float(ey1), 4), "surv_control": round(1 - float(ey0), 4),
                "risk_ratio": r.get("risk_ratio"), "e_value": r.get("e_value"),
                "n": int(keep.sum()), "n_treated": int(A[keep].sum()),
                "censored_frac": round(float(censored.mean()), 4),
            })
            logger.info(f"    d{t:>3}: RD {r['ate_pct']:+6.2f}pp "
                        f"[{r['ci_low']*100:+.2f},{r['ci_high']*100:+.2f}] "
                        f"S1={1-ey1:.3f} S0={1-ey0:.3f} cens={censored.mean()*100:.1f}%")

    traj = pd.DataFrame(rows)
    if save and len(traj):
        DIR2RESULTS_TRIALS.mkdir(parents=True, exist_ok=True)
        traj.to_parquet(TRAJECTORY_PARQUET)
        MONITOR_TRAJECTORY_JSON.write_text(json.dumps(build_trajectory_json(traj), indent=2))
        logger.info(f"Saved trajectory ({len(traj)} rows) → {TRAJECTORY_PARQUET}")
    return traj


def _trend(rd: List[float]) -> str:
    """Classify the trajectory shape of the risk difference over weeks."""
    if len(rd) < 2:
        return "flat"
    a, b = rd[0], rd[-1]
    if np.sign(a) != np.sign(b) and abs(b) > 0.5 and abs(a) > 0.5:
        return "reversing"
    if abs(b) > abs(a) * 1.25 + 0.5:
        return "growing"
    if abs(b) < abs(a) * 0.75 - 0.5:
        return "attenuating"
    return "stable"


def build_trajectory_json(traj: pd.DataFrame) -> dict:
    cards = []
    for key in traj["intervention"].unique():
        s = traj[traj["intervention"] == key].sort_values("day")
        rd = s["rd_pp"].tolist()
        trend = _trend(rd)
        last = s.iloc[-1]
        cards.append({
            "key": key,
            "label": _INTV[key].label if key in _INTV else key,
            "plain": _INTV[key].plain if key in _INTV else key,
            "cohort": last["cohort"],
            "trend": trend,
            "headline": _traj_headline(key, s, trend),
            "series": [
                {"day": int(r.day), "week": int(r.week), "rd_pp": r.rd_pp,
                 "ci": [r.ci_low, r.ci_high],
                 "surv_treated": r.surv_treated, "surv_control": r.surv_control}
                for r in s.itertuples()
            ],
        })
    return {
        "artifact": "intervention_mortality_trajectory",
        "grid_days": sorted(traj["day"].unique().tolist()),
        "method": "weekly cross-fit AIPW on the equipoise cohort (all-cause mortality from t0)",
        "interventions": cards,
        "interpretation_note": (
            "Each point is the doubly-robust difference in cumulative mortality by "
            "that day between treated and untreated, within the clinical-equipoise "
            "cohort, adjusted for pre-treatment baseline. Trends are descriptive."
        ),
    }


def _traj_headline(key: str, s: pd.DataFrame, trend: str) -> str:
    plain = _INTV[key].plain if key in _INTV else key
    first, last = s.iloc[0], s.iloc[-1]
    verb = {"growing": "widens", "attenuating": "narrows", "reversing": "reverses",
            "stable": "stays steady", "flat": "is flat"}[trend]
    return (f"For {plain}, the mortality gap {verb} over time — "
            f"{first['rd_pp']:+.1f} per 100 by day {int(first['day'])} → "
            f"{last['rd_pp']:+.1f} by day {int(last['day'])}.")


def load_trajectory() -> pd.DataFrame:
    if not TRAJECTORY_PARQUET.exists():
        raise FileNotFoundError(f"No trajectory at {TRAJECTORY_PARQUET}; run it first.")
    return pd.read_parquet(TRAJECTORY_PARQUET)
