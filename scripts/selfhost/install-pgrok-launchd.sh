#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer supports macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LABEL="${LABEL:-app.starpark.pgrok.tunnel}"
PLIST_TEMPLATE="${SCRIPT_DIR}/app.starpark.pgrok.tunnel.plist.template"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/starpark"
TUNNEL_SCRIPT="${REPO_ROOT}/scripts/selfhost/tunnel-pgrok.sh"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env.selfhost}"
PGROK_REPO="${PGROK_REPO:-/Users/core/Documents/pgrok}"

if [[ ! -f "${PLIST_TEMPLATE}" ]]; then
  echo "Missing plist template: ${PLIST_TEMPLATE}" >&2
  exit 1
fi

if [[ ! -x "${TUNNEL_SCRIPT}" ]]; then
  echo "Tunnel script must be executable: ${TUNNEL_SCRIPT}" >&2
  exit 1
fi

if [[ ! -d "${PGROK_REPO}" ]]; then
  echo "PGROK_REPO does not exist: ${PGROK_REPO}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${REPO_ROOT}/.env.selfhost.example" ]]; then
    cp "${REPO_ROOT}/.env.selfhost.example" "${ENV_FILE}"
    echo "Created ${ENV_FILE} from example. Update secrets and rerun." >&2
    exit 1
  fi

  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"

python3 - "${PLIST_TEMPLATE}" "${PLIST_PATH}" "${TUNNEL_SCRIPT}" "${REPO_ROOT}" "${ENV_FILE}" "${PGROK_REPO}" "${LOG_DIR}" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
tunnel_script = sys.argv[3]
repo_root = sys.argv[4]
env_file = sys.argv[5]
pgrok_repo = sys.argv[6]
log_dir = sys.argv[7]

content = template_path.read_text(encoding="utf-8")
content = content.replace("__TUNNEL_SCRIPT__", tunnel_script)
content = content.replace("__REPO_ROOT__", repo_root)
content = content.replace("__ENV_FILE__", env_file)
content = content.replace("__PGROK_REPO__", pgrok_repo)
content = content.replace("__LOG_DIR__", log_dir)
output_path.write_text(content, encoding="utf-8")
PY

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "Installed launchd job: ${LABEL}"
echo "Plist: ${PLIST_PATH}"
echo "Logs: ${LOG_DIR}/pgrok.out.log"
echo "Logs: ${LOG_DIR}/pgrok.err.log"
