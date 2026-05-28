#!/usr/bin/env bash
# Run-everything: post-revision execution batch.
# Logs every stage and never aborts on a single failure.

set -u
cd "$(dirname "$0")"
LOG="run_everything.log"
mark() { echo "" | tee -a "$LOG"; echo "═══ [$(date '+%Y-%m-%d %H:%M:%S')] $* ═══" | tee -a "$LOG"; }
section() { local rc; "$@" >>"$LOG" 2>&1; rc=$?; echo "→ exit=$rc ($*)" | tee -a "$LOG"; }

mark "STAGE 0 — environment"
python3 -V                                                       2>&1 | tee -a "$LOG"
python3 -c "import polars, pandas, sklearn, econml; print('deps OK')" 2>&1 | tee -a "$LOG"

mark "STAGE 1 — cohort + variables + VFD + DAG (steps 1-4)"
section python3 -m antibiotic_pipeline.run_pipeline --steps 1 2 3 4

mark "STAGE 2 — full sensitivity grid (steps 5; resumes from cached fits)"
section python3 -m antibiotic_pipeline.run_pipeline --steps 5

mark "STAGE 3 — CATE exploration (step 6)"
section python3 -m antibiotic_pipeline.run_pipeline --steps 6

mark "STAGE 4 — window sweep (±6, ±12, ±24h)"
section python3 -m antibiotic_pipeline.experiments.window_sweep --bootstrap 200

mark "STAGE 5 — anchor sweep (T0 = 48h, 72h, 96h)"
section python3 -m antibiotic_pipeline.experiments.anchor_sweep --bootstrap 200

mark "STAGE 6 — 8-estimator benchmark on real cohort"
section python3 -c "
import pandas as pd
from antibiotic_pipeline.constants import COLNAME_ICUSTAY_ID, COLNAME_INTERVENTION_STATUS, COLNAME_MORTALITY_28D, DIR2COHORT, DIR2DATA
from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH
from antibiotic_pipeline.experiments.benchmarks import run_benchmark_grid
cohort_dir = DIR2COHORT / 'antibiotic_continuation_sepsis'
pop  = pd.read_parquet(cohort_dir / 'target_population.parquet')
conf = pd.read_parquet(cohort_dir / 'confounders.parquet')
feature_cols = [c for c in CAUSAL_GRAPH.all_confounder_names if c in conf.columns]
feature_cols += [f'{c}__missing' for c in feature_cols if f'{c}__missing' in conf.columns]
data = pop[[COLNAME_ICUSTAY_ID, COLNAME_INTERVENTION_STATUS, COLNAME_MORTALITY_28D]].merge(conf, on=COLNAME_ICUSTAY_ID)
bench = run_benchmark_grid(X=data, T=data[COLNAME_INTERVENTION_STATUS], y=data[COLNAME_MORTALITY_28D], feature_cols=feature_cols, bootstrap=500)
bench.to_parquet(DIR2DATA / 'diagnostics' / 'benchmark_grid.parquet')
print(bench.to_string())
"

mark "STAGE 7 — balance diagnostics (multi-panel)"
section python3 -m antibiotic_pipeline.experiments.balance_diagnostics

mark "STAGE 8 — simulation-based CI coverage"
section python3 -m antibiotic_pipeline.experiments.simulation_coverage --n 3000 --sims 300 --bootstrap 300

mark "STAGE 9 — negative-control outcome (NCO)"
section python3 -m antibiotic_pipeline.experiments.nco

mark "STAGE 10 — E-values"
section python3 -m antibiotic_pipeline.experiments.evalues

mark "STAGE 11 — per-arm calibration + diagnostics refresh"
section python3 -m antibiotic_pipeline.experiments.diagnostics

mark "STAGE 12 — eICU external validation (skipped unless data is mounted)"
if [[ -d "data/eicu" || -d "${DIR2EICU:-/__missing__}" ]]; then
  section python3 -m antibiotic_pipeline.run_eicu_pipeline --bootstrap 500
else
  echo "eICU data not present — stage 12 skipped" | tee -a "$LOG"
fi

mark "STAGE 13 — re-render manuscript figures"
section python3 paper/make_figures.py

mark "ALL STAGES DONE"
echo "Final tail of log:"
tail -10 "$LOG"
