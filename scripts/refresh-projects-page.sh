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
CATEGORY_OVERRIDES_PATH="${CHATGLANCE_PROJECTS_CATEGORY_OVERRIDES_JSON:-$RUNTIME_HOME/config/project-category-overrides.json}"
BASELINE_PATH="${CHATGLANCE_PROJECTS_BASELINE_JSON:-}"
NEXT_DATA_PATH="${CHATGLANCE_PROJECTS_NEXT_JSON:-$DATA_PATH.next}"
NEXT_PAGE_PATH="${CHATGLANCE_PROJECTS_NEXT_PAGE_YML:-$PAGE_PATH.next}"

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$BACKUP_DIR"

(
  cd "$REPO_ROOT"
  baseline_args=()
  if [[ -z "$BASELINE_PATH" && -s "$CATEGORY_OVERRIDES_PATH" ]]; then
    BASELINE_PATH="$CATEGORY_OVERRIDES_PATH"
  fi
  if [[ -z "$BASELINE_PATH" ]]; then
    BASELINE_PATH="$DATA_PATH"
  fi
  if [[ -s "$BASELINE_PATH" ]]; then
    baseline_args=(--baseline-data "$BASELINE_PATH")
  fi
  "$CHATGLANCE_BIN" projects collect \
    --owner "$OWNER" \
    --chatgh-bin "$CHATGH_BIN" \
    "${baseline_args[@]}" \
    --output "$NEXT_DATA_PATH"
)

"$CHATGLANCE_BIN" projects render-page \
  --data "$NEXT_DATA_PATH" \
  --output "$NEXT_PAGE_PATH"

"$CHATGLANCE_BIN" projects update-config \
  --data "$NEXT_DATA_PATH" \
  --config "$CONFIG_PATH" \
  --output "$CANDIDATE_PATH"

"$GLANCE_BIN" -config "$CANDIDATE_PATH" config:validate

if cmp -s "$CANDIDATE_PATH" "$CONFIG_PATH"; then
  unchanged="$BACKUP_DIR/glance.projects.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$CANDIDATE_PATH" "$unchanged"
  unchanged_page="$BACKUP_DIR/projects-page.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$NEXT_PAGE_PATH" "$unchanged_page"
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged page_candidate=$unchanged_page"
  exit 0
fi

backup="$BACKUP_DIR/glance.projects.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
cp "$CONFIG_PATH" "$backup"
data_backup="$BACKUP_DIR/chatarch-projects.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
if [[ -f "$DATA_PATH" ]]; then
  cp "$DATA_PATH" "$data_backup"
fi
page_backup="$BACKUP_DIR/projects-page.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
if [[ -f "$PAGE_PATH" ]]; then
  cp "$PAGE_PATH" "$page_backup"
fi
mv "$NEXT_DATA_PATH" "$DATA_PATH"
mv "$NEXT_PAGE_PATH" "$PAGE_PATH"
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH backup=$backup data_backup=$data_backup page_backup=$page_backup"
