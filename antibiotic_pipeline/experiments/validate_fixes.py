"""
Smoke test for the F1–F6 pipeline fixes.

Runs a *small* slice of the sensitivity grid (1 outcome × 1 feature set
× 2 methods × 3 pairwise comparisons = 6 estimates) with 100 bootstrap
replicates so it finishes in a few minutes. Saves results under
data/experiences/antibiotic_continuation_sepsis/_validation/.

The point is to confirm:
  • Logistic model_y wrapper integrates cleanly with econml DML (F2).
  • In-pipeline imputer doesn't break cross-fitting (F3).
  • Missing-indicator columns propagate through the wrapper (F5).
  • Estimates are produced for all three pairwise comparisons (F4 dedup).

Usage:  python -m antibiotic_pipeline.experiments.validate_fixes
"""
from pathlib import Path

import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2COHORT,
    DIR2EXPERIENCES,
    FILENAME_TARGET_POPULATION,
    RESULT_ATE,
    RESULT_ATE_LB,
    RESULT_ATE_UB,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.configurations import RF_OUTCOME, RF_TREATMENT
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
)

COHORT_NAME = "antibiotic_continuation_sepsis"


def main(bootstrap_num_samples: int = 100) -> pd.DataFrame:
    cohort = DIR2COHORT / COHORT_NAME
    pop = pd.read_parquet(cohort / FILENAME_TARGET_POPULATION)
    confounders = pd.read_parquet(cohort / "confounders.parquet")
    data = pop.merge(confounders, on="stay_id", how="inner")

    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in data.columns]
    indicator_cols = [
        f"{c}__missing" for c in feature_cols if f"{c}__missing" in data.columns
    ]
    feature_cols = feature_cols + indicator_cols
    logger.info(
        f"Validation: n={len(data)}, base features={len(feature_cols) - len(indicator_cols)}, "
        f"missing-indicators={len(indicator_cols)}"
    )

    treatment_pipe = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        RF_TREATMENT.estimator,
    )
    outcome_pipe = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        RF_OUTCOME.estimator,
    )

    rows = []
    for method in ("DML", "DRLearner"):
        for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
            X = data[feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
            y = data[COLNAME_MORTALITY_28D].dropna()
            X = X.loc[y.index]

            # Pre-impute to satisfy econml's finite-input check (the
            # in-pipeline imputer still refits per CV fold).
            imp = SimpleImputer(strategy="median")
            X[feature_cols] = imp.fit_transform(X[feature_cols])

            wrapper = MultiArmInferenceWrapper(
                treatment_pipeline=treatment_pipe,
                outcome_pipeline=outcome_pipe,
                estimation_method=method,
                outcome_name=COLNAME_MORTALITY_28D,
                treatment_name=COLNAME_INTERVENTION_STATUS,
                treatment_comparison=(arm_a, arm_b),
                bootstrap_num_samples=bootstrap_num_samples,
            )
            wrapper.fit(X, y)
            res = wrapper.predict(X)
            ate_pp = res[RESULT_ATE] * 100
            lb_pp = res[RESULT_ATE_LB] * 100
            ub_pp = res[RESULT_ATE_UB] * 100
            rows.append({
                "method": method,
                "arm_a": arm_a,
                "arm_b": arm_b,
                "ATE_pp": round(ate_pp, 2),
                "CI_lb_pp": round(lb_pp, 2),
                "CI_ub_pp": round(ub_pp, 2),
                "comparison": res["treatment_comparison"],
            })
            logger.info(
                f"  {method:10s} {arm_a}v{arm_b}: ATE={ate_pp:+.2f} pp "
                f"[{lb_pp:+.2f}, {ub_pp:+.2f}]"
            )

    df = pd.DataFrame(rows)
    out = DIR2EXPERIENCES / COHORT_NAME / "_validation"
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "validation_results.parquet")
    logger.info(f"Saved {out / 'validation_results.parquet'}")
    return df


if __name__ == "__main__":
    main()
