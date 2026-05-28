#!/usr/bin/env bash
# Self-healing repair loop. Runs every 20 minutes:
#   1. Respawn anchor sweep once (skips if it succeeds, retries otherwise)
#   2. Respawn NCO once
#   3. Re-aggregate cached fits → sensitivity_results.parquet
#   4. Run validate_fixes (small smoke fits → validation_results.parquet)
#   5. Run evalues against the freshest validation_results
#   6. Re-render manuscript figures (will succeed once all upstream
#      artefacts are present)
#
# Steps that fail are noted and the loop continues; once everything
# succeeds in a single iteration, the loop exits clean.

set -u
cd "$(dirname "$0")"
LOG="run_repairs.log"
MAX_ITER="${MAX_ITER:-100}"
SLEEP_BETWEEN="${SLEEP_BETWEEN:-1200}"   # 20 minutes
: > "$LOG"

ts()    { date '+%Y-%m-%d %H:%M:%S'; }
note()  { echo "[$(ts)] $*" | tee -a "$LOG"; }
try()   { note "▶ $*"; "$@" >>"$LOG" 2>&1; local rc=$?; note "  exit=$rc"; return $rc; }

all_ok=0
for ((i=1; i<=MAX_ITER; i++)); do
    note ""
    note "═══ repair iteration $i ═══"
    iter_ok=1

    # Step 1: anchor sweep (idempotent: skips already-done fits inside the script)
    if ! [[ -s data/diagnostics/anchor_sweep.parquet ]]; then
        if ! try python3 -m antibiotic_pipeline.experiments.anchor_sweep --bootstrap 100; then
            iter_ok=0
        fi
    else
        note "anchor_sweep.parquet exists — skip"
    fi

    # Step 2: NCO (idempotent if it's resumable; otherwise overwrites)
    if ! [[ -s data/diagnostics/nco/permutation_placebo.parquet ]]; then
        if ! try python3 -m antibiotic_pipeline.experiments.nco; then
            iter_ok=0
        fi
    else
        note "permutation_placebo.parquet exists — skip"
    fi

    # Step 3: aggregate cached sensitivity fits into a flat parquet for plotting
    try python3 -m antibiotic_pipeline.experiments.aggregate_cached_fits

    # Step 4: validate_fixes (cheap, produces validation_results.parquet)
    if ! [[ -s data/experiences/antibiotic_continuation_sepsis/_validation/validation_results.parquet ]]; then
        if ! try python3 -m antibiotic_pipeline.experiments.validate_fixes; then
            iter_ok=0
        fi
    else
        note "validation_results.parquet exists — skip"
    fi

    # Step 5: E-values (closed-form, cheap once validation_results exists)
    if [[ -s data/experiences/antibiotic_continuation_sepsis/_validation/validation_results.parquet ]]; then
        if ! [[ -s data/diagnostics/evalues.parquet ]]; then
            if ! try python3 -m antibiotic_pipeline.experiments.evalues; then
                iter_ok=0
            fi
        else
            note "evalues.parquet exists — skip"
        fi
    fi

    # Step 6: re-render manuscript figures from whatever is available
    try python3 paper/make_figures.py

    if [[ $iter_ok -eq 1 ]]; then
        note "iteration $i — all repair steps green"
        all_ok=1
        break
    fi

    note "iteration $i — at least one step failed; sleeping ${SLEEP_BETWEEN}s"
    sleep "$SLEEP_BETWEEN"
done

if [[ $all_ok -eq 1 ]]; then
    note "repair loop done."
    exit 0
fi
note "MAX_ITER=$MAX_ITER reached; some repairs still pending."
exit 1
