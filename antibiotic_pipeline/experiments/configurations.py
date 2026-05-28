"""
Base estimator configurations for the antibiotic continuation pipeline.
Mirrors caumim/experiments/configurations.py from the albumin pipeline.
"""

from sklearn.ensemble import (
    GradientBoostingClassifier, GradientBoostingRegressor,
    RandomForestClassifier, RandomForestRegressor,
)
from sklearn.linear_model import LogisticRegression, RidgeCV
from sklearn.pipeline import Pipeline
from sklearn.utils import Bunch
import numpy as np

from antibiotic_pipeline.constants import RANDOM_STATE

# ── Propensity (treatment) models ─────────────────────────────────────────────

LOGISTIC_TREATMENT = Bunch(
    name="Logistic regression",
    estimator=LogisticRegression(max_iter=500, random_state=RANDOM_STATE, C=1.0),
)

RF_TREATMENT = Bunch(
    name="Random Forest",
    estimator=RandomForestClassifier(
        n_estimators=100, max_depth=6, random_state=RANDOM_STATE, n_jobs=2
    ),
)

HGB_TREATMENT = Bunch(
    name="Hist Gradient Boosting",
    estimator=GradientBoostingClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05, random_state=RANDOM_STATE
    ),
)

# ── Outcome models ─────────────────────────────────────────────────────────────

RIDGE_OUTCOME = Bunch(
    name="Ridge",
    estimator=RidgeCV(alphas=np.logspace(-3, 3, 13)),
)

RF_OUTCOME = Bunch(
    name="Random Forest",
    estimator=RandomForestRegressor(
        n_estimators=100, max_depth=6, random_state=RANDOM_STATE, n_jobs=2
    ),
)

HGB_OUTCOME = Bunch(
    name="Hist Gradient Boosting",
    estimator=GradientBoostingRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05, random_state=RANDOM_STATE
    ),
)

# ── Default configuration (DML with RF nuisance, as in the albumin pipeline) ──

DEFAULT_TREATMENT_CONFIG = RF_TREATMENT
DEFAULT_OUTCOME_CONFIG = RF_OUTCOME

# ── Sensitivity grid ───────────────────────────────────────────────────────────
# Varies estimation method × nuisance estimator

SENSITIVITY_GRID = [
    # (estimation_method, treatment_config, outcome_config)
    ("DML", RF_TREATMENT, RF_OUTCOME),
    ("LinearDML", RF_TREATMENT, RF_OUTCOME),
    ("DRLearner", RF_TREATMENT, RF_OUTCOME),
    ("TLearner", RF_TREATMENT, RF_OUTCOME),
    ("DML", LOGISTIC_TREATMENT, RIDGE_OUTCOME),
    ("LinearDML", LOGISTIC_TREATMENT, RIDGE_OUTCOME),
    ("CausalForest", RF_TREATMENT, RF_OUTCOME),
]
