#!/usr/bin/env bash
# Refresh the ChatGlance Infra/server-status page from an external scheduler.
#
# This script deliberately orchestrates public CLI commands instead of embedding
# live credentials. It can be run manually, by cron, or by a systemd user timer.
# Required inputs are paths and SSH config on the control machine.

set -euo pipefail

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

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$BACKUP_DIR"

"$CHATGLANCE_BIN" servers collect \
  --inventory-config "$INVENTORY_CONFIG" \
  --output "$DATA_PATH"

"$CHATGLANCE_BIN" servers render-page \
  --inventory-config "$INVENTORY_CONFIG" \
  --data "$DATA_PATH" \
  --output "$PAGE_PATH"

"$CHATGLANCE_BIN" servers update-config \
  --inventory-config "$INVENTORY_CONFIG" \
  --data "$DATA_PATH" \
  --config "$CONFIG_PATH" \
  --output "$CANDIDATE_PATH"

"$GLANCE_BIN" -config "$CANDIDATE_PATH" config:validate

if cmp -s "$CANDIDATE_PATH" "$CONFIG_PATH"; then
  unchanged="$BACKUP_DIR/glance.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$CANDIDATE_PATH" "$unchanged"
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged"
  exit 0
fi

backup="$BACKUP_DIR/glance.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
cp "$CONFIG_PATH" "$backup"
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH backup=$backup service_name=$SERVICE_NAME service_action=external"
