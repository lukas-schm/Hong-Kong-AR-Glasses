"""
WS11 — Train per-horizon T-Learner mortality models for the CDSS API.

For each of the four trajectory endpoints (7d, 14d, 21d, 28d), fit one
``LogisticRegression`` per treatment arm so the API can return
``{t7, t14, t21, t28}`` per arm for any patient. CIs are computed via a
**joint bootstrap**: a single resample of the cohort is applied to all
four horizons at once, so the resulting trajectory CI band is coherent
across horizons (independent per-horizon bootstraps produce
technically-inconsistent bands — see WS11 review note #10).

The fitted models are saved as a single pickle for the API to consume,
and the bootstrap-derived trajectory matrix
``shape=(n_boot, 4_horizons, 3_arms)`` is saved as a parquet for the
manuscript trajectory figure.

Output
------
* ``data/models/trajectory_tlearner.joblib`` — dict keyed by horizon then arm
* ``data/diagnostics/trajectory_boot.parquet`` — long-form bootstrap risks
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
import joblib
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_ICUSTAY_ID,
    COLNAME_INTERVENTION_STATUS,
    DIR2COHORT,
    DIR2DATA,
    MORTALITY_TRAJECTORY,
    RANDOM_STATE,
    TREATMENT_ARM_LABELS,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH


def _fit_one(X_arm, y_arm):
    pipe = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(max_iter=1000, C=1.0, random_state=RANDOM_STATE),
    )
    pipe.fit(X_arm, y_arm)
    return pipe


def main(n_bootstrap: int = 300, cohort_name: str = "antibiotic_continuation_sepsis"):
    cohort_dir = DIR2COHORT / cohort_name
    pop = pd.read_parquet(cohort_dir / "target_population.parquet")
    conf = pd.read_parquet(cohort_dir / "confounders.parquet")
    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in conf.columns]
    feature_cols += [f"{c}__missing" for c in feature_cols if f"{c}__missing" in conf.columns]
    horizon_cols = [c for _, c in MORTALITY_TRAJECTORY]
    arms = sorted(pop[COLNAME_INTERVENTION_STATUS].unique())

    keep = pop[[COLNAME_ICUSTAY_ID, COLNAME_INTERVENTION_STATUS] + horizon_cols]
    data = keep.merge(conf, on=COLNAME_ICUSTAY_ID, how="inner")
    data = data.dropna(subset=horizon_cols).reset_index(drop=True)
    logger.info(f"trajectory cohort: {len(data)} stays (all 4 horizons non-NaN)")
    logger.info(f"arm counts: {dict(data[COLNAME_INTERVENTION_STATUS].value_counts())}")

    # ── Headline fit (one T-Learner per (arm, horizon)) ─────────────────────
    headline: dict[int, dict[int, object]] = {h: {} for h, _ in MORTALITY_TRAJECTORY}
    for h, col in MORTALITY_TRAJECTORY:
        for a in arms:
            sub = data[data[COLNAME_INTERVENTION_STATUS] == a]
            n_events = int(sub[col].sum())
            if n_events < 10:
                logger.warning(f"  skipping arm={a} horizon={h}d — only {n_events} events")
                continue
            headline[h][a] = _fit_one(sub[feature_cols], sub[col])
        logger.info(f"  horizon {h:>2}d fitted for arms {sorted(headline[h].keys())}")

    # ── Joint bootstrap ──────────────────────────────────────────────────────
    rng = np.random.default_rng(RANDOM_STATE)
    n = len(data)
    boot_records = []
    for b in range(n_bootstrap):
        idx = rng.integers(0, n, n)
        boot = data.iloc[idx]
        for h, col in MORTALITY_TRAJECTORY:
            for a in arms:
                sub = boot[boot[COLNAME_INTERVENTION_STATUS] == a]
                if int(sub[col].sum()) < 5:
                    continue
                try:
                    pipe = _fit_one(sub[feature_cols], sub[col])
                except Exception:
                    continue
                # Population-mean predicted risk under arm a (a marginalised
                # counterfactual estimate evaluated on the full bootstrap pool).
                p = pipe.predict_proba(boot[feature_cols])[:, 1].mean()
                boot_records.append(
                    {"bootstrap_idx": b, "horizon_days": h, "arm": a, "mean_risk": float(p)}
                )
        if (b + 1) % 50 == 0:
            logger.info(f"  bootstrap {b+1}/{n_bootstrap}")

    boot_df = pd.DataFrame(boot_records)
    DIR2DATA.joinpath("diagnostics").mkdir(parents=True, exist_ok=True)
    DIR2DATA.joinpath("models").mkdir(parents=True, exist_ok=True)
    boot_path = DIR2DATA / "diagnostics" / "trajectory_boot.parquet"
    boot_df.to_parquet(boot_path)
    logger.info(f"saved bootstrap matrix to {boot_path} ({len(boot_df)} rows)")

    model_path = DIR2DATA / "models" / "trajectory_tlearner.joblib"
    joblib.dump(
        {
            "headline_models": headline,
            "horizons": [h for h, _ in MORTALITY_TRAJECTORY],
            "arms": arms,
            "arm_labels": TREATMENT_ARM_LABELS,
            "feature_cols": feature_cols,
            "n_bootstrap": n_bootstrap,
        },
        model_path,
    )
    logger.info(f"saved headline T-Learner trajectory models to {model_path}")

    # Summary table for the manuscript
    summary = (
        boot_df.groupby(["horizon_days", "arm"])["mean_risk"]
        .agg(point="median", lb=lambda s: s.quantile(0.025), ub=lambda s: s.quantile(0.975))
        .reset_index()
    )
    summary["point_pct"] = (summary["point"] * 100).round(2)
    summary["lb_pct"]    = (summary["lb"]    * 100).round(2)
    summary["ub_pct"]    = (summary["ub"]    * 100).round(2)
    summary["arm_label"] = summary["arm"].map(TREATMENT_ARM_LABELS)
    summary_path = DIR2DATA / "diagnostics" / "trajectory_summary.parquet"
    summary.to_parquet(summary_path)
    logger.info(f"saved trajectory summary to {summary_path}")
    print()
    print(summary.pivot(index="horizon_days", columns="arm_label",
                       values="point_pct").to_string())
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=int, default=300)
    args = parser.parse_args()
    main(n_bootstrap=args.bootstrap)
