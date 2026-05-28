"""
F17: Treatment-classification window sensitivity sweep.

The treatment-arm classifier looks ±window_h hours around T0 = 72h. A patient
with a brief order-gap could be miscoded as "stop" when clinically continued.
This sweep re-runs the full classify-then-DML pipeline with window_h in
{6, 12, 24} and tabulates how stable the headline ATE is across windows.

Output: data/diagnostics/window_sweep.parquet
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils import Bunch

from antibiotic_pipeline.constants import (
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2COHORT,
    DIR2DATA,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.configurations import RF_OUTCOME, RF_TREATMENT
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
)
from antibiotic_pipeline.framing.antibiotic_continuation_sepsis import (
    _classify_treatment_arm,
)
from antibiotic_pipeline.framing.treatment_classification import (
    classify_from_inputevents,
)

COHORT_NAME = "antibiotic_continuation_sepsis"


def main(windows=(6, 12, 24), bootstrap_num_samples: int = 50):
    cohort = DIR2COHORT / COHORT_NAME
    pop_base = pd.read_parquet(cohort / "target_population.parquet")
    confounders = pd.read_parquet(cohort / "confounders.parquet")

    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in confounders.columns]
    feature_cols += [
        f"{c}__missing" for c in feature_cols if f"{c}__missing" in confounders.columns
    ]

    treatment_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_TREATMENT.estimator,
    )
    outcome_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_OUTCOME.estimator,
    )

    rows = []
    for window_h in windows:
        cfg = Bunch(treatment_classify_window_hours=window_h)
        # Re-classify treatment arms for this window
        pop = pop_base.drop(columns=[COLNAME_INTERVENTION_STATUS]).copy()
        pop_ie = classify_from_inputevents(pop, cfg)
        pop_pres = _classify_treatment_arm(pop.copy(), cfg)
        # Same disagreement-resolution as the main framing
        mask_disagree_c = (
            (pop_ie[COLNAME_INTERVENTION_STATUS] == 2)
            & (pop_pres[COLNAME_INTERVENTION_STATUS] == 0)
        )
        mask_disagree_d = (
            (pop_ie[COLNAME_INTERVENTION_STATUS] == 2)
            & (pop_pres[COLNAME_INTERVENTION_STATUS] == 1)
        )
        pop_ie.loc[mask_disagree_c, COLNAME_INTERVENTION_STATUS] = 0
        pop_ie.loc[mask_disagree_d, COLNAME_INTERVENTION_STATUS] = 1
        pop_w = pop_ie

        counts = pop_w[COLNAME_INTERVENTION_STATUS].value_counts().sort_index()
        logger.info(f"window_h={window_h}h arm counts: {counts.to_dict()}")

        data = pop_w.merge(confounders, on="stay_id", how="inner")
        for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
            X = data[feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
            y = data[COLNAME_MORTALITY_28D].dropna()
            X = X.loc[y.index]
            imp = SimpleImputer(strategy="median")
            X[feature_cols] = imp.fit_transform(X[feature_cols])

            wrapper = MultiArmInferenceWrapper(
                treatment_pipeline=treatment_pipe,
                outcome_pipeline=outcome_pipe,
                estimation_method="DML",
                outcome_name=COLNAME_MORTALITY_28D,
                treatment_name=COLNAME_INTERVENTION_STATUS,
                treatment_comparison=(arm_a, arm_b),
                bootstrap_num_samples=bootstrap_num_samples,
            )
            wrapper.fit(X, y)
            res = wrapper.predict(X)
            rows.append({
                "window_h":  window_h,
                "arm_a":     arm_a,
                "arm_b":     arm_b,
                "n_a":       int((data[COLNAME_INTERVENTION_STATUS] == arm_a).sum()),
                "n_b":       int((data[COLNAME_INTERVENTION_STATUS] == arm_b).sum()),
                "ATE_pp":    round(res["ATE"] * 100, 2),
                "CI_lb_pp":  round(res["ATE lower bound"] * 100, 2),
                "CI_ub_pp":  round(res["ATE upper bound"] * 100, 2),
            })
            logger.info(
                f"  w={window_h}h {arm_a}v{arm_b}: ATE={rows[-1]['ATE_pp']:+.2f} pp "
                f"[{rows[-1]['CI_lb_pp']:+.2f}, {rows[-1]['CI_ub_pp']:+.2f}] "
                f"(n_a={rows[-1]['n_a']}, n_b={rows[-1]['n_b']})"
            )

    df = pd.DataFrame(rows)
    out = DIR2DATA / "diagnostics" / "window_sweep.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    logger.info(f"Saved {out}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=int, default=50)
    args = parser.parse_args()
    main(bootstrap_num_samples=args.bootstrap)
