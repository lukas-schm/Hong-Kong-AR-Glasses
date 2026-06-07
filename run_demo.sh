#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# CDARS CDSS — voice-first, AR-glasses clinical decision support over a
# realistic Hospital Authority CDARS warehouse.
#
#   • FastAPI backend  : CDARS warehouse (SQLite) + REST + agent + realtime bus
#   • Vite frontend    : #monitor (model monitor + live HUD)
#                        #glasses (Even Realities G2 surface, voice + buttons)
#                        #cdars   (territory-wide cohort workbench + audit)
#
# Usage:  ./run_demo.sh
# Optional: export ANTHROPIC_API_KEY=...   → the agent uses Claude tool-use
#           (otherwise the deterministic planner drives it — no key needed).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

API_PORT=8002
WEB_PORT=5000
mkdir -p logs

echo "▸ starting CDARS API (uvicorn :$API_PORT) …"
lsof -ti tcp:$API_PORT | xargs kill -9 2>/dev/null || true
uvicorn api.server:app --host "${API_HOST:-0.0.0.0}" --port $API_PORT > logs/cdars_api.log 2>&1 &
API_PID=$!

echo "▸ waiting for the warehouse + model to load …"
for i in $(seq 1 60); do
  if curl -s "http://127.0.0.1:$API_PORT/api/v1/health" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "  ✓ API ready"; break
  fi
  sleep 1
done

echo "▸ starting frontend (vite :$WEB_PORT) …"
lsof -ti tcp:$WEB_PORT | xargs kill -9 2>/dev/null || true
( cd frontend && npm run dev > ../logs/vite.log 2>&1 & )

cleanup() { echo; echo "▸ stopping …"; kill $API_PID 2>/dev/null || true; lsof -ti tcp:$WEB_PORT | xargs kill -9 2>/dev/null || true; }
trap cleanup EXIT INT TERM

sleep 3
cat <<EOF

  ──────────────────────────────────────────────────────────────
   CDARS CDSS is up.  Open in Chrome/Edge (use localhost, not 127.0.0.1):

     Monitor :  http://localhost:$WEB_PORT/#monitor
     Glasses :  http://localhost:$WEB_PORT/#glasses
     CDARS   :  http://localhost:$WEB_PORT/#cdars

   Try it: open #glasses on one window and #monitor on another, then
   tap-to-talk (or press space) and say "show Chan Tai Man", "what's the
   lactate?", "de-escalate the antibiotics". Both HUDs stay in sync; the
   monitor narrates each step and the CDARS audit trail logs every write.

   Agent engine: $( [ -n "${ANTHROPIC_API_KEY:-}" ] && echo "Claude (ANTHROPIC_API_KEY set)" || echo "deterministic planner (set ANTHROPIC_API_KEY for Claude)" )
  ──────────────────────────────────────────────────────────────

  Logs: logs/cdars_api.log · logs/vite.log    (Ctrl-C to stop)
EOF

wait $API_PID
