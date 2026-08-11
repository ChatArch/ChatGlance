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
UVX_BIN="${CHATGLANCE_UVX_BIN:-uvx}"
GLANCE_BIN="${GLANCE_BIN:-$RUNTIME_HOME/bin/glance}"
OWNER="${CHATGLANCE_PROJECTS_OWNER:-ChatArch}"
DATA_PATH="${CHATGLANCE_PROJECTS_JSON:-$RUNTIME_HOME/data/chatarch-projects.json}"
PAGE_PATH="${CHATGLANCE_PROJECTS_PAGE_YML:-$RUNTIME_HOME/data/projects-page.yml}"
CLI_REPORT_PATH="${CHATGLANCE_PROJECTS_CLI_REPORT_TSV:-$RUNTIME_HOME/data/project-cli-tree-report.tsv}"
CONFIG_PATH="${CHATGLANCE_CONFIG:-$RUNTIME_HOME/config/glance.yml}"
CANDIDATE_PATH="${CHATGLANCE_CANDIDATE_CONFIG:-$RUNTIME_HOME/config/glance.yml.projects-candidate}"
BACKUP_DIR="${CHATGLANCE_BACKUP_DIR:-$RUNTIME_HOME/config/backups}"
CATEGORY_OVERRIDES_PATH="${CHATGLANCE_PROJECTS_CATEGORY_OVERRIDES_JSON:-$RUNTIME_HOME/config/project-category-overrides.json}"
BASELINE_PATH="${CHATGLANCE_PROJECTS_BASELINE_JSON:-}"
NEXT_DATA_PATH="${CHATGLANCE_PROJECTS_NEXT_JSON:-$DATA_PATH.next}"
NEXT_PAGE_PATH="${CHATGLANCE_PROJECTS_NEXT_PAGE_YML:-$PAGE_PATH.next}"
NEXT_CLI_REPORT_PATH="${CHATGLANCE_PROJECTS_NEXT_CLI_REPORT_TSV:-$CLI_REPORT_PATH.next}"
PROJECT_WORKERS="${CHATGLANCE_PROJECTS_WORKERS:-4}"
COLLECT_ACTUAL_CLI_TREES="${CHATGLANCE_COLLECT_ACTUAL_CLI_TREES:-1}"
CLI_TREE_TIMEOUT="${CHATGLANCE_CLI_TREE_TIMEOUT:-90}"

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$(dirname "$CLI_REPORT_PATH")" "$BACKUP_DIR"

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
  cli_tree_args=(--no-actual-cli-tree)
  if [[ "$COLLECT_ACTUAL_CLI_TREES" != "0" && "$COLLECT_ACTUAL_CLI_TREES" != "false" && "$COLLECT_ACTUAL_CLI_TREES" != "False" ]]; then
    cli_tree_args=(--actual-cli-tree --uvx-bin "$UVX_BIN" --cli-tree-timeout "$CLI_TREE_TIMEOUT")
  fi
  "$CHATGLANCE_BIN" projects collect \
    --owner "$OWNER" \
    --chatgh-bin "$CHATGH_BIN" \
    --workers "$PROJECT_WORKERS" \
    "${baseline_args[@]}" \
    "${cli_tree_args[@]}" \
    --output "$NEXT_DATA_PATH"
)

python3 - "$NEXT_DATA_PATH" "$NEXT_CLI_REPORT_PATH" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

data_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])
data = json.loads(data_path.read_text(encoding="utf-8"))
rows = []
for item in sorted(data.get("repositories", []), key=lambda row: str(row.get("name") or "").lower()):
    if not isinstance(item, dict):
        continue
    cli = item.get("cli") if isinstance(item.get("cli"), dict) else {}
    tree = cli.get("actual_tree") if isinstance(cli.get("actual_tree"), dict) else {}
    version = item.get("version") if isinstance(item.get("version"), dict) else {}
    commands = [str(command) for command in (cli.get("commands") or [])]
    business_commands = [str(command) for command in (tree.get("business_commands") or [])]
    rows.append({
        "name": item.get("name") or "",
        "category_label": item.get("category_label") or "",
        "category": item.get("category") or "",
        "version": version.get("value") or "",
        "version_source": version.get("source") or "",
        "entrypoint_count": len(commands),
        "entrypoints": ",".join(commands),
        "actual_tree_status": tree.get("status") or "",
        "actual_business_command_count": tree.get("business_command_count") if tree.get("business_command_count") is not None else "",
        "actual_business_commands": ",".join(business_commands),
        "description": " ".join(str(item.get("description") or "").split()),
    })
report_path.parent.mkdir(parents=True, exist_ok=True)
with report_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["name"], delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
print(f"wrote {report_path} rows={len(rows)}")
PY

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
  unchanged_data="$BACKUP_DIR/chatarch-projects.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
  mv "$NEXT_DATA_PATH" "$unchanged_data"
  unchanged_page="$BACKUP_DIR/projects-page.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$NEXT_PAGE_PATH" "$unchanged_page"
  unchanged_cli_report="$BACKUP_DIR/project-cli-tree-report.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).tsv"
  if [[ -f "$NEXT_CLI_REPORT_PATH" ]]; then
    mv "$NEXT_CLI_REPORT_PATH" "$unchanged_cli_report"
  fi
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged data_candidate=$unchanged_data page_candidate=$unchanged_page cli_report_candidate=$unchanged_cli_report"
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
cli_report_backup="$BACKUP_DIR/project-cli-tree-report.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).tsv"
if [[ -f "$CLI_REPORT_PATH" ]]; then
  cp "$CLI_REPORT_PATH" "$cli_report_backup"
fi
mv "$NEXT_DATA_PATH" "$DATA_PATH"
mv "$NEXT_PAGE_PATH" "$PAGE_PATH"
if [[ -f "$NEXT_CLI_REPORT_PATH" ]]; then
  mv "$NEXT_CLI_REPORT_PATH" "$CLI_REPORT_PATH"
fi
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH cli_report=$CLI_REPORT_PATH config=$CONFIG_PATH backup=$backup data_backup=$data_backup page_backup=$page_backup cli_report_backup=$cli_report_backup"
