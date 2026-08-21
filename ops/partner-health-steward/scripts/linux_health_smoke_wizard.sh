#!/usr/bin/env bash
# Post-Ticket-14 acceptance wizard. It verifies; it never installs or edits config.

set -euo pipefail

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  BOLD=$(tput bold || true); RESET=$(tput sgr0 || true)
  GREEN=$(tput setaf 2 || true); YELLOW=$(tput setaf 3 || true)
else
  BOLD=""; RESET=""; GREEN=""; YELLOW=""
fi

stage() { printf '\n%s[%s/4] %s%s\n' "$BOLD" "$1" "$2" "$RESET"; }
step() { printf '  - %s\n' "$1"; }
warn() { printf '  %sWARNING: %s%s\n' "$YELLOW" "$1" "$RESET"; }
confirm() {
  local answer=""
  printf '  %s? %s [y/N]%s ' "$YELLOW" "$1" "$RESET"
  read -r answer || true
  [[ "$answer" =~ ^[Yy]$ ]]
}

HERMES_HOME=/var/lib/hermes-partner/.hermes/profiles/partner
SOCKET_PATH=/run/health-sidecar/health.sock
DEPLOYMENT_STATE=/var/lib/partner-health-steward/deployment-state.json
PYTHON_BIN=/usr/local/lib/hermes-agent/venv/bin/python
PARTNER_EXEC="/usr/local/lib/hermes-agent/venv/bin/python -m hermes_cli.main --profile partner gateway run"

printf '\n%sHermes partner health Linux smoke%s\n' "$BOLD" "$RESET"
printf '  Verifies the isolated deployment and the two fixed Jobs.\n'

stage 1 "Resolve the installed immutable release"
if [[ "$(uname -s)" != Linux* || "$(id -u)" -ne 0 ]]; then
  warn "Run this wizard as root on the approved Linux host."
  exit 1
fi
if [[ ! -f "$DEPLOYMENT_STATE" ]]; then
  warn "Ticket 14 deployment state is absent. This wizard will not install it."
  exit 1
fi
RELEASE_ID=$("$PYTHON_BIN" - "$DEPLOYMENT_STATE" <<'PY'
import json, re, sys
release = json.load(open(sys.argv[1], encoding="utf-8")).get("current_release")
if not isinstance(release, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release):
    raise SystemExit("invalid current release")
print(release)
PY
)
SOURCE_ROOT="/opt/partner-health-steward/releases/$RELEASE_ID"
if [[ ! -f "$SOURCE_ROOT/MANIFEST.json" ]]; then
  warn "The active release manifest is absent: $SOURCE_ROOT"
  exit 1
fi
step "Release $RELEASE_ID"
step "Fixed profile $HERMES_HOME"

stage 2 "Verify the Linux process and file boundary"
"$PYTHON_BIN" "$SOURCE_ROOT/scripts/deploy_health_steward.py" verify-runtime \
  --source-root "$SOURCE_ROOT" \
  --release-id "$RELEASE_ID" \
  --receipt-public-key /etc/health-sidecar/receipt-public.key \
  --sidecar-python "$PYTHON_BIN" \
  --hermes-python "$PYTHON_BIN" \
  --partner-exec-start "$PARTNER_EXEC"
step "Restricted PIDs, private socket, projection, file denial, no TCP listener, and two Jobs passed"

stage 3 "Approve the non-production Job smoke"
warn "Today's scheduled 04:00 daily Job must already be complete."
warn "The next action schedules only the dispatcher once and can consume one LLM call."
if ! confirm "Is this the approved non-production partner profile?"; then
  warn "Job smoke cancelled; the runtime verification remains valid."
  exit 0
fi

stage 4 "Prove fresh sessions, plugin calls, and sidecar socket use"
runuser --user hermes-partner -- env \
  HERMES_HOME="$HERMES_HOME" \
  HEALTH_STEWARD_SOURCE_ROOT="$SOURCE_ROOT" \
  HEALTH_STEWARD_SOCKET="$SOCKET_PATH" \
  PYTHONPATH="$SOURCE_ROOT" \
  "$PYTHON_BIN" "$SOURCE_ROOT/scripts/verify_health_steward_job_smoke.py" \
  --timeout-seconds 900
printf '\n  %sLinux smoke passed%s\n\n' "$GREEN" "$RESET"
