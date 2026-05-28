"""
Inference wrapper for the antibiotic continuation pipeline.

Extends the albumin pipeline's InferenceWrapper to support:
  - Multi-arm treatment (continue / de-escalate / stop)
  - Multiple outcomes (VFD-28, VaPFD-28, ICU LOS, mortality, AKI, secondary infection)
  - Pairwise comparisons between any two treatment arms
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from attr import dataclass
from econml.dml import DML, LinearDML
from econml.dr import DRLearner, LinearDRLearner
from econml.grf import CausalForest
from econml.inference import BootstrapInference
from econml.metalearners import TLearner
from econml.sklearn_extensions.linear_model import StatsModelsLinearRegression
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.discriminant_analysis import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder

from antibiotic_pipeline.constants import (
    BINARY_OUTCOMES,
    MIN_PS_SCORE,
    RANDOM_STATE,
    RESULT_ATE,
    RESULT_ATE_LB,
    RESULT_ATE_UB,
    RESULT_TREATMENT_COMPARISON,
    TREATMENT_ARM_LABELS,
)

DEFAULT_BS_NUM_SAMPLES = 500


class _ProbaAsRegressor(BaseEstimator, RegressorMixin):
    """Wrap a sklearn classifier so econml's DML uses predict_proba(...)[:,1].

    Why: DML's `model_y` is expected to be a regressor (returns E[Y|W]).
    For a Bernoulli outcome, the correct conditional mean is P(Y=1|W),
    which a logistic/HGB classifier provides via predict_proba — but DML
    calls `.predict()`. This shim adapts the API.
    """

    def __init__(self, classifier):
        self.classifier = classifier

    def fit(self, X, y, **kw):
        self.classifier_ = clone(self.classifier)
        self.classifier_.fit(X, y, **kw)
        return self

    def predict(self, X):
        return self.classifier_.predict_proba(X)[:, 1]

    def get_params(self, deep=True):
        return {"classifier": self.classifier}

    def set_params(self, **params):
        if "classifier" in params:
            self.classifier = params["classifier"]
        return self


def _build_outcome_pipeline(base_pipeline: Pipeline, outcome_name: str) -> Pipeline:
    """Return a DML-compatible outcome estimator.

    For binary outcomes, wrap the pipeline's final estimator in a logistic
    classifier exposed via _ProbaAsRegressor; otherwise pass through unchanged.
    """
    if outcome_name in BINARY_OUTCOMES:
        steps = list(base_pipeline.steps[:-1])
        clf = LogisticRegression(max_iter=1000, C=1.0, random_state=RANDOM_STATE)
        steps.append(("classifier_as_reg", _ProbaAsRegressor(clf)))
        return Pipeline(steps)
    return base_pipeline
ECONML_CATE_LEARNERS = ["DML", "LinearDML", "DRLearner", "LinearDRLearner", "CausalForest"]
ECONML_META_LEARNERS = ["TLearner"]
ECONML_LEARNERS = [*ECONML_CATE_LEARNERS, *ECONML_META_LEARNERS]


@dataclass
class ExperimentConfig:
    expe_name: str
    cohort_folder: Path
    outcome_name: str
    feature_set_name: str
    treatment_comparison: Tuple[int, int]   # e.g. (0, 1) = continue vs de-escalate
    bootstrap_num_samples: int = DEFAULT_BS_NUM_SAMPLES
    fraction: float = 1.0
    random_state: int = RANDOM_STATE
    test_size: float = 0.2


def log_estimate(estimate: Dict, estimate_folder: str):
    estimate_folder_path = Path(estimate_folder)
    estimate_folder_path.mkdir(parents=True, exist_ok=True)
    estimate_ = {k: [v] for k, v in estimate.items()}
    estimate_["time_stamp"] = [datetime.now().strftime("%m-%d-%Y-%H-%M-%S")]
    ts = estimate_["time_stamp"][0]
    pd.DataFrame(estimate_).to_parquet(str(estimate_folder_path / f"{ts}.parquet"))


def make_column_transformer(
    numerical_features: List[str],
    categorical_features: List[str],
) -> ColumnTransformer:
    categorical_preprocessor = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    numerical_preprocessor = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
    )
    return ColumnTransformer(
        [
            ("one-hot-encoder", categorical_preprocessor, categorical_features),
            ("standard_scaler", numerical_preprocessor, numerical_features),
        ],
        remainder="passthrough",
        verbose_feature_names_out=False,
    )


class MultiArmInferenceWrapper(BaseEstimator):
    """Causal estimator for multi-arm or pairwise antibiotic treatment comparisons.

    Parameters
    ----------
    treatment_pipeline : sklearn Pipeline with a propensity model
    outcome_pipeline   : sklearn Pipeline with an outcome model
    estimation_method  : one of ECONML_LEARNERS
    outcome_name       : target column name
    treatment_name     : treatment column name (integer-coded arms)
    treatment_comparison : (arm_a, arm_b) tuple; restricts data to these two arms
                           and recodes arm_a=0, arm_b=1 for binary estimation.
                           Set to None for full multi-class DML.
    bootstrap_num_samples : bootstrap replicates for confidence intervals
    model_final        : final linear model for DML/DRLearner (optional)
    """

    def __init__(
        self,
        treatment_pipeline: Pipeline,
        outcome_pipeline: Pipeline,
        estimation_method: str,
        outcome_name: str,
        treatment_name: str,
        treatment_comparison: Optional[Tuple[int, int]] = None,
        bootstrap_num_samples: int = DEFAULT_BS_NUM_SAMPLES,
        model_final: Optional[BaseEstimator] = None,
    ) -> None:
        super().__init__()
        self.treatment_pipeline = treatment_pipeline
        self.outcome_pipeline = outcome_pipeline
        self.estimation_method = estimation_method
        self.outcome_name = outcome_name
        self.treatment_name = treatment_name
        self.treatment_comparison = treatment_comparison
        self.bootstrap_num_samples = bootstrap_num_samples
        self.model_final = model_final

    def _prepare_data(
        self, X: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Subset to treatment comparison arms and recode treatment as binary."""
        if self.treatment_comparison is not None:
            arm_a, arm_b = self.treatment_comparison
            mask = X[self.treatment_name].isin([arm_a, arm_b])
            X = X.loc[mask].copy()
            X[self.treatment_name] = (X[self.treatment_name] == arm_b).astype(int)
        a = X[self.treatment_name]
        X_ = X.drop(columns=self.treatment_name)
        return X_, a

    def fit(self, X: pd.DataFrame, y: pd.Series, X_cate: Optional[pd.DataFrame] = None):
        X_, a = self._prepare_data(X)
        y = y.loc[X_.index]   # align y to the (possibly subset) X indices
        if X_cate is not None:
            X_cate = X_cate.loc[X_.index]  # align CATE features to same two-arm subset
        self.fit_index_ = X_.index         # store for predict_cate alignment

        if self.estimation_method in ECONML_LEARNERS:
            self.inference_estimator_ = self._fit_econml(X_, a, y, X_cate)
        else:
            raise ValueError(f"Unsupported estimation method: {self.estimation_method}")
        return self

    def _fit_econml(
        self,
        X_: pd.DataFrame,
        a: pd.Series,
        y: pd.Series,
        X_cate: Optional[pd.DataFrame],
    ) -> BaseEstimator:
        # Use full pipelines (preprocessor + estimator) so NaN imputation runs automatically.
        model_t = self.treatment_pipeline
        # F2: route binary outcomes through a probability-returning classifier.
        model_y = _build_outcome_pipeline(self.outcome_pipeline, self.outcome_name)
        bs = BootstrapInference(n_bootstrap_samples=self.bootstrap_num_samples)

        if self.estimation_method == "DML":
            model_final = self.model_final or StatsModelsLinearRegression(fit_intercept=False)
            learner = DML(
                model_t=model_t,
                model_y=model_y,
                model_final=model_final,
                discrete_treatment=True,
                cv=5,
                random_state=RANDOM_STATE,
            )
            learner.fit(y, a, X=X_cate, W=X_, inference=bs)

        elif self.estimation_method == "LinearDML":
            # LinearDML has a fixed linear model_final — don't pass model_final
            learner = LinearDML(
                model_t=model_t,
                model_y=model_y,
                discrete_treatment=True,
                cv=5,
                random_state=RANDOM_STATE,
            )
            learner.fit(y, a, X=X_cate, W=X_, inference=bs)

        elif self.estimation_method in ("DRLearner", "LinearDRLearner"):
            model_final = self.model_final or StatsModelsLinearRegression(fit_intercept=True)
            cls = LinearDRLearner if self.estimation_method == "LinearDRLearner" else DRLearner
            learner = cls(
                model_propensity=model_t,
                model_regression=model_y,
                model_final=model_final,
                min_propensity=MIN_PS_SCORE,
                cv=5,
                random_state=RANDOM_STATE,
            )
            learner.fit(y, a, X=X_cate, W=X_, inference=bs)

        elif self.estimation_method == "TLearner":
            from sklearn.impute import SimpleImputer
            imp = SimpleImputer(strategy="median")
            X_imp = pd.DataFrame(imp.fit_transform(X_), columns=X_.columns, index=X_.index)
            learner = TLearner(models=[model_y, model_y])
            learner.fit(y, a, X=X_imp, inference=bs)

        elif self.estimation_method == "CausalForest":
            # F18: route through econml's CausalForestDML so nuisance models
            # are cross-fit (orthogonalisation) and honest splits are used
            # for valid inference — directly comparable to the DML family.
            from econml.dml import CausalForestDML
            learner = CausalForestDML(
                model_t=model_t,
                model_y=model_y,
                discrete_treatment=True,
                cv=5,
                n_estimators=200,
                min_samples_leaf=10,
                max_depth=None,
                honest=True,
                random_state=RANDOM_STATE,
            )
            learner.fit(y, a, X=X_cate, W=X_, inference="auto")

        else:
            raise ValueError(f"Unknown EconML method: {self.estimation_method}")

        return learner

    def predict(self, X: pd.DataFrame) -> Dict:
        X_, a = self._prepare_data(X)
        results = {}

        if self.treatment_comparison is not None:
            arm_a, arm_b = self.treatment_comparison
            results[RESULT_TREATMENT_COMPARISON] = (
                f"{TREATMENT_ARM_LABELS[arm_a]} vs {TREATMENT_ARM_LABELS[arm_b]}"
            )

        if self.estimation_method in ECONML_CATE_LEARNERS:
            ate_inf = self.inference_estimator_.ate_inference(X=None)
            results[RESULT_ATE] = ate_inf.mean_point
            results[RESULT_ATE_LB], results[RESULT_ATE_UB] = ate_inf.conf_int_mean()

        elif self.estimation_method in ECONML_META_LEARNERS:
            ate_inf = self.inference_estimator_.ate_inference(X=X_)
            results[RESULT_ATE] = ate_inf.mean_point
            results[RESULT_ATE_LB], results[RESULT_ATE_UB] = ate_inf.conf_int_mean()

        return results

    def predict_cate(
        self, X_cate: pd.DataFrame, alpha: float = 0.05
    ) -> Dict:
        out = {f"X_cate__{c}": X_cate[c].values for c in X_cate.columns}
        out["cate_predictions"] = self.inference_estimator_.effect(X_cate)
        lb, ub = self.inference_estimator_.effect_interval(X_cate, alpha=alpha)
        out["cate_lb"] = lb
        out["cate_ub"] = ub
        return out


# ── All pairwise comparisons helper ─────────────────────────────────────────

ALL_PAIRWISE_COMPARISONS = [
    (0, 1),  # continue vs de-escalate
    (0, 2),  # continue vs stop
    (1, 2),  # de-escalate vs stop
]


def run_all_pairwise_estimates(
    X: pd.DataFrame,
    y: pd.Series,
    treatment_pipeline: Pipeline,
    outcome_pipeline: Pipeline,
    estimation_method: str,
    outcome_name: str,
    treatment_name: str,
    bootstrap_num_samples: int = DEFAULT_BS_NUM_SAMPLES,
) -> pd.DataFrame:
    """Run all pairwise comparisons and return a combined results dataframe."""
    rows = []
    for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
        wrapper = MultiArmInferenceWrapper(
            treatment_pipeline=treatment_pipeline,
            outcome_pipeline=outcome_pipeline,
            estimation_method=estimation_method,
            outcome_name=outcome_name,
            treatment_name=treatment_name,
            treatment_comparison=(arm_a, arm_b),
            bootstrap_num_samples=bootstrap_num_samples,
        )
        wrapper.fit(X, y)
        result = wrapper.predict(X)
        result["arm_a"] = arm_a
        result["arm_b"] = arm_b
        result["outcome"] = outcome_name
        result["method"] = estimation_method
        rows.append(result)
    return pd.DataFrame(rows)


def score_binary_classification(y_true: pd.Series, y_pred_proba: np.ndarray) -> Dict:
    from sklearn.metrics import (
        accuracy_score, average_precision_score, confusion_matrix,
        precision_score, recall_score, roc_auc_score,
    )
    y_bin = (y_pred_proba >= 0.5).astype(int)
    return {
        "n_samples": len(y_true),
        "prevalence": float(y_true.mean()),
        "accuracy": accuracy_score(y_true, y_bin),
        "precision": precision_score(y_true, y_bin, zero_division=0),
        "recall": recall_score(y_true, y_bin, zero_division=0),
        "roc_auc": roc_auc_score(y_true, y_pred_proba),
        "pr_auc": average_precision_score(y_true, y_pred_proba),
        "confusion_matrix": confusion_matrix(y_true, y_bin).tolist(),
    }
