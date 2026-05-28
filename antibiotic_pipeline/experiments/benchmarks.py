"""
WS5 — estimator benchmarks: multinomial GPS + IPTW + overlap weighting + AIPW
+ TMLE + g-computation + propensity matching.

These are deliberately hand-rolled (rather than pulled from a heavy CRAN-style
dep) so that:

  * the implementations are auditable in a single file,
  * every estimator can share the same propensity model (the multinomial GPS),
    making pairwise contrasts coherent on a single covariate support,
  * estimand annotations (ATE / ATT / ATO) are explicit at the call site.

Output is a dataframe with one row per (estimator, contrast, estimand) cell,
columns: estimator, estimand, arm_a, arm_b, n_a, n_b, ATE_pp, CI_lb_pp,
CI_ub_pp. CIs come from bootstrap-percentile (default 500 reps).

Usage::

    from antibiotic_pipeline.experiments.benchmarks import run_benchmark_grid

    grid = run_benchmark_grid(
        X=confounders_df,
        T=pop['treatment_arm'],
        y=pop['mortality_28days'],
        feature_cols=feature_cols,
        bootstrap=500,
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import MIN_PS_SCORE, RANDOM_STATE


# ── Estimand labels ────────────────────────────────────────────────────────

ATE = "ATE"            # marginal risk difference
ATT = "ATT"            # average treatment effect on the treated
ATO = "ATO"            # overlap-weighted ATE (Li 2018)


@dataclass
class Contrast:
    arm_a: int
    arm_b: int

    @property
    def label(self) -> str:
        return f"{self.arm_a}v{self.arm_b}"


ALL_PAIRS: Tuple[Contrast, ...] = (Contrast(0, 1), Contrast(0, 2), Contrast(1, 2))


# ── Utilities ──────────────────────────────────────────────────────────────


def _preprocess(X: pd.DataFrame, cols: List[str]) -> np.ndarray:
    """Median-impute + standard-scale numeric columns for downstream estimators.

    Categorical columns must already be one-hot encoded by the caller; this
    helper is intentionally minimal.
    """
    imp = SimpleImputer(strategy="median")
    scl = StandardScaler()
    return scl.fit_transform(imp.fit_transform(X[cols].values))


def _multinomial_propensity(
    Xp: np.ndarray, T: np.ndarray, *, max_iter: int = 1000
) -> Tuple[np.ndarray, List[int]]:
    """Fit a multinomial RF classifier and return P(T=k | X) for k in classes.

    Returns
    -------
    proba : (n, K) array
    classes : list of K class labels
    """
    clf = RandomForestClassifier(
        n_estimators=200,
        min_samples_leaf=20,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    clf.fit(Xp, T)
    proba = clf.predict_proba(Xp)
    proba = np.clip(proba, MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    return proba, list(clf.classes_)


def _pairwise_propensity(
    proba: np.ndarray, classes: List[int], pair: Contrast
) -> np.ndarray:
    """Per-row probability of treatment B given treatment in {A, B}."""
    iA = classes.index(pair.arm_a)
    iB = classes.index(pair.arm_b)
    p = proba[:, iB] / (proba[:, iA] + proba[:, iB])
    return np.clip(p, MIN_PS_SCORE, 1 - MIN_PS_SCORE)


# ── IPTW (stabilised) ──────────────────────────────────────────────────────


def iptw_ate(y: np.ndarray, T: np.ndarray, e_hat: np.ndarray) -> float:
    """Stabilised IPTW estimate of the ATE on a binary treatment T ∈ {0, 1}.

    e_hat is P(T=1 | X). Stabilisation uses the marginal P(T=1).
    """
    p1 = float(np.mean(T == 1))
    w = T * (p1 / e_hat) + (1 - T) * ((1 - p1) / (1 - e_hat))
    return float(
        np.average(y[T == 1], weights=w[T == 1])
        - np.average(y[T == 0], weights=w[T == 0])
    )


# ── Overlap weighting (Li, Morgan, Zaslavsky 2018) ─────────────────────────


def overlap_weighted_ate(y: np.ndarray, T: np.ndarray, e_hat: np.ndarray) -> float:
    """ATO: weight is e(1-e) on the treated side and e(1-e) on the control side.

    Standard formulation: ATO = mean(w*y | T=1) - mean(w*y | T=0)
    where w = 1-e for treated and w = e for control (giving harmonic mean
    overlap weight). Returns the overlap-weighted treatment-effect estimand.
    """
    w_treat = 1.0 - e_hat
    w_ctrl = e_hat
    mu1 = np.sum(w_treat[T == 1] * y[T == 1]) / np.sum(w_treat[T == 1])
    mu0 = np.sum(w_ctrl[T == 0] * y[T == 0]) / np.sum(w_ctrl[T == 0])
    return float(mu1 - mu0)


# ── AIPW (doubly-robust) ───────────────────────────────────────────────────


def aipw_ate(
    y: np.ndarray, T: np.ndarray, e_hat: np.ndarray, mu0: np.ndarray, mu1: np.ndarray
) -> float:
    score = (
        mu1 - mu0
        + (T / e_hat) * (y - mu1)
        - ((1 - T) / (1 - e_hat)) * (y - mu0)
    )
    return float(np.mean(score))


# ── G-computation ──────────────────────────────────────────────────────────


def gcomp_ate(mu0: np.ndarray, mu1: np.ndarray) -> float:
    return float(np.mean(mu1) - np.mean(mu0))


# ── TMLE (single-step targeted maximum likelihood update) ──────────────────


def tmle_ate(
    y: np.ndarray, T: np.ndarray, e_hat: np.ndarray, mu0: np.ndarray, mu1: np.ndarray
) -> float:
    """One-step TMLE for a bounded outcome on [0, 1].

    Targeting step: regress (y - mu_a) on the clever covariate H_a within
    each treatment arm, then update mu_a -> mu_a* and compute the
    g-computation difference. See van der Laan & Rose (2011), Ch. 4.
    """
    eps = 1e-6
    y_b = np.clip(y, eps, 1 - eps)
    # Clever covariates
    H1 = T / e_hat
    H0 = -(1 - T) / (1 - e_hat)
    H = H1 + H0
    # Logistic offset model
    from scipy.special import logit, expit
    Q = T * mu1 + (1 - T) * mu0
    Q = np.clip(Q, eps, 1 - eps)
    # Fit one-parameter logistic with offset = logit(Q)
    # Iteratively reweighted update via simple Newton step
    eps_param = 0.0
    for _ in range(50):
        p = expit(logit(Q) + eps_param * H)
        grad = float(np.sum(H * (y_b - p)))
        hess = float(np.sum((H ** 2) * p * (1 - p)))
        if hess < 1e-12:
            break
        delta = grad / hess
        eps_param += delta
        if abs(delta) < 1e-8:
            break
    mu1_star = expit(logit(np.clip(mu1, eps, 1 - eps)) + eps_param * (1.0 / e_hat))
    mu0_star = expit(logit(np.clip(mu0, eps, 1 - eps)) + eps_param * (-1.0 / (1 - e_hat)))
    return float(np.mean(mu1_star - mu0_star))


# ── Propensity matching (ATT, not ATE) ─────────────────────────────────────


def matched_att(
    y: np.ndarray, T: np.ndarray, e_hat: np.ndarray, caliper: float = 0.2
) -> float:
    """1:1 nearest-neighbour propensity matching with a caliper.

    Caliper is in standard-deviation units of the propensity (Austin 2011).
    Treated units without a match within caliper are dropped (and reported
    as the caliper-rejection rate); the returned estimand is ATT on the
    matched-treated subset.
    """
    sd_e = float(np.std(e_hat))
    cal = caliper * sd_e
    e_ctrl = e_hat[T == 0].reshape(-1, 1)
    y_ctrl = y[T == 0]
    nn = NearestNeighbors(n_neighbors=1).fit(e_ctrl)

    e_t = e_hat[T == 1].reshape(-1, 1)
    y_t = y[T == 1]
    dist, idx = nn.kneighbors(e_t)
    dist = dist.flatten()
    idx = idx.flatten()
    kept = dist <= cal
    if kept.sum() < 5:
        return float("nan")
    matched_treated = y_t[kept]
    matched_ctrl = y_ctrl[idx[kept]]
    return float(np.mean(matched_treated) - np.mean(matched_ctrl))


# ── Outcome regression (for AIPW / TMLE / g-comp) ──────────────────────────


def _fit_outcome_per_arm(
    Xp: np.ndarray, T: np.ndarray, y: np.ndarray, binary_outcome: bool
):
    """Fit one outcome regressor per arm and return predicted potential
    outcomes for every row under each arm.
    """
    if binary_outcome:
        mdl = LogisticRegression(max_iter=1000, C=1.0, random_state=RANDOM_STATE)
    else:
        mdl = RandomForestRegressor(
            n_estimators=200,
            min_samples_leaf=20,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )
    from sklearn.base import clone
    m0 = clone(mdl).fit(Xp[T == 0], y[T == 0])
    m1 = clone(mdl).fit(Xp[T == 1], y[T == 1])
    if binary_outcome:
        mu0 = m0.predict_proba(Xp)[:, 1]
        mu1 = m1.predict_proba(Xp)[:, 1]
    else:
        mu0 = m0.predict(Xp)
        mu1 = m1.predict(Xp)
    return mu0, mu1


# ── Bootstrap ──────────────────────────────────────────────────────────────


def _bootstrap_ci(
    fn: Callable[[np.random.Generator], float],
    n_reps: int = 500,
    alpha: float = 0.05,
    seed: int = RANDOM_STATE,
) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_reps):
        v = fn(rng)
        if not np.isnan(v):
            samples.append(v)
    if not samples:
        return float("nan"), float("nan")
    return float(np.quantile(samples, alpha / 2)), float(np.quantile(samples, 1 - alpha / 2))


# ── Top-level driver ───────────────────────────────────────────────────────


def run_benchmark_grid(
    X: pd.DataFrame,
    T: pd.Series,
    y: pd.Series,
    feature_cols: List[str],
    binary_outcome: bool = True,
    bootstrap: int = 500,
    pairs: Iterable[Contrast] = ALL_PAIRS,
) -> pd.DataFrame:
    """Run the eight-estimator benchmark grid across all three pairwise contrasts.

    Returns a long-form dataframe with columns:
      estimator, estimand, arm_a, arm_b, n_a, n_b, ATE_pp, CI_lb_pp, CI_ub_pp.
    """
    # Drop rows with missing outcome
    mask = ~y.isna()
    X = X.loc[mask].reset_index(drop=True)
    T = T.loc[mask].reset_index(drop=True).astype(int)
    y = y.loc[mask].reset_index(drop=True).astype(float)

    Xp = _preprocess(X, feature_cols)
    proba, classes = _multinomial_propensity(Xp, T.values)

    rows: List[dict] = []
    for pair in pairs:
        m = T.isin([pair.arm_a, pair.arm_b]).values
        T_bin = (T.values[m] == pair.arm_b).astype(int)
        e_hat = _pairwise_propensity(proba[m], classes, pair)
        Xp_pair = Xp[m]
        y_pair = y.values[m]
        n_a = int((T.values[m] == pair.arm_a).sum())
        n_b = int((T.values[m] == pair.arm_b).sum())

        # Outcome regressions for AIPW/TMLE/g-comp
        mu0, mu1 = _fit_outcome_per_arm(Xp_pair, T_bin, y_pair, binary_outcome)

        # Closures for bootstrap resampling
        def boot_iptw(rng):
            idx = rng.integers(0, len(y_pair), len(y_pair))
            return iptw_ate(y_pair[idx], T_bin[idx], e_hat[idx])

        def boot_overlap(rng):
            idx = rng.integers(0, len(y_pair), len(y_pair))
            return overlap_weighted_ate(y_pair[idx], T_bin[idx], e_hat[idx])

        def boot_aipw(rng):
            idx = rng.integers(0, len(y_pair), len(y_pair))
            return aipw_ate(y_pair[idx], T_bin[idx], e_hat[idx], mu0[idx], mu1[idx])

        def boot_gcomp(rng):
            idx = rng.integers(0, len(y_pair), len(y_pair))
            return gcomp_ate(mu0[idx], mu1[idx])

        def boot_tmle(rng):
            idx = rng.integers(0, len(y_pair), len(y_pair))
            return tmle_ate(y_pair[idx], T_bin[idx], e_hat[idx], mu0[idx], mu1[idx])

        def boot_match(rng):
            idx = rng.integers(0, len(y_pair), len(y_pair))
            return matched_att(y_pair[idx], T_bin[idx], e_hat[idx])

        for est_name, estimand, point_fn, boot_fn in [
            ("IPTW_stabilised", ATE, lambda: iptw_ate(y_pair, T_bin, e_hat), boot_iptw),
            ("Overlap_weighted", ATO, lambda: overlap_weighted_ate(y_pair, T_bin, e_hat), boot_overlap),
            ("AIPW", ATE, lambda: aipw_ate(y_pair, T_bin, e_hat, mu0, mu1), boot_aipw),
            ("G_computation", ATE, lambda: gcomp_ate(mu0, mu1), boot_gcomp),
            ("TMLE", ATE, lambda: tmle_ate(y_pair, T_bin, e_hat, mu0, mu1), boot_tmle),
            ("PS_matching", ATT, lambda: matched_att(y_pair, T_bin, e_hat), boot_match),
        ]:
            pt = point_fn()
            ci_lb, ci_ub = _bootstrap_ci(boot_fn, n_reps=bootstrap)
            rows.append({
                "estimator": est_name,
                "estimand":  estimand,
                "arm_a":     pair.arm_a,
                "arm_b":     pair.arm_b,
                "n_a":       n_a,
                "n_b":       n_b,
                "ATE_pp":    round(pt * 100, 2),
                "CI_lb_pp":  round(ci_lb * 100, 2),
                "CI_ub_pp":  round(ci_ub * 100, 2),
            })
            logger.info(
                f"  {est_name:18s} ({estimand}) {pair.label}: "
                f"{pt*100:+.2f}pp [{ci_lb*100:+.2f}, {ci_ub*100:+.2f}]"
            )

    return pd.DataFrame(rows)
