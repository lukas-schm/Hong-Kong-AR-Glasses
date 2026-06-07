"""
P5 — estimator robustness: TMLE + SuperLearner + repeated cross-fitting.

This does **not** change the bias story (that is design-driven; see the sequential
module) — it upgrades the *estimator* to the gold standard and shows the headline
effect is not an artifact of estimator choice:

  * **AIPW (HGB, single split)** — the original headline.
  * **TMLE (HGB, single split)** — bounded, efficient substitution estimator.
  * **TMLE (HGB, repeated ×5)** — median-DML, removes fold-split randomness.
  * **TMLE (SuperLearner)** — CV-stacked nuisance ensemble (LR + HGB + RF), so the
    double-robustness no longer rests on one model family.

If these agree, the estimate is estimator-robust. Run on each intervention's
headline (equipoise, else full) cohort and primary outcome.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from mortality_pipeline.constants import (
    DIR2RESULTS_TRIALS, PRIMARY_OUTCOME, TRIALS, TRIAL_CONFOUNDERS,
)
from mortality_pipeline.credibility import _equipoise_frame
from mortality_pipeline.estimators import (
    aipw_ate, crossfit_nuisances, repeated_estimate, tmle_ate,
)

P5_JSON = DIR2RESULTS_TRIALS / "p5_estimator_robustness.json"


def _cell(row: Dict) -> Dict:
    return {"rd_pp": round(row["ate_pct"], 2),
            "ci": [round(row["ci_low"] * 100, 2), round(row["ci_high"] * 100, 2)]}


def run_p5(interventions: Optional[List[str]] = None, outcome: str = PRIMARY_OUTCOME,
           repeats: int = 5, save: bool = True) -> Dict:
    keys = interventions or [t.key for t in TRIALS]
    conf = TRIAL_CONFOUNDERS
    out = {}
    for key in keys:
        cdf, cohort, _ = _equipoise_frame(key, outcome)
        sub = cdf[cdf[outcome].notna()]
        A = sub["treated"].to_numpy(int)
        if A.sum() < 50 or (A == 0).sum() < 50:
            logger.warning(f"  {key}: too few; skipping P5"); continue
        X = sub[conf]; Y = sub[outcome].to_numpy(float)
        logger.info(f"▶ P5 {key} [{cohort}] n={len(sub):,} — AIPW/TMLE/repeated/SuperLearner")

        nuis_hgb = crossfit_nuisances(X, A, Y, learner="hgb")
        estimates = {
            "aipw_hgb": _cell(aipw_ate(A, Y, nuis_hgb)),
            "tmle_hgb": _cell(tmle_ate(A, Y, nuis_hgb)),
            "tmle_hgb_repeated": _cell(repeated_estimate(X, A, Y, estimator="tmle",
                                                         learner="hgb", repeats=repeats)),
        }
        try:
            nuis_sl = crossfit_nuisances(X, A, Y, learner="superlearner")
            estimates["tmle_superlearner"] = _cell(tmle_ate(A, Y, nuis_sl))
        except Exception as exc:  # keep P5 resilient if the ensemble fails
            logger.warning(f"    SuperLearner failed for {key}: {exc}")
            estimates["tmle_superlearner"] = None

        pts = [v["rd_pp"] for v in estimates.values() if v]
        out[key] = {
            "cohort": cohort, "outcome": outcome, "estimates": estimates,
            "max_spread_pp": round(max(pts) - min(pts), 2),
            "robust": bool(max(pts) - min(pts) <= 2.0),
        }
        logger.info("    " + " | ".join(
            f"{k}={v['rd_pp']:+.2f}" for k, v in estimates.items() if v)
            + f"  spread={out[key]['max_spread_pp']}pp")

    result = {"artifact": "intervention_mortality_p5_estimator_robustness",
              "outcome": outcome, "interventions": out}
    if save:
        DIR2RESULTS_TRIALS.mkdir(parents=True, exist_ok=True)
        P5_JSON.write_text(json.dumps(result, indent=2))
        logger.info(f"Saved P5 robustness → {P5_JSON}")
    return result


if __name__ == "__main__":
    run_p5()
