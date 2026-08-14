from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "refresh-live-pages.sh"


def test_live_refresh_script_runs_three_page_refreshers_hourly_ready_and_restarts_only_on_changes() -> None:
    assert SCRIPT_PATH.exists(), "missing combined live refresh script"
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "set +x" in text
    assert "refresh-server-status.sh" in text
    assert "refresh-account-limits-page.sh" in text
    assert "refresh-projects-page.sh" in text
    assert text.index("refresh-server-status.sh") < text.index("refresh-account-limits-page.sh") < text.index("refresh-projects-page.sh")
    assert "failed_any" in text
    assert "success_any" in text
    assert "refresh_failed" in text
    assert "changed=true" in text
    assert "systemctl --user restart" in text
    assert "if [[ \"$changed_any\" == \"1\" ]]" in text
    assert "service_action=restarted" in text
    assert "service_action=unchanged" in text
    assert "export CHATGH_BIN" in text
    assert "export CHATCRS_BIN" in text
    assert "${CHATCRS_BIN:-$HOME/.chatarch/venv/bin/chatcrs}" in text
    assert "export CHATGLANCE_CHATCLASH_BIN" in text
    assert "export CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION" in text
    assert "${CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION:-1}" in text
    assert "CHATGLANCE_REFRESH_LOCK" in text
    assert "flock -n 9" in text
    assert "service_action=skipped_locked" in text


def test_live_refresh_script_publishes_reviewed_server_outages_by_default() -> None:
    assert SCRIPT_PATH.exists(), "missing combined live refresh script"
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION" in text
    assert "including\n# real outages" in text
    assert text.index("CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION") < text.index("run_refresh refresh-server-status.sh")


def test_live_refresh_script_continues_after_one_page_refresh_fails() -> None:
    assert SCRIPT_PATH.exists(), "missing combined live refresh script"
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "run_refresh refresh-server-status.sh" in text
    assert "run_refresh refresh-account-limits-page.sh" in text
    assert "run_refresh refresh-projects-page.sh" in text
    assert "run_refresh refresh-server-status.sh || true" in text
    assert "run_refresh refresh-account-limits-page.sh || true" in text
    assert "run_refresh refresh-projects-page.sh || true" in text
    assert "if [[ \"$success_any\" != \"1\" ]]" in text


def test_source_chatglance_wrapper_for_live_scripts_uses_repo_src_without_shell_eval() -> None:
    wrapper = REPO_ROOT / "scripts" / "chatglance-from-source"
    assert wrapper.exists(), "missing source wrapper for live timer"
    text = wrapper.read_text(encoding="utf-8")

    assert "set +x" in text
    assert "PYTHONPATH" in text
    assert "exec python3 -m chatglance.cli \"$@\"" in text
    assert "eval" not in text
