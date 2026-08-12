from click.testing import CliRunner

from chatglance import __version__
from chatglance.cli import main


def test_version_option_reports_package_version():
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert f"chatglance, version {__version__}" in result.output


def test_tree_option_prints_registered_cli_tree():
    result = CliRunner().invoke(main, ["--tree"])

    assert result.exit_code == 0, result.output
    assert "chatglance  # Generate and maintain ChatArch Glance dashboard config" in result.output
    assert "projects" in result.output
    assert "collect" in result.output
    assert "render-page" in result.output
    assert "update-config" in result.output
    assert "disks" in result.output
    assert "root-only" in result.output
    assert "runtime" in result.output
    assert "maintain" in result.output
    assert "render-systemd" in result.output
    assert "install-systemd" in result.output
    assert "start" in result.output
    assert "servers" in result.output
    assert "sites" in result.output
    assert "export-covers" in result.output
    assert "account-limits" in result.output
    assert "render-page" in result.output
    assert "update-config" in result.output
    assert "status" in result.output
