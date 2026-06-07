"""
Causal-ML estimators for a single binary intervention → binary outcome.

The headline estimator is **cross-fit AIPW** (augmented inverse-propensity
weighting, a.k.a. doubly-robust / double machine learning for the ATE):

    psi_i = mu1(X_i) - mu0(X_i)
            + A_i (Y_i - mu1(X_i)) / e(X_i)
            - (1-A_i)(Y_i - mu0(X_i)) / (1 - e(X_i))

    ATE = mean(psi),   SE = sd(psi) / sqrt(n)        (influence-function based)

Nuisances e(X)=P(A=1|X), mu_a(X)=E[Y|A=a,X] are fit with gradient-boosted trees
and **cross-fitted** over K folds, so the same data are never used to both fit a
nuisance and evaluate it (Chernozhukov et al. 2018). AIPW is consistent if
*either* the propensity *or* the outcome model is correct — hence "doubly
robust." Gradient boosting also consumes MIMIC's missing labs natively, so no
imputation is forced on the nuisance models.

For contrast we also report the naive **unadjusted** risk difference and a
stabilised **IPTW** (Hájek) estimate, plus positivity/overlap diagnostics and a
VanderWeele–Ding **E-value** for residual unmeasured confounding.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# Reuse the antibiotic pipeline's validated E-value implementation.
from antibiotic_pipeline.experiments.evalues import ate_to_rr, evalue, evalue_ci
from mortality_pipeline.constants import (
    ALPHA,
    CONFOUNDER_KEYS,
    IPTW_TRUNC,
    METHOD_AIPW,
    METHOD_ATO,
    METHOD_ATT,
    METHOD_IPTW,
    METHOD_TMLE,
    METHOD_UNADJUSTED,
    MIN_PS_SCORE,
    N_CROSSFIT_FOLDS,
    RANDOM_STATE,
)

_Z = norm.ppf(1 - ALPHA / 2)


# ── nuisance learners ───────────────────────────────────────────────────────
def _make_classifier(kind: str):
    """Return a fresh probabilistic classifier.

    ``hgb`` (default) handles NaNs natively and captures nonlinear
    confounding; ``logistic`` is a transparent, fast linear baseline (wrapped
    with median-imputation + scaling because it cannot ingest NaNs).
    """
    if kind == "hgb":
        return HistGradientBoostingClassifier(
            max_depth=4, max_iter=300, learning_rate=0.05,
            l2_regularization=1.0, random_state=RANDOM_STATE,
        )
    if kind == "logistic":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=2000, C=1.0, random_state=RANDOM_STATE),
        )
    if kind == "superlearner":
        # CV-stacked ensemble (a practical SuperLearner): a linear model, gradient
        # boosting and a random forest, combined by a logistic meta-learner. Makes
        # the double-robustness real — no single nuisance family is trusted.
        from sklearn.ensemble import RandomForestClassifier, StackingClassifier
        base = [
            ("lr", make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                 LogisticRegression(max_iter=1000, random_state=RANDOM_STATE))),
            ("hgb", HistGradientBoostingClassifier(max_depth=4, max_iter=300,
                    learning_rate=0.05, l2_regularization=1.0, random_state=RANDOM_STATE)),
            ("rf", make_pipeline(SimpleImputer(strategy="median"),
                                 RandomForestClassifier(n_estimators=150, max_depth=8,
                                 n_jobs=-1, random_state=RANDOM_STATE))),
        ]
        return StackingClassifier(estimators=base,
                                  final_estimator=LogisticRegression(max_iter=1000),
                                  cv=3, n_jobs=-1)
    raise ValueError(f"Unknown learner kind: {kind}")


def _proba(clf, X) -> np.ndarray:
    return clf.predict_proba(X)[:, 1]


def crossfit_propensity(
    X: pd.DataFrame,
    A: np.ndarray,
    learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS,
    seed: int = RANDOM_STATE,
) -> np.ndarray:
    """K-fold cross-fitted propensity e(X) = P(A=1 | X).

    Outcome-independent, so it is computed once per intervention and reused
    across all of that intervention's mortality outcomes.
    """
    e_hat = np.zeros(len(A))
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    for train, test in skf.split(X.to_numpy(float), A):
        ps = _make_classifier(learner)
        ps.fit(X.iloc[train], A[train])
        e_hat[test] = _proba(ps, X.iloc[test])
    return e_hat


def crossfit_nuisances(
    X: pd.DataFrame,
    A: np.ndarray,
    Y: np.ndarray,
    learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS,
    precomputed_e: Optional[np.ndarray] = None,
    seed: int = RANDOM_STATE,
) -> Dict[str, np.ndarray]:
    """K-fold cross-fitted nuisances: propensity e(X) and outcomes mu1/mu0.

    The outcome model is fit on [X, A] and queried with A toggled to 1/0, so a
    single cross-fitted regression yields both counterfactual surfaces. Pass
    ``precomputed_e`` to skip re-fitting the (outcome-independent) propensity;
    vary ``seed`` for repeated cross-fitting (median DML).
    """
    n = len(Y)
    fit_ps = precomputed_e is None
    e_hat = np.zeros(n) if fit_ps else np.asarray(precomputed_e, dtype=float)
    mu1 = np.zeros(n)
    mu0 = np.zeros(n)
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed)

    Xv = X.to_numpy(dtype=float)
    XA = np.column_stack([Xv, A.astype(float)])  # outcome model features = [X, A]

    for train, test in skf.split(Xv, A):
        if fit_ps:
            ps = _make_classifier(learner)
            ps.fit(X.iloc[train], A[train])
            e_hat[test] = _proba(ps, X.iloc[test])

        # outcome mu_a(X) = E[Y | X, A=a]
        om = _make_classifier(learner)
        om.fit(_as_df(XA[train], X, with_a=True), Y[train])
        X1 = XA[test].copy(); X1[:, -1] = 1.0
        X0 = XA[test].copy(); X0[:, -1] = 0.0
        mu1[test] = _proba(om, _as_df(X1, X, with_a=True))
        mu0[test] = _proba(om, _as_df(X0, X, with_a=True))

    return {"e": e_hat, "mu1": mu1, "mu0": mu0}


def _as_df(arr: np.ndarray, X_ref: pd.DataFrame, with_a: bool) -> pd.DataFrame:
    cols = list(X_ref.columns) + (["_A"] if with_a else [])
    return pd.DataFrame(arr, columns=cols)


# ── individual estimators ───────────────────────────────────────────────────
def unadjusted_rd(A: np.ndarray, Y: np.ndarray) -> Dict:
    p1 = Y[A == 1].mean()
    p0 = Y[A == 0].mean()
    n1 = int((A == 1).sum())
    n0 = int((A == 0).sum())
    se = np.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    return _ci_row(METHOD_UNADJUSTED, p1 - p0, se, ey0=p0)


def iptw_ate(A: np.ndarray, Y: np.ndarray, e: np.ndarray, truncate: float = IPTW_TRUNC) -> Dict:
    """Stabilised, truncated Hájek IPTW with influence-function SE (e fixed).

    Stabilised weights p/e (treated), (1-p)/(1-e) (control), truncated at the
    ``truncate`` / 1-``truncate`` quantiles to tame the tail under poor overlap.
    """
    e = np.clip(e, MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    p = A.mean()
    sw = np.where(A == 1, p / e, (1 - p) / (1 - e))
    if truncate:
        lo, hi = np.quantile(sw, [truncate, 1 - truncate])
        sw = np.clip(sw, lo, hi)
    w1, w0 = A * sw, (1 - A) * sw
    ey1 = np.sum(w1 * Y) / np.sum(w1)
    ey0 = np.sum(w0 * Y) / np.sum(w0)
    if1 = (w1 / w1.mean()) * (Y - ey1)
    if0 = (w0 / w0.mean()) * (Y - ey0)
    inf = if1 - if0
    se = inf.std(ddof=1) / np.sqrt(len(Y))
    return _ci_row(METHOD_IPTW, ey1 - ey0, se, ey0=ey0)


def att_aipw(A: np.ndarray, Y: np.ndarray, nuis: Dict[str, np.ndarray]) -> Dict:
    """Doubly-robust ATT (effect on the treated)."""
    e = np.clip(nuis["e"], MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    mu0 = nuis["mu0"]
    p1 = A.mean()
    psi = (A * (Y - mu0) - (1 - A) * (e / (1 - e)) * (Y - mu0)) / p1
    ate = psi.mean()
    se = psi.std(ddof=1) / np.sqrt(len(Y))
    ey0 = np.mean(A * mu0 + (1 - A) * (e / (1 - e)) * (Y - mu0)) / p1
    row = _ci_row(METHOD_ATT, ate, se, ey0=ey0)
    row["counterfactual_risk_control"] = float(ey0)
    return row


def ato_ipw(A: np.ndarray, Y: np.ndarray, e: np.ndarray) -> Dict:
    """Overlap-weighted ATO (Li–Morgan–Zaslavsky): the clinical-equipoise estimand.

    Weights = (1-e) for treated, e for control — exact mean balance, bounded
    weights, target population = patients whose treatment is genuinely uncertain.
    """
    e = np.clip(e, MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    w = np.where(A == 1, 1 - e, e)
    w1, w0 = A * w, (1 - A) * w
    ey1 = np.sum(w1 * Y) / np.sum(w1)
    ey0 = np.sum(w0 * Y) / np.sum(w0)
    if1 = (w1 / w1.mean()) * (Y - ey1)
    if0 = (w0 / w0.mean()) * (Y - ey0)
    inf = if1 - if0
    se = inf.std(ddof=1) / np.sqrt(len(Y))
    return _ci_row(METHOD_ATO, ey1 - ey0, se, ey0=ey0)


def aipw_ate(A: np.ndarray, Y: np.ndarray, nuis: Dict[str, np.ndarray]) -> Dict:
    """Doubly-robust AIPW with influence-function SE (the headline estimate)."""
    e = np.clip(nuis["e"], MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    mu1, mu0 = nuis["mu1"], nuis["mu0"]
    psi1 = mu1 + A * (Y - mu1) / e
    psi0 = mu0 + (1 - A) * (Y - mu0) / (1 - e)
    ey1, ey0 = psi1.mean(), psi0.mean()
    psi = psi1 - psi0
    ate = psi.mean()
    se = psi.std(ddof=1) / np.sqrt(len(Y))
    row = _ci_row(METHOD_AIPW, ate, se, ey0=ey0)
    row["counterfactual_risk_treated"] = float(ey1)
    row["counterfactual_risk_control"] = float(ey0)
    return row


def _ci_row(method: str, ate: float, se: float, ey0: float) -> Dict:
    z = ate / se if se > 0 else np.nan
    return {
        "method": method,
        "ate": float(ate),                 # risk difference (probability scale)
        "ate_pct": float(ate * 100),       # percentage points
        "ci_low": float(ate - _Z * se),
        "ci_high": float(ate + _Z * se),
        "se": float(se),
        "p_value": float(2 * norm.sf(abs(z))) if np.isfinite(z) else np.nan,
        "_ey0": float(ey0),
    }


# ── P5: TMLE (targeted MLE) ─────────────────────────────────────────────────
def _logit(p, eps=1e-6):
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def _expit(x):
    return 1.0 / (1.0 + np.exp(-x))


def tmle_ate(A: np.ndarray, Y: np.ndarray, nuis: Dict[str, np.ndarray],
             q_bound: float = 1e-3) -> Dict:
    """Targeted maximum-likelihood estimate of the ATE (binary outcome).

    Fluctuates the cross-fitted outcome surface toward the efficient influence
    curve using the clever covariate H = A/g − (1−A)/(1−g), with a single-
    parameter logistic tilt solved by Newton's method. Bounded (expit keeps the
    targeted predictions in [0,1]) and asymptotically efficient; this is the
    gold-standard doubly-robust estimator and pairs with cross-fitting (CV-TMLE).
    """
    g = np.clip(nuis["e"], MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    Q1 = np.clip(nuis["mu1"], q_bound, 1 - q_bound)
    Q0 = np.clip(nuis["mu0"], q_bound, 1 - q_bound)
    QA = np.where(A == 1, Q1, Q0)
    H = A / g - (1 - A) / (1 - g)
    H1, H0 = 1.0 / g, -1.0 / (1 - g)

    # solve the fluctuation parameter eps: logit(Q*) = logit(QA) + eps*H
    off = _logit(QA)
    eps = 0.0
    for _ in range(50):
        p = _expit(off + eps * H)
        score = np.sum(H * (Y - p))
        info = np.sum(H * H * p * (1 - p))
        if info < 1e-12:
            break
        step = score / info
        eps += step
        if abs(step) < 1e-8:
            break

    Q1s = _expit(_logit(Q1) + eps * H1)
    Q0s = _expit(_logit(Q0) + eps * H0)
    QAs = _expit(off + eps * H)
    psi = float(np.mean(Q1s - Q0s))
    ic = H * (Y - QAs) + (Q1s - Q0s) - psi          # efficient influence curve
    se = float(ic.std(ddof=1) / np.sqrt(len(Y)))
    row = _ci_row(METHOD_TMLE, psi, se, ey0=float(np.mean(Q0s)))
    row["counterfactual_risk_treated"] = float(np.mean(Q1s))
    row["counterfactual_risk_control"] = float(np.mean(Q0s))
    return row


def repeated_estimate(
    X: pd.DataFrame, A: np.ndarray, Y: np.ndarray,
    estimator: str = "tmle", learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS, repeats: int = 5,
) -> Dict:
    """Repeated cross-fitting (median DML): aggregate over ``repeats`` independent
    fold splits to remove single-split randomness. Median point estimate; variance
    = median of (within-split var + squared deviation from the median).
    """
    psis, vars = [], []
    for r in range(repeats):
        nuis = crossfit_nuisances(X, A, Y, learner=learner, n_folds=n_folds, seed=RANDOM_STATE + r)
        row = tmle_ate(A, Y, nuis) if estimator == "tmle" else aipw_ate(A, Y, nuis)
        psis.append(row["ate"]); vars.append(row["se"] ** 2)
    psis, vars = np.array(psis), np.array(vars)
    psi_med = float(np.median(psis))
    var_med = float(np.median(vars + (psis - psi_med) ** 2))
    se = float(np.sqrt(var_med))
    row = _ci_row(estimator, psi_med, se, ey0=np.nan)
    row["repeats"] = repeats
    row["point_spread"] = float(psis.max() - psis.min()) * 100
    return row


# ── diagnostics ─────────────────────────────────────────────────────────────
def _weighted_mean_var(x, w):
    m = ~np.isnan(x)
    if m.sum() == 0:
        return np.nan, np.nan
    xw, ww = x[m], w[m]
    mu = np.sum(ww * xw) / np.sum(ww)
    var = np.sum(ww * (xw - mu) ** 2) / np.sum(ww)
    return mu, var


def _smd(x, A, w=None):
    """Standardised mean difference between arms (NaN-aware, optionally weighted)."""
    xt, xc = x[A == 1], x[A == 0]
    if w is None:
        mt, vt = np.nanmean(xt), np.nanvar(xt)
        mc, vc = np.nanmean(xc), np.nanvar(xc)
    else:
        mt, vt = _weighted_mean_var(xt, w[A == 1])
        mc, vc = _weighted_mean_var(xc, w[A == 0])
    pooled = np.sqrt((vt + vc) / 2)
    return abs(mt - mc) / pooled if pooled and np.isfinite(pooled) and pooled > 0 else np.nan


def overlap_diagnostics(X: pd.DataFrame, A: np.ndarray, e: np.ndarray) -> Dict:
    e_clip = np.clip(e, MIN_PS_SCORE, 1 - MIN_PS_SCORE)
    w = A / e_clip + (1 - A) / (1 - e_clip)        # ATE weights for balance check
    smd_raw = [_smd(X[c].to_numpy(float), A) for c in X.columns]
    smd_wt = [_smd(X[c].to_numpy(float), A, w) for c in X.columns]
    ess = (w.sum() ** 2) / np.sum(w ** 2)
    return {
        "ps_overlap_frac": float(np.mean((e > 0.1) & (e < 0.9))),
        "ps_min": float(e.min()),
        "ps_max": float(e.max()),
        "frac_clipped": float(np.mean((e < MIN_PS_SCORE) | (e > 1 - MIN_PS_SCORE))),
        "max_smd_raw": float(np.nanmax(smd_raw)),
        "mean_smd_raw": float(np.nanmean(smd_raw)),
        "max_smd_weighted": float(np.nanmax(smd_wt)),
        "mean_smd_weighted": float(np.nanmean(smd_wt)),
        "ess": float(ess),
        "ess_frac": float(ess / len(A)),
    }


def add_evalue(aipw_row: Dict) -> Dict:
    """Attach the E-value for the doubly-robust estimate to its scoreboard row."""
    ey0 = aipw_row.get("counterfactual_risk_control", aipw_row["_ey0"])
    baseline_pct = ey0 * 100
    rr = ate_to_rr(aipw_row["ate_pct"], baseline_pct)
    rr_lb = ate_to_rr(aipw_row["ci_low"] * 100, baseline_pct)
    rr_ub = ate_to_rr(aipw_row["ci_high"] * 100, baseline_pct)
    aipw_row["risk_ratio"] = float(rr) if rr else np.nan
    aipw_row["e_value"] = float(evalue(rr)) if rr else np.nan
    aipw_row["e_value_ci"] = (
        float(evalue_ci(rr_lb, rr_ub)) if (rr_lb and rr_ub) else 1.0
    )
    return aipw_row


# ── orchestration for one (intervention, outcome) cell ──────────────────────
def estimate_intervention_effect(
    df: pd.DataFrame,
    intervention: str,
    outcome: str,
    confounders: Optional[List[str]] = None,
    learner: str = "hgb",
    n_folds: int = N_CROSSFIT_FOLDS,
    precomputed_e: Optional[np.ndarray] = None,
) -> Dict:
    """Run all three estimators + diagnostics + E-value for one cell.

    Returns a dict with ``rows`` (one per method) and ``diagnostics``. Pass
    ``precomputed_e`` (the cross-fitted propensity, aligned to the full ``df``
    that was handed in, or to the outcome-observed subset) to reuse the
    outcome-independent propensity across an intervention's mortality outcomes.
    """
    confounders = confounders or CONFOUNDER_KEYS
    mask = df[outcome].notna() & df[intervention].notna()
    sub = df.loc[mask]
    X = sub[confounders]
    A = sub[intervention].to_numpy(int)
    Y = sub[outcome].to_numpy(float)

    n_treated, n_control = int(A.sum()), int((A == 0).sum())
    if n_treated < 50 or n_control < 50:
        logger.warning(f"  {intervention} × {outcome}: too few in an arm "
                       f"(treated={n_treated}, control={n_control}); skipping")
        return {"rows": [], "diagnostics": {}}

    # Align a precomputed propensity to this outcome's observed-Y subset.
    e_sub: Optional[np.ndarray] = None
    if precomputed_e is not None:
        pe = np.asarray(precomputed_e, dtype=float)
        if len(pe) == len(df):
            e_sub = pe[mask.to_numpy()]
        elif len(pe) == len(sub):
            e_sub = pe

    nuis = crossfit_nuisances(X, A, Y, learner=learner, n_folds=n_folds, precomputed_e=e_sub)

    rows = [
        unadjusted_rd(A, Y),
        iptw_ate(A, Y, nuis["e"]),
        add_evalue(aipw_ate(A, Y, nuis)),
    ]
    diag = overlap_diagnostics(X, A, nuis["e"])
    meta = {
        "intervention": intervention,
        "outcome": outcome,
        "n": int(len(Y)),
        "n_treated": n_treated,
        "n_control": n_control,
        "outcome_rate": float(np.mean(Y)),
        "learner": learner,
    }
    for r in rows:
        r.update(meta)
        r.update({f"diag_{k}": v for k, v in diag.items()})
        r.pop("_ey0", None)
    return {"rows": rows, "diagnostics": {**meta, **diag}, "nuisances": nuis}
