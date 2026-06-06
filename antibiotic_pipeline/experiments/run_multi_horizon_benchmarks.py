"""
P3 — Benchmark grid over all 4 mortality horizons × all 3 pairwise contrasts.

Produces trajectory_benchmark.parquet with 72 rows:
  6 estimators × 3 contrasts × 4 horizons

Replaces the earlier 24-row file (6 estimators × 4 horizons, 0v2 only).

Usage::

    python -m antibiotic_pipeline.experiments.run_multi_horizon_benchmarks
    python -m antibiotic_pipeline.experiments.run_multi_horizon_benchmarks --bootstrap 200
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from antibiotic_pipeline.constants import (
    COLNAME_ICUSTAY_ID,
    COLNAME_INTERVENTION_STATUS,
    DIR2COHORT,
    DIR2DATA,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.benchmarks import ALL_PAIRS, run_benchmark_grid

COHORT_NAME = "antibiotic_continuation_sepsis"

HORIZONS = [
    (7,  "mortality_7d"),
    (14, "mortality_14d"),
    (21, "mortality_21d"),
    (28, "mortality_28days"),
]


def main(bootstrap: int = 500) -> pd.DataFrame:
    cohort_dir = DIR2COHORT / COHORT_NAME
    pop  = pd.read_parquet(cohort_dir / "target_population.parquet")
    conf = pd.read_parquet(cohort_dir / "confounders.parquet")

    feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in conf.columns]
    feature_cols += [f"{c}__missing" for c in feature_cols if f"{c}__missing" in conf.columns]

    outcome_cols = [col for _, col in HORIZONS]
    keep_cols = [COLNAME_ICUSTAY_ID, COLNAME_INTERVENTION_STATUS] + outcome_cols
    data = pop[keep_cols].merge(conf, on=COLNAME_ICUSTAY_ID, how="inner")
    logger.info(f"Merged cohort: {len(data)} stays, {len(feature_cols)} feature cols")

    all_rows: list[pd.DataFrame] = []
    for h_days, outcome_col in HORIZONS:
        logger.info(f"[horizon={h_days}d  outcome={outcome_col}]")
        grid = run_benchmark_grid(
            X=data,
            T=data[COLNAME_INTERVENTION_STATUS],
            y=data[outcome_col],
            feature_cols=feature_cols,
            binary_outcome=True,
            bootstrap=bootstrap,
            pairs=ALL_PAIRS,
        )
        grid["horizon_days"] = h_days
        all_rows.append(grid)
        logger.info(f"  horizon={h_days}d done ({len(grid)} rows)")

    result = pd.concat(all_rows, ignore_index=True)
    out = DIR2DATA / "diagnostics" / "trajectory_benchmark.parquet"
    result.to_parquet(out)
    logger.info(f"Saved {len(result)} rows → {out}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=int, default=500,
                        help="Bootstrap replicates per cell (default 500)")
    args = parser.parse_args()
    main(args.bootstrap)
