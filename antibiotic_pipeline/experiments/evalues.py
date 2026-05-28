"""
E-value sensitivity analysis (F10).

For every estimated ATE (and its CI), compute the VanderWeele & Ding (2017)
E-value: the minimum strength of association on the risk-ratio scale that an
unmeasured confounder would need to have with *both* the treatment and the
outcome to fully explain away the observed effect.

The metric answers the implicit clinician question:
    "Could a single unmeasured confounder plausibly flip this conclusion?"

References
----------
    VanderWeele TJ, Ding P. Sensitivity Analysis in Observational Research:
    Introducing the E-Value. Ann Intern Med. 2017;167(4):268-274.

Usage
-----
    python -m antibiotic_pipeline.experiments.evalues \\
        --input  data/experiences/antibiotic_continuation_sepsis/_validation/validation_results.parquet \\
        --output data/diagnostics/evalues.parquet
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from antibiotic_pipeline.constants import (
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2COHORT,
    DIR2DATA,
)

DIR2DIAG = DIR2DATA / "diagnostics"
COHORT_NAME = "antibiotic_continuation_sepsis"


def evalue(rr: float) -> float:
    """E-value for a point risk ratio (or hazard ratio) on the harm side.

    Symmetric form: if rr < 1, invert to 1/rr (the "protective" side) then
    apply the same formula. Returns 1.0 if rr is non-positive or undefined.
    """
    if not np.isfinite(rr) or rr <= 0:
        return 1.0
    rr_h = rr if rr >= 1 else 1.0 / rr
    return float(rr_h + np.sqrt(rr_h * (rr_h - 1)))


def evalue_ci(rr_lb: float, rr_ub: float) -> float:
    """E-value for the CI bound nearest the null (RR = 1).

    Convention from VanderWeele & Ding 2017: if the entire CI is on the harm
    side (LB > 1), use LB; if entirely protective (UB < 1), use UB; if the CI
    crosses 1, return 1.0 (no claim of robustness).
    """
    if not (np.isfinite(rr_lb) and np.isfinite(rr_ub)):
        return 1.0
    if rr_lb >= 1.0:
        return evalue(rr_lb)
    if rr_ub <= 1.0:
        return evalue(rr_ub)
    return 1.0


def ate_to_rr(ate_pp: float, baseline_pct: float) -> Optional[float]:
    """Convert an absolute-risk-difference ATE (percentage points) to a risk
    ratio, using the comparison-arm event rate as the baseline risk.
    """
    if baseline_pct <= 0 or baseline_pct >= 100:
        return None
    p0 = baseline_pct / 100.0
    delta = ate_pp / 100.0
    p1 = p0 + delta
    if p1 <= 0 or p1 >= 1:
        return None
    return p1 / p0


def _baseline_rates() -> dict:
    """Per-arm 28-day mortality rate from the cohort."""
    cohort = pd.read_parquet(DIR2COHORT / COHORT_NAME / "target_population.parquet")
    rates = {}
    for arm in (0, 1, 2):
        sub = cohort.loc[cohort[COLNAME_INTERVENTION_STATUS] == arm, COLNAME_MORTALITY_28D]
        rates[arm] = float(sub.mean()) if len(sub) else None
    return rates


def annotate_with_evalues(df: pd.DataFrame) -> pd.DataFrame:
    """Add `RR`, `E_value`, `E_value_CI` columns to a results frame.

    Expects columns: arm_a, arm_b, ATE_pp, CI_lb_pp, CI_ub_pp.
    Baseline risk for the RR conversion is the arm_a event rate
    (i.e., the reference arm — the comparison runs arm_a → arm_b).
    """
    rates = _baseline_rates()
    out = df.copy()
    rr_vals, ev_vals, ev_ci_vals, baseline_vals = [], [], [], []
    for _, row in df.iterrows():
        base_pct = (rates.get(int(row["arm_a"])) or 0.0) * 100.0
        rr_point = ate_to_rr(float(row["ATE_pp"]), base_pct)
        rr_lb = ate_to_rr(float(row["CI_lb_pp"]), base_pct)
        rr_ub = ate_to_rr(float(row["CI_ub_pp"]), base_pct)
        rr_vals.append(round(rr_point, 3) if rr_point else None)
        ev_vals.append(round(evalue(rr_point), 2) if rr_point else 1.0)
        if rr_lb is not None and rr_ub is not None:
            ev_ci_vals.append(round(evalue_ci(rr_lb, rr_ub), 2))
        else:
            ev_ci_vals.append(1.0)
        baseline_vals.append(round(base_pct, 2))
    out["baseline_pct"] = baseline_vals
    out["RR"] = rr_vals
    out["E_value"] = ev_vals
    out["E_value_CI"] = ev_ci_vals
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=DIR2DATA / "experiences" / COHORT_NAME / "_validation" / "validation_results.parquet",
        help="Parquet of ATE results (cols: arm_a, arm_b, ATE_pp, CI_lb_pp, CI_ub_pp)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DIR2DIAG / "evalues.parquet",
        help="Where to write the annotated frame",
    )
    args = parser.parse_args()

    df = pd.read_parquet(args.input)
    out = annotate_with_evalues(df)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output)
    logger.info(f"Saved {args.output} with E-values")
    logger.info("\n" + out.to_string(index=False))

    # Also persist a short interpretive JSON
    summary = {
        "interpretation": (
            "An E-value of 2 means an unmeasured confounder would need risk "
            "ratios of 2 with both treatment and outcome to fully explain the "
            "association. E-values close to 1 mean the estimate is fragile. "
            "E_value_CI: same calculation on the CI bound nearest the null — "
            "if it equals 1.0, the CI already crosses the null."
        ),
        "rows": out.to_dict(orient="records"),
    }
    with open(args.output.with_suffix(".json"), "w") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
