#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/docker-compose.selfhost.yml}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env.selfhost}"
PROJECT_NAME="${PROJECT_NAME:-starpark}"
MODE="${1:-${DEPLOY_MODE:-deploy}}"

log() {
  printf '[starpark-selfhost] %s\n' "$*"
}

fail() {
  printf '[starpark-selfhost] ERROR: %s\n' "$*" >&2
  exit 1
}

resolve_compose_command() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return
  fi

  fail "docker compose is required but not installed"
}

compose() {
  "${COMPOSE_CMD[@]}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" "$@"
}

ensure_dependencies() {
  command -v docker >/dev/null 2>&1 || fail "docker is required"
  command -v curl >/dev/null 2>&1 || fail "curl is required"
  resolve_compose_command

  if ! docker info >/dev/null 2>&1; then
    fail "docker daemon is not running; start Docker Desktop first"
  fi
}

ensure_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return
  fi

  local example_file="${REPO_ROOT}/.env.selfhost.example"
  if [[ -f "${example_file}" ]]; then
    cp "${example_file}" "${ENV_FILE}"
    fail "Created ${ENV_FILE}. Update secrets and rerun deploy."
  fi

  fail "Missing ${ENV_FILE} and no example file found"
}

validate_environment() {
  set -a
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +a

  local password="${POSTGRES_PASSWORD:-}"
  case "${password}" in
    ""|changeme|CHANGE_ME_TO_A_LONG_RANDOM_PASSWORD)
      fail "Set a strong POSTGRES_PASSWORD in ${ENV_FILE}"
      ;;
  esac

  if [[ "${BACKEND_BIND_HOST:-127.0.0.1}" != "127.0.0.1" && "${ALLOW_PUBLIC_BIND:-false}" != "true" ]]; then
    fail "BACKEND_BIND_HOST must be 127.0.0.1 unless ALLOW_PUBLIC_BIND=true"
  fi
}

wait_for_health() {
  local bind_host="${BACKEND_BIND_HOST:-127.0.0.1}"
  local health_host="${bind_host}"
  local port="${BACKEND_PORT:-8000}"

  if [[ "${health_host}" == "0.0.0.0" ]]; then
    health_host="127.0.0.1"
  fi

  local health_url="${HEALTH_URL:-http://${health_host}:${port}/api/v1/health}"
  log "Waiting for backend health at ${health_url}"

  local attempt
  for attempt in $(seq 1 40); do
    if curl -fsS "${health_url}" >/dev/null 2>&1; then
      log "Backend is healthy"
      return
    fi
    sleep 3
  done

  log "Backend did not become healthy in time"
  compose ps
  compose logs --no-color --tail=100 backend
  fail "Deployment failed health check"
}

run_deploy() {
  log "Pulling base images"
  compose pull postgres redis || true

  log "Building backend image"
  compose build backend

  log "Starting services"
  compose up -d --remove-orphans
}

run_ensure_up() {
  log "Ensuring services are running"
  compose up -d --no-build --remove-orphans
}

run_down() {
  log "Stopping services"
  compose down
}

print_usage() {
  cat <<'EOF'
Usage: ./scripts/selfhost/deploy.sh [mode]

Modes:
  deploy      Pull, build, and start services (default)
  ensure-up   Start services without rebuild
  down        Stop services
EOF
}

main() {
  case "${MODE}" in
    help|-h|--help)
      print_usage
      return
      ;;
  esac

  ensure_dependencies
  ensure_env_file
  validate_environment

  case "${MODE}" in
    deploy|full)
      run_deploy
      wait_for_health
      ;;
    ensure-up|up)
      run_ensure_up
      wait_for_health
      ;;
    down)
      run_down
      ;;
    *)
      fail "Unknown mode: ${MODE}"
      ;;
  esac

  if [[ "${MODE}" != "down" ]]; then
    compose ps
  fi
}

main
