#!/usr/bin/env bash
# Refresh the ChatGlance account-limits page data and apply a validated config.
#
# Scope:
# - collects Codex usage/quota/reset windows for reviewed ChatEnv OpenAI profiles;
# - enables the local ChatClash proxy environment when available/needed;
# - renders data/page/config candidates and validates the config candidate;
# - replaces the data/page/config files only after validation and backups;
# - does not restart/reload Glance. Service lifecycle is intentionally external.

set -euo pipefail
set +x

RUNTIME_HOME="${CHATGLANCE_RUNTIME_HOME:-$HOME/.chatarch/glance}"
CHATGLANCE_BIN="${CHATGLANCE_BIN:-chatglance}"
CHATCRS_BIN="${CHATGLANCE_CHATCRS_BIN:-chatcrs}"
GLANCE_BIN="${GLANCE_BIN:-$RUNTIME_HOME/bin/glance}"
CHATCLASH_BIN="${CHATGLANCE_CHATCLASH_BIN:-$HOME/.chatarch/venv/bin/chatclash}"
PROFILES="${CHATGLANCE_ACCOUNT_LIMITS_PROFILES:-73-wzh allis lookeng yifei}"
DATA_PATH="${CHATGLANCE_ACCOUNT_LIMITS_JSON:-$RUNTIME_HOME/data/account-limits.json}"
PAGE_PATH="${CHATGLANCE_ACCOUNT_LIMITS_PAGE_YML:-$RUNTIME_HOME/data/account-limits-page.yml}"
CONFIG_PATH="${CHATGLANCE_CONFIG:-$RUNTIME_HOME/config/glance.yml}"
CANDIDATE_PATH="${CHATGLANCE_CANDIDATE_CONFIG:-$RUNTIME_HOME/config/glance.yml.account-limits-candidate}"
BACKUP_DIR="${CHATGLANCE_BACKUP_DIR:-$RUNTIME_HOME/config/backups}"
NEXT_DATA_PATH="${CHATGLANCE_ACCOUNT_LIMITS_NEXT_JSON:-$DATA_PATH.next}"
NEXT_PAGE_PATH="${CHATGLANCE_ACCOUNT_LIMITS_NEXT_PAGE_YML:-$PAGE_PATH.next}"
COLLECTOR="${CHATGLANCE_ACCOUNT_LIMITS_COLLECTOR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/collect-codex-account-limits.py}"
TIMEOUT="${CHATGLANCE_ACCOUNT_LIMITS_TIMEOUT:-60}"
ENABLE_PROXY="${CHATGLANCE_ENABLE_PROXY:-auto}"

mkdir -p "$(dirname "$DATA_PATH")" "$(dirname "$PAGE_PATH")" "$(dirname "$CANDIDATE_PATH")" "$BACKUP_DIR"

if [[ ! -x "$COLLECTOR" ]]; then
  if [[ -f "$COLLECTOR" ]]; then
    chmod 0755 "$COLLECTOR"
  else
    echo "missing collector=$COLLECTOR" >&2
    exit 2
  fi
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "missing config=$CONFIG_PATH" >&2
  exit 2
fi

proxy_enabled=false
if [[ "$ENABLE_PROXY" != "0" && "$ENABLE_PROXY" != "false" ]]; then
  if [[ -x "$CHATCLASH_BIN" ]]; then
    # Do not print proxy values. Import only known proxy variable assignments.
    PROXY_EXPORTS="$($CHATCLASH_BIN proxy env --no-mask 2>/dev/null || true)"
    if [[ -n "$PROXY_EXPORTS" ]]; then
      while IFS= read -r proxy_line; do
        proxy_line="${proxy_line#export }"
        proxy_key="${proxy_line%%=*}"
        proxy_value="${proxy_line#*=}"
        case "$proxy_key" in
          HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|http_proxy|https_proxy|all_proxy|no_proxy)
            proxy_value="${proxy_value%\"}"
            proxy_value="${proxy_value#\"}"
            proxy_value="${proxy_value%\'}"
            proxy_value="${proxy_value#\'}"
            export "$proxy_key=$proxy_value"
            proxy_enabled=true
            ;;
        esac
      done <<< "$PROXY_EXPORTS"
    elif [[ "$ENABLE_PROXY" == "1" || "$ENABLE_PROXY" == "true" ]]; then
      echo "proxy helper returned no environment" >&2
      exit 3
    fi
    unset PROXY_EXPORTS proxy_line proxy_key proxy_value
  elif [[ "$ENABLE_PROXY" == "1" || "$ENABLE_PROXY" == "true" ]]; then
    echo "missing proxy helper=$CHATCLASH_BIN" >&2
    exit 3
  fi
fi

collector_args=(
  --profiles "$PROFILES"
  --output "$NEXT_DATA_PATH"
  --chatcrs-bin "$CHATCRS_BIN"
  --timeout "$TIMEOUT"
)
if [[ -f "$DATA_PATH" ]]; then
  collector_args+=(--history "$DATA_PATH")
fi
"$COLLECTOR" "${collector_args[@]}"

"$CHATGLANCE_BIN" account-limits render-page \
  --data "$NEXT_DATA_PATH" \
  --output "$NEXT_PAGE_PATH"

"$CHATGLANCE_BIN" account-limits update-config \
  --data "$NEXT_DATA_PATH" \
  --config "$CONFIG_PATH" \
  --output "$CANDIDATE_PATH.account-limits"

"$CHATGLANCE_BIN" home remove-widget \
  --config "$CANDIDATE_PATH.account-limits" \
  --output "$CANDIDATE_PATH" \
  --type hacker-news

"$GLANCE_BIN" -config "$CANDIDATE_PATH" config:validate

if cmp -s "$NEXT_DATA_PATH" "$DATA_PATH" 2>/dev/null && cmp -s "$NEXT_PAGE_PATH" "$PAGE_PATH" 2>/dev/null && cmp -s "$CANDIDATE_PATH" "$CONFIG_PATH" 2>/dev/null; then
  unchanged_candidate="$BACKUP_DIR/glance.account-limits.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  unchanged_data="$BACKUP_DIR/account-limits.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
  unchanged_page="$BACKUP_DIR/account-limits-page.unchanged.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
  mv "$CANDIDATE_PATH" "$unchanged_candidate"
  mv "$NEXT_DATA_PATH" "$unchanged_data"
  mv "$NEXT_PAGE_PATH" "$unchanged_page"
  echo "changed=false data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH candidate=$unchanged_candidate data_candidate=$unchanged_data page_candidate=$unchanged_page proxy_enabled=$proxy_enabled service_action=external"
  exit 0
fi

backup="$BACKUP_DIR/glance.account-limits.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
cp "$CONFIG_PATH" "$backup"
data_backup="$BACKUP_DIR/account-limits.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).json"
if [[ -f "$DATA_PATH" ]]; then
  cp "$DATA_PATH" "$data_backup"
fi
page_backup="$BACKUP_DIR/account-limits-page.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml"
if [[ -f "$PAGE_PATH" ]]; then
  cp "$PAGE_PATH" "$page_backup"
fi

mv "$NEXT_DATA_PATH" "$DATA_PATH"
mv "$NEXT_PAGE_PATH" "$PAGE_PATH"
mv "$CANDIDATE_PATH" "$CONFIG_PATH"

echo "changed=true data=$DATA_PATH page=$PAGE_PATH config=$CONFIG_PATH backup=$backup data_backup=$data_backup page_backup=$page_backup proxy_enabled=$proxy_enabled service_action=external"
