from click.testing import CliRunner

from chatglance import __version__
from chatglance.cli import main


def test_help_and_version_expose_shared_root_contract():
    runner = CliRunner()
    help_result = runner.invoke(main, ["--help"])
    version_result = runner.invoke(main, ["--version"])

    assert main.name == "chatglance"
    assert help_result.exit_code == 0, help_result.output
    assert "--tree" in help_result.output
    assert "--tree-brief" in help_result.output
    assert version_result.exit_code == 0, version_result.output
    assert f"chatglance, version {__version__}" in version_result.output


def test_tree_option_prints_registered_cli_tree_with_signatures_and_boundaries():
    result = CliRunner().invoke(main, ["--tree"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "chatglance"
    assert result.output.splitlines().count("chatglance") == 1
    for expected in [
        "--version",
        "--tree",
        "--tree-brief",
        "account-limits",
        "json",
        "disks",
        "root-only",
        "home",
        "remove-widget",
        "projects",
        "collect",
        "render-page",
        "update-config",
        "runtime",
        "maintain",
        "render-systemd",
        "install-systemd",
        "start",
        "status",
        "servers",
        "candidates",
        "validate-refresh",
        "sites",
        "export-covers",
        "read-only GitHub metadata",
        "read-only SSH probes",
        "redacted account/quota JSON",
        "optionally restart a service",
    ]:
        assert expected in result.output
    assert "[--output OUTPUT-PATH]" in result.output
    assert "[--runtime-home RUNTIME-HOME]" in result.output
    assert "[--chatglance-bin CHATGLANCE-BIN]" in result.output


def test_tree_brief_keeps_nodes_and_omits_signatures():
    result = CliRunner().invoke(main, ["--tree-brief"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "chatglance"
    for expected in [
        "--version",
        "--tree",
        "--tree-brief",
        "account-limits",
        "projects",
        "collect",
        "runtime",
        "install-systemd",
        "servers",
        "validate-refresh",
        "sites",
        "export-covers",
        "redacted account/quota JSON",
        "optionally restart a service",
    ]:
        assert expected in result.output
    assert "[--output OUTPUT-PATH]" not in result.output
    assert "[--runtime-home RUNTIME-HOME]" not in result.output
    assert "[--chatglance-bin CHATGLANCE-BIN]" not in result.output
