"""
WS7 — End-to-end eICU-CRD external-validation pipeline runner.

Runs the parallel framing + confounder extraction + benchmark grid on the
eICU-CRD cohort, then writes a per-hospital subgroup forest plot dataset
that directly addresses reviewer concern #9 (institution-specific
stewardship patterns).

Steps
-----
1. Cohort: :func:`framing.eicu_framing.get_eicu_population` (sepsis-3 + first
   broad-spectrum + T0 + arm classification + 28-day mortality).
2. Confounders: :func:`variables.eicu_selection.get_eicu_confounders`.
3. Estimator benchmark grid: same eight estimators as MIMIC; primary contrast
   is continue-vs-cease.
4. Per-hospital subgroup: re-run primary DML estimator within each
   hospital (where n >= 200), report the forest plot.
5. Save all results to ``data/diagnostics/eicu_external/``.

Run from the repo root::

    python -m antibiotic_pipeline.run_eicu_pipeline
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from antibiotic_pipeline.constants import (
    COLNAME_ICUSTAY_ID,
    COLNAME_INTERVENTION_STATUS,
    COLNAME_MORTALITY_28D,
    DIR2DATA,
)
from antibiotic_pipeline.experiments.benchmarks import (
    Contrast,
    run_benchmark_grid,
)
from antibiotic_pipeline.experiments.balance_diagnostics import (
    run_balance_diagnostics,
)
from antibiotic_pipeline.framing.eicu_framing import (
    EICU_COHORT_CONFIG,
    get_eicu_population,
)
from antibiotic_pipeline.variables.eicu_selection import get_eicu_confounders


def main(bootstrap: int = 500, min_hospital_n: int = 200):
    out_dir = DIR2DATA / "diagnostics" / "eicu_external"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Step 1: building eICU cohort")
    pop, inclusion_ids = get_eicu_population(EICU_COHORT_CONFIG)
    pop.to_parquet(out_dir / "eicu_population.parquet")
    logger.info(f"  Cohort flow: {pop[COLNAME_INTERVENTION_STATUS].value_counts().to_dict()}")

    logger.info("Step 2: extracting eICU confounders")
    conf = get_eicu_confounders(pop)
    conf.to_parquet(out_dir / "eicu_confounders.parquet")

    feature_cols = [c for c in conf.columns if c != COLNAME_ICUSTAY_ID]
    data = pop[[COLNAME_ICUSTAY_ID, COLNAME_INTERVENTION_STATUS,
                COLNAME_MORTALITY_28D, "hospitalid"]].merge(
        conf, on=COLNAME_ICUSTAY_ID, how="inner"
    )

    logger.info("Step 3: estimator benchmark grid (continue-vs-cease)")
    bench = run_benchmark_grid(
        X=data,
        T=data[COLNAME_INTERVENTION_STATUS],
        y=data[COLNAME_MORTALITY_28D],
        feature_cols=feature_cols,
        bootstrap=bootstrap,
        pairs=(Contrast(0, 2),),  # primary contrast only on eICU
    )
    bench.to_parquet(out_dir / "eicu_benchmark.parquet")
    logger.info(f"  Saved benchmark with {len(bench)} rows")

    logger.info("Step 4: balance diagnostics on eICU")
    run_balance_diagnostics(
        X=data, T=data[COLNAME_INTERVENTION_STATUS], feature_cols=feature_cols,
        pairs=(Contrast(0, 2),),
        out_dir=out_dir / "balance",
    )

    logger.info("Step 5: per-hospital subgroup analysis")
    hospital_counts = data["hospitalid"].value_counts()
    eligible_hospitals = hospital_counts[hospital_counts >= min_hospital_n].index.tolist()
    rows = []
    for hid in eligible_hospitals:
        sub = data[data["hospitalid"] == hid]
        sub_n = sub[COLNAME_INTERVENTION_STATUS].isin([0, 2]).sum()
        if sub_n < min_hospital_n:
            continue
        bench_h = run_benchmark_grid(
            X=sub,
            T=sub[COLNAME_INTERVENTION_STATUS],
            y=sub[COLNAME_MORTALITY_28D],
            feature_cols=feature_cols,
            bootstrap=max(100, bootstrap // 5),
            pairs=(Contrast(0, 2),),
        )
        # Keep only the AIPW row as the per-hospital headline.
        aipw = bench_h[bench_h["estimator"] == "AIPW"]
        if not aipw.empty:
            r = aipw.iloc[0].to_dict()
            r["hospitalid"] = hid
            r["n_stays"]    = sub_n
            rows.append(r)
            logger.info(
                f"  hosp={hid} n={sub_n}: AIPW {r['ATE_pp']:+.2f}pp "
                f"[{r['CI_lb_pp']:+.2f}, {r['CI_ub_pp']:+.2f}]"
            )
    per_hosp = pd.DataFrame(rows)
    per_hosp.to_parquet(out_dir / "eicu_per_hospital.parquet")
    logger.info(f"Per-hospital subgroup saved: {len(per_hosp)} hospitals")

    logger.info("eICU external-validation pipeline complete.")
    return {
        "population":   pop,
        "benchmark":    bench,
        "per_hospital": per_hosp,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--min-hospital-n", type=int, default=200)
    args = parser.parse_args()
    main(bootstrap=args.bootstrap, min_hospital_n=args.min_hospital_n)
