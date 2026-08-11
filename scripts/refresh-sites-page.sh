#!/usr/bin/env bash
# Refresh the ChatGlance website-services page from a reviewed fixed inventory.
#
# This script is intentionally manual/config-driven. It does not discover new
# Nginx sites automatically and it does not restart/reload Glance by default.

set -euo pipefail

RUNTIME_HOME="${CHATGLANCE_RUNTIME_HOME:-$HOME/.chatarch/glance}"
CHATGLANCE_BIN="${CHATGLANCE_BIN:-chatglance}"
GLANCE_BIN="${GLANCE_BIN:-$RUNTIME_HOME/bin/glance}"
INVENTORY_CONFIG="${CHATGLANCE_SITES_CONFIG:-$RUNTIME_HOME/config/site-services.yml}"
GATUS_DB="${CHATGLANCE_GATUS_DB:-$HOME/.chatarch/uptime-gatus/data/gatus.db}"
DATA_PATH="${CHATGLANCE_SITES_JSON:-$RUNTIME_HOME/data/site-services.json}"
PAGE_PATH="${CHATGLANCE_SITES_PAGE_YML:-$RUNTIME_HOME/data/site-services-page.yml}"
CONFIG_PATH="${CHATGLANCE_CONFIG:-$RUNTIME_HOME/config/glance.yml}"
CANDIDATE_PATH="${CHATGLANCE_CANDIDATE_CONFIG:-$RUNTIME_HOME/config/glance.yml.sites-candidate}"
BACKUP_DIR="${CHATGLANCE_BACKUP_DIR:-$RUNTIME_HOME/config/backups}"
NEXT_DATA_PATH="${CHATGLANCE_SITES_NEXT_JSON:-$DATA_PATH.next}"
NEXT_PAGE_PATH="${CHATGLANCE_SITES_NEXT_PAGE_YML:-$PAGE_PATH.next}"

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$BACKUP_DIR"

if [[ ! -f "$INVENTORY_CONFIG" ]]; then
  echo "missing inventory_config=$INVENTORY_CONFIG; set CHATGLANCE_SITES_CONFIG or create the runtime reviewed inventory file" >&2
  exit 2
fi

collect_args=(sites collect --inventory-config "$INVENTORY_CONFIG" --output "$NEXT_DATA_PATH")
if [[ -f "$GATUS_DB" ]]; then
  collect_args+=(--gatus-db "$GATUS_DB")
fi
"$CHATGLANCE_BIN" "${collect_args[@]}"

"$CHATGLANCE_BIN" sites render-page \
  --data "$NEXT_DATA_PATH" \
  --output "$NEXT_PAGE_PATH"

"$CHATGLANCE_BIN" sites update-config \
  --data "$NEXT_DATA_PATH" \
  --config "$CONFIG_PATH" \
  --output "$CANDIDATE_PATH"

"$GLANCE_BIN" -config "$CANDIDATE_PATH" config:validate

if cmp -s "$CANDIDATE_PATH" "$CONFIG_PATH"; then
  unchanged="$BACKUP_DIR/glance.sites.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$CANDIDATE_PATH" "$unchanged"
  unchanged_data="$BACKUP_DIR/site-services.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
  mv "$NEXT_DATA_PATH" "$unchanged_data"
  unchanged_page="$BACKUP_DIR/site-services-page.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$NEXT_PAGE_PATH" "$unchanged_page"
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged data_candidate=$unchanged_data page_candidate=$unchanged_page service_action=external"
  exit 0
fi

backup="$BACKUP_DIR/glance.sites.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
cp "$CONFIG_PATH" "$backup"
data_backup="$BACKUP_DIR/site-services.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
if [[ -f "$DATA_PATH" ]]; then
  cp "$DATA_PATH" "$data_backup"
fi
page_backup="$BACKUP_DIR/site-services-page.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
if [[ -f "$PAGE_PATH" ]]; then
  cp "$PAGE_PATH" "$page_backup"
fi
mv "$NEXT_DATA_PATH" "$DATA_PATH"
mv "$NEXT_PAGE_PATH" "$PAGE_PATH"
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH backup=$backup data_backup=$data_backup page_backup=$page_backup service_action=external"
