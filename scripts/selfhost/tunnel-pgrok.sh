#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env.selfhost}"
PGROK_REPO="${PGROK_REPO:-/Users/core/Documents/pgrok}"
PGROK_SUBDOMAIN="${PGROK_SUBDOMAIN:-api}"
PGROK_BIN="${PGROK_BIN:-}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${BACKEND_PORT}/api/v1/health}"
EXPECTED_PGROK_DOMAIN="${EXPECTED_PGROK_DOMAIN:-}"

log() {
  printf '[starpark-pgrok] %s\n' "$*"
}

fail() {
  printf '[starpark-pgrok] ERROR: %s\n' "$*" >&2
  exit 1
}

load_env() {
  if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
  fi
}

resolve_pgrok_bin() {
  if [[ -n "${PGROK_BIN}" && -x "${PGROK_BIN}" ]]; then
    return
  fi

  if command -v pgrok >/dev/null 2>&1; then
    PGROK_BIN="$(command -v pgrok)"
    return
  fi

  if [[ -x "${PGROK_REPO}/client/tui/pgrok" ]]; then
    PGROK_BIN="${PGROK_REPO}/client/tui/pgrok"
    return
  fi

  fail "pgrok binary not found. Set PGROK_BIN or build pgrok in ${PGROK_REPO}."
}

ensure_pgrok_config() {
  local config_file="${HOME}/.pgrok/config"
  if [[ -f "${config_file}" ]]; then
    if [[ -n "${EXPECTED_PGROK_DOMAIN}" ]]; then
      local current_domain
      current_domain="$(grep -E '^PGROK_DOMAIN=' "${config_file}" | tail -n 1 | cut -d '=' -f2-)"
      if [[ "${current_domain}" != "${EXPECTED_PGROK_DOMAIN}" ]]; then
        fail "~/.pgrok/config has PGROK_DOMAIN=${current_domain}. Expected ${EXPECTED_PGROK_DOMAIN}."
      fi
    fi
    return
  fi

  fail "Missing ${config_file}. Run ${PGROK_REPO}/setup.sh client first."
}

wait_for_backend() {
  log "Waiting for backend at ${HEALTH_URL}"
  local attempt
  for attempt in $(seq 1 30); do
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
      log "Backend is healthy"
      return
    fi
    sleep 2
  done

  fail "Backend is not reachable at ${HEALTH_URL}"
}

main() {
  command -v curl >/dev/null 2>&1 || fail "curl is required"
  load_env
  resolve_pgrok_bin
  ensure_pgrok_config
  wait_for_backend

  log "Starting tunnel ${PGROK_SUBDOMAIN} -> localhost:${BACKEND_PORT}"
  exec "${PGROK_BIN}" "${PGROK_SUBDOMAIN}" "${BACKEND_PORT}" --print-logs
}

main
