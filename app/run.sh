#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

MODEL="${OLLAMA_MODEL:-qwen3:8b}"
API_URL="http://localhost:8000"

c()   { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info(){ echo "$(c '1;34' '›') $*"; }
ok()  { echo "$(c '1;32' '✓') $*"; }
warn(){ echo "$(c '1;33' '!') $*"; }
err() { echo "$(c '1;31' '✗') $*" >&2; }

confirm() {
  read -rp "$(c '1;33' '? ')$1 [y/N] " a
  [[ "$a" =~ ^[Yy]$ ]]
}

up() {
  info "building + starting services..."
  docker compose up -d --build
  ok "services up. api → $API_URL"
  pull_model
}

pull_model() {
  info "ensuring model '$MODEL' is present..."

  if docker compose exec -T ollama ollama list 2>/dev/null |
    grep -q "${MODEL%%:*}"; then
    ok "model '$MODEL' already pulled."
  else
    docker compose exec -T ollama ollama pull "$MODEL"
    ok "pulled '$MODEL'."
  fi
}

logs() {
  docker compose logs -f "${1:-}"
}

health() {
  if curl -fsS "$API_URL/health" >/dev/null 2>&1; then
    ok "api healthy at $API_URL"
  else
    err "api not responding at $API_URL"
  fi
}

status() {
  docker compose ps
  echo
  health
}

reset_venv() {
  warn "this removes api container + .venv volume, then rebuilds."
  confirm "reset .venv?" || {
    info "skipped."
    return
  }

  docker compose rm -sf api
  docker volume prune -f >/dev/null
  docker compose build --no-cache api
  docker compose up -d api

  ok ".venv reset + api rebuilt."
}

reset() {
  warn "this deletes containers, volumes, and local project images."
  confirm "reset everything?" || {
    info "skipped."
    return
  }

  docker compose down -v --rmi local
  docker volume prune -f >/dev/null

  ok "reset complete."
}

menu() {
  echo
  echo "$(c '1;36' 'router — dev menu')"

  cat <<'EOF'
  1) up          build + start + pull model
  2) logs        follow api logs
  3) status      containers + health
  4) health      api health check
  5) pull-model  ensure ollama model present
  6) reset       full reset
  7) reset-venv  rebuild api + wipe .venv
  q) quit
EOF

  read -rp "$(c '1;36' 'choose› ')" choice

  case "$choice" in
    1) up ;;
    2) logs api ;;
    3) status ;;
    4) health ;;
    5) pull_model ;;
    6) reset ;;
    7) reset_venv ;;
    q|Q) exit 0 ;;
    *) warn "unknown option" ;;
  esac
}

if [[ $# -gt 0 ]]; then
  cmd="$1"
  shift

  case "$cmd" in
    up)          up ;;
    logs)        logs "${1:-}" ;;
    status)      status ;;
    health)      health ;;
    pull-model|pull) pull_model ;;
    reset)       reset ;;
    reset-venv)  reset_venv ;;
    *)           err "unknown command: $cmd"; exit 1 ;;
  esac
else
  while true; do
    menu
  done
fi