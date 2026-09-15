#!/usr/bin/env bash
# fetcher.sh — test the router API (outside app/).
# Examples:
#   ./fetcher.sh health
#   ./fetcher.sh classify "transfer 200 euros to savings"
#   ./fetcher.sh run 30
#   ./fetcher.sh batch          # fires a preset spread of tasks
#   ./fetcher.sh                # interactive menu
#   BASE=http://localhost:8000 ./fetcher.sh classify "book a flight"
set -uo pipefail

BASE="${BASE:-http://localhost:8000}"

c()   { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info(){ echo "$(c '1;34' '›') $*"; }
ok()  { echo "$(c '1;32' '✓') $*"; }
err() { echo "$(c '1;31' '✗') $*" >&2; }

# pretty-print JSON if python is around, else raw
pp() { if command -v python3 >/dev/null; then python3 -m json.tool; else cat; fi; }

require_up() {
  if ! curl -fsS "$BASE/health" >/dev/null 2>&1; then
    err "API not reachable at $BASE — start it (app/run.sh up)"; exit 1
  fi
}

health() {
  info "GET $BASE/health"
  curl -fsS "$BASE/health" | pp
}

classify() {                       # classify one task
  local task="$*"
  [[ -z "$task" ]] && { read -rp "task› " task; }
  require_up
  info "POST /classify  →  \"$task\""
  curl -fsS -X POST "$BASE/classify" \
    -H "Content-Type: application/json" \
    -d "$(printf '{"task":%s}' "$(json_str "$task")")" | pp
}

run() {                            # batch accuracy over n dataset rows
  local n="${1:-20}"
  require_up
  info "POST /run?n=$n  (first call downloads CLINC; be patient)"
  curl -fsS -X POST "$BASE/run?n=$n" | pp
}

# preset spread — one task per category, quick sanity of routing
batch() {
  require_up
  local tasks=(
    "what's my current account balance"
    "book me a flight to Berlin next friday"
    "add milk and eggs to my shopping list"
    "schedule a meeting with Sarah tomorrow at 3pm"
    "what's the euro to dollar exchange rate"
    "why was my credit card declined"
    "tell me a joke"
  )
  printf "%-52s %-14s %s\n" "TASK" "CATEGORY" "CONF"
  printf '%.0s-' {1..80}; echo
  for t in "${tasks[@]}"; do
    local resp
    resp=$(curl -fsS -X POST "$BASE/classify" -H "Content-Type: application/json" \
             -d "$(printf '{"task":%s}' "$(json_str "$t")")" 2>/dev/null)
    if command -v python3 >/dev/null; then
      echo "$resp" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'{\"$t\"[:52]:52} {d.get(\"category\",\"?\"):14} {d.get(\"confidence\",\"?\")}')
except Exception:
    print(f'{\"$t\"[:52]:52} ERROR')"
    else
      printf "%-52s %s\n" "${t:0:52}" "$resp"
    fi
  done
}

# minimal JSON string escaper (quotes + backslashes) so tasks with quotes don't break the body
json_str() {
  if command -v python3 >/dev/null; then
    python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1"
  else
    printf '"%s"' "${1//\"/\\\"}"
  fi
}

menu() {
  echo
  echo "$(c '1;36' "router tester")   (target: $BASE)"
  cat <<'EOF'
  1) health         ping /health
  2) classify       classify one task you type
  3) run N          batch accuracy over N dataset rows
  4) batch          preset one-per-category spread
  5) set base URL
  q) quit
EOF
  read -rp "$(c '1;36' 'choose› ')" ch
  case "$ch" in
    1) health ;;
    2) classify ;;
    3) read -rp "n (default 20)› " n; run "${n:-20}" ;;
    4) batch ;;
    5) read -rp "base url› " BASE; ok "target set to $BASE" ;;
    q|Q) exit 0 ;;
    *) err "unknown option" ;;
  esac
}

# ---- dispatch -----------------------------------------------------------
if [[ $# -gt 0 ]]; then
  cmd="$1"; shift
  case "$cmd" in
    health)   health ;;
    classify) classify "$@" ;;
    run)      run "${1:-20}" ;;
    batch)    batch ;;
    *) err "unknown command: $cmd"
       echo "usage: $0 {health|classify <task>|run [n]|batch}"; exit 1 ;;
  esac
else
  while true; do menu; done
fi