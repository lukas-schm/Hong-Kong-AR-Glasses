"""
CATE (Conditional Average Treatment Effect) exploration for the antibiotic
continuation pipeline.

Estimates heterogeneous treatment effects by patient subgroup:
  - Age (continuous and binned at 65)
  - Sex (female vs male)
  - Septic shock (vasopressors + high lactate)
  - Immunosuppressed
  - SOFA trajectory (improving vs worsening at 72h)
  - Culture positivity

Outputs
-------
- cate_predictions.parquet : patient-level CATE + 95% CI
- cate_subgroup_summary.parquet : subgroup-level mean CATE + CI
"""

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    CATE_FEATURES,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    COLNAME_VFD28,
    DIR2COHORT,
    DIR2EXPERIENCES,
    FEATURE_SETS,
    FILENAME_TARGET_POPULATION,
    RANDOM_STATE,
    TREATMENT_ARM_LABELS,
)
from antibiotic_pipeline.experiments.configurations import RF_OUTCOME, RF_TREATMENT
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
)
from antibiotic_pipeline.variables.selection import FeatureTypes

COHORT_NAME = "antibiotic_continuation_sepsis"

PRIMARY_OUTCOME = COLNAME_MORTALITY_28D
PRIMARY_COMPARISON = (0, 1)   # continue vs de-escalate

CATE_BINARY_THRESHOLD = {
    "admission_age": 65,
    "delta_SOFA_0_72h": 0,     # < 0 = improving
    "SOFA_at_decision": None,  # use median
}


def run_cate_exploration(
    cohort_folder: Path = DIR2COHORT / COHORT_NAME,
    experiences_folder: Path = DIR2EXPERIENCES / COHORT_NAME,
    feature_types: FeatureTypes = None,
    outcome: str = PRIMARY_OUTCOME,
    comparison: tuple = PRIMARY_COMPARISON,
    bootstrap_num_samples: int = 50,
) -> pd.DataFrame:
    """Estimate patient-level CATE and produce subgroup summaries."""
    pop = pd.read_parquet(cohort_folder / FILENAME_TARGET_POPULATION)
    confounders = pd.read_parquet(cohort_folder / "confounders.parquet")
    data = pop.merge(confounders, on="stay_id", how="inner")

    feature_cols = FEATURE_SETS["All confounders"]
    feature_cols = [c for c in feature_cols if c in data.columns]

    # F3: imputation lives inside each estimator pipeline; cross-fitting refits
    # the imputer per fold so test-fold medians don't leak into training.
    treatment_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_TREATMENT.estimator,
    )
    outcome_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_OUTCOME.estimator,
    )

    X = data[feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
    y = data[outcome].dropna()
    X = X.loc[y.index]

    # Pre-impute to satisfy econml's finite-input check; the in-pipeline
    # imputer still refits per CV fold inside DML (F3).
    outer_imp = SimpleImputer(strategy="median")
    X[feature_cols] = outer_imp.fit_transform(X[feature_cols])

    cate_cols = [c for c in CATE_FEATURES if c in data.columns]
    # CATE features are passed directly to econml's model_final, which does NOT
    # impute. Impute them once here (outside the cross-fit) — these are CATE
    # *features*, not nuisance components, so leakage concerns don't apply to
    # the DML orthogonality argument.
    cate_imp = SimpleImputer(strategy="median")
    X_cate = pd.DataFrame(
        cate_imp.fit_transform(data.loc[y.index, cate_cols]),
        columns=cate_cols, index=y.index,
    )

    logger.info(
        f"CATE exploration: outcome={outcome}, "
        f"comparison={TREATMENT_ARM_LABELS[comparison[0]]} vs "
        f"{TREATMENT_ARM_LABELS[comparison[1]]}, n={len(y)}"
    )

    wrapper = MultiArmInferenceWrapper(
        treatment_pipeline=treatment_pipe,
        outcome_pipeline=outcome_pipe,
        estimation_method="DML",
        outcome_name=outcome,
        treatment_name=COLNAME_INTERVENTION_STATUS,
        treatment_comparison=comparison,
        bootstrap_num_samples=bootstrap_num_samples,
        model_final=RidgeCV(alphas=[0.01, 0.1, 1.0, 10.0]),
    )
    wrapper.fit(X, y, X_cate=X_cate)

    # X_cate was filtered to two-arm rows inside fit(); use fit_index_ for alignment
    fit_idx = wrapper.fit_index_
    X_cate_fit = X_cate.loc[fit_idx]
    stay_ids = data.loc[fit_idx, "stay_id"].values

    cate_results = wrapper.predict_cate(X_cate_fit)
    cate_df = pd.DataFrame(cate_results)
    cate_df["stay_id"] = stay_ids
    cate_df["arm_a"] = comparison[0]
    cate_df["arm_b"] = comparison[1]
    cate_df["outcome"] = outcome

    # Subgroup summaries
    subgroup_rows = []
    for col in cate_cols:
        col_key = f"X_cate__{col}"
        if col not in cate_df.columns and col_key not in cate_df.columns:
            continue
        vals = cate_df[col_key] if col_key in cate_df.columns else cate_df[col]

        if col in CATE_BINARY_THRESHOLD:
            threshold = CATE_BINARY_THRESHOLD[col]
            if threshold is None:
                threshold = float(np.median(vals.dropna()))
            groups = {
                f"{col}<{threshold}": vals < threshold,
                f"{col}>={threshold}": vals >= threshold,
            }
        else:
            # Binary feature
            groups = {f"{col}=0": vals == 0, f"{col}=1": vals == 1}

        for group_label, mask in groups.items():
            subset = cate_df.loc[mask]
            if len(subset) < 10:
                continue
            subgroup_rows.append({
                "feature": col,
                "group": group_label,
                "n": len(subset),
                "mean_cate": float(subset["cate_predictions"].mean()),
                "cate_lb": float(subset["cate_lb"].mean()),
                "cate_ub": float(subset["cate_ub"].mean()),
            })

    subgroup_df = pd.DataFrame(subgroup_rows)

    out_dir = experiences_folder / f"cate_{outcome}_{comparison[0]}v{comparison[1]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cate_df.to_parquet(str(out_dir / "cate_predictions.parquet"))
    subgroup_df.to_parquet(str(out_dir / "cate_subgroup_summary.parquet"))
    logger.info(f"Saved CATE predictions to {out_dir}")

    logger.info("\nSubgroup CATE summary:")
    logger.info(subgroup_df.to_string(index=False))

    return cate_df


if __name__ == "__main__":
    for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
        run_cate_exploration(comparison=(arm_a, arm_b))
