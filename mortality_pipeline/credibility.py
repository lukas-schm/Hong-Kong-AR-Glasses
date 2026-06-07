"""
P4 — credibility suite: does each effect survive falsification and external checks?

A well-balanced doubly-robust estimate can still be wrong (residual / time-varying
confounding by indication). This module *stress-tests* each headline estimate:

  1. **Permutation placebo** (negative-control treatment) — shuffle the treatment
     label and re-estimate. A randomised "treatment" cannot cause anything, so the
     placebo RD should be ≈0; a non-zero placebo RD measures residual structural
     bias of the whole estimation procedure.
  2. **Random common cause** — add a pure-noise covariate; the estimate must not move.
  3. **Subset stability** — re-estimate on random subsets; the estimate must be stable.
  4. **Negative-control outcome** — estimate the same effect on an outcome the
     treatment should not cause (pressure injury). A large NCO effect flags residual
     confounding (imperfect NCO — shares an immobility pathway with ventilation).
  5. **RCT benchmark** — compare direction/magnitude to randomised-trial evidence.
     Discordance with trials is the strongest available signal that an observational
     effect is confounded.

The output is a per-intervention **credibility verdict** that contextualises (and
usually tempers) the identification-confidence label from the scoreboard.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    DIR2RESULTS_TRIALS, DUCKDB_PATH, PRIMARY_OUTCOME, RANDOM_STATE,
    TRIAL_CONFOUNDERS, TRIALS, TRIAL_BY_KEY,
)
from mortality_pipeline.estimators import aipw_ate, crossfit_nuisances, crossfit_propensity
from mortality_pipeline.trials import load_trial

CREDIBILITY_JSON = DIR2RESULTS_TRIALS / "credibility.json"
_REFUTER_FOLDS = 3      # lighter cross-fitting for the (many) refuter re-fits


# ── RCT benchmark priors (encoded from the trial literature) ────────────────
@dataclass(frozen=True)
class RCTBenchmark:
    benchmarkable: bool
    direction: Optional[str]      # 'null' | 'benefit' | 'harm' | None
    rd_approx_pp: Optional[float] # approximate trial risk difference (deaths/100), if any
    source: str


RCT_BENCHMARKS: Dict[str, RCTBenchmark] = {
    # No RCT randomises the life-support itself vs nothing → not benchmarkable.
    "intv_vasopressors": RCTBenchmark(False, None, None,
        "No RCT of vasopressors vs none; vasopressin add-on neutral (VASST, VANISH)."),
    "intv_mechanical_ventilation": RCTBenchmark(False, None, None,
        "No ethical RCT of invasive ventilation vs none."),
    # Early-vs-late RRT: no mortality benefit in the large multicentre trials.
    "intv_rrt": RCTBenchmark(True, "null", 0.0,
        "Early vs delayed RRT: no mortality difference (AKIKI, IDEAL-ICU, STARRT-AKI); "
        "ELAIN single-centre benefit. Trial RD ≈ 0."),
    # Septic-shock steroids: null to small benefit, never harm.
    "intv_corticosteroids": RCTBenchmark(True, "null", -2.0,
        "Septic shock: ADRENAL neutral on 90d mortality; APROCCHSS ≈ -2.6pp 90d. "
        "Trial RD ≈ 0 to slightly protective."),
    "intv_antibiotics": RCTBenchmark(False, None, None,
        "No RCT of antibiotics vs none in infection (unethical); observational early-abx benefit."),
}


# ── core re-estimation helper ───────────────────────────────────────────────
def _aipw_rd(X: pd.DataFrame, A: np.ndarray, Y: np.ndarray,
             folds: int = _REFUTER_FOLDS, e: Optional[np.ndarray] = None) -> float:
    nuis = crossfit_nuisances(X, A, Y, n_folds=folds, precomputed_e=e)
    return float(aipw_ate(A, Y, nuis)["ate_pct"])


def _equipoise_frame(key: str, outcome: str = PRIMARY_OUTCOME):
    """Mirror the scoreboard's headline cohort: equipoise if it has a valid two-arm
    contrast (≥50 each), else the full target-trial cohort (e.g. antibiotics)."""
    cfg = TRIAL_BY_KEY[key]
    df = load_trial(key)
    eq = df[df["equipoise"] == 1]
    sub = eq[eq[outcome].notna()]
    if sub["treated"].sum() >= 50 and (sub["treated"] == 0).sum() >= 50:
        return eq, "equipoise", cfg
    return df, "full", cfg


# ── refuters ────────────────────────────────────────────────────────────────
def permutation_placebo(X, A, Y, base_rd, n_perm=8) -> Dict:
    rng = np.random.RandomState(RANDOM_STATE)
    placebo = []
    for _ in range(n_perm):
        A_perm = rng.permutation(A)
        placebo.append(_aipw_rd(X, A_perm, Y))
    placebo = np.array(placebo)
    # pass if the real effect is far outside the placebo distribution AND placebo ≈ 0
    p_exceed = float(np.mean(np.abs(placebo) >= abs(base_rd)))
    return {
        "placebo_rd_mean": round(float(placebo.mean()), 3),
        "placebo_rd_sd": round(float(placebo.std()), 3),
        "placebo_abs_max": round(float(np.abs(placebo).max()), 3),
        "p_exceed_real": p_exceed,                 # fraction of placebos ≥ |real|
        "pass": bool(abs(placebo.mean()) < 1.0 and p_exceed <= 0.1),
    }


def random_common_cause(X, A, Y, base_rd) -> Dict:
    rng = np.random.RandomState(RANDOM_STATE + 1)
    Xn = X.copy()
    Xn["_rcc_noise"] = rng.normal(size=len(X))
    rd = _aipw_rd(Xn, A, Y)
    return {"rcc_rd": round(rd, 3), "shift": round(rd - base_rd, 3),
            "pass": bool(abs(rd - base_rd) <= max(0.5, 0.1 * abs(base_rd)))}


def subset_stability(X, A, Y, base_rd, frac=0.7, n=4) -> Dict:
    rng = np.random.RandomState(RANDOM_STATE + 2)
    rds = []
    idx = np.arange(len(Y))
    for _ in range(n):
        s = rng.choice(idx, size=int(frac * len(idx)), replace=False)
        rds.append(_aipw_rd(X.iloc[s], A[s], Y[s]))
    rds = np.array(rds)
    return {"subset_rd_mean": round(float(rds.mean()), 3), "subset_rd_sd": round(float(rds.std()), 3),
            "pass": bool(rds.std() <= max(1.0, 0.25 * abs(base_rd)))}


def negative_control_outcome(cdf: pd.DataFrame, confounders: List[str], con) -> Dict:
    """Estimate the effect on pressure injury (an outcome the acute treatment
    should not cause). Imperfect NCO — interpret a large effect as residual-
    confounding evidence, not proof."""
    pi = con.execute("""
        SELECT DISTINCT hadm_id, 1 AS nco_pressure_injury FROM mimiciv_hosp.diagnoses_icd
        WHERE icd_code LIKE 'L89%' OR icd_code LIKE '7070%'""").fetch_df()
    d = cdf.merge(pi, on="hadm_id", how="left")
    d["nco_pressure_injury"] = d["nco_pressure_injury"].fillna(0).astype(float)
    X = d[confounders]; A = d["treated"].to_numpy(int); Y = d["nco_pressure_injury"].to_numpy(float)
    if Y.sum() < 50:
        return {"nco": "pressure_injury", "nco_prevalence": float(Y.mean()), "skipped": True}
    rd = _aipw_rd(X, A, Y)
    return {"nco": "pressure_injury", "nco_prevalence": round(float(Y.mean()), 3),
            "nco_rd": round(rd, 3), "pass": bool(abs(rd) < 2.0)}


def rct_benchmark(key: str, base_rd: float, ci: List[float]) -> Dict:
    b = RCT_BENCHMARKS[key]
    out = {"benchmarkable": b.benchmarkable, "source": b.source,
           "trial_direction": b.direction, "trial_rd_pp": b.rd_approx_pp}
    if not b.benchmarkable:
        out["concordant"] = None
        out["note"] = "No randomised benchmark exists for this contrast."
        return out
    lo, hi = ci
    concordant = (b.rd_approx_pp is not None) and (lo <= b.rd_approx_pp <= hi)
    out["concordant"] = bool(concordant)
    out["note"] = (
        f"Trial RD≈{b.rd_approx_pp:+.0f}pp ({b.direction}); our 95% CI [{lo:+.1f},{hi:+.1f}] "
        + ("includes it → concordant." if concordant
           else "excludes it → DISCORDANT (observational effect likely confounded).")
    )
    return out


def _verdict(checks: Dict) -> str:
    estimator_ok = checks["placebo"]["pass"] and checks["random_common_cause"]["pass"] and checks["subset"]["pass"]
    nco = checks.get("nco", {})
    nco_ok = nco.get("pass", True)
    rct = checks["rct"]
    if not estimator_ok:
        return "estimator-invalid (refuters failed) — do not trust"
    if rct.get("concordant") is False:
        return "RCT-discordant — effect likely inflated by residual confounding"
    if not nco_ok:
        return "negative-control non-null — residual confounding likely"
    if rct.get("benchmarkable"):
        return "corroborated (refuters pass, NCO ~null, RCT-concordant)"
    return "internally valid; not externally benchmarkable (no RCT) — treat as hypothesis"


def run_credibility(interventions: Optional[List[str]] = None,
                    outcome: str = PRIMARY_OUTCOME, n_perm: int = 8, save: bool = True) -> Dict:
    from mortality_pipeline.trial_scoreboard import load_trial_scoreboard
    board = load_trial_scoreboard()
    keys = interventions or [t.key for t in TRIALS]
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    results = {}
    try:
        for key in keys:
            cdf, cohort, cfg = _equipoise_frame(key)
            sub = cdf[cdf[outcome].notna()]
            if sub["treated"].sum() < 50 or (sub["treated"] == 0).sum() < 50:
                logger.warning(f"  {key}: too few for credibility; skipping"); continue
            X = sub[TRIAL_CONFOUNDERS]; A = sub["treated"].to_numpy(int); Y = sub[outcome].to_numpy(float)
            # base estimate from the saved board (equipoise/full AIPW, primary outcome)
            row = board[(board.intervention == key) & (board.cohort == cohort)
                        & (board.method == "aipw") & (board.outcome == outcome)]
            if row.empty:
                base_rd = _aipw_rd(X, A, Y); ci = [base_rd - 2, base_rd + 2]
            else:
                base_rd = float(row.iloc[0]["ate_pct"])
                ci = [float(row.iloc[0]["ci_low"] * 100), float(row.iloc[0]["ci_high"] * 100)]

            logger.info(f"▶ Credibility {key} [{cohort}] base RD={base_rd:+.2f}pp — running refuters")
            checks = {
                "base_rd_pp": round(base_rd, 3), "ci": [round(ci[0], 2), round(ci[1], 2)],
                "cohort": cohort,
                "placebo": permutation_placebo(X, A, Y, base_rd, n_perm=n_perm),
                "random_common_cause": random_common_cause(X, A, Y, base_rd),
                "subset": subset_stability(X, A, Y, base_rd),
                "nco": negative_control_outcome(sub, TRIAL_CONFOUNDERS, con),
                "rct": rct_benchmark(key, base_rd, ci),
            }
            checks["verdict"] = _verdict(checks)
            results[key] = checks
            logger.info(f"    placebo μ={checks['placebo']['placebo_rd_mean']:+.2f} "
                        f"(pass={checks['placebo']['pass']}) | NCO RD={checks['nco'].get('nco_rd','—')} "
                        f"| RCT {checks['rct'].get('concordant')} | {checks['verdict']}")
    finally:
        con.close()

    out = {"artifact": "intervention_mortality_credibility", "outcome": outcome, "interventions": results}
    if save:
        DIR2RESULTS_TRIALS.mkdir(parents=True, exist_ok=True)
        CREDIBILITY_JSON.write_text(json.dumps(out, indent=2))
        logger.info(f"Saved credibility → {CREDIBILITY_JSON}")
    return out


if __name__ == "__main__":
    run_credibility()
