"""
ModelStore: fits and caches T-Learner + DML models for the API.

T-Learner  → per-arm absolute risk estimates (withTreatment / withoutTreatment)
DML        → population ATE with 95 % CI per pairwise comparison
"""
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, RidgeCV
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    CATE_FEATURES,
    COLNAME_ICU_LOS,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    COLNAME_VAPFD28,
    COLNAME_VFD28,
    RANDOM_STATE,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

DIR_COHORT = Path("data/cohort/antibiotic_continuation_sepsis")
DIR_MODELS = Path("data/models")

TREATMENT_MAP = {"continue": 0, "deescalate": 1, "cease": 2}
ARM_LABEL = {0: "continue", 1: "deescalate", 2: "cease"}

# For display: (arm_a, arm_b, flip)
# flip=True means active treatment is arm_a and we need -DML(a,b).effect
COMPARE_CONFIG = {
    "continue":   (0, 1, True),   # DML(0v1): E[Y(1)-Y(0)]; flip → E[Y(0)-Y(1)]
    "deescalate": (0, 1, False),  # DML(0v1): E[Y(1)-Y(0)] = E[Y(deesc)-Y(cont)]
    "cease":      (1, 2, False),  # DML(1v2): E[Y(2)-Y(1)] = E[Y(cease)-Y(deesc)]
}

FEATURE_LABELS = {
    "admission_age":         "Age",
    "Female":                "Female sex",
    "SOFA_at_decision":      "SOFA score",
    "positive_blood_culture":"Positive blood culture",
    "immunosuppressed":      "Immunosuppression",
    "delta_SOFA_0_72h":      "SOFA trajectory (0→72 h)",
}


class ModelStore:
    def __init__(self):
        self.ready = False
        self.dml_models: Dict = {}
        self.dml_cate_mean: Dict = {}        # (arm_a, arm_b) → X_cate mean for ate_inference
        self.tlearner_mortality: Dict = {}   # arm → sklearn pipeline (logistic)
        self.tlearner_continuous: Dict = {}  # arm → {outcome: pipeline}
        self.imputer: Optional[SimpleImputer] = None
        self.scaler: Optional[StandardScaler] = None
        self.X_scaled: Optional[np.ndarray] = None
        self.feature_cols: List[str] = []
        self.cate_cols: List[str] = []
        self.cate_idx: List[int] = []
        self.training_medians: Dict[str, float] = {}
        self.nn_model: Optional[NearestNeighbors] = None
        self.cohort_df: Optional[pd.DataFrame] = None
        # F23: covariance for Mahalanobis OOD check (lazy init)
        self.cov_inv_: Optional[np.ndarray] = None
        self.training_mean_: Optional[np.ndarray] = None
        self.training_mahalanobis_p99_: Optional[float] = None
        # F9: clinically valid continuous-outcome ranges
        self.continuous_bounds_: Dict[str, tuple] = {
            COLNAME_VFD28: (0.0, 28.0),
            COLNAME_VAPFD28: (0.0, 28.0),
            COLNAME_ICU_LOS: (0.0, 28.0),
        }

    # ── Public ────────────────────────────────────────────────────────────────

    def load_or_fit(self):
        DIR_MODELS.mkdir(parents=True, exist_ok=True)
        cache = DIR_MODELS / "api_models.joblib"
        if cache.exists():
            logger.info("Loading cached API models …")
            saved = joblib.load(cache)
            self.__dict__.update(saved)
            self.ready = True
            logger.info("Models loaded from cache.")
            return
        logger.info("Fitting API models from MIMIC data (first run, ~2 min) …")
        self._fit(cache)

    def predict(self, features: Dict[str, Any], treatment_id: str) -> Dict:
        arm_active = TREATMENT_MAP[treatment_id]
        arm_a, arm_b, flip = COMPARE_CONFIG[treatment_id]
        arm_compare = arm_b if not flip else arm_a  # the *other* arm
        if flip:
            arm_compare = arm_b  # continue vs deescalate → compare = deescalate

        # Recompute: compare arm is always the one that is NOT arm_active
        arm_compare = arm_b if arm_active == arm_a else arm_a

        X_patient = self._to_vector(features)  # shape (1, n_features)

        # Absolute risks from T-Learner
        p_active  = self._predict_mortality(arm_active,  X_patient)
        p_compare = self._predict_mortality(arm_compare, X_patient)

        # Secondary outcomes
        vfd     = self._predict_continuous(arm_active, COLNAME_VFD28, X_patient)
        vapfd   = self._predict_continuous(arm_active, COLNAME_VAPFD28, X_patient)
        icu_los = self._predict_continuous(arm_active, COLNAME_ICU_LOS, X_patient)

        # ATE + CI from DML
        ate, ate_lb, ate_ub = self._get_ate(arm_a, arm_b, flip)

        # Per-patient CATE from DML
        X_cate_patient = X_patient[:, self.cate_idx]
        patient_cate = self._get_patient_cate(arm_a, arm_b, flip, X_cate_patient)

        effect = float(p_active - p_compare)
        ci_width = abs(ate_ub - ate_lb)
        abs_ate  = abs(ate)
        confidence = (
            "high"     if abs_ate > 0.06 and ci_width < 0.06 else
            "moderate" if abs_ate > 0.02 and ci_width < 0.12 else
            "low"
        )

        pfi = self._feature_contributions(arm_active, X_patient, p_active)
        ood = self._ood_check(X_patient)

        return {
            "withTreatment":    round(p_active * 100,  1),
            "withoutTreatment": round(p_compare * 100, 1),
            "effect":           round(effect * 100,    1),
            "ate":              round(ate * 100,       1),
            "ateLowerBound":    round(ate_lb * 100,    1),
            "ateUpperBound":    round(ate_ub * 100,    1),
            "confidence":       confidence,
            # F9: predictions are already clipped to clinical bounds inside
            # _predict_continuous, so no defensive max(...) needed here.
            "vfdDays":          round(float(vfd)),
            "icuLosDays":       round(float(icu_los)),
            **({"patientFeatureImportance": pfi} if pfi else {}),
            **({"ood": ood} if ood else {}),
        }

    def similar_patients(self, features: Dict[str, Any], n: int = 8) -> List[Dict]:
        X_patient = self._to_vector(features)
        X_scaled  = self.scaler.transform(X_patient)
        dists, idxs = self.nn_model.kneighbors(X_scaled, n_neighbors=n + 1)

        results = []
        for dist, idx in zip(dists[0][1:], idxs[0][1:]):  # skip self (idx 0)
            row     = self.cohort_df.iloc[idx]
            arm     = int(row[COLNAME_INTERVENTION_STATUS])
            mort    = int(row[COLNAME_MORTALITY_28D]) if pd.notna(row.get(COLNAME_MORTALITY_28D)) else 0
            culture = "positive" if row.get("positive_blood_culture", 0) == 1 else "negative"
            sim     = max(0.0, 1.0 / (1.0 + dist / 3.0))
            results.append({
                "id":             f"mimic-{int(row['stay_id'])}",
                "age":            int(row.get("admission_age", 65)),
                "sofa":           int(row.get("SOFA_at_decision", 7)),
                "crp":            round(float(row.get("CRP_at_decision", 100) or 100), 1),
                "cultureResult":  culture,
                "antibioticDays": int(round(float(row.get("days_on_abx", 3) or 3))),
                "vaso":           "YES" if row.get("vasopressors_at_decision", 0) == 1 else "NO",
                "aki":            int(row.get("AKI_stage_at_decision", 0) or 0),
                "treatment":      ARM_LABEL.get(arm, "continue"),
                "outcome":        "Deceased" if mort == 1 else "Survived",
                "sim":            round(float(sim), 2),
            })
        return sorted(results, key=lambda p: p["sim"], reverse=True)

    # ── Private: fitting ──────────────────────────────────────────────────────

    def _fit(self, cache: Path):
        pop        = pd.read_parquet(DIR_COHORT / "target_population.parquet")
        confounders = pd.read_parquet(DIR_COHORT / "confounders.parquet")
        data       = pop.merge(confounders, on="stay_id", how="inner")

        self.feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in data.columns]
        self.cate_cols    = [c for c in CATE_FEATURES if c in self.feature_cols]
        self.cate_idx     = [self.feature_cols.index(c) for c in self.cate_cols]

        # Impute
        imp = SimpleImputer(strategy="median")
        X_full = pd.DataFrame(
            imp.fit_transform(data[self.feature_cols]),
            columns=self.feature_cols, index=data.index,
        )
        self.imputer         = imp
        self.training_medians = dict(zip(self.feature_cols, imp.statistics_))

        T = data[COLNAME_INTERVENTION_STATUS].values
        Y_mort = data[COLNAME_MORTALITY_28D].fillna(0).values

        # Scale for KNN
        scaler   = StandardScaler()
        X_scaled = scaler.fit_transform(X_full.values)
        self.scaler   = scaler
        self.X_scaled = X_scaled

        # NearestNeighbors for similar-patients lookup
        self.nn_model = NearestNeighbors(n_neighbors=9, metric="euclidean")
        self.nn_model.fit(X_scaled)
        self.cohort_df = data.copy()
        for col in self.feature_cols:
            self.cohort_df[col] = X_full[col].values

        # T-Learner: logistic regression per arm for mortality
        # F8: drop the parallel Ridge model used for feature contributions
        # and decompose contributions from the *same* logistic pipeline that
        # produces the displayed risk.
        def _fill(series, fallback):
            m = series.median()
            return series.fillna(m if pd.notna(m) else fallback)
        CONT_OUTCOMES = {
            COLNAME_VFD28:   _fill(data[COLNAME_VFD28],   0.0),
            COLNAME_VAPFD28: _fill(data[COLNAME_VAPFD28], 0.0),
            COLNAME_ICU_LOS: _fill(data[COLNAME_ICU_LOS], 3.0),
        }
        for arm in [0, 1, 2]:
            mask  = T == arm
            X_arm = X_full.values[mask]
            # Mortality (binary): logistic — used for both prediction and contributions
            self.tlearner_mortality[arm] = make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=1000, C=1.0, random_state=RANDOM_STATE),
            )
            self.tlearner_mortality[arm].fit(X_arm, Y_mort[mask].astype(int))
            # Continuous outcomes
            self.tlearner_continuous[arm] = {}
            for col, y_series in CONT_OUTCOMES.items():
                self.tlearner_continuous[arm][col] = make_pipeline(
                    StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13)),
                )
                self.tlearner_continuous[arm][col].fit(X_arm, y_series.values[mask])

        # DML per pairwise comparison
        # F2: binary mortality outcome → probability-returning logistic model_y.
        # F3 not needed here because X_full is already imputed and DML refits
        # the pipelines per fold.
        from econml.dml import DML
        from antibiotic_pipeline.experiments.utils import _ProbaAsRegressor

        for arm_a, arm_b in [(0, 1), (0, 2), (1, 2)]:
            mask    = np.isin(T, [arm_a, arm_b])
            X_sub   = X_full.values[mask]
            T_bin   = (T[mask] == arm_b).astype(int)
            y_sub   = Y_mort[mask]
            nuis_idx = [i for i in range(len(self.feature_cols)) if i not in self.cate_idx]
            X_cate  = X_sub[:, self.cate_idx]
            W       = X_sub[:, nuis_idx]
            model_t = make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
            )
            model_y = make_pipeline(
                StandardScaler(),
                _ProbaAsRegressor(
                    LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)
                ),
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                dml = DML(
                    model_t=model_t,
                    model_y=model_y,
                    model_final=RidgeCV(alphas=np.logspace(-3, 3, 13)),
                    discrete_treatment=True,
                    cv=5,
                    random_state=RANDOM_STATE,
                )
                dml.fit(y_sub, T_bin, X=X_cate, W=W, inference="auto")
            self.dml_models[(arm_a, arm_b)] = {"model": dml, "nuisance_idx": nuis_idx}
            self.dml_cate_mean[(arm_a, arm_b)] = X_cate.mean(axis=0, keepdims=True)

        # F23: Mahalanobis-distance background for out-of-distribution check.
        # Computed once on the imputed+scaled training matrix.
        try:
            self.training_mean_ = X_scaled.mean(axis=0)
            cov = np.cov(X_scaled, rowvar=False)
            self.cov_inv_ = np.linalg.pinv(cov + 1e-6 * np.eye(cov.shape[0]))
            centered = X_scaled - self.training_mean_
            mahal_sq = np.einsum("ij,jk,ik->i", centered, self.cov_inv_, centered)
            self.training_mahalanobis_p99_ = float(np.quantile(np.sqrt(mahal_sq), 0.99))
            logger.info(
                f"OOD reference: Mahalanobis p99 = {self.training_mahalanobis_p99_:.2f}"
            )
        except Exception as exc:
            logger.warning(f"OOD reference setup failed (continuing): {exc}")
            self.cov_inv_ = None

        self.ready = True
        save_keys = [
            "dml_models", "dml_cate_mean", "tlearner_mortality", "tlearner_continuous",
            "imputer", "scaler", "X_scaled",
            "feature_cols", "cate_cols", "cate_idx", "training_medians",
            "nn_model", "cohort_df",
            "cov_inv_", "training_mean_", "training_mahalanobis_p99_",
            "continuous_bounds_",
        ]
        joblib.dump({k: getattr(self, k) for k in save_keys}, cache, compress=3)
        logger.info(f"Models saved to {cache}")

    # ── Private: inference ────────────────────────────────────────────────────

    def _to_vector(self, features: Dict[str, Any]) -> np.ndarray:
        row = np.array([
            features.get(c) if features.get(c) is not None else self.training_medians.get(c, 0.0)
            for c in self.feature_cols
        ], dtype=float)
        return row.reshape(1, -1)

    def _predict_mortality(self, arm: int, X: np.ndarray) -> float:
        return float(self.tlearner_mortality[arm].predict_proba(X)[0, 1])

    def _predict_continuous(self, arm: int, outcome: str, X: np.ndarray) -> float:
        if outcome not in self.tlearner_continuous.get(arm, {}):
            return 0.0
        raw = float(self.tlearner_continuous[arm][outcome].predict(X)[0])
        # F9: enforce clinically valid range without silent clipping inside callers.
        bounds = self.continuous_bounds_.get(outcome)
        if bounds is None:
            return raw
        lo, hi = bounds
        return float(np.clip(raw, lo, hi))

    def _get_ate(self, arm_a: int, arm_b: int, flip: bool):
        dml = self.dml_models[(arm_a, arm_b)]["model"]
        X_mean = self.dml_cate_mean.get(
            (arm_a, arm_b), np.zeros((1, len(self.cate_idx)))
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            inf = dml.ate_inference(X=X_mean)
            ate = float(inf.mean_point)
            try:
                lb_v, ub_v = inf.conf_int_mean()
                lb, ub = float(lb_v), float(ub_v)
            except AttributeError:
                # inference="auto" may not support conf_int_mean; fall back to
                # const_marginal_effect_interval evaluated at the training mean.
                try:
                    lo_arr, hi_arr = dml.const_marginal_effect_interval(X_mean, alpha=0.05)
                    lb = float(np.squeeze(lo_arr))
                    ub = float(np.squeeze(hi_arr))
                except Exception:
                    lb, ub = ate - 0.05, ate + 0.05
        if flip:
            ate, lb, ub = -ate, -ub, -lb
        return ate, lb, ub

    def _get_patient_cate(self, arm_a: int, arm_b: int, flip: bool, X_cate: np.ndarray) -> float:
        dml = self.dml_models[(arm_a, arm_b)]["model"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cate = float(dml.effect(X_cate)[0])
        return -cate if flip else cate

    def _feature_contributions(
        self, arm: int, X_patient: np.ndarray, base_risk: float
    ) -> Optional[Dict]:
        """Logit-space decomposition of the *same* T-Learner that produced
        the displayed risk (F8).

        We decompose logit(p_patient) - logit(p_reference) ≈ Σ β_i * (x_i - x_ref_i)
        on the standardized feature space, then map each contribution back to
        an additive change in absolute risk via the local derivative
        dp/dlogit = p_ref * (1 - p_ref). This is approximate but bounded and
        sums (over features) to a value close to the displayed risk delta.
        """
        try:
            pipe = self.tlearner_mortality[arm]
            scaler = pipe[0]
            logit = pipe[-1]  # LogisticRegression
            coef = logit.coef_[0]            # in standardized space
            intercept = float(logit.intercept_[0])

            ref_vals = np.array(
                [self.training_medians.get(c, 0.0) for c in self.feature_cols]
            )
            ref_scaled = scaler.transform(ref_vals.reshape(1, -1))[0]
            patient_scaled = scaler.transform(X_patient)[0]
            delta_scaled = patient_scaled - ref_scaled

            # Logit at reference + local linear → absolute-risk space
            ref_logit = float(intercept + np.dot(coef, ref_scaled))
            p_ref = 1.0 / (1.0 + np.exp(-ref_logit))
            slope = p_ref * (1.0 - p_ref)  # derivative of sigmoid at ref logit

            contributions = []
            for i, feat in enumerate(self.feature_cols):
                contrib_logit = float(coef[i] * delta_scaled[i])
                contrib_abs = contrib_logit * slope  # absolute-risk approximation
                if abs(contrib_abs) < 1e-4:
                    continue
                contributions.append({
                    "feature":        feat,
                    "label":          FEATURE_LABELS.get(feat, feat.replace("_", " ")),
                    "patientValue":   round(float(X_patient[0, i]), 2),
                    "referenceValue": round(float(ref_vals[i]), 2),
                    "contribution":   round(contrib_abs * 100, 2),
                    "importance":     abs(contrib_abs),
                    "direction":      "increase" if contrib_abs > 0 else "decrease",
                })
            contributions.sort(key=lambda x: x["importance"], reverse=True)
            return {
                "referenceMortality": round(p_ref * 100, 1),
                "baseMortality":      round(base_risk * 100, 1),
                "contributions":      contributions[:8],
            }
        except Exception as exc:
            logger.debug(f"Feature contributions failed: {exc}")
            return None

    # ── F23: OOD detection ───────────────────────────────────────────────────
    def _ood_check(self, X_patient: np.ndarray) -> Optional[Dict]:
        """Mahalanobis distance from the training-cohort centroid.

        Flag the patient as 'out of distribution' if their distance exceeds the
        99th percentile of training-data distances. Used by the API to add a
        warning so clinicians know whether the estimate is interpolation or
        extrapolation.
        """
        if self.cov_inv_ is None or self.training_mean_ is None:
            return None
        try:
            X_scaled = self.scaler.transform(X_patient)[0]
            centered = X_scaled - self.training_mean_
            d2 = float(centered @ self.cov_inv_ @ centered)
            distance = float(np.sqrt(max(d2, 0.0)))
            threshold = float(self.training_mahalanobis_p99_ or distance)
            return {
                "mahalanobis":  round(distance, 2),
                "trainingP99":  round(threshold, 2),
                "outOfDistribution": distance > threshold,
            }
        except Exception as exc:
            logger.debug(f"OOD check failed: {exc}")
            return None
