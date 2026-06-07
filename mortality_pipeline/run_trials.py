"""
Runner for the **target-trial** causal-ML design (P1 + P2 + weekly trajectory).

    # build trial cohorts, scoreboard, weekly trajectory, report
    python -m mortality_pipeline.run_trials

    # rebuild cohorts from DuckDB; only two interventions; skip trajectory
    python -m mortality_pipeline.run_trials --rebuild --interventions intv_vasopressors intv_rrt --no-trajectory

    # custom weekly grid
    python -m mortality_pipeline.run_trials --weeks 7 14 28 56 84

Outputs (data/results/intervention_trials/):
    trial_scoreboard.parquet/.csv        full × equipoise × {unadj,iptw,aipw,att,ato}
    monitor_trials_scoreboard.json       earned-confidence cards for monitor/HUD
    trajectory.parquet                   weekly RD(t) + survival curves
    monitor_trajectory.json              animated trajectory cards
And RESULTS_INTERVENTION_TRIALS.md at the repo root.
"""
from __future__ import annotations

import argparse
import sys

from loguru import logger

from mortality_pipeline.constants import INTERVENTION_KEYS, N_CROSSFIT_FOLDS, WEEKLY_GRID_DAYS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true", help="rebuild trial cohorts from DuckDB")
    ap.add_argument("--interventions", nargs="*", default=None, help=f"subset of {INTERVENTION_KEYS}")
    ap.add_argument("--outcomes", nargs="*", default=None)
    ap.add_argument("--weeks", nargs="*", type=int, default=None, help="weekly grid in days")
    ap.add_argument("--learner", choices=["hgb", "logistic"], default="hgb")
    ap.add_argument("--folds", type=int, default=N_CROSSFIT_FOLDS)
    ap.add_argument("--no-trajectory", action="store_true")
    ap.add_argument("--no-credibility", action="store_true",
                    help="skip the P4 credibility suite (placebo/refuters/NCO/RCT benchmark)")
    ap.add_argument("--perm", type=int, default=8, help="placebo permutations for P4")
    ap.add_argument("--no-sequential", action="store_true",
                    help="skip the time-varying sequential target-trial design")
    ap.add_argument("--p5", action="store_true",
                    help="run the P5 estimator-robustness suite (TMLE/SuperLearner; slow)")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)
    save = not args.no_save

    logger.info("=" * 78)
    logger.info("Target-trial causal-ML pipeline (P1 baselines · P2 equipoise · weekly trajectory)")
    logger.info("=" * 78)

    if args.rebuild:
        from mortality_pipeline.trials import build_all_trials
        build_all_trials(save=True)

    from mortality_pipeline.trial_scoreboard import run_trial_scoreboard
    board = run_trial_scoreboard(
        interventions=args.interventions, outcomes=args.outcomes,
        learner=args.learner, n_folds=args.folds, rebuild=args.rebuild, save=save,
    )
    if board.empty:
        logger.error("No scoreboard rows produced.")
        return 1

    traj = None
    if not args.no_trajectory:
        from mortality_pipeline.trajectory import run_trajectory
        traj = run_trajectory(
            interventions=args.interventions, weeks=args.weeks or WEEKLY_GRID_DAYS,
            learner=args.learner, n_folds=args.folds, save=save,
        )

    cred = None
    if not args.no_credibility:
        from mortality_pipeline.credibility import run_credibility
        cred = run_credibility(interventions=args.interventions, n_perm=args.perm, save=save)

    seq = None
    if not args.no_sequential:
        from mortality_pipeline.sequential import run_sequential
        seq = run_sequential(interventions=args.interventions, learner=args.learner, save=save)

    p5 = None
    if args.p5:
        from mortality_pipeline.estimator_robustness import run_p5
        p5 = run_p5(interventions=args.interventions, save=save)

    from mortality_pipeline import report_trials
    report_trials.print_console(board)
    if save:
        paths = report_trials.save_all(board, traj, cred, seq, p5)
        logger.info(f"Monitor JSON → {paths['monitor_json']}")
        logger.info(f"Report → {paths['report_md']}")

    logger.success("Target-trial pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
