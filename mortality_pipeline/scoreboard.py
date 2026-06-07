"""
Run the causal-ML estimators across the whole intervention panel × mortality
outcomes and assemble the tidy "intervention scoreboard".

For each intervention the (outcome-independent) cross-fitted propensity is
computed once and reused across its three mortality horizons, so the full
panel runs in a few minutes.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    CONFOUNDER_KEYS,
    DIR2RESULTS_MORTALITY,
    INTERVENTION_KEYS,
    N_CROSSFIT_FOLDS,
)
from mortality_pipeline.constants import MORTALITY_OUTCOMES
from mortality_pipeline.estimators import (
    crossfit_propensity,
    estimate_intervention_effect,
)

SCOREBOARD_PARQUET = DIR2RESULTS_MORTALITY / "scoreboard.parquet"
SCOREBOARD_CSV = DIR2RESULTS_MORTALITY / "scoreboard.csv"


def run_scoreboard(
    df: pd.DataFrame,
    interventions: Optional[List[str]] = None,
    outcomes: Optional[List[str]] = None,
    confounders: Optional[List[str]] = None,
    learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS,
    save: bool = True,
) -> pd.DataFrame:
    """Estimate every (intervention × outcome × method) cell → tidy DataFrame."""
    interventions = interventions or INTERVENTION_KEYS
    outcomes = outcomes or [o.key for o in MORTALITY_OUTCOMES]
    confounders = confounders or CONFOUNDER_KEYS

    all_rows = []
    for intv in interventions:
        logger.info(f"▶ Intervention: {intv}  (learner={learner})")
        # outcome-independent propensity, computed once over the full cohort
        A_full = df[intv].to_numpy(int)
        e_full = crossfit_propensity(df[confounders], A_full, learner=learner, n_folds=n_folds)
        logger.info(f"    propensity cross-fit done "
                    f"(treated={int(A_full.sum()):,} / {len(A_full):,})")

        for outcome in outcomes:
            res = estimate_intervention_effect(
                df, intv, outcome, confounders=confounders,
                learner=learner, n_folds=n_folds, precomputed_e=e_full,
            )
            for r in res["rows"]:
                all_rows.append(r)
            aipw = next((r for r in res["rows"] if r["method"] == "aipw"), None)
            if aipw:
                logger.info(
                    f"    {outcome:<22} AIPW {aipw['ate_pct']:+6.2f}pp "
                    f"[{aipw['ci_low']*100:+6.2f},{aipw['ci_high']*100:+6.2f}] "
                    f"E={aipw.get('e_value', float('nan')):.2f}"
                )

    board = pd.DataFrame(all_rows)
    board = _order_columns(board)

    if save and len(board):
        DIR2RESULTS_MORTALITY.mkdir(parents=True, exist_ok=True)
        board.to_parquet(SCOREBOARD_PARQUET)
        board.to_csv(SCOREBOARD_CSV, index=False)
        logger.info(f"Saved scoreboard ({len(board)} rows) → {SCOREBOARD_PARQUET}")
    return board


def _order_columns(board: pd.DataFrame) -> pd.DataFrame:
    lead = [
        "intervention", "outcome", "method", "ate_pct", "ci_low", "ci_high",
        "se", "p_value", "risk_ratio", "e_value", "e_value_ci",
        "n", "n_treated", "n_control", "outcome_rate",
        "counterfactual_risk_treated", "counterfactual_risk_control",
    ]
    cols = [c for c in lead if c in board.columns]
    cols += [c for c in board.columns if c not in cols]
    return board[cols]


def load_scoreboard() -> pd.DataFrame:
    if not SCOREBOARD_PARQUET.exists():
        raise FileNotFoundError(
            f"No scoreboard at {SCOREBOARD_PARQUET}. Run the pipeline first.")
    return pd.read_parquet(SCOREBOARD_PARQUET)
