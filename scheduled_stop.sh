#!/usr/bin/env bash
# One-shot scheduled stop: pause all compute loops at TARGET, then stay off.
# Resume is manual: `bash run_sensitivity_respawn.sh`
set -u
cd "$(dirname "$0")"
TARGET="2026-05-27 10:30:00"
LOG="scheduled_stop.log"

target_epoch=$(date -j -f "%Y-%m-%d %H:%M:%S" "$TARGET" +%s)
echo "[$(date '+%F %T')] scheduled-stop armed for $TARGET" | tee -a "$LOG"

while true; do
    now=$(date +%s)
    (( now >= target_epoch )) && break
    remaining=$(( target_epoch - now ))
    if (( remaining > 300 )); then sleep 300; else sleep "$remaining"; fi
done

echo "[$(date '+%F %T')] STOP TIME reached — pausing compute" | tee -a "$LOG"
pkill -f run_sensitivity_respawn.sh 2>/dev/null && echo "  killed respawn loop" | tee -a "$LOG"
pkill -f run_repairs.sh            2>/dev/null && echo "  killed repair loop"  | tee -a "$LOG"
sleep 3
pkill -f "python3 -m antibiotic_pipeline" 2>/dev/null && echo "  killed in-flight python fit" | tee -a "$LOG"
sleep 2
nfits=$(ls data/experiences/antibiotic_continuation_sepsis/ 2>/dev/null | grep -v _validation | wc -l | awk '{print $1}')
echo "[$(date '+%F %T')] PAUSED. fits cached at stop: ${nfits} / 750" | tee -a "$LOG"
echo "[$(date '+%F %T')] resume with: cd $(pwd) && bash run_sensitivity_respawn.sh" | tee -a "$LOG"
