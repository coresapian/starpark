#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer supports macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LABEL="${LABEL:-app.starpark.selfhost}"
PLIST_TEMPLATE="${SCRIPT_DIR}/app.starpark.selfhost.plist.template"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/starpark"
DEPLOY_SCRIPT="${REPO_ROOT}/scripts/selfhost/deploy.sh"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env.selfhost}"

if [[ ! -f "${PLIST_TEMPLATE}" ]]; then
  echo "Missing plist template: ${PLIST_TEMPLATE}" >&2
  exit 1
fi

if [[ ! -x "${DEPLOY_SCRIPT}" ]]; then
  echo "Deploy script must be executable: ${DEPLOY_SCRIPT}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${REPO_ROOT}/.env.selfhost.example" ]]; then
    cp "${REPO_ROOT}/.env.selfhost.example" "${ENV_FILE}"
    echo "Created ${ENV_FILE} from example. Update secrets before first launch." >&2
  else
    echo "Missing ${ENV_FILE}" >&2
    exit 1
  fi
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"

python3 - "${PLIST_TEMPLATE}" "${PLIST_PATH}" "${DEPLOY_SCRIPT}" "${REPO_ROOT}" "${ENV_FILE}" "${LOG_DIR}" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
deploy_script = sys.argv[3]
repo_root = sys.argv[4]
env_file = sys.argv[5]
log_dir = sys.argv[6]

content = template_path.read_text(encoding="utf-8")
content = content.replace("__DEPLOY_SCRIPT__", deploy_script)
content = content.replace("__REPO_ROOT__", repo_root)
content = content.replace("__ENV_FILE__", env_file)
content = content.replace("__LOG_DIR__", log_dir)
output_path.write_text(content, encoding="utf-8")
PY

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "Installed launchd job: ${LABEL}"
echo "Plist: ${PLIST_PATH}"
echo "Logs: ${LOG_DIR}/selfhost.out.log"
echo "Logs: ${LOG_DIR}/selfhost.err.log"
