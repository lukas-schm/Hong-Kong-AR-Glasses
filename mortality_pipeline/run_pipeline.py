"""
End-to-end runner for the holistic intervention→mortality causal-ML pipeline.

    # full run (build cohort if needed, all interventions × outcomes)
    python -m mortality_pipeline.run_pipeline

    # quick demo on a 20% sample
    python -m mortality_pipeline.run_pipeline --fraction 0.2

    # rebuild the cohort from the DuckDB and add a causal-forest CATE
    python -m mortality_pipeline.run_pipeline --rebuild-cohort \
        --heterogeneity intv_vasopressors

Outputs (under data/results/intervention_mortality/):
    scoreboard.parquet / .csv     tidy results (intervention × outcome × method)
    monitor_scoreboard.json       plain-language cards for the monitor / glasses HUD
    cate_<intv>_<outcome>.parquet per-patient CATE (only with --heterogeneity)
And RESULTS_INTERVENTION_MORTALITY.md at the repo root.
"""
from __future__ import annotations

import argparse
import sys

from loguru import logger

from mortality_pipeline.cohort import load_cohort
from mortality_pipeline.constants import (
    INTERVENTION_KEYS,
    N_CROSSFIT_FOLDS,
    RANDOM_STATE,
)
from mortality_pipeline.constants import MORTALITY_OUTCOMES
from mortality_pipeline.report import print_console, save_all
from mortality_pipeline.scoreboard import run_scoreboard


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild-cohort", action="store_true",
                    help="rebuild the cohort from the MIMIC-IV DuckDB")
    ap.add_argument("--fraction", type=float, default=1.0,
                    help="random subsample fraction for a fast run (default 1.0)")
    ap.add_argument("--interventions", nargs="*", default=None,
                    help=f"subset of {INTERVENTION_KEYS}")
    ap.add_argument("--outcomes", nargs="*", default=None,
                    help=f"subset of {[o.key for o in MORTALITY_OUTCOMES]}")
    ap.add_argument("--learner", choices=["hgb", "logistic"], default="hgb",
                    help="nuisance learner family (default hgb)")
    ap.add_argument("--folds", type=int, default=N_CROSSFIT_FOLDS,
                    help="cross-fitting folds (default 5)")
    ap.add_argument("--heterogeneity", default=None,
                    help="intervention key for an optional causal-forest CATE")
    ap.add_argument("--no-save", action="store_true", help="do not write outputs")
    args = ap.parse_args(argv)

    logger.info("=" * 70)
    logger.info("Holistic causal-ML pipeline — interventions vs mortality")
    logger.info("=" * 70)

    cohort = load_cohort(rebuild=args.rebuild_cohort)
    if args.fraction < 1.0:
        cohort = cohort.sample(frac=args.fraction, random_state=RANDOM_STATE).reset_index(drop=True)
        logger.info(f"Subsampled to {len(cohort):,} stays ({args.fraction:.0%})")

    board = run_scoreboard(
        cohort,
        interventions=args.interventions,
        outcomes=args.outcomes,
        learner=args.learner,
        n_folds=args.folds,
        save=not args.no_save,
    )
    if board.empty:
        logger.error("No results produced.")
        return 1

    print_console(board)
    if not args.no_save:
        paths = save_all(board, cohort)
        logger.info(f"Monitor JSON → {paths['monitor_json']}")
        logger.info(f"Markdown report → {paths['report_md']}")

    if args.heterogeneity:
        from mortality_pipeline.heterogeneity import estimate_cate
        estimate_cate(cohort, args.heterogeneity, save=not args.no_save)

    logger.success("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
