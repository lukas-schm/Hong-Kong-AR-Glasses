#!/usr/bin/env bash
# Respawn the sensitivity grid every time it dies (OOM or otherwise).
# The grid resumes from its cache automatically, so each iteration
# completes ~5-10 fits before the next OOM kill.
# Exits cleanly when the grid completes (exit 0) or after MAX_ITER attempts.

set -u
cd "$(dirname "$0")"
LOG="run_sensitivity_respawn.log"
MAX_ITER="${MAX_ITER:-200}"
COOLDOWN_S="${COOLDOWN_S:-30}"

: > "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting respawn loop (MAX_ITER=$MAX_ITER, cooldown=${COOLDOWN_S}s)" | tee -a "$LOG"

for ((i=1; i<=MAX_ITER; i++)); do
    echo "" | tee -a "$LOG"
    echo "═══ iteration $i — $(date '+%Y-%m-%d %H:%M:%S') ═══" | tee -a "$LOG"
    n_before=$(ls data/experiences/antibiotic_continuation_sepsis/ 2>/dev/null | wc -l | awk '{print $1}')
    echo "fits cached before: $n_before" | tee -a "$LOG"

    python3 -m antibiotic_pipeline.run_pipeline --steps 5 >> "$LOG" 2>&1
    rc=$?

    n_after=$(ls data/experiences/antibiotic_continuation_sepsis/ 2>/dev/null | wc -l | awk '{print $1}')
    delta=$((n_after - n_before))
    echo "iteration $i exit=$rc — fits cached after: $n_after (+$delta this iter)" | tee -a "$LOG"

    if [[ $rc -eq 0 ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] grid complete (exit 0) — stopping respawn loop" | tee -a "$LOG"
        exit 0
    fi

    if [[ $delta -eq 0 && $rc -ne 0 ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] no progress this iteration — likely deterministic failure, aborting" | tee -a "$LOG"
        exit 1
    fi

    echo "cooling down ${COOLDOWN_S}s for OS to reclaim memory..." | tee -a "$LOG"
    sleep "$COOLDOWN_S"
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] hit MAX_ITER=$MAX_ITER — stopping" | tee -a "$LOG"
