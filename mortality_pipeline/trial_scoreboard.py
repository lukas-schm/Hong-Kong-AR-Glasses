"""
Run the target-trial estimators (P1 cohorts + P2 estimands) into a tidy board.

For each intervention we estimate the effect on each mortality outcome in two
populations — the **full** target-trial cohort and the **equipoise** sub-cohort —
with five estimators: unadjusted, truncated IPTW, doubly-robust AIPW (ATE), ATT
and overlap-weighted ATO. The equipoise + AIPW/ATO cells are the credible
headline; the full-cohort + unadjusted cells are the contrast that shows why the
restriction and adjustment matter.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    DIR2RESULTS_TRIALS,
    MORTALITY_OUTCOMES,
    N_CROSSFIT_FOLDS,
    TRIAL_CONFOUNDERS,
    TRIALS,
)
from mortality_pipeline.estimators import (
    add_evalue,
    aipw_ate,
    ato_ipw,
    att_aipw,
    crossfit_nuisances,
    crossfit_propensity,
    iptw_ate,
    overlap_diagnostics,
    unadjusted_rd,
)
from mortality_pipeline.trials import load_trial

BOARD_PARQUET = DIR2RESULTS_TRIALS / "trial_scoreboard.parquet"
BOARD_CSV = DIR2RESULTS_TRIALS / "trial_scoreboard.csv"


def _estimate_cell(
    df: pd.DataFrame, outcome: str, confounders: List[str],
    learner: str, n_folds: int, precomputed_e: Optional[np.ndarray], cohort: str,
) -> List[dict]:
    mask = df[outcome].notna()
    sub = df.loc[mask]
    X = sub[confounders]
    A = sub["treated"].to_numpy(int)
    Y = sub[outcome].to_numpy(float)
    if A.sum() < 50 or (A == 0).sum() < 50:
        return []

    e_sub = None
    if precomputed_e is not None:
        pe = np.asarray(precomputed_e, float)
        e_sub = pe[mask.to_numpy()] if len(pe) == len(df) else (pe if len(pe) == len(sub) else None)

    nuis = crossfit_nuisances(X, A, Y, learner=learner, n_folds=n_folds, precomputed_e=e_sub)
    rows = [
        unadjusted_rd(A, Y),
        iptw_ate(A, Y, nuis["e"]),
        add_evalue(aipw_ate(A, Y, nuis)),
        att_aipw(A, Y, nuis),
        ato_ipw(A, Y, nuis["e"]),
    ]
    diag = overlap_diagnostics(X, A, nuis["e"])
    meta = {
        "cohort": cohort, "outcome": outcome, "n": int(len(Y)),
        "n_treated": int(A.sum()), "n_control": int((A == 0).sum()),
        "outcome_rate": float(np.mean(Y)),
    }
    for r in rows:
        r.update(meta)
        r.update({f"diag_{k}": v for k, v in diag.items()})
        r.pop("_ey0", None)
    return rows


def run_trial_scoreboard(
    interventions: Optional[List[str]] = None,
    outcomes: Optional[List[str]] = None,
    learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS,
    rebuild: bool = False,
    save: bool = True,
) -> pd.DataFrame:
    cfgs = [c for c in TRIALS if (interventions is None or c.key in interventions)]
    outcomes = outcomes or [o.key for o in MORTALITY_OUTCOMES]
    conf = TRIAL_CONFOUNDERS
    all_rows = []

    for cfg in cfgs:
        df = load_trial(cfg.key, rebuild=rebuild)
        for cohort, cdf in [("full", df), ("equipoise", df[df["equipoise"] == 1])]:
            if cdf["treated"].sum() < 50 or (cdf["treated"] == 0).sum() < 50:
                logger.warning(f"  {cfg.key}/{cohort}: too few in an arm; skipping")
                continue
            e_full = crossfit_propensity(cdf[conf], cdf["treated"].to_numpy(int),
                                         learner=learner, n_folds=n_folds)
            for outcome in outcomes:
                rows = _estimate_cell(cdf, outcome, conf, learner, n_folds, e_full, cohort)
                for r in rows:
                    r["intervention"] = cfg.key
                    r["equipoise_def"] = cfg.equipoise
                all_rows.extend(rows)
                aipw = next((r for r in rows if r["method"] == "aipw"), None)
                ato = next((r for r in rows if r["method"] == "ato"), None)
                if aipw:
                    logger.info(
                        f"  {cfg.key:<28} {cohort:<9} {outcome:<22} "
                        f"AIPW {aipw['ate_pct']:+6.2f} [{aipw['ci_low']*100:+.2f},{aipw['ci_high']*100:+.2f}] "
                        f"E={aipw.get('e_value', float('nan')):.2f} "
                        f"ATO {ato['ate_pct']:+6.2f} SMDw={aipw.get('diag_max_smd_weighted', float('nan')):.2f}")

    board = pd.DataFrame(all_rows)
    if save and len(board):
        DIR2RESULTS_TRIALS.mkdir(parents=True, exist_ok=True)
        board.to_parquet(BOARD_PARQUET)
        board.to_csv(BOARD_CSV, index=False)
        logger.info(f"Saved trial scoreboard ({len(board)} rows) → {BOARD_PARQUET}")
    return board


def load_trial_scoreboard() -> pd.DataFrame:
    if not BOARD_PARQUET.exists():
        raise FileNotFoundError(f"No trial scoreboard at {BOARD_PARQUET}; run the pipeline.")
    return pd.read_parquet(BOARD_PARQUET)
