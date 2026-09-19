"""Native manual/scheduled entry: network providers faked, pipeline is real."""
import json
import os

from click.testing import CliRunner
import pytest
import yaml

from chatglance.cli import main
from chatglance import refresh as pipeline
from test_refresh import configure_fake_collection, runtime as runtime
from test_codex_resets import FakeClient, NOW


@pytest.mark.parametrize("scheduled", [False, True])
def test_explicit_scheduled_mode_preserves_account_policy(runtime, monkeypatch, scheduled):
    from chatglance import codex_resets
    client = FakeClient()
    calls = []
    def factory(profile, **kwargs):
        calls.append(kwargs)
        return client
    monkeypatch.setattr(codex_resets.CodexClient, "from_profile", factory)
    monkeypatch.setattr(codex_resets.time, "time", lambda: NOW)
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", '{"work":{"enabled":true}}')
    monkeypatch.setattr(pipeline, "validate_glance_config", lambda *a: None)
    result = CliRunner().invoke(main, ["refresh", "account-limits", "--profiles", "work", "--no-public-reset", "--runtime-home", str(runtime), "--no-restart", "--json-output", *(["--scheduled"] if scheduled else [])])
    assert result.exit_code == 0, result.output
    assert len(client.posts) == int(scheduled)
    assert json.loads(result.output)["reset_execution"] is scheduled
    snapshot = json.loads((runtime / "data/account-limits.json").read_text())
    assert snapshot["codex"][0]["auto_reset"]["policy"]["enabled"] is True
    assert snapshot["codex"][0]["auto_reset"]["status"] == ("reset_verified" if scheduled else "dry_run")
    assert calls[0]["refresh"] is True


def test_scheduled_defaults_preserve_trees_and_offline_policy(runtime, monkeypatch):
    calls, restarts = configure_fake_collection(monkeypatch, pipeline)
    result = pipeline.refresh_runtime(runtime, pages=["projects", "servers"], scheduled=True)
    assert result["ok"]
    assert len(restarts) == 1
    assert all(kw["actual_cli_tree"] and kw["allow_offline_regression"] for _, kw in calls)
    assert result["reset_execution"] is False  # no account page selected


def test_scheduled_overrides_and_environment_paths_are_explicit(runtime, monkeypatch):
    calls, _ = configure_fake_collection(monkeypatch, pipeline)
    monkeypatch.setenv("CHATGLANCE_RUNTIME_HOME", str(runtime))
    monkeypatch.setenv("CHATGLANCE_PROJECTS_OWNER", "ExampleOrg")
    monkeypatch.setenv("CHATGLANCE_SITES_CONFIG", str(runtime / "reviewed.yml"))
    result = CliRunner().invoke(main, ["refresh", "projects", "--scheduled", "--no-actual-cli-tree", "--no-allow-offline-regression", "--project-workers", "2", "--uvx-bin", "/opt/tools/uvx", "--cli-tree-timeout", "33", "--no-restart"])
    assert result.exit_code == 0, result.output
    kw = calls[0][1]
    assert kw["actual_cli_tree"] is False and kw["allow_offline_regression"] is False
    assert kw["collection"].projects_owner == "ExampleOrg"
    assert kw["collection"].sites_inventory == runtime / "reviewed.yml"
    assert kw["collection"].project_workers == 2
    assert kw["collection"].uvx_bin == "/opt/tools/uvx"
    assert kw["collection"].cli_tree_timeout == 33


def test_explicit_inputs_reach_python_collectors_without_shell(runtime, monkeypatch):
    from chatglance import project_inventory, sites, servers, codex_collector
    assert hasattr(pipeline, "CollectionOptions")
    opts = pipeline.CollectionOptions(projects_owner="ExampleOrg", project_workers=2, uvx_bin="custom-uvx", cli_tree_timeout=33, server_inventory=runtime/"servers.yml", sites_inventory=runtime/"sites.yml", gatus_db=runtime/"monitor.db", account_timeout=7, reset_timeout=9, no_public_reset=True, reset_base_url="https://relay.example/backend-api")
    stage = runtime / "stage"; stage.mkdir()
    (runtime/"monitor.db").touch()
    calls = {}
    def project(**kwargs):
        calls["project"] = kwargs
        return {"repositories": []}
    monkeypatch.setattr(project_inventory, "refresh_project_inventory", project)
    monkeypatch.setattr(sites, "load_sites_inventory", lambda path: calls.setdefault("sites", path) and {"sites": []})
    monkeypatch.setattr(sites, "apply_gatus_status", lambda data, db: calls.setdefault("db", db) and data)
    opts.server_inventory.write_text(yaml.safe_dump({
        "inventory": {"hosts": [{"alias": "unit-host", "hostname": "unit.example"}]},
        "collection": {"timeout": 5, "workers": 2},
    }))
    def collect_servers(aliases, **kwargs):
        calls["servers"] = (aliases, kwargs)
        return {"servers": [], "count": 0}
    monkeypatch.setattr(servers, "collect_server_status", collect_servers)
    monkeypatch.setattr(codex_collector, "collect_account_limits", lambda **kw: calls.setdefault("account", kw) and {"codex": [], "codex_reset": {"status": "skipped"}})
    def forbidden(*a, **kw):
        pytest.fail("native collector invoked subprocess/CLI")
    monkeypatch.setattr(pipeline.subprocess, "run", forbidden)
    for page in pipeline.PAGE_KEYS:
        pipeline._collect_page(page, runtime, stage, profiles=["work"], actual_cli_tree=True, allow_offline_regression=False, scheduled=False, collection=opts)
    assert calls["project"]["options"].owner == "ExampleOrg"
    assert calls["project"]["options"].workers == 2
    assert calls["project"]["options"].uvx_bin == "custom-uvx"
    assert calls["project"]["options"].cli_tree_timeout == 33
    assert calls["sites"] == opts.sites_inventory and calls["db"] == opts.gatus_db
    assert calls["servers"] == (["unit-host"], {
        "timeout": 5, "workers": 2,
        "host_overrides": {"unit-host": {"hostname": "unit.example"}},
    })
    assert calls["account"]["timeout"] == 7 and calls["account"]["reset_timeout"] == 9
    assert calls["account"]["no_public_reset"] is True
    assert calls["account"]["reset_base_url"] == opts.reset_base_url


def test_account_failure_does_not_change_proxy_environment_for_other_pages(runtime, monkeypatch):
    before = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, "http://unreachable.example:9")
        before[key] = os.environ[key]
    from chatglance import codex_resets
    def bad_auth(*a, **kw):
        raise RuntimeError("secret=NEVER-OUTPUT")
    monkeypatch.setattr(codex_resets.CodexClient, "from_profile", bad_auth)
    monkeypatch.setattr(pipeline, "validate_glance_config", lambda *a: None)
    def forbidden(*a, **kw):
        pytest.fail("unexpected proxy helper or CLI subprocess")
    monkeypatch.setattr(pipeline.subprocess, "run", forbidden)
    result = CliRunner().invoke(main, ["refresh", "account-limits", "sites", "--profiles", "work", "--no-public-reset", "--runtime-home", str(runtime), "--no-restart", "--json-output"])
    assert result.exit_code == 1, result.output
    assert [p["status"] for p in json.loads(result.output)["pages"]] == ["partial", "ok"]
    assert {k: os.environ[k] for k in before} == before
    assert "NEVER-OUTPUT" not in result.output + (runtime/"data/account-limits.json").read_text()


@pytest.mark.parametrize("flag", ["--project-workers", "--account-timeout", "--reset-timeout", "--cli-tree-timeout"])
def test_invalid_tunables_fail_before_side_effects(tmp_path, flag):
    result = CliRunner().invoke(main, ["refresh", "--runtime-home", str(tmp_path/"absent"), flag, "0"])
    assert result.exit_code == 2
    assert "not in the range" in result.output
    assert not (tmp_path/"absent").exists()
