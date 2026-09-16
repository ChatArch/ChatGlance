import importlib
import importlib.util
import json
from pathlib import Path

from click.testing import CliRunner
import pytest
import yaml
from chatglance.cli import main


def test_manual_refresh_command_is_registered():
    assert "refresh" in main.commands


def test_manual_refresh_has_importable_python_api():
    assert importlib.util.find_spec("chatglance.refresh") is not None
    assert callable(importlib.import_module("chatglance.refresh").refresh_runtime)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CHATGLANCE_ACCOUNT_LIMITS_PROFILES", raising=False)
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "bin").mkdir()
    (root / "bin/glance").write_text("fixture validator")
    config = {"auth": {"users": {}}, "pages": [
        {"name": "ChatArch", "columns": []},
        {"name": "网站服务", "slug": "sites", "columns": []},
        {"name": "Custom", "columns": []},
    ]}
    (root / "config/glance.yml").write_text(yaml.safe_dump(config, allow_unicode=True))
    (root / "config/site-services.yml").write_text("sites: []\n")
    (root / "data/site-services.json").write_text('{"generated_at":"old","sites":[]}')
    return root


def configure_fake_collection(monkeypatch, module, *, failing=(), partial=()):
    calls, restarts = [], []
    names = {"sites": "网站服务", "servers": "服务器", "projects": "项目", "account-limits": "订阅详情"}
    def collect(key, *args, **kwargs):
        calls.append((key, kwargs))
        if key in failing:
            raise RuntimeError("access_token=not-for-output")
        return module.PageUpdate(key, {"generated_at": "fresh", "counts": {}}, {"name": names[key], "slug": key, "columns": []}, partial=key in partial)
    monkeypatch.setattr(module, "_collect_page", collect)
    monkeypatch.setattr(module, "validate_glance_config", lambda *a: None)
    monkeypatch.setattr(module, "_restart", lambda service: restarts.append(service))
    return calls, restarts


def test_refreshes_only_configured_pages_and_preserves_order(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    calls, restarts = configure_fake_collection(monkeypatch, m)
    before = yaml.safe_load((runtime / "config/glance.yml").read_text())
    result = m.refresh_runtime(runtime)
    assert result["ok"] and result["changed"]
    assert [c[0] for c in calls] == ["sites"]
    after = yaml.safe_load((runtime / "config/glance.yml").read_text())
    assert [p["name"] for p in after["pages"]] == [p["name"] for p in before["pages"]]
    assert after["auth"] == before["auth"]
    assert after["pages"][0] == before["pages"][0]
    assert len(restarts) == 1
    assert json.loads((runtime / "data/site-services.json").read_text())["generated_at"] == "fresh"
    assert list((runtime / "config/backups").glob("refresh-*"))


def test_selected_page_does_not_collect_other_pages(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    calls, restarts = configure_fake_collection(monkeypatch, m)
    result = m.refresh_runtime(runtime, pages=["sites"], restart=False)
    assert result["ok"] and not result["restarted"]
    assert [c[0] for c in calls] == ["sites"] and restarts == []


def test_unchanged_artifacts_do_not_restart_again(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    _, restarts = configure_fake_collection(monkeypatch, m)
    m.refresh_runtime(runtime)
    result = m.refresh_runtime(runtime)
    assert not result["changed"] and not result["restarted"]
    assert len(restarts) == 1


def test_validation_failure_keeps_every_live_artifact(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    _, restarts = configure_fake_collection(monkeypatch, m)
    original = {p: p.read_bytes() for p in [runtime / "config/glance.yml", runtime / "data/site-services.json"]}
    def invalid(*args):
        raise RuntimeError("validation failed")
    monkeypatch.setattr(m, "validate_glance_config", invalid)
    with pytest.raises(m.RefreshError):
        m.refresh_runtime(runtime)
    assert all(p.read_bytes() == content for p, content in original.items())
    assert restarts == []


def test_one_page_failure_preserves_its_data_and_reports_partial(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    _, restarts = configure_fake_collection(monkeypatch, m, failing={"sites"})
    old = (runtime / "data/site-services.json").read_bytes()
    result = m.refresh_runtime(runtime, pages=["sites", "projects"])
    assert not result["ok"] and result["changed"]
    assert (runtime / "data/site-services.json").read_bytes() == old
    assert [p["status"] for p in result["pages"]] == ["error", "ok"]
    assert "not-for-output" not in json.dumps(result)
    assert len(restarts) == 1


def test_cached_partial_result_is_published_but_not_claimed_fully_fresh(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    configure_fake_collection(monkeypatch, m, partial={"sites"})
    result = m.refresh_runtime(runtime)
    assert not result["ok"] and result["changed"]
    assert result["pages"][0]["status"] == "partial"


def test_lock_contention_makes_no_collection_or_live_write(runtime, monkeypatch):
    import fcntl
    m = importlib.import_module("chatglance.refresh")
    calls, _ = configure_fake_collection(monkeypatch, m)
    (runtime / "logs").mkdir()
    with (runtime / "logs/refresh-live-pages.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(m.RefreshError, match="running"):
            m.refresh_runtime(runtime)
    assert calls == []


def test_config_edit_during_validation_is_not_overwritten(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    configure_fake_collection(monkeypatch, m)
    path = runtime / "config/glance.yml"
    changed = path.read_text() + "operator_note: keep\n"
    monkeypatch.setattr(m, "validate_glance_config", lambda *a: path.write_text(changed))
    with pytest.raises(m.RefreshError, match="changed"):
        m.refresh_runtime(runtime)
    assert path.read_text() == changed
    assert json.loads((runtime / "data/site-services.json").read_text())["generated_at"] == "old"


def test_cli_json_and_partial_exit_code(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    configure_fake_collection(monkeypatch, m, partial={"sites"})
    result = CliRunner().invoke(main, ["refresh", "sites", "--runtime-home", str(runtime), "--no-restart", "--json-output"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["pages"][0]["status"] == "partial"
    assert payload["restarted"] is False


def test_invalid_page_is_rejected_before_runtime_creation(tmp_path):
    result = CliRunner().invoke(main, ["refresh", "unknown", "--runtime-home", str(tmp_path / "absent")])
    assert result.exit_code != 0
    assert not (tmp_path / "absent").exists()


def test_account_refresh_is_monitor_only_even_if_reset_is_enabled(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    from chatglance import codex_collector
    (runtime / "data/account-limits.json").write_text(json.dumps({"codex": [{"profile": "work"}], "codex_reset": {"status": "ok", "events": []}}))
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE", "true")
    calls = []
    def collect(**kwargs):
        calls.append(kwargs)
        data = {"generated_at": "fresh", "codex": [], "codex_reset": {"status": "error", "using_last_known_values": True, "events": []}, "refresh_status": {"failed_count": 0}}
        kwargs["output_path"].write_text(json.dumps(data))
        return data
    monkeypatch.setattr(codex_collector, "collect_account_limits", collect)
    monkeypatch.setattr(m, "validate_glance_config", lambda *a: None)
    result = m.refresh_runtime(runtime, pages=["account-limits"], restart=False)
    assert calls[0]["execute_resets"] is False
    assert calls[0]["timeout"] == 60
    assert calls[0]["history_path"] == runtime / "data/account-limits.json"
    assert calls[0]["profiles"] == ["work"]
    assert result["pages"][0]["status"] == "partial"
    assert not result["ok"]


def test_invalid_collector_summary_does_not_publish_failed_page(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    _, restarts = configure_fake_collection(monkeypatch, m)
    path = runtime / "data/account-limits.json"
    path.write_text('{"generated_at":"old","codex":[]}')
    before = path.read_bytes()
    monkeypatch.setattr(m, "_collect_page", lambda *a, **kw: m.PageUpdate("account-limits", {"refresh_status": None, "codex": []}, {"name": "订阅详情", "columns": []}))
    result = m.refresh_runtime(runtime, pages=["account-limits"])
    assert not result["ok"] and not result["changed"]
    assert path.read_bytes() == before
    assert restarts == []


def test_maintenance_command_shares_manual_refresh_lock(runtime, monkeypatch):
    import fcntl
    from types import SimpleNamespace
    import chatglance.cli as cli
    calls = []
    def maintain(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_path=kwargs["output_path"], changed=False, validated=False, restarted=False, backup_path=None)
    monkeypatch.setattr(cli, "maintain_config", maintain)
    monkeypatch.setattr(cli, "discover_meaningful_mountpoints", lambda: {"/": "root"})
    (runtime / "logs").mkdir()
    with (runtime / "logs/refresh-live-pages.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = CliRunner().invoke(main, ["runtime", "maintain", "--runtime-home", str(runtime), "--no-validate"])
    assert result.exit_code != 0 and "running" in result.output
    assert calls == []


def test_default_runtime_respects_chatarch_home(tmp_path, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "private-home"))
    assert m.default_runtime_home() == tmp_path / "private-home/glance"


def test_publication_failure_restores_prior_files(runtime, monkeypatch):
    m = importlib.import_module("chatglance.refresh")
    _, restarts = configure_fake_collection(monkeypatch, m)
    paths = [runtime / "config/glance.yml", runtime / "data/site-services.json"]
    previous = {path: path.read_bytes() for path in paths}
    real_replace = m.os.replace
    def fail_config(source, target):
        if Path(target) == runtime / "config/glance.yml":
            raise OSError("injected publication failure")
        return real_replace(source, target)
    monkeypatch.setattr(m.os, "replace", fail_config)
    with pytest.raises(m.RefreshError, match="restored"):
        m.refresh_runtime(runtime)
    assert all(path.read_bytes() == body for path, body in previous.items())
    assert not (runtime / "data/site-services-page.yml").exists()
    assert restarts == []


@pytest.mark.parametrize("version, expected", [("1.0.0", True), ("1.0.1", False), (None, False)])
def test_cli_evidence_is_reused_only_for_same_released_artifact(version, expected):
    m = importlib.import_module("chatglance.refresh")
    previous = {"generated_at": "earlier", "repositories": [{"name": "Example", "version": {"value": "1.0.0"}, "package": {"python_name": "example"}, "cli": {"commands": ["example"], "actual_tree": {"status": "ok", "business_command_count": 1}}}]}
    current = {"repositories": [{"name": "Example", "version": {"value": version}, "package": {"python_name": "example"}, "cli": {"commands": ["example"]}}]}
    m._preserve_same_version_trees(current, previous)
    assert ("actual_tree" in current["repositories"][0]["cli"]) is expected
    assert current["counts"]["with_actual_cli_tree"] == int(expected)


def test_manual_script_is_only_a_public_cli_wrapper(tmp_path):
    import os
    import subprocess
    script = Path(__file__).resolve().parents[1] / "scripts/refresh-manual.sh"
    binary = tmp_path / "fake-cli"
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    binary.chmod(0o700)
    result = subprocess.run(["bash", str(script), "sites", "--no-restart"], env={**os.environ, "CHATGLANCE_BIN": str(binary)}, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ["refresh", "sites", "--no-restart"]
