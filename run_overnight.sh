#!/bin/bash
# Overnight pipeline run: build derived tables, then full causal ML pipeline
# Logs to run_overnight.log

set -e
PROJECT="/Users/lukas/Projects/Causal_ML/Antibiotic"
LOG="$PROJECT/run_overnight.log"
PYTHON=python3

cd "$PROJECT"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

log "========================================================"
log "Overnight pipeline run starting"
log "Project: $PROJECT"
log "========================================================"

# ── Step 0: Build derived tables via DuckDB ──────────────────────────────────
log "STEP 0: Building derived tables from MIMIC-IV (expected 20-60 min)"
$PYTHON data/build_derived.py >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 0 DONE: derived tables built"
    ls -lh data/derived/*.parquet 2>/dev/null | tee -a "$LOG" || log "Warning: no derived parquet files found"
    ls -lh data/raw/*.parquet 2>/dev/null | tee -a "$LOG" || log "Warning: no raw parquet files found"
else
    log "STEP 0 FAILED — check log above for DuckDB errors"
    exit 1
fi

# ── Step 1: Framing — build cohort ───────────────────────────────────────────
log "STEP 1: Framing — building target trial population"
$PYTHON -m antibiotic_pipeline.run_pipeline --steps 1 >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 1 DONE"
    ls -lh data/cohort/antibiotic_continuation_sepsis/ 2>/dev/null | tee -a "$LOG" || true
else
    log "STEP 1 FAILED — check log"
    exit 1
fi

# ── Step 2: Variables — extract confounders ───────────────────────────────────
log "STEP 2: Variables — extracting confounders at 72h"
$PYTHON -m antibiotic_pipeline.run_pipeline --steps 2 >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 2 DONE"
else
    log "STEP 2 FAILED — check log"
    exit 1
fi

# ── Step 3: VFD — ventilator/vasopressor-free days ───────────────────────────
log "STEP 3: Computing VFD-28 and VaPFD-28"
$PYTHON -m antibiotic_pipeline.run_pipeline --steps 3 >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 3 DONE"
else
    log "STEP 3 FAILED — check log"
    exit 1
fi

# ── Step 4: DAG — save causal graph JSON/DOT ─────────────────────────────────
log "STEP 4: Saving causal DAG"
$PYTHON -m antibiotic_pipeline.run_pipeline --steps 4 >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 4 DONE"
else
    log "STEP 4 FAILED — check log"
    exit 1
fi

# ── Step 5: Sensitivity grid ─────────────────────────────────────────────────
log "STEP 5: Running sensitivity grid (DML, CausalForest, etc.)"
$PYTHON -m antibiotic_pipeline.run_pipeline --steps 5 >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 5 DONE"
else
    log "STEP 5 FAILED (econml issue?) — check log. Continuing to CATE..."
fi

# ── Step 6: CATE ─────────────────────────────────────────────────────────────
log "STEP 6: Estimating heterogeneous treatment effects (CATE)"
$PYTHON -m antibiotic_pipeline.run_pipeline --steps 6 >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    log "STEP 6 DONE"
else
    log "STEP 6 FAILED — check log"
fi

log "========================================================"
log "Overnight run complete. Check $LOG for full output."
log "Key outputs:"
log "  data/cohort/antibiotic_continuation_sepsis/target_population.parquet"
log "  data/cohort/antibiotic_continuation_sepsis/confounders.parquet"
log "  data/experiences/antibiotic_continuation_sepsis/sensitivity_results.parquet"
log "========================================================"
