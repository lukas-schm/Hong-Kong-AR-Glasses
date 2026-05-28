"""
End-to-end pipeline runner for antibiotic continuation causal analysis.

Steps
-----
  WP1  Framing    – build cohort, classify treatment arms, compute outcomes
  WP2a Variables  – extract confounders at 72h decision point
  WP2b VFD        – compute ventilator/vasopressor-free days
  WP2c DAG        – save causal DAG JSON
  WP2d Estimation – run sensitivity grid
  WP2e CATE       – estimate heterogeneous treatment effects

Usage
-----
    python -m antibiotic_pipeline.run_pipeline [--steps 1 2 3 ...]
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

from antibiotic_pipeline.constants import DIR2COHORT, DIR2EXPERIENCES

COHORT_NAME = "antibiotic_continuation_sepsis"
COHORT_FOLDER = DIR2COHORT / COHORT_NAME
EXPERIENCES_FOLDER = DIR2EXPERIENCES / COHORT_NAME


def step1_framing():
    logger.info("=" * 60)
    logger.info("WP1 — Framing: building target trial population")
    from antibiotic_pipeline.framing.antibiotic_continuation_sepsis import (
        COHORT_CONFIG_ANTIBIOTIC_CONTINUATION,
        get_population,
    )
    pop, ids = get_population(COHORT_CONFIG_ANTIBIOTIC_CONTINUATION)
    logger.info(f"Cohort size: {len(pop)} stays")
    for step, patients in ids.items():
        logger.info(f"  {step}: {len(patients)} patients")
    return pop


def step2_variables(pop=None):
    logger.info("=" * 60)
    logger.info("WP2a — Variables: extracting confounders at 72h")
    import pandas as pd
    if pop is None:
        pop = pd.read_parquet(COHORT_FOLDER / "target_population.parquet")
    from antibiotic_pipeline.variables.selection import get_confounders_at_decision_time
    features_df, feature_types = get_confounders_at_decision_time(pop)
    out_path = COHORT_FOLDER / "confounders.parquet"
    features_df.to_parquet(str(out_path))
    logger.info(f"Saved {features_df.shape[1]} features for {len(features_df)} stays → {out_path}")
    return features_df, feature_types


def step3_vfd(pop=None):
    logger.info("=" * 60)
    logger.info("WP2b — Outcomes: computing VFD-28 and VaPFD-28")
    import pandas as pd
    if pop is None:
        pop = pd.read_parquet(COHORT_FOLDER / "target_population.parquet")
    from antibiotic_pipeline.variables.selection import compute_vfd28
    pop = compute_vfd28(pop)
    pop.to_parquet(str(COHORT_FOLDER / "target_population.parquet"))
    logger.info(f"VFD-28 mean: {pop['ventilator_free_days_28'].mean():.1f} days")
    logger.info(f"VaPFD-28 mean: {pop['vasopressor_free_days_28'].mean():.1f} days")
    return pop


def step4_dag():
    logger.info("=" * 60)
    logger.info("WP2c — DAG: saving causal graph")
    from antibiotic_pipeline.dag.antibiotic_dag import ANTIBIOTIC_DAG
    dag_path = COHORT_FOLDER / "antibiotic_dag.json"
    import json
    with open(dag_path, "w") as f:
        json.dump(ANTIBIOTIC_DAG.to_json(), f, indent=2)
    logger.info(f"Saved DAG ({len(ANTIBIOTIC_DAG.all_confounders)} confounders) → {dag_path}")

    dot_path = COHORT_FOLDER / "antibiotic_dag.dot"
    dot_path.write_text(ANTIBIOTIC_DAG.to_dot())
    logger.info(f"Saved DOT file → {dot_path}")


def step5_sensitivity(feature_types=None):
    logger.info("=" * 60)
    logger.info("WP2d — Estimation: running sensitivity grid")
    from antibiotic_pipeline.experiments.sensitivity_antibiotic import run_sensitivity_grid
    results = run_sensitivity_grid(
        cohort_folder=COHORT_FOLDER,
        experiences_folder=EXPERIENCES_FOLDER,
        feature_types=feature_types,
    )
    logger.info(f"Sensitivity grid complete: {len(results)} estimates")
    return results


def step6_cate(feature_types=None):
    logger.info("=" * 60)
    logger.info("WP2e — CATE: estimating heterogeneous treatment effects")
    from antibiotic_pipeline.experiments.cate_exploration_antibiotic import (
        run_cate_exploration,
        ALL_PAIRWISE_COMPARISONS,
    )
    from antibiotic_pipeline.experiments.utils import ALL_PAIRWISE_COMPARISONS
    for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
        run_cate_exploration(
            cohort_folder=COHORT_FOLDER,
            experiences_folder=EXPERIENCES_FOLDER,
            feature_types=feature_types,
            comparison=(arm_a, arm_b),
        )


def main(steps=None):
    if steps is None:
        steps = [1, 2, 3, 4, 5, 6]

    pop = None
    features_df = None
    feature_types = None

    if 1 in steps:
        pop = step1_framing()
    if 2 in steps:
        features_df, feature_types = step2_variables(pop)
    if 3 in steps:
        pop = step3_vfd(pop)
    if 4 in steps:
        step4_dag()
    if 5 in steps:
        step5_sensitivity(feature_types)
    if 6 in steps:
        step6_cate(feature_types)

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--steps", nargs="+", type=int, default=None,
        help="Pipeline steps to run (1=framing, 2=variables, 3=vfd, 4=dag, 5=sensitivity, 6=cate)"
    )
    args = parser.parse_args()
    main(args.steps)
