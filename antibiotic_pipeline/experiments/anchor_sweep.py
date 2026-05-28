"""
WS2 / reviewer concern #14: $T_0$ anchor sensitivity sweep.

Re-runs the framing module under different time-zero anchors and compares the
headline continue-vs-cease ATE across anchors:

  * 48h after first broad-spectrum administration
  * 72h (default)
  * 96h
  * culture-finalisation time (data-driven; falls back to 72h if no
    culture finalisation observed within 96h)

For each anchor, the pipeline re-classifies arms, recomputes outcomes, and
re-fits the DML primary estimator. Output: data/diagnostics/anchor_sweep.parquet.

This is a longer-running sensitivity than the window sweep because every
anchor requires a full cohort rebuild; we therefore default to a single
estimator (DML with RF nuisances) and use the cached confounders frame for
the same stays where they overlap, rather than re-extracting from scratch.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Iterable

import pandas as pd
from loguru import logger
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from antibiotic_pipeline.constants import (
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2DATA,
)
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.configurations import RF_OUTCOME, RF_TREATMENT
from antibiotic_pipeline.experiments.utils import (
    ALL_PAIRWISE_COMPARISONS,
    MultiArmInferenceWrapper,
)
from antibiotic_pipeline.framing.antibiotic_continuation_sepsis import (
    COHORT_CONFIG_ANTIBIOTIC_CONTINUATION,
    get_population,
)
from antibiotic_pipeline.variables.selection import (
    get_confounders_at_decision_time,
)


def _build_config_for_anchor(anchor: str | int):
    cfg = copy.deepcopy(COHORT_CONFIG_ANTIBIOTIC_CONTINUATION)
    if isinstance(anchor, int):
        cfg["decision_window_hours"] = anchor
        cfg["t0_anchor"] = f"{anchor}h_after_first_broad"
    elif anchor == "culture_finalisation":
        cfg["t0_anchor"] = "culture_finalisation"
    else:
        raise ValueError(f"Unknown anchor: {anchor!r}")
    # Don't overwrite the default cohort; use a per-anchor sub-folder.
    cfg["cohort_name"] = f"anchor_sweep/{cfg['t0_anchor']}"
    cfg["save_cohort"] = False
    return cfg


def main(anchors: Iterable[str | int] = (48, 72, 96, "culture_finalisation"),
         bootstrap_num_samples: int = 100):
    treatment_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_TREATMENT.estimator,
    )
    outcome_pipe = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(), RF_OUTCOME.estimator,
    )

    rows = []
    for anchor in anchors:
        cfg = _build_config_for_anchor(anchor)
        logger.info(f"Building cohort under anchor={cfg['t0_anchor']}")
        try:
            pop, _ = get_population(cfg)
        except NotImplementedError:
            logger.warning(
                f"Anchor {cfg['t0_anchor']} not implemented in framing; "
                "skip this anchor and add the resolver to "
                "framing.antibiotic_continuation_sepsis"
            )
            continue
        conf, _ = get_confounders_at_decision_time(pop)
        feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in conf.columns]
        feature_cols += [
            f"{c}__missing" for c in feature_cols if f"{c}__missing" in conf.columns
        ]
        data = pop.merge(conf, on="stay_id", how="inner")
        for arm_a, arm_b in ALL_PAIRWISE_COMPARISONS:
            mask = data[COLNAME_INTERVENTION_STATUS].isin([arm_a, arm_b])
            X = data.loc[mask, feature_cols + [COLNAME_INTERVENTION_STATUS]].copy()
            y = data.loc[mask, COLNAME_MORTALITY_28D].dropna()
            X = X.loc[y.index]
            imp = SimpleImputer(strategy="median")
            X[feature_cols] = imp.fit_transform(X[feature_cols])

            wrapper = MultiArmInferenceWrapper(
                treatment_pipeline=treatment_pipe,
                outcome_pipeline=outcome_pipe,
                estimation_method="DML",
                outcome_name=COLNAME_MORTALITY_28D,
                treatment_name=COLNAME_INTERVENTION_STATUS,
                treatment_comparison=(arm_a, arm_b),
                bootstrap_num_samples=bootstrap_num_samples,
            )
            wrapper.fit(X, y)
            res = wrapper.predict(X)
            rows.append({
                "anchor":   cfg["t0_anchor"],
                "arm_a":    arm_a,
                "arm_b":    arm_b,
                "n_a":      int((data[COLNAME_INTERVENTION_STATUS] == arm_a).sum()),
                "n_b":      int((data[COLNAME_INTERVENTION_STATUS] == arm_b).sum()),
                "ATE_pp":   round(res["ATE"] * 100, 2),
                "CI_lb_pp": round(res["ATE lower bound"] * 100, 2),
                "CI_ub_pp": round(res["ATE upper bound"] * 100, 2),
            })
            logger.info(
                f"  anchor={cfg['t0_anchor']} {arm_a}v{arm_b}: "
                f"ATE={rows[-1]['ATE_pp']:+.2f} pp "
                f"[{rows[-1]['CI_lb_pp']:+.2f}, {rows[-1]['CI_ub_pp']:+.2f}]"
            )

    df = pd.DataFrame(rows)
    out = DIR2DATA / "diagnostics" / "anchor_sweep.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    logger.info(f"Saved {out}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=int, default=100)
    args = parser.parse_args()
    main(bootstrap_num_samples=args.bootstrap)
