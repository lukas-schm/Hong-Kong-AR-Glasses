"""
Optional heterogeneity (CATE) analysis for a single intervention, reusing the
project's existing econml stack (CausalForestDML). Answers "who benefits / is
harmed most?" rather than the population-average question of the scoreboard.

This is a bonus layer — it is only run when ``--heterogeneity <intervention>``
is passed, and it is wrapped defensively so a failure never breaks the main
scoreboard run.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer

from mortality_pipeline.constants import (
    CONFOUNDER_KEYS,
    DIR2RESULTS_MORTALITY,
    PRIMARY_OUTCOME,
    RANDOM_STATE,
)

# Reuse the antibiotic pipeline's classifier→regressor shim for binary outcomes.
from antibiotic_pipeline.experiments.utils import _ProbaAsRegressor

DEFAULT_EFFECT_MODIFIERS = ["admission_age", "sofa", "charlson_comorbidity_index", "lactate_max"]


def estimate_cate(
    cohort: pd.DataFrame,
    intervention: str,
    outcome: str = PRIMARY_OUTCOME,
    effect_modifiers: Optional[List[str]] = None,
    n_sample: int = 25_000,
    save: bool = True,
) -> Optional[Dict]:
    """Fit a causal forest and summarise CATE by tertiles of each modifier."""
    try:
        from econml.dml import CausalForestDML
    except Exception as exc:  # pragma: no cover
        logger.warning(f"econml unavailable; skipping heterogeneity: {exc}")
        return None

    effect_modifiers = effect_modifiers or DEFAULT_EFFECT_MODIFIERS
    df = cohort[cohort[outcome].notna()].copy()
    if len(df) > n_sample:
        df = df.sample(n=n_sample, random_state=RANDOM_STATE)

    controls = [c for c in CONFOUNDER_KEYS if c not in effect_modifiers]
    # CATE features must be NaN-free for the GRF; nuisance controls can keep NaN
    # because the gradient-boosted nuisances ingest them natively.
    X = pd.DataFrame(
        SimpleImputer(strategy="median").fit_transform(df[effect_modifiers]),
        columns=effect_modifiers, index=df.index,
    )
    W = df[controls]
    A = df[intervention].to_numpy(int)
    Y = df[outcome].to_numpy(float)

    logger.info(f"Heterogeneity: causal forest for {intervention} → {outcome} "
                f"(n={len(df):,}, modifiers={effect_modifiers})")
    est = CausalForestDML(
        model_y=_ProbaAsRegressor(HistGradientBoostingClassifier(
            max_depth=4, max_iter=200, learning_rate=0.05, random_state=RANDOM_STATE)),
        model_t=HistGradientBoostingClassifier(
            max_depth=4, max_iter=200, learning_rate=0.05, random_state=RANDOM_STATE),
        discrete_treatment=True, cv=4, n_estimators=300,
        min_samples_leaf=25, random_state=RANDOM_STATE,
    )
    est.fit(Y, A, X=X, W=W)
    cate = est.effect(X)            # per-patient risk difference
    df_out = df[[*effect_modifiers]].copy()
    df_out["cate_pp"] = cate * 100

    subgroups = {}
    for mod in effect_modifiers:
        try:
            tert = pd.qcut(df_out[mod], 3, labels=["low", "mid", "high"], duplicates="drop")
            subgroups[mod] = {
                str(level): round(float(df_out.loc[tert == level, "cate_pp"].mean()), 2)
                for level in tert.cat.categories
            }
        except Exception:
            continue

    summary = {
        "intervention": intervention,
        "outcome": outcome,
        "n": int(len(df)),
        "ate_pp": round(float(cate.mean() * 100), 2),
        "cate_pp_range": [round(float(np.percentile(cate * 100, 5)), 2),
                          round(float(np.percentile(cate * 100, 95)), 2)],
        "subgroup_cate_pp": subgroups,
    }
    logger.info(f"  CATE 5–95%: {summary['cate_pp_range']} pp; subgroups: {subgroups}")

    if save:
        DIR2RESULTS_MORTALITY.mkdir(parents=True, exist_ok=True)
        out_path = DIR2RESULTS_MORTALITY / f"cate_{intervention}_{outcome}.parquet"
        df_out.to_parquet(out_path)
        logger.info(f"  saved per-patient CATE → {out_path}")
    return summary
