#!/bin/bash
# Self-restarting wrapper for the NCO permutation job.
# Keeps re-launching until all 3 pairs have >= 1000 permutations.
LOG=/tmp/nco_1000.log
TARGET=1000

check_done() {
    python3 -c "
import pandas as pd, sys
try:
    df = pd.read_parquet('data/diagnostics/nco/permutation_placebo.parquet')
    counts = df[df['kind']=='permutation'].groupby(['arm_a','arm_b']).size()
    done = int((counts >= $TARGET).all())
    total = int(counts.sum())
    print(f'Perms: {counts.to_dict()}  total={total}')
    sys.exit(0 if done else 1)
except Exception as e:
    print(f'check failed: {e}', file=sys.stderr)
    sys.exit(1)
"
}

echo "$(date): Starting NCO restart loop (target: ${TARGET} perms per pair)" | tee -a $LOG

while ! check_done; do
    echo "" | tee -a $LOG
    echo "$(date): Launching permutation run..." | tee -a $LOG
    caffeinate -i python3 -u -m antibiotic_pipeline.experiments.nco \
        --n-permutations $TARGET --bootstrap 50 >> $LOG 2>&1
    EXIT=$?
    echo "$(date): Process exited (code $EXIT). Checking progress..." | tee -a $LOG
    check_done
    sleep 2
done

echo "$(date): All done — $TARGET permutations per pair reached." | tee -a $LOG
