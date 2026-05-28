"""
Read every cached per-fit parquet under
``data/experiences/<cohort>/<outcome>_<method>_<armA>v<armB>_<feature_set>/logs/*.parquet``
and concatenate into a single ``sensitivity_results.parquet`` aggregate.

The sensitivity grid normally writes this aggregate only after every fit
completes; if it OOM-kills partway through, the aggregate is missing and
``paper/make_figures.py`` cannot render its forest plot. This module
produces a current snapshot at any point in time and is safe to re-run.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from antibiotic_pipeline.constants import DIR2EXPERIENCES


def main(cohort_name: str = "antibiotic_continuation_sepsis") -> Path:
    root = DIR2EXPERIENCES / cohort_name
    if not root.exists():
        raise FileNotFoundError(f"experiences root not found: {root}")

    rows = []
    for fit_dir in sorted(root.iterdir()):
        if not fit_dir.is_dir() or fit_dir.name.startswith("_"):
            continue
        logs = fit_dir / "logs"
        if not logs.exists():
            continue
        parts = list(logs.glob("*.parquet"))
        if not parts:
            continue
        # The most recent parquet is the canonical fit.
        latest = max(parts, key=lambda p: p.stat().st_mtime)
        try:
            df = pd.read_parquet(latest)
        except Exception as exc:
            logger.warning(f"failed to read {latest}: {exc}")
            continue
        if df.empty:
            continue
        df["fit_dir"] = fit_dir.name
        rows.append(df)

    if not rows:
        raise RuntimeError("no cached fit parquets found")

    agg = pd.concat(rows, ignore_index=True)
    out = root / "sensitivity_results.parquet"
    agg.to_parquet(out)
    logger.info(f"aggregated {len(agg)} rows from {len(rows)} fit folders → {out}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", default="antibiotic_continuation_sepsis")
    args = parser.parse_args()
    main(args.cohort)
