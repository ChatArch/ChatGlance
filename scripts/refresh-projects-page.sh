#!/usr/bin/env bash
# Refresh the ChatGlance projects page from current GitHub/ChatGH data.
#
# This script deliberately keeps credentials outside the repository. ChatGH is
# used for the authenticated repository list. For GitHub contents/file fetches,
# chatglance also honors CHATGLANCE_GITHUB_TOKEN, GITHUB_TOKEN, or GH_TOKEN when
# one is present in the environment; otherwise it can reuse the repo-local
# GitHub HTTPS credential configured by `chatgh set-token` in this checkout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RUNTIME_HOME="${CHATGLANCE_RUNTIME_HOME:-$HOME/.chatarch/glance}"
CHATGLANCE_BIN="${CHATGLANCE_BIN:-chatglance}"
CHATGH_BIN="${CHATGH_BIN:-chatgh}"
GLANCE_BIN="${GLANCE_BIN:-$RUNTIME_HOME/bin/glance}"
OWNER="${CHATGLANCE_PROJECTS_OWNER:-ChatArch}"
DATA_PATH="${CHATGLANCE_PROJECTS_JSON:-$RUNTIME_HOME/data/chatarch-projects.json}"
PAGE_PATH="${CHATGLANCE_PROJECTS_PAGE_YML:-$RUNTIME_HOME/data/projects-page.yml}"
CONFIG_PATH="${CHATGLANCE_CONFIG:-$RUNTIME_HOME/config/glance.yml}"
CANDIDATE_PATH="${CHATGLANCE_CANDIDATE_CONFIG:-$RUNTIME_HOME/config/glance.yml.projects-candidate}"
BACKUP_DIR="${CHATGLANCE_BACKUP_DIR:-$RUNTIME_HOME/config/backups}"

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$BACKUP_DIR"

(
  cd "$REPO_ROOT"
  "$CHATGLANCE_BIN" projects collect \
    --owner "$OWNER" \
    --chatgh-bin "$CHATGH_BIN" \
    --output "$DATA_PATH"
)

"$CHATGLANCE_BIN" projects render-page \
  --data "$DATA_PATH" \
  --output "$PAGE_PATH"

"$CHATGLANCE_BIN" projects update-config \
  --data "$DATA_PATH" \
  --config "$CONFIG_PATH" \
  --output "$CANDIDATE_PATH"

"$GLANCE_BIN" -config "$CANDIDATE_PATH" config:validate

if cmp -s "$CANDIDATE_PATH" "$CONFIG_PATH"; then
  unchanged="$BACKUP_DIR/glance.projects.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$CANDIDATE_PATH" "$unchanged"
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged"
  exit 0
fi

backup="$BACKUP_DIR/glance.projects.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
cp "$CONFIG_PATH" "$backup"
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH backup=$backup"
