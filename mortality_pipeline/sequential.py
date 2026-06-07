"""
Time-varying design — **sequential target-trial emulation** with time-updated
confounders. The fix for the binding limitation P3/P4 exposed: confounding by
indication that *evolves after the 6 h baseline*.

Idea (Hernán's sequential trials): discretise the ICU stay into decision blocks.
At each block, among patients still **alive, in-ICU and untreated**, contrast
those who **initiate now** vs those who **defer**, adjusting for physiology
measured *up to that block* (cumulative-to-decision LOCF) plus time-varying
co-treatments and time-in-ICU. Stack all blocks and estimate one pooled
doubly-robust effect with **subject-clustered** standard errors (patients recur
across blocks until they initiate or leave the risk set).

Because the adjustment set now contains the deterioration that precedes the
treatment decision, the estimate should move toward the randomised-trial benchmark
if the static effect was inflated by time-varying confounding. We report
static vs sequential vs RCT side by side.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    ALPHA, DIR2RESULTS_TRIALS, DUCKDB_PATH, RANDOM_STATE, TRIALS, TRIAL_BY_KEY,
)
from mortality_pipeline.estimators import crossfit_nuisances
from mortality_pipeline.trials import _start_times, load_trial
from scipy.stats import norm

_Z = norm.ppf(1 - ALPHA / 2)
SEQUENTIAL_JSON = DIR2RESULTS_TRIALS / "sequential.json"

# Baseline-fixed confounders carried from the trial table.
_FIXED = ["admission_age", "female", "charlson_comorbidity_index",
          "surgical_admission", "elective_admission", "sepsis3", "aki_stage_max"]
# Time-updated (cumulative-to-block) physiology. (col, source, agg)
_TV_PHYS = [
    ("mbp", "vitalsign", "min"), ("heart_rate", "vitalsign", "max"),
    ("spo2", "vitalsign", "min"), ("resp_rate", "vitalsign", "max"),
    ("lactate", "bg", "max"), ("creatinine", "chemistry", "max"), ("bun", "chemistry", "max"),
]
# index treatment → its own onset marker (excluded from co-treatment confounders)
_OWN_MARKER = {"intv_vasopressors": "on_vaso", "intv_mechanical_ventilation": "on_vent"}


def _phys_long(con, src: str, col: str, stays, hadms, max_h: int) -> pd.DataFrame:
    """Pull one physiology column with hours-since-intime, within the first max_h."""
    if src == "vitalsign":
        q = f"""SELECT v.stay_id, date_diff('minute', d.icu_intime, v.charttime)/60.0 AS hour,
                       v.{col} AS val
                FROM mimiciv_derived.vitalsign v
                JOIN mimiciv_derived.icustay_detail d ON d.stay_id = v.stay_id
                WHERE v.stay_id IN ({stays}) AND v.{col} IS NOT NULL
                  AND v.charttime BETWEEN d.icu_intime AND d.icu_intime + INTERVAL '{max_h} hours'"""
    else:  # hadm-keyed labs (bg, chemistry)
        q = f"""SELECT d.stay_id, date_diff('minute', d.icu_intime, m.charttime)/60.0 AS hour,
                       m.{col} AS val
                FROM mimiciv_derived.{src} m
                JOIN mimiciv_derived.icustay_detail d ON d.hadm_id = m.hadm_id
                WHERE d.hadm_id IN ({hadms}) AND m.{col} IS NOT NULL AND d.first_icu_stay
                  AND m.charttime BETWEEN d.icu_intime AND d.icu_intime + INTERVAL '{max_h} hours'"""
    return con.execute(q).fetch_df()


def build_person_time(cfg, block_h: int = 6, max_h: Optional[int] = None,
                      horizon_d: int = 28) -> pd.DataFrame:
    """Construct the stacked sequential-trials person-time table for one intervention."""
    max_h = max_h or min(168, cfg.grace_hours + 48)
    trial = load_trial(cfg.key)
    coh = trial[trial["equipoise"] == 1].copy()
    if len(coh) < 200:
        coh = trial.copy()
    keep_fixed = [c for c in _FIXED if c in coh.columns]
    coh = coh[["subject_id", "hadm_id", "stay_id", *keep_fixed]].drop_duplicates("stay_id")

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        stay_list = ",".join(map(str, coh["stay_id"].tolist()))
        hadm_list = ",".join(map(str, coh["hadm_id"].unique().tolist()))
        times = con.execute(f"""
            SELECT stay_id, icu_intime, icu_outtime, dod
            FROM mimiciv_derived.icustay_detail WHERE stay_id IN ({stay_list})""").fetch_df()
        onset = _start_times(con, cfg.start_source).rename(columns={"t0_treat": "treat_h"})
        vent = _start_times(con, "invasive_vent").rename(columns={"t0_treat": "vent_t"})
        vaso = _start_times(con, "vasoactive").rename(columns={"t0_treat": "vaso_t"})
        phys = {f"{col}_tv": _phys_long(con, src, col, stay_list, hadm_list, max_h)
                for (col, src, agg) in _TV_PHYS}
    finally:
        con.close()

    df = coh.merge(times, on="stay_id", how="inner")
    for c in ["icu_intime", "icu_outtime", "dod"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for name, frame, tcol in [("treat", onset, "treat_h"), ("vent", vent, "vent_t"), ("vaso", vaso, "vaso_t")]:
        df = df.merge(frame, on="stay_id", how="left")
        df[f"{name}_hour"] = (pd.to_datetime(df[tcol]) - df["icu_intime"]).dt.total_seconds() / 3600.0
        df = df.drop(columns=[tcol])
    df["death_hour"] = (df["dod"] - df["icu_intime"]).dt.total_seconds() / 3600.0
    df["dc_hour"] = (df["icu_outtime"] - df["icu_intime"]).dt.total_seconds() / 3600.0

    # cumulative-to-hour step functions for each physiology var (per stay)
    cum = {}
    for name, (col, src, agg) in zip(phys.keys(), _TV_PHYS):
        p = phys[name].sort_values(["stay_id", "hour"])
        p["cum"] = (p.groupby("stay_id")["val"].cummax() if agg == "max"
                    else p.groupby("stay_id")["val"].cummin())
        cum[name] = p[["stay_id", "hour", "cum"]].rename(columns={"cum": name})

    blocks = list(range(0, max_h, block_h))
    rows = []
    own = _OWN_MARKER.get(cfg.key)
    for k in blocks:
        bt = k                                   # decision time = intime + k hours
        at_risk = (
            ((df["treat_hour"].isna()) | (df["treat_hour"] >= bt))    # untreated at block start
            & ((df["death_hour"].isna()) | (df["death_hour"] > bt))   # alive
            & (df["dc_hour"] > bt)                                    # still in ICU
        )
        sub = df[at_risk].copy()
        if len(sub) < 50:
            continue
        sub["k"] = k
        sub["hours_k"] = float(k)
        sub["treated_now"] = ((sub["treat_hour"] >= bt) & (sub["treat_hour"] < bt + block_h)).astype(int)
        # outcome: death within horizon_d of the decision time
        horizon_h = bt + horizon_d * 24
        sub["Y"] = ((sub["death_hour"].notna()) & (sub["death_hour"] <= horizon_h)).astype(int)
        # time-varying co-treatments already started by the decision
        sub["on_vent"] = (sub["vent_hour"] <= bt).fillna(False).astype(int)
        sub["on_vaso"] = (sub["vaso_hour"] <= bt).fillna(False).astype(int)
        rows.append(sub)

    pt = pd.concat(rows, ignore_index=True)

    # attach cumulative-to-k physiology via as-of merge (latest value at hour ≤ k)
    pt["k"] = pt["k"].astype(float)
    pt = pt.sort_values("k")
    for name in cum:
        right = cum[name].sort_values("hour")
        pt = pd.merge_asof(pt, right, by="stay_id", left_on="k", right_on="hour",
                           direction="backward")
        pt = pt.drop(columns=["hour"])

    co_treat = [m for m in ["on_vent", "on_vaso"] if m != own]
    confounders = keep_fixed + ["hours_k"] + list(cum.keys()) + co_treat
    pt.attrs["confounders"] = confounders
    logger.info(f"  person-time: {len(pt):,} rows, {pt['stay_id'].nunique():,} subjects, "
                f"{int(pt['treated_now'].sum()):,} initiations, {int(pt['Y'].sum()):,} deaths-in-window; "
                f"{len(confounders)} confounders")
    return pt


def estimate_sequential(pt: pd.DataFrame, confounders: List[str],
                        learner: str = "hgb", n_folds: int = 5) -> Dict:
    """Pooled doubly-robust effect of initiate-now vs defer, subject-clustered SE."""
    X = pt[confounders]
    A = pt["treated_now"].to_numpy(int)
    Y = pt["Y"].to_numpy(float)
    nuis = crossfit_nuisances(X, A, Y, learner=learner, n_folds=n_folds)
    e = np.clip(nuis["e"], 0.02, 0.98)
    mu1, mu0 = nuis["mu1"], nuis["mu0"]
    psi = (mu1 - mu0) + A * (Y - mu1) / e - (1 - A) * (Y - mu0) / (1 - e)
    ate = float(psi.mean())
    # subject-clustered influence-function variance
    centered = pd.Series(psi - ate)
    g = centered.groupby(pt["subject_id"].to_numpy()).sum()
    var = float((g ** 2).sum()) / len(psi) ** 2
    se = float(np.sqrt(var))
    return {
        "rd_pp": round(ate * 100, 3),
        "ci_low": round((ate - _Z * se) * 100, 3),
        "ci_high": round((ate + _Z * se) * 100, 3),
        "se_pp": round(se * 100, 3),
        "n_rows": int(len(pt)), "n_subjects": int(pt["subject_id"].nunique()),
        "n_initiations": int(A.sum()), "n_events": int(Y.sum()),
    }


def run_sequential(interventions: Optional[List[str]] = None, horizon_d: int = 28,
                   block_h: int = 6, learner: str = "hgb", save: bool = True) -> Dict:
    from mortality_pipeline.credibility import RCT_BENCHMARKS
    from mortality_pipeline.trial_scoreboard import load_trial_scoreboard
    board = load_trial_scoreboard()
    keys = interventions or [t.key for t in TRIALS]
    out = {}
    for key in keys:
        cfg = TRIAL_BY_KEY[key]
        logger.info(f"▶ Sequential trials: {key} (block={block_h}h, horizon={horizon_d}d)")
        pt = build_person_time(cfg, block_h=block_h, horizon_d=horizon_d)
        if pt["treated_now"].sum() < 50:
            logger.warning(f"  {key}: too few initiations; skipping"); continue
        seq = estimate_sequential(pt, pt.attrs["confounders"], learner=learner)

        # static comparator: equipoise (else full) AIPW at the matching horizon
        out_col = f"mortality_{horizon_d}d" if horizon_d in (28, 90) else "mortality_in_hospital"
        for cohort in ("equipoise", "full"):
            r = board[(board.intervention == key) & (board.cohort == cohort)
                      & (board.method == "aipw") & (board.outcome == out_col)]
            if not r.empty:
                static_rd = float(r.iloc[0]["ate_pct"]); static_cohort = cohort; break
        else:
            static_rd = float("nan"); static_cohort = "—"

        rct = RCT_BENCHMARKS.get(key)
        attenuation = (None if not np.isfinite(static_rd) or static_rd == 0
                       else round((1 - seq["rd_pp"] / static_rd) * 100, 0))
        moved_toward_rct = None
        if rct and rct.benchmarkable and rct.rd_approx_pp is not None and np.isfinite(static_rd):
            moved_toward_rct = bool(abs(seq["rd_pp"] - rct.rd_approx_pp) < abs(static_rd - rct.rd_approx_pp))

        out[key] = {
            "static_rd_pp": round(static_rd, 2), "static_cohort": static_cohort,
            "sequential": seq,
            "attenuation_pct": attenuation,
            "rct_rd_pp": (rct.rd_approx_pp if rct else None),
            "rct_benchmarkable": (rct.benchmarkable if rct else None),
            "moved_toward_rct": moved_toward_rct,
            "outcome": out_col, "horizon_d": horizon_d,
        }
        logger.info(f"    static {static_rd:+.2f}pp ({static_cohort}) → sequential "
                    f"{seq['rd_pp']:+.2f}pp [{seq['ci_low']:+.2f},{seq['ci_high']:+.2f}] "
                    f"| attenuation {attenuation}% | toward RCT: {moved_toward_rct}")

    result = {"artifact": "intervention_mortality_sequential", "horizon_d": horizon_d,
              "block_hours": block_h, "interventions": out}
    if save:
        DIR2RESULTS_TRIALS.mkdir(parents=True, exist_ok=True)
        SEQUENTIAL_JSON.write_text(json.dumps(result, indent=2))
        logger.info(f"Saved sequential → {SEQUENTIAL_JSON}")
    return result


if __name__ == "__main__":
    run_sequential()
