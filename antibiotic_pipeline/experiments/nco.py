"""
Negative-control diagnostics (F11).

Two flavours:

A) Permutation placebo (always runnable). Shuffle treatment labels within the
   cohort and re-estimate the ATE. The shuffled-label "treatment" cannot
   cause anything, so any non-zero ATE measures residual model bias plus
   noise. We report a distribution over many shuffles and compare it to the
   real-data ATE.

B) Negative-control outcome (data-dependent). Estimate the same DML on an
   outcome that is *not* causally affected by the 72 h antibiotic decision
   but is plausibly affected by the same unmeasured confounders (e.g.,
   in-hospital fall events, pressure-ulcer codes). A non-zero estimate on
   such an outcome signals residual confounding.

This module ships the permutation placebo turnkey and exposes a hook for the
NCO once a proper outcome column is engineered.

Usage:
    python -m antibiotic_pipeline.experiments.nco --n-permutations 20
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_ICUSTAY_ID,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2COHORT,
    DIR2DATA,
    RANDOM_STATE,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.configurations import RF_OUTCOME, RF_TREATMENT
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
)

DIR2DIAG = DIR2DATA / "diagnostics"
COHORT_NAME = "antibiotic_continuation_sepsis"


def _prep_data():
    cohort = DIR2COHORT / COHORT_NAME
    pop = pd.read_parquet(cohort / "target_population.parquet")
    conf = pd.read_parquet(cohort / "confounders.parquet")
    data = pop.merge(conf, on=COLNAME_ICUSTAY_ID, how="inner")

    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in data.columns]
    feature_cols += [
        f"{c}__missing" for c in feature_cols if f"{c}__missing" in data.columns
    ]
    return data, feature_cols


def _ate(
    data: pd.DataFrame,
    feature_cols: list[str],
    outcome: str,
    arm_a: int,
    arm_b: int,
    bootstrap_num_samples: int,
    treatment_override: Optional[pd.Series] = None,
) -> dict:
    treat = treatment_override if treatment_override is not None else data[COLNAME_INTERVENTION_STATUS]
    X = data[feature_cols].copy()
    X[COLNAME_INTERVENTION_STATUS] = treat.values
    y = data[outcome].dropna()
    X = X.loc[y.index]

    imp = SimpleImputer(strategy="median")
    X[feature_cols] = imp.fit_transform(X[feature_cols])

    # n_jobs=1 avoids accumulating loky semaphores across hundreds of permutations
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from antibiotic_pipeline.constants import RANDOM_STATE
    treatment_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(),
        RandomForestClassifier(n_estimators=100, max_depth=6, random_state=RANDOM_STATE, n_jobs=1),
    )
    outcome_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(),
        RandomForestRegressor(n_estimators=100, max_depth=6, random_state=RANDOM_STATE, n_jobs=1),
    )
    wrapper = MultiArmInferenceWrapper(
        treatment_pipeline=treatment_pipe,
        outcome_pipeline=outcome_pipe,
        estimation_method="DML",
        outcome_name=outcome,
        treatment_name=COLNAME_INTERVENTION_STATUS,
        treatment_comparison=(arm_a, arm_b),
        bootstrap_num_samples=bootstrap_num_samples,
    )
    wrapper.fit(X, y)
    result = wrapper.predict(X)
    del wrapper  # let refcount handle cleanup; no explicit gc to avoid loky teardown
    return result


_SAVE_EVERY = 10  # flush to disk and log after every N permutations


def _flush(rows: list, out_path: Path) -> None:
    pd.DataFrame(rows).to_parquet(out_path)


def run_permutation_placebo(
    n_permutations: int = 20,
    bootstrap_num_samples: int = 50,
    outcome: str = COLNAME_MORTALITY_28D,
    out_dir: Path = DIR2DIAG / "nco",
) -> pd.DataFrame:
    """Estimate ATE on shuffled treatment labels and on the true labels.

    Supports resume: if permutation_placebo.parquet already exists the
    already-completed seeds are loaded and only missing ones are computed.
    Flushes to disk every _SAVE_EVERY permutations so a crash loses at most
    that many fits. Calls gc.collect() periodically to keep peak RSS low.
    """
    data, feature_cols = _prep_data()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "permutation_placebo.parquet"

    # ── Resume: load existing rows ────────────────────────────────────────────
    rows: list[dict] = []
    done_real: set[tuple] = set()       # (arm_a, arm_b)
    done_perms: set[tuple] = set()      # (arm_a, arm_b, perm_seed)
    if out_path.exists():
        prev = pd.read_parquet(out_path)
        rows = prev.to_dict("records")
        for r in rows:
            if r["kind"] == "real":
                done_real.add((int(r["arm_a"]), int(r["arm_b"])))
            else:
                if r["perm_seed"] is not None:
                    done_perms.add((int(r["arm_a"]), int(r["arm_b"]), int(r["perm_seed"])))
        logger.info(
            f"Resuming: {len(done_real)} real estimates, "
            f"{len(done_perms)} permutation fits already done"
        )

    rng = np.random.default_rng(RANDOM_STATE)

    for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
        # 1) True-label estimate (skip if already done)
        if (arm_a, arm_b) not in done_real:
            real = _ate(data, feature_cols, outcome, arm_a, arm_b, bootstrap_num_samples)
            rows.append({
                "kind":        "real",
                "perm_seed":   None,
                "arm_a":       arm_a,
                "arm_b":       arm_b,
                "ATE_pp":      round(real["ATE"] * 100, 2),
                "CI_lb_pp":    round(real["ATE lower bound"] * 100, 2),
                "CI_ub_pp":    round(real["ATE upper bound"] * 100, 2),
            })
            done_real.add((arm_a, arm_b))
            _flush(rows, out_path)
            gc.collect()

        # 2) Permutation-null distribution
        # Pre-generate all seeds for this pair so resume is deterministic
        pair_rng = np.random.default_rng(RANDOM_STATE + arm_a * 100 + arm_b)
        seeds = [int(pair_rng.integers(0, 1_000_000)) for _ in range(n_permutations)]

        new_this_pair = 0
        for k, seed in enumerate(seeds):
            if (arm_a, arm_b, seed) in done_perms:
                continue
            permuted = pd.Series(
                pair_rng.permutation(data[COLNAME_INTERVENTION_STATUS].values),
                index=data.index,
            )
            try:
                ph = _ate(
                    data, feature_cols, outcome, arm_a, arm_b,
                    bootstrap_num_samples, treatment_override=permuted,
                )
                rows.append({
                    "kind":      "permutation",
                    "perm_seed": seed,
                    "arm_a":     arm_a,
                    "arm_b":     arm_b,
                    "ATE_pp":    round(ph["ATE"] * 100, 2),
                    "CI_lb_pp":  round(ph["ATE lower bound"] * 100, 2),
                    "CI_ub_pp":  round(ph["ATE upper bound"] * 100, 2),
                })
                done_perms.add((arm_a, arm_b, seed))
                new_this_pair += 1
            except Exception as exc:
                logger.warning(f"perm {k} {arm_a}v{arm_b} failed: {exc}")

            if new_this_pair % _SAVE_EVERY == 0 and new_this_pair > 0:
                _flush(rows, out_path)
                logger.info(f"  {arm_a}v{arm_b}: {new_this_pair} new perms done (k={k})")

        # Flush remainder and print mid-loop summary
        _flush(rows, out_path)
        gc.collect()  # safe here — between pairs, no active loky workers
        sub = pd.DataFrame(rows)
        perm_sub = sub[(sub["arm_a"] == arm_a) & (sub["arm_b"] == arm_b) & (sub["kind"] == "permutation")]
        real_pp = abs(sub.loc[(sub["arm_a"] == arm_a) & (sub["arm_b"] == arm_b) & (sub["kind"] == "real"), "ATE_pp"].iloc[0])
        if len(perm_sub) >= 5:
            perm_q95 = float(np.percentile(np.abs(perm_sub["ATE_pp"].values), 95))
            logger.info(
                f"  {arm_a}v{arm_b}: |ATE_real|={real_pp:.2f} pp, "
                f"|ATE_perm| 95th = {perm_q95:.2f} pp  "
                f"({'signal > null' if real_pp > perm_q95 else 'signal NOT distinguishable from null'})"
                f"  [{len(perm_sub)} shuffles]"
            )

    df = pd.DataFrame(rows)
    df.to_parquet(out_path)

    # Summary JSON
    summary = []
    for (arm_a, arm_b), sub in df.groupby(["arm_a", "arm_b"]):
        real_row = sub.loc[sub["kind"] == "real"].iloc[0]
        perm_rows = sub.loc[sub["kind"] == "permutation"]
        summary.append({
            "arm_a": int(arm_a),
            "arm_b": int(arm_b),
            "real_ATE_pp": float(real_row["ATE_pp"]),
            "real_CI": [float(real_row["CI_lb_pp"]), float(real_row["CI_ub_pp"])],
            "perm_abs_q50": float(np.percentile(np.abs(perm_rows["ATE_pp"].values), 50)) if len(perm_rows) else None,
            "perm_abs_q95": float(np.percentile(np.abs(perm_rows["ATE_pp"].values), 95)) if len(perm_rows) else None,
            "n_permutations": int(len(perm_rows)),
        })
    with open(out_dir / "permutation_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
    logger.info(f"Saved {out_path}")
    return df


def run_nco(
    outcome_column: str,
    bootstrap_num_samples: int = 100,
    out_dir: Path = DIR2DIAG / "nco",
) -> pd.DataFrame:
    """Estimate the DML ATE on a user-provided negative-control outcome column.

    The outcome must already exist in `confounders.parquet` or
    `target_population.parquet`. A non-zero, statistically-significant ATE
    here signals residual confounding (the antibiotic decision cannot
    plausibly cause the NCO).
    """
    data, feature_cols = _prep_data()
    if outcome_column not in data.columns:
        raise KeyError(f"NCO outcome '{outcome_column}' not present in cohort/confounder tables")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
        res = _ate(data, feature_cols, outcome_column, arm_a, arm_b, bootstrap_num_samples)
        rows.append({
            "outcome":  outcome_column,
            "arm_a":    arm_a,
            "arm_b":    arm_b,
            "ATE_pp":   round(res["ATE"] * 100, 2),
            "CI_lb_pp": round(res["ATE lower bound"] * 100, 2),
            "CI_ub_pp": round(res["ATE upper bound"] * 100, 2),
        })
        logger.info(f"  NCO {outcome_column} {arm_a}v{arm_b}: ATE = {rows[-1]['ATE_pp']:+.2f} pp")
    df = pd.DataFrame(rows)
    df.to_parquet(out_dir / f"nco_{outcome_column}.parquet")
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-permutations", type=int, default=20)
    parser.add_argument("--bootstrap", type=int, default=50,
                        help="Bootstrap replicates per fit (kept low so permutation runs are quick)")
    parser.add_argument("--nco", type=str, default=None,
                        help="Run a real negative-control outcome with this column name")
    args = parser.parse_args()

    if args.nco:
        run_nco(args.nco)
    else:
        run_permutation_placebo(args.n_permutations, args.bootstrap)


if __name__ == "__main__":
    main()
