#!/usr/bin/env bash
# Optional convenience wrapper; the published Python CLI owns the workflow.
set -euo pipefail
set +x
CHATARCH_HOME="${CHATARCH_HOME:-$HOME/.chatarch}"
CHATGLANCE_BIN="${CHATGLANCE_BIN:-$CHATARCH_HOME/venv/bin/chatglance}"
if [[ ! -x "$CHATGLANCE_BIN" ]]; then
  CHATGLANCE_BIN=chatglance
fi
exec "$CHATGLANCE_BIN" refresh "$@"
