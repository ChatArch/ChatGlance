from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def read_script(name: str) -> str:
    path = SCRIPTS / name
    assert path.exists(), f"missing script {name}"
    return path.read_text(encoding="utf-8")


def test_refresh_scripts_stage_candidate_config_parent_before_config_validate() -> None:
    for name in ["refresh-server-status.sh", "refresh-account-limits-page.sh", "refresh-projects-page.sh"]:
        text = read_script(name)

        assert "mkdir -p" in text
        assert '"$(dirname "$CANDIDATE_PATH")"' in text, f"{name} must create candidate config parent"
        assert text.index('"$(dirname "$CANDIDATE_PATH")"') < text.index("config:validate")


def test_refresh_scripts_compare_data_page_and_config_before_reporting_unchanged() -> None:
    expectations = {
        "refresh-server-status.sh": ["$NEXT_DATA_PATH", "$DATA_PATH", "$NEXT_PAGE_PATH", "$PAGE_PATH", "$CANDIDATE_PATH", "$CONFIG_PATH"],
        "refresh-account-limits-page.sh": ["$NEXT_DATA_PATH", "$DATA_PATH", "$NEXT_PAGE_PATH", "$PAGE_PATH", "$CANDIDATE_PATH", "$CONFIG_PATH"],
        "refresh-projects-page.sh": ["$NEXT_DATA_PATH", "$DATA_PATH", "$NEXT_PAGE_PATH", "$PAGE_PATH", "$NEXT_CLI_REPORT_PATH", "$CLI_REPORT_PATH", "$CANDIDATE_PATH", "$CONFIG_PATH"],
    }
    for name, fragments in expectations.items():
        text = read_script(name)
        unchanged_block = text.split("changed=false", 1)[0]
        for fragment in fragments:
            assert fragment in unchanged_block, f"{name} unchanged decision should inspect {fragment}"
        assert unchanged_block.count("cmp -s") >= len(fragments) // 2, f"{name} should compare generated artifacts, not only config"


def test_refresh_scripts_report_external_service_lifecycle_consistently() -> None:
    for name in ["refresh-server-status.sh", "refresh-account-limits-page.sh", "refresh-projects-page.sh"]:
        text = read_script(name)
        assert "service_action=external" in text, f"{name} must not imply it restarted Glance"
        assert "systemctl" not in text, f"{name} should leave service lifecycle external"


def test_refresh_scripts_run_with_xtrace_disabled_before_credential_or_proxy_helpers() -> None:
    for name in ["refresh-server-status.sh", "refresh-account-limits-page.sh", "refresh-projects-page.sh"]:
        text = read_script(name)
        assert "set +x" in text, f"{name} should disable xtrace before helper commands and path reporting"
        assert text.index("set +x") < text.index("$CHATGLANCE_BIN")
    account_text = read_script("refresh-account-limits-page.sh")
    assert account_text.index("set +x") < account_text.index("proxy env --no-mask")
    project_text = read_script("refresh-projects-page.sh")
    assert project_text.index("set +x") < project_text.index("$CHATGH_BIN")


def test_refresh_account_limits_script_cleans_intermediate_config_candidate() -> None:
    text = read_script("refresh-account-limits-page.sh")

    assert 'INTERMEDIATE_CANDIDATE_PATH="${CANDIDATE_PATH}.account-limits"' in text
    assert "cleanup_intermediate_candidate" in text
    assert "trap cleanup_intermediate_candidate EXIT" in text
    assert '--output "$INTERMEDIATE_CANDIDATE_PATH"' in text
    assert '--config "$INTERMEDIATE_CANDIDATE_PATH"' in text
    assert '"$CANDIDATE_PATH.account-limits"' not in text
