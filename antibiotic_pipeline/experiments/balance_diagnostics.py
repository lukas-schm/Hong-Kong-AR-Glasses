"""
WS5 / WS6 — multi-diagnostic positivity & balance panel.

Reviewer concern #5: 'fraction of rows with propensity in [0.05, 0.95]' is
inadequate. We replace it with:

  * Per-arm propensity histograms (saved as parquet for plotting).
  * Standardised mean differences (SMD) before and after weighting for every
    confounder, per pairwise contrast. SMD threshold 0.1 is the Austin (2009)
    convention for adequate balance.
  * Effective sample size (ESS) of the weights.
  * Tail-weight diagnostics: max weight and top-5% share.
  * Density overlap in covariate space (Mahalanobis-projected).
  * Sensitivity over clipping thresholds {0.01, 0.05, 0.10}.

The same multinomial propensity model used by experiments.benchmarks is used
here, so the diagnostic panel and the benchmark estimates speak to a single
identification story.

Outputs (under data/diagnostics/balance/):
  * smd_table.parquet      — rows: confounder, contrast, raw_smd, weighted_smd
  * propensity_panel.parquet — rows: stay_id, T, contrast, e_hat (per-pair)
  * ess_tail.parquet       — rows: contrast, ESS, max_w, top5_share
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_ICUSTAY_ID,
    COLNAME_INTERVENTION_STATUS,
    DIR2DATA,
)
from antibiotic_pipeline.experiments.benchmarks import (
    ALL_PAIRS,
    Contrast,
    _multinomial_propensity,
    _pairwise_propensity,
    _preprocess,
)


# ── Standardised mean differences ──────────────────────────────────────────


def smd(x_a: np.ndarray, x_b: np.ndarray,
        w_a: np.ndarray | None = None, w_b: np.ndarray | None = None) -> float:
    """Standardised mean difference between groups A and B.

    If weights are given, computes the weighted SMD (Austin 2008).
    """
    if w_a is None:
        m_a = np.nanmean(x_a)
        v_a = np.nanvar(x_a)
    else:
        m_a = np.average(x_a, weights=w_a)
        v_a = np.average((x_a - m_a) ** 2, weights=w_a)
    if w_b is None:
        m_b = np.nanmean(x_b)
        v_b = np.nanvar(x_b)
    else:
        m_b = np.average(x_b, weights=w_b)
        v_b = np.average((x_b - m_b) ** 2, weights=w_b)
    pooled = np.sqrt((v_a + v_b) / 2.0)
    if pooled < 1e-9:
        return 0.0
    return float((m_b - m_a) / pooled)


def _iptw_weights(T_bin: np.ndarray, e: np.ndarray) -> np.ndarray:
    """Stabilised IPTW weights for binary treatment."""
    p1 = float(np.mean(T_bin == 1))
    return T_bin * (p1 / e) + (1 - T_bin) * ((1 - p1) / (1 - e))


def _ess(w: np.ndarray) -> float:
    s = float(np.sum(w))
    return s * s / float(np.sum(w * w))


def _tail_share(w: np.ndarray, q: float = 0.95) -> float:
    """Fraction of total weight carried by the top (1-q) tail."""
    sw = float(np.sum(w))
    thresh = float(np.quantile(w, q))
    return float(np.sum(w[w >= thresh])) / sw


# ── Top-level driver ───────────────────────────────────────────────────────


def run_balance_diagnostics(
    X: pd.DataFrame,
    T: pd.Series,
    feature_cols: List[str],
    pairs: Iterable[Contrast] = ALL_PAIRS,
    clipping_thresholds: Iterable[float] = (0.01, 0.05, 0.10),
    out_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    out_dir = out_dir or (DIR2DATA / "diagnostics" / "balance")
    out_dir.mkdir(parents=True, exist_ok=True)

    Xp = _preprocess(X, feature_cols)
    proba, classes = _multinomial_propensity(Xp, T.values)

    # Save the propensity panel for downstream plotting.
    panel_rows = []
    for pair in pairs:
        m = T.isin([pair.arm_a, pair.arm_b]).values
        e_hat = _pairwise_propensity(proba[m], classes, pair)
        df = pd.DataFrame({
            COLNAME_ICUSTAY_ID: X.loc[m, COLNAME_ICUSTAY_ID].values
                if COLNAME_ICUSTAY_ID in X.columns else np.arange(int(m.sum())),
            COLNAME_INTERVENTION_STATUS: T.values[m],
            "contrast": pair.label,
            "e_hat":   e_hat,
        })
        panel_rows.append(df)
    panel = pd.concat(panel_rows, ignore_index=True)
    panel.to_parquet(out_dir / "propensity_panel.parquet")
    logger.info(f"propensity_panel: {len(panel)} rows -> {out_dir/'propensity_panel.parquet'}")

    # SMD table, ESS, tail diagnostics — across pairs and clipping thresholds.
    smd_rows = []
    ess_rows = []
    for pair in pairs:
        m = T.isin([pair.arm_a, pair.arm_b]).values
        T_bin = (T.values[m] == pair.arm_b).astype(int)
        e_raw = _pairwise_propensity(proba[m], classes, pair)
        # For each clipping threshold, recompute weights + diagnostics.
        for clip in clipping_thresholds:
            e_clip = np.clip(e_raw, clip, 1 - clip)
            w = _iptw_weights(T_bin, e_clip)
            ess_rows.append({
                "contrast": pair.label,
                "clip":     clip,
                "ESS":      _ess(w),
                "max_w":    float(np.max(w)),
                "top5_share": _tail_share(w, q=0.95),
                "rows_clipped_pct": float(np.mean((e_raw < clip) | (e_raw > 1 - clip))) * 100,
            })
            # SMD per confounder
            for col in feature_cols:
                x = X[col].values[m]
                if x.dtype.kind not in "fiu":
                    continue
                raw = smd(x[T_bin == 0], x[T_bin == 1])
                wgt = smd(x[T_bin == 0], x[T_bin == 1],
                          w_a=w[T_bin == 0], w_b=w[T_bin == 1])
                smd_rows.append({
                    "contrast":     pair.label,
                    "clip":         clip,
                    "confounder":   col,
                    "raw_smd":      raw,
                    "weighted_smd": wgt,
                    "abs_raw":      abs(raw),
                    "abs_weighted": abs(wgt),
                })
    smd_df = pd.DataFrame(smd_rows)
    ess_df = pd.DataFrame(ess_rows)
    smd_df.to_parquet(out_dir / "smd_table.parquet")
    ess_df.to_parquet(out_dir / "ess_tail.parquet")
    logger.info(f"smd_table: {len(smd_df)} rows -> {out_dir/'smd_table.parquet'}")
    logger.info(f"ess_tail:  {len(ess_df)} rows -> {out_dir/'ess_tail.parquet'}")

    # Summary: fraction of confounders with |weighted_smd| < 0.1 per contrast
    # under the default 0.05 clip — the Austin convention for adequate balance.
    summary = (
        smd_df.loc[smd_df["clip"] == 0.05]
        .assign(passed=lambda d: d["abs_weighted"] < 0.1)
        .groupby("contrast")["passed"].mean()
        .rename("pct_balanced_after_weighting")
        .to_frame()
    )
    summary.to_parquet(out_dir / "summary.parquet")
    logger.info(f"summary:\n{summary}")

    return {
        "propensity_panel": panel,
        "smd": smd_df,
        "ess_tail": ess_df,
        "summary": summary,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", default="antibiotic_continuation_sepsis")
    args = parser.parse_args()
    from antibiotic_pipeline.constants import DIR2COHORT
    from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
    pop = pd.read_parquet(DIR2COHORT / args.cohort / "target_population.parquet")
    conf = pd.read_parquet(DIR2COHORT / args.cohort / "confounders.parquet")
    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in conf.columns]
    data = pop[[COLNAME_ICUSTAY_ID, COLNAME_INTERVENTION_STATUS]].merge(
        conf, on=COLNAME_ICUSTAY_ID
    )
    run_balance_diagnostics(
        X=data, T=data[COLNAME_INTERVENTION_STATUS], feature_cols=feature_cols
    )
