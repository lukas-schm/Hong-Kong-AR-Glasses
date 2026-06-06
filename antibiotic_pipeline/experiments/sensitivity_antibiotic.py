"""
Sensitivity analysis for antibiotic continuation causal estimates.

Grid dimensions
---------------
1. Feature set   : all confounders / without infection markers / severity only / etc.
2. Estimation    : DML, LinearDML, DRLearner, TLearner, CausalForest
3. Outcome       : VFD-28, VaPFD-28, ICU LOS, 28-day mortality
4. Comparison    : continue vs de-escalate / continue vs stop / de-escalate vs stop

Usage
-----
    python -m antibiotic_pipeline.experiments.sensitivity_antibiotic
"""

import gc
import itertools
from pathlib import Path
from typing import List

import pandas as pd
from loguru import logger
from sklearn.pipeline import Pipeline

from antibiotic_pipeline.constants import (
    ALL_OUTCOMES,
    COLNAME_AKI_WORSENING,
    COLNAME_CDIFF_28D,
    COLNAME_ICU_LOS,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_7D,
    COLNAME_MORTALITY_14D,
    COLNAME_MORTALITY_21D,
    COLNAME_MORTALITY_28D,
    COLNAME_SECONDARY_INFECTION,
    COLNAME_VAPFD28,
    COLNAME_VFD28,
    DIR2COHORT,
    DIR2EXPERIENCES,
    FILENAME_TARGET_POPULATION,
    RANDOM_STATE,
    RESULT_ATE,
    RESULT_ATE_LB,
    RESULT_ATE_UB,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.configurations import (
    DEFAULT_OUTCOME_CONFIG,
    DEFAULT_TREATMENT_CONFIG,
    SENSITIVITY_GRID,
)
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
    log_estimate,
    make_column_transformer,
    run_all_pairwise_estimates,
)
from antibiotic_pipeline.variables.selection import FeatureTypes

COHORT_NAME = "antibiotic_continuation_sepsis"

SENSITIVITY_OUTCOMES = [
    COLNAME_MORTALITY_28D,        # cached (grid already complete)
    # WS11 trajectory horizons — ordered first among the new outcomes so the
    # vibration sweep computes them before the lower-priority secondary
    # binaries. Already-cached outcomes are skipped instantly on resume.
    COLNAME_MORTALITY_7D,
    COLNAME_MORTALITY_14D,
    COLNAME_MORTALITY_21D,
    COLNAME_VFD28,                # cached
    COLNAME_VAPFD28,              # cached
    COLNAME_ICU_LOS,              # cached
    # Secondary binary outcomes — were never in the original grid.
    COLNAME_AKI_WORSENING,
    COLNAME_SECONDARY_INFECTION,
    COLNAME_CDIFF_28D,
]

# Feature set names come from causal_graph.yaml sensitivity_feature_sets
SENSITIVITY_FEATURE_SETS: List[str] = list(CAUSAL_GRAPH.sensitivity_feature_sets.keys())


def run_sensitivity_grid(
    cohort_folder: Path = DIR2COHORT / COHORT_NAME,
    experiences_folder: Path = DIR2EXPERIENCES / COHORT_NAME,
    feature_types: FeatureTypes = None,
    bootstrap_num_samples: int = 500,
) -> pd.DataFrame:
    """Run all sensitivity analyses and return a combined results dataframe.

    Expects the cohort folder to contain:
      - target_population.parquet  (from framing step)
      - confounders.parquet         (from variables/selection step – merged features)

    Returns
    -------
    pd.DataFrame with columns:
        outcome, feature_set, method, treatment_comparison, ATE, ATE lower/upper bound
    """
    pop = pd.read_parquet(cohort_folder / FILENAME_TARGET_POPULATION)
    confounders = pd.read_parquet(cohort_folder / "confounders.parquet")

    data = pop.merge(confounders, on="stay_id", how="inner")
    logger.info(f"Loaded {len(data)} stays for sensitivity analysis")

    if feature_types is None:
        from antibiotic_pipeline.variables.selection import get_confounders_at_decision_time
        _, feature_types = get_confounders_at_decision_time(pop)

    all_results = []
    combos = list(itertools.product(
        SENSITIVITY_OUTCOMES,
        SENSITIVITY_FEATURE_SETS,
        SENSITIVITY_GRID,
        ALL_PAIRWISE_COMPARISONS,
    ))
    logger.info(f"Running {len(combos)} sensitivity combinations")

    # Load any already-completed results from individual log files (resume support)
    # Each logs/ dir can hold runs from multiple treatment_model variants (e.g. DML-RF
    # and DML-Logistic share the same directory), so read ALL files in each dir.
    completed_keys: set = set()
    for logs_dir in sorted(experiences_folder.glob("*/logs")):
        for pq in sorted(logs_dir.glob("*.parquet")):
            try:
                prev = pd.read_parquet(pq)
                key = (
                    str(prev["outcome"].iloc[0]),
                    str(prev["feature_set"].iloc[0]),
                    str(prev["method"].iloc[0]),
                    str(prev["treatment_model"].iloc[0]),
                    int(prev["arm_a"].iloc[0]),
                    int(prev["arm_b"].iloc[0]),
                )
                if key not in completed_keys:
                    completed_keys.add(key)
                    row = {c: prev[c].iloc[0] for c in prev.columns if c != "time_stamp"}
                    all_results.append(row)
            except Exception:
                pass
    if completed_keys:
        logger.info(f"Resuming: {len(completed_keys)} already-completed estimates loaded")

    for outcome, feature_set_name, (method, treatment_cfg, outcome_cfg), (arm_a, arm_b) in combos:
        if outcome not in data.columns or data[outcome].isnull().all():
            logger.debug(f"Skipping {outcome} – not available")
            continue

        # Skip already-completed combinations
        resume_key = (outcome, feature_set_name, method, treatment_cfg.name, arm_a, arm_b)
        if resume_key in completed_keys:
            logger.debug(f"Already done: {method}/{outcome}/{arm_a}v{arm_b}/{feature_set_name}")
            continue

        try:
            feature_cols = CAUSAL_GRAPH.feature_set(feature_set_name)
        except KeyError:
            feature_cols = list(confounders.columns)
        feature_cols = [c for c in feature_cols if c in data.columns]

        # F5: also pull in the matching missing-indicator columns so the model
        # can use "value was unmeasured" as a feature in its own right.
        indicator_cols = [
            f"{c}__missing" for c in feature_cols
            if f"{c}__missing" in data.columns
        ]
        feature_cols = feature_cols + indicator_cols

        if not feature_cols:
            logger.warning(f"No features available for set '{feature_set_name}', skipping")
            continue

        # F3: SimpleImputer lives *inside* each pipeline so it refits per CV
        # fold during DML cross-fitting (no leakage of test-fold medians into
        # the train-fold imputation).
        from sklearn.pipeline import make_pipeline as _make_pipe
        from sklearn.preprocessing import StandardScaler
        from sklearn.impute import SimpleImputer
        treatment_pipe = _make_pipe(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            treatment_cfg.estimator,
        )
        outcome_pipe = _make_pipe(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            outcome_cfg.estimator,
        )

        X = data[feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
        y = data[outcome].dropna()
        X = X.loc[y.index]

        # Pre-impute the outer matrix so econml's `OrthoLearner` finite-input
        # check passes. The in-pipeline imputer (F3) still refits per CV fold;
        # this outer pass is a global-median fill that satisfies validation
        # without materially changing the per-fold behaviour. Leakage here is
        # bounded by the robustness of the median.
        imp = SimpleImputer(strategy="median")
        X[feature_cols] = imp.fit_transform(X[feature_cols])

        try:
            wrapper = MultiArmInferenceWrapper(
                treatment_pipeline=treatment_pipe,
                outcome_pipeline=outcome_pipe,
                estimation_method=method,
                outcome_name=outcome,
                treatment_name=COLNAME_INTERVENTION_STATUS,
                treatment_comparison=(arm_a, arm_b),
                bootstrap_num_samples=bootstrap_num_samples,
            )
            wrapper.fit(X, y)
            result = wrapper.predict(X)
        except Exception as exc:
            logger.warning(f"Failed {method}/{outcome}/{arm_a}v{arm_b}: {exc}")
            continue

        row = {
            "outcome": outcome,
            "feature_set": feature_set_name,
            "method": method,
            "arm_a": arm_a,
            "arm_b": arm_b,
            "treatment_comparison": result.get("treatment_comparison", f"{arm_a}v{arm_b}"),
            "treatment_model": treatment_cfg.name,
            "outcome_model": outcome_cfg.name,
            RESULT_ATE: result[RESULT_ATE],
            RESULT_ATE_LB: result[RESULT_ATE_LB],
            RESULT_ATE_UB: result[RESULT_ATE_UB],
            "n_arm_a": (data[COLNAME_INTERVENTION_STATUS] == arm_a).sum(),
            "n_arm_b": (data[COLNAME_INTERVENTION_STATUS] == arm_b).sum(),
        }
        all_results.append(row)

        # Log estimate to disk
        exp_dir = experiences_folder / f"{outcome}_{method}_{arm_a}v{arm_b}_{feature_set_name}"
        log_estimate(row, str(exp_dir / "logs"))

        del wrapper
        if len(all_results) % 10 == 0:
            gc.collect()

        logger.info(
            f"  {outcome} | {method:15s} | {arm_a}v{arm_b} | "
            f"ATE={result[RESULT_ATE]:+.4f} "
            f"[{result[RESULT_ATE_LB]:+.4f}, {result[RESULT_ATE_UB]:+.4f}]"
        )

    results_df = pd.DataFrame(all_results)
    out_path = experiences_folder / "sensitivity_results.parquet"
    experiences_folder.mkdir(parents=True, exist_ok=True)
    results_df.to_parquet(str(out_path))
    logger.info(f"Saved {len(results_df)} results to {out_path}")
    return results_df


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Use 100 bootstrap samples (default 500)")
    args = parser.parse_args()
    bs = 100 if args.quick else 500
    results = run_sensitivity_grid(bootstrap_num_samples=bs)
    print(results.groupby(["outcome", "method"])["ATE"].describe())
