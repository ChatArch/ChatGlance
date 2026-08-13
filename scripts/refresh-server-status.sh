#!/usr/bin/env bash
# Refresh the ChatGlance Infra/server-status page from an external scheduler.
#
# This script deliberately orchestrates public CLI commands instead of embedding
# live credentials. It can be run manually, by cron, or by a systemd user timer.
# Required inputs are paths and SSH config on the control machine.

set -euo pipefail
set +x

RUNTIME_HOME="${CHATGLANCE_RUNTIME_HOME:-$HOME/.chatarch/glance}"
CHATGLANCE_BIN="${CHATGLANCE_BIN:-chatglance}"
GLANCE_BIN="${GLANCE_BIN:-$RUNTIME_HOME/bin/glance}"
INVENTORY_CONFIG="${CHATGLANCE_INFRA_CONFIG:-$RUNTIME_HOME/config/server-inventory.yml}"
DATA_PATH="${CHATGLANCE_SERVER_STATUS_JSON:-$RUNTIME_HOME/data/server-status.json}"
PAGE_PATH="${CHATGLANCE_SERVER_PAGE_YML:-$RUNTIME_HOME/data/server-page.yml}"
CONFIG_PATH="${CHATGLANCE_CONFIG:-$RUNTIME_HOME/config/glance.yml}"
CANDIDATE_PATH="${CHATGLANCE_CANDIDATE_CONFIG:-$RUNTIME_HOME/config/glance.yml.infra-candidate}"
BACKUP_DIR="${CHATGLANCE_BACKUP_DIR:-$RUNTIME_HOME/config/backups}"
SERVICE_NAME="${CHATGLANCE_SERVICE_NAME:-chatarch-glance.service}"
NEXT_DATA_PATH="${CHATGLANCE_SERVER_STATUS_NEXT_JSON:-$DATA_PATH.next}"
NEXT_PAGE_PATH="${CHATGLANCE_SERVER_PAGE_NEXT_YML:-$PAGE_PATH.next}"
ALLOW_OFFLINE_REGRESSION="${CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION:-0}"

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$(dirname "$CANDIDATE_PATH")" "$BACKUP_DIR"

if [[ ! -f "$INVENTORY_CONFIG" ]]; then
  echo "missing inventory_config=$INVENTORY_CONFIG; set CHATGLANCE_INFRA_CONFIG or create the runtime inventory file" >&2
  exit 2
fi

"$CHATGLANCE_BIN" servers collect \
  --inventory-config "$INVENTORY_CONFIG" \
  --output "$NEXT_DATA_PATH"

validate_args=(servers validate-refresh --previous "$DATA_PATH" --next "$NEXT_DATA_PATH")
if [[ "$ALLOW_OFFLINE_REGRESSION" == "1" || "$ALLOW_OFFLINE_REGRESSION" == "true" ]]; then
  validate_args+=(--allow-offline-regression)
fi
"$CHATGLANCE_BIN" "${validate_args[@]}"

"$CHATGLANCE_BIN" servers render-page \
  --inventory-config "$INVENTORY_CONFIG" \
  --data "$NEXT_DATA_PATH" \
  --output "$NEXT_PAGE_PATH"

"$CHATGLANCE_BIN" servers update-config \
  --inventory-config "$INVENTORY_CONFIG" \
  --data "$NEXT_DATA_PATH" \
  --config "$CONFIG_PATH" \
  --output "$CANDIDATE_PATH"

"$GLANCE_BIN" -config "$CANDIDATE_PATH" config:validate

if cmp -s "$NEXT_DATA_PATH" "$DATA_PATH" 2>/dev/null && cmp -s "$NEXT_PAGE_PATH" "$PAGE_PATH" 2>/dev/null && cmp -s "$CANDIDATE_PATH" "$CONFIG_PATH" 2>/dev/null; then
  unchanged="$BACKUP_DIR/glance.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$CANDIDATE_PATH" "$unchanged"
  unchanged_data="$BACKUP_DIR/server-status.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
  unchanged_page="$BACKUP_DIR/server-page.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$NEXT_DATA_PATH" "$unchanged_data"
  mv "$NEXT_PAGE_PATH" "$unchanged_page"
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged data_candidate=$unchanged_data page_candidate=$unchanged_page service_action=external"
  exit 0
fi

backup="$BACKUP_DIR/glance.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
cp "$CONFIG_PATH" "$backup"
data_backup="$BACKUP_DIR/server-status.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
if [[ -f "$DATA_PATH" ]]; then
  cp "$DATA_PATH" "$data_backup"
fi
page_backup="$BACKUP_DIR/server-page.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
if [[ -f "$PAGE_PATH" ]]; then
  cp "$PAGE_PATH" "$page_backup"
fi
mv "$NEXT_DATA_PATH" "$DATA_PATH"
mv "$NEXT_PAGE_PATH" "$PAGE_PATH"
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH backup=$backup data_backup=$data_backup page_backup=$page_backup service_name=$SERVICE_NAME service_action=external"
