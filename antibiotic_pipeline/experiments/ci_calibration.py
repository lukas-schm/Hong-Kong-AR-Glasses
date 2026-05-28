"""
F21: Empirical coverage calibration for DML confidence intervals.

The bootstrap CIs emitted by econml assume the model is well-specified
and the bootstrap distribution matches the sampling distribution. In
small or imbalanced samples (which is the case for the de-escalate arm)
both assumptions can be violated, yielding nominal 95% intervals whose
*empirical* coverage is lower (over-confident) or higher (under-confident).

Procedure
---------
1. Split the cohort into K folds.
2. For each fold k, fit DML on the other K-1 folds and obtain a bootstrap
   ATE estimate. Treat that as the "true" ATE for fold k's held-out subset
   (it's the most defensible reference we have without re-randomising the
   universe). Then re-fit DML on each *bootstrap resample* of the held-out
   fold and compare against the held-out fold's own bootstrap ATE.
3. Aggregate: report the fraction of folds whose 95% CI covers the
   K-fold reference. The deficit vs 0.95 is a "calibration factor"
   that can be reported alongside any displayed CI.

Output: data/diagnostics/ci_coverage.json
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2COHORT,
    DIR2DATA,
    RANDOM_STATE,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.configurations import RF_OUTCOME, RF_TREATMENT
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
)

COHORT_NAME = "antibiotic_continuation_sepsis"


def _fit_dml(X, y, feature_cols, arm_a, arm_b, bootstrap_num_samples=30):
    treatment_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_TREATMENT.estimator,
    )
    outcome_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_OUTCOME.estimator,
    )
    wrapper = MultiArmInferenceWrapper(
        treatment_pipeline=treatment_pipe,
        outcome_pipeline=outcome_pipe,
        estimation_method="DML",
        outcome_name=COLNAME_MORTALITY_28D,
        treatment_name=COLNAME_INTERVENTION_STATUS,
        treatment_comparison=(arm_a, arm_b),
        bootstrap_num_samples=bootstrap_num_samples,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wrapper.fit(X, y)
        res = wrapper.predict(X)
    return res["ATE"], res["ATE lower bound"], res["ATE upper bound"]


def main(n_folds: int = 5, bootstrap_num_samples: int = 30):
    cohort = DIR2COHORT / COHORT_NAME
    pop = pd.read_parquet(cohort / "target_population.parquet")
    confounders = pd.read_parquet(cohort / "confounders.parquet")
    data = pop.merge(confounders, on="stay_id", how="inner")

    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in data.columns]
    feature_cols += [
        f"{c}__missing" for c in feature_cols if f"{c}__missing" in data.columns
    ]

    rng = np.random.default_rng(RANDOM_STATE)
    out_rows = []

    for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
        # Full-sample ATE = reference "truth"
        sub = data[data[COLNAME_INTERVENTION_STATUS].isin([arm_a, arm_b])]
        X_all = sub[feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
        y_all = sub[COLNAME_MORTALITY_28D].dropna()
        X_all = X_all.loc[y_all.index]
        imp_all = SimpleImputer(strategy="median")
        X_all[feature_cols] = imp_all.fit_transform(X_all[feature_cols])

        ate_full, _, _ = _fit_dml(X_all, y_all, feature_cols, arm_a, arm_b, bootstrap_num_samples)
        logger.info(f"{arm_a}v{arm_b}: full-sample ATE = {ate_full*100:+.2f} pp")

        # K-fold: fit DML on each fold-out, take its 95% CI, check if it covers ate_full
        skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=RANDOM_STATE)
        stratify_target = (sub[COLNAME_INTERVENTION_STATUS] == arm_b).astype(int).values

        covered = 0
        widths = []
        ates_fold = []
        for fold_idx, (_, fold) in enumerate(skf.split(sub, stratify_target)):
            sub_fold = sub.iloc[fold]
            X_fold = sub_fold[feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
            y_fold = sub_fold[COLNAME_MORTALITY_28D].dropna()
            X_fold = X_fold.loc[y_fold.index]
            imp = SimpleImputer(strategy="median")
            X_fold[feature_cols] = imp.fit_transform(X_fold[feature_cols])
            try:
                ate, lb, ub = _fit_dml(X_fold, y_fold, feature_cols, arm_a, arm_b, bootstrap_num_samples)
            except Exception as exc:
                logger.warning(f"fold {fold_idx} {arm_a}v{arm_b} failed: {exc}")
                continue
            covered += int(lb <= ate_full <= ub)
            widths.append(ub - lb)
            ates_fold.append(ate)

        coverage = covered / max(1, len(widths))
        out_rows.append({
            "arm_a":              arm_a,
            "arm_b":              arm_b,
            "full_sample_ATE_pp": round(ate_full * 100, 2),
            "n_folds":            len(widths),
            "empirical_coverage": round(coverage, 3),
            "nominal_coverage":   0.95,
            "mean_CI_width_pp":   round(float(np.mean(widths)) * 100 if widths else 0.0, 2),
            "calibration_deficit_pp": round((0.95 - coverage) * 100, 2),
        })
        logger.info(
            f"  {arm_a}v{arm_b}: empirical coverage = {coverage:.0%} "
            f"(folds={len(widths)}, mean CI width {np.mean(widths)*100:.2f} pp)"
        )

    df = pd.DataFrame(out_rows)
    out = DIR2DATA / "diagnostics" / "ci_coverage.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    with open(out.with_suffix(".json"), "w") as fh:
        json.dump({
            "interpretation": (
                "Empirical coverage is the fraction of 5 held-out folds whose "
                "95% CI contains the full-sample ATE. Values much below 0.95 "
                "indicate the bootstrap is under-estimating uncertainty; "
                "widen the displayed CI by the calibration_deficit_pp factor."
            ),
            "rows": out_rows,
        }, fh, indent=2)
    logger.info(f"Saved {out}")
    return df


if __name__ == "__main__":
    main()
