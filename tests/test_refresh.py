import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from click.testing import CliRunner
import pytest
import yaml
from chatglance.cli import main


def test_manual_refresh_command_is_registered():
    assert "refresh" in main.commands


def test_manual_refresh_has_importable_python_api():
    assert importlib.util.find_spec("chatglance.refresh") is not None
    assert callable(importlib.import_module("chatglance.refresh").refresh_runtime)


def test_linux_restart_contract_stays_systemd(tmp_path, monkeypatch):
    module = importlib.import_module("chatglance.refresh")
    runtime = importlib.import_module("chatglance.runtime")
    calls = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(runtime.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))

    module._restart("chatarch-glance.service", tmp_path)

    assert calls[0][0] == ["systemctl", "--user", "restart", "chatarch-glance.service"]


def test_darwin_restart_uses_owned_plist_new_pid_and_http_readiness(tmp_path, monkeypatch):
    module = importlib.import_module("chatglance.refresh")
    runtime = importlib.import_module("chatglance.runtime")
    import plistlib
    root = tmp_path / "glance"
    (root / "config").mkdir(parents=True)
    (root / "config/glance.yml").write_text("server: {host: 192.168.1.7, port: 15678}\n")
    agents = tmp_path / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "chatarch-glance.service.plist"
    plist.write_bytes(plistlib.dumps({"Label": "chatarch-glance.service", "ProgramArguments": [
        sys.executable, "-m", "chatglance.cli", "runtime", "serve", "--runtime-home", str(root),
    ]}))
    calls = []
    states = ["state = running\n pid = 123\n", "state = running\n pid = 456\n", "state = running\n pid = 456\n"]
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(runtime.os, "getuid", lambda: plist.stat().st_uid)
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    def command(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=states.pop(0) if args[1] == "print" else "")
    monkeypatch.setattr(runtime.subprocess, "run", command)
    monkeypatch.setattr(runtime, "_web_ready", lambda host, port: (host, port) == ("192.168.1.7", 15678), raising=False)

    module._restart("chatarch-glance.service", root)

    assert calls == [
        ["/bin/launchctl", "print", f"gui/{runtime.os.getuid()}/chatarch-glance.service"],
        ["/bin/launchctl", "bootout", "--wait", f"gui/{runtime.os.getuid()}/chatarch-glance.service"],
        ["/bin/launchctl", "bootstrap", f"gui/{runtime.os.getuid()}", str(plist)],
        ["/bin/launchctl", "print", f"gui/{runtime.os.getuid()}/chatarch-glance.service"],
        ["/bin/launchctl", "print", f"gui/{runtime.os.getuid()}/chatarch-glance.service"],
    ]

    with pytest.raises(ValueError, match="Glance launchd label"):
        module._restart("com.example.unowned", root)
    assert len(calls) == 5


@pytest.fixture
def darwin_job(tmp_path, monkeypatch):
    import plistlib
    from chatglance import runtime
    root = tmp_path / "glance"
    (root / "config").mkdir(parents=True)
    (root / "config/glance.yml").write_text("server: {host: 192.168.1.7, port: 15678}\n")
    agents = tmp_path / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "chatarch-glance.service.plist"
    plist.write_bytes(plistlib.dumps({"Label": "chatarch-glance.service", "ProgramArguments": [
        sys.executable, "-m", "chatglance.cli", "runtime", "serve", "--runtime-home", str(root),
    ]}))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(runtime.os, "getuid", lambda: plist.stat().st_uid)
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(runtime.time, "sleep", lambda delay: None)
    return runtime, root, plist


def test_darwin_bootout_wait_is_bounded_and_never_bootstraps_while_stopping(darwin_job, monkeypatch):
    runtime, root, _ = darwin_job
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == "bootout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0, stdout="state = running\n pid = 123\n")
    monkeypatch.setattr(runtime.subprocess, "run", command)
    with pytest.raises(subprocess.TimeoutExpired):
        runtime.restart_user_service("chatarch-glance.service", root)
    assert [call[0][1] for call in calls] == ["print", "bootout"]
    assert calls[1][0] == ["/bin/launchctl", "bootout", "--wait", f"gui/{runtime.os.getuid()}/chatarch-glance.service"]
    assert 0 < calls[1][1]["timeout"] <= 10


def test_darwin_bootstrap_failure_retries_owned_plist_but_reports_original_failure(darwin_job, monkeypatch):
    runtime, root, plist = darwin_job
    calls = []
    snapshots = iter([123, 456, 456])
    def command(args, **kwargs):
        calls.append(args)
        if args[1] == "print":
            return subprocess.CompletedProcess(args, 0, stdout=f"state = running\n pid = {next(snapshots)}\n")
        if args[1] == "bootstrap" and sum(call[1] == "bootstrap" for call in calls) == 1:
            raise subprocess.CalledProcessError(5, args)
        return subprocess.CompletedProcess(args, 0, stdout="")
    monkeypatch.setattr(runtime.subprocess, "run", command)
    monkeypatch.setattr(runtime, "_web_ready", lambda host, port: True)
    with pytest.raises(RuntimeError, match="recovered") as error:
        runtime.restart_user_service("chatarch-glance.service", root)
    assert isinstance(error.value.__cause__, subprocess.CalledProcessError)
    assert [call for call in calls if call[1] == "bootstrap"] == [
        ["/bin/launchctl", "bootstrap", f"gui/{runtime.os.getuid()}", str(plist)],
    ] * 2


def test_darwin_readiness_failure_retries_once_and_requires_stable_pid(darwin_job, monkeypatch):
    runtime, root, plist = darwin_job
    calls = []
    snapshots = iter([123, 456, 789, 789])
    def command(args, **kwargs):
        calls.append(args)
        if args[1] == "print":
            return subprocess.CompletedProcess(args, 0, stdout=f"state = running\n pid = {next(snapshots, 789)}\n")
        return subprocess.CompletedProcess(args, 0, stdout="")
    monkeypatch.setattr(runtime.subprocess, "run", command)
    monkeypatch.setattr(runtime, "_web_ready", lambda host, port: sum(call[1] == "bootstrap" for call in calls) == 2)
    ticks = iter(range(100))
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="recovered"):
        runtime.restart_user_service("chatarch-glance.service", root)
    assert [call for call in calls if call[1] == "bootstrap"] == [
        ["/bin/launchctl", "bootstrap", f"gui/{runtime.os.getuid()}", str(plist)],
    ] * 2


def test_darwin_failed_recovery_preserves_original_bootstrap_error(darwin_job, monkeypatch):
    runtime, root, _ = darwin_job
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        if args[1] == "print":
            return subprocess.CompletedProcess(args, 0, stdout="state = running\n pid = 123\n")
        if args[1] == "bootstrap":
            raise subprocess.CalledProcessError(5, args)
        return subprocess.CompletedProcess(args, 0, stdout="")
    monkeypatch.setattr(runtime.subprocess, "run", command)
    with pytest.raises(RuntimeError, match="recovery failed") as error:
        runtime.restart_user_service("chatarch-glance.service", root)
    assert isinstance(error.value.__cause__, subprocess.CalledProcessError)
    assert sum(call[1] == "bootstrap" for call in calls) == 2


def test_darwin_restart_rejects_mismatched_plist_without_lifecycle(tmp_path, monkeypatch):
    import plistlib
    from chatglance import runtime
    root = tmp_path / "glance"
    (root / "config").mkdir(parents=True)
    (root / "config/glance.yml").write_text("server: {host: 127.0.0.1, port: 15678}\n")
    agents = tmp_path / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "chatarch-glance.service.plist").write_bytes(plistlib.dumps({
        "Label": "chatarch-glance.service", "ProgramArguments": ["/bin/echo", "unowned"],
    }))
    calls = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="LaunchAgent"):
        runtime.restart_user_service("chatarch-glance.service", root)
    assert calls == []


def test_darwin_restart_rejects_writable_or_unowned_plist_before_bootout(tmp_path, monkeypatch):
    import plistlib
    from chatglance import runtime
    root = tmp_path / "glance"
    root.mkdir()
    agents = tmp_path / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "chatarch-glance.service.plist"
    plist.write_bytes(plistlib.dumps({"Label": "chatarch-glance.service", "ProgramArguments": [
        sys.executable, "-m", "chatglance.cli", "runtime", "serve", "--runtime-home", str(root),
    ]}))
    plist.chmod(0o666)
    calls = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="LaunchAgent"):
        runtime.restart_user_service("chatarch-glance.service", root)
    assert calls == []


@pytest.mark.parametrize("status,expected", [(200, True), (303, True), (500, False)])
def test_web_readiness_probes_only_guest_home_without_redirects(monkeypatch, status, expected):
    from chatglance import runtime
    requests = []
    class Connection:
        def __init__(self, host, port, timeout):
            requests.append((host, port, timeout))
        def request(self, method, path):
            requests.append((method, path))
        def getresponse(self):
            return type("Response", (), {"status": status})()
        def close(self):
            requests.append("closed")
    monkeypatch.setattr(runtime.http.client, "HTTPConnection", Connection)
    assert runtime._web_ready("192.168.1.7", 15678) is expected
    assert requests == [("192.168.1.7", 15678, 1), ("GET", "/"), "closed"]


@pytest.mark.parametrize("next_state,ready", [
    ("state = running\n pid = 123\n", True),
    ("state = waiting\n pid = 456\n", True),
    ("state = running\n pid = 456\n", False),
])
def test_darwin_restart_does_not_accept_old_or_unready_process(tmp_path, monkeypatch, next_state, ready):
    import plistlib
    from chatglance import runtime
    root = tmp_path / "glance"
    (root / "config").mkdir(parents=True)
    (root / "config/glance.yml").write_text("server: {host: 127.0.0.1, port: 15678}\n")
    agents = tmp_path / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "chatarch-glance.service.plist").write_bytes(plistlib.dumps({
        "Label": "chatarch-glance.service", "ProgramArguments": [sys.executable, "-m", "chatglance.cli", "runtime", "serve", "--runtime-home", str(root)],
    }))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    snapshots = iter(["state = running\n pid = 123\n", next_state])
    monkeypatch.setattr(runtime.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=(next(snapshots, next_state) if args[1] == "print" else "")))
    monkeypatch.setattr(runtime, "_web_ready", lambda host, port: ready, raising=False)
    monkeypatch.setattr(runtime.time, "sleep", lambda delay: None, raising=False)
    ticks = iter(range(100))
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(ticks), raising=False)
    with pytest.raises((RuntimeError, TimeoutError), match="restart|readiness"):
        runtime.restart_user_service("chatarch-glance.service", root)


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
    monkeypatch.setattr(module, "_restart", lambda service, root: restarts.append(service))
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
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", '{"test":{"enabled":true}}')
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
