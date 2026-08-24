#!/usr/bin/env bash
# Refresh all ChatGlance generated live pages from an external hourly scheduler.
#
# The per-page refresh scripts own artifact generation, candidate config
# validation, backups, and replacement. They deliberately report
# service_action=external. This orchestrator is the service lifecycle boundary:
# it restarts Glance once after all page refreshes when at least one page changed.
# A single page failure is reported but does not prevent the other pages from
# refreshing; if every page fails, the service exits non-zero.

set -euo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_HOME="${CHATGLANCE_RUNTIME_HOME:-$HOME/.chatarch/glance}"
SERVICE_NAME="${CHATGLANCE_SERVICE_NAME:-chatarch-glance.service}"
LOCK_FILE="${CHATGLANCE_REFRESH_LOCK:-$RUNTIME_HOME/logs/refresh-live-pages.lock}"
mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "changed_any=false failed_any=true service=$SERVICE_NAME service_action=skipped_locked lock=$LOCK_FILE"
  exit 0
fi
export CHATGLANCE_RUNTIME_HOME="$RUNTIME_HOME"
export CHATGLANCE_BIN="${CHATGLANCE_BIN:-$SCRIPT_DIR/chatglance-from-source}"
export CHATGLANCE_CHATCLASH_BIN="${CHATGLANCE_CHATCLASH_BIN:-$HOME/.chatarch/venv/bin/chatclash}"
export GLANCE_BIN="${GLANCE_BIN:-$RUNTIME_HOME/bin/glance}"
# The live dashboard should publish the current reviewed server state, including
# real outages. The lower-level server refresh script still supports fail-closed
# runs by explicitly setting CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION=0.
export CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION="${CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION:-1}"

changed_any=0
failed_any=0
success_any=0
run_refresh() {
  local name="$1"
  local output
  if ! output="$($SCRIPT_DIR/$name 2>&1)"; then
    failed_any=1
    printf 'refresh_failed script=%s\n' "$name" >&2
    printf '%s\n' "$output" >&2
    return 1
  fi
  success_any=1
  printf '%s\n' "$output"
  if grep -q 'changed=true' <<< "$output"; then
    changed_any=1
  fi
}

run_refresh refresh-server-status.sh || true
run_refresh refresh-account-limits-page.sh || true
run_refresh refresh-projects-page.sh || true

if [[ "$success_any" != "1" ]]; then
  echo "changed_any=false failed_any=true service=$SERVICE_NAME service_action=failed"
  exit 1
fi

if [[ "$changed_any" == "1" ]]; then
  systemctl --user restart "$SERVICE_NAME"
  echo "changed_any=true failed_any=$([[ "$failed_any" == "1" ]] && echo true || echo false) service=$SERVICE_NAME service_action=restarted"
else
  echo "changed_any=false failed_any=$([[ "$failed_any" == "1" ]] && echo true || echo false) service=$SERVICE_NAME service_action=unchanged"
fi
