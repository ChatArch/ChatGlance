"""Explicit account subscriptions: synthetic profiles, no real credentials."""
import json
from pathlib import Path
from types import ModuleType
import sys

import pytest
from click.testing import CliRunner
from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig, collection_settings
from chatglance import codex_collector as collector, codex_resets as resets
from chatglance.cli import main
from test_codex_resets import FakeClient, NOW

KEY = "CHATGLANCE_ACCOUNT_LIMITS_SUBSCRIPTIONS"
POLICY = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    for key in list(__import__("os").environ):
        if key.startswith("CHATGLANCE_ACCOUNT_LIMITS_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(resets.time, "time", lambda: NOW)


def entry(profile="reader", account="account-1", enabled=True):
    return {"crs_profile": profile, "account_id": account, "enabled": enabled}


def store(home):
    return EnvStore(get_paths(home).envs_dir)


def run_collect(tmp_path, **kwargs):
    return collector.collect_account_limits(
        output_path=tmp_path / "output" / "snapshot.json", home=tmp_path,
        no_public_reset=True, execute_resets=False, **kwargs
    )


def install_clients(monkeypatch, failing=()):
    calls, clients = [], []
    module = ModuleType("chatcrs.managed_codex")
    class Managed:
        @classmethod
        def from_profile(cls, crs_profile, *, account_id, **kwargs):
            assert kwargs["require_management_key"] is True
            calls.append((crs_profile, account_id))
            if account_id in failing:
                raise RuntimeError("password=SECRET_CANARY_DO_NOT_PRINT")
            client = FakeClient()
            client.identity = "https://relay.example#" + account_id
            client.token_service = "CRS"
            clients.append(client)
            return client
    module.CrsManagedCodexClient = Managed
    monkeypatch.setitem(sys.modules, "chatcrs.managed_codex", module)
    monkeypatch.setattr(resets.CodexClient, "from_profile", lambda *a, **kw: pytest.fail("local OAuth fallback"))
    return calls, clients


def test_four_accounts_use_three_explicit_profiles(monkeypatch, tmp_path):
    values = {"alpha": entry("shared", "id-a"), "beta": entry("shared", "id-b"),
              "gamma": entry("reader-c", "id-c"), "delta": entry("reader-d", "id-d")}
    monkeypatch.setenv(KEY, json.dumps(values))
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE", "poisoned")
    calls, clients = install_clients(monkeypatch)
    result = run_collect(tmp_path)
    assert calls == [(r["crs_profile"], r["account_id"]) for r in values.values()]
    assert result["refresh_status"]["ok_count"] == 4
    assert all(not r["auto_reset"]["policy"]["enabled"] for r in result["codex"])
    assert all(not c.posts for c in clients)


def test_partial_account_failure_does_not_hide_healthy_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY, json.dumps({"good": entry(), "bad": entry("other", "id-bad")}))
    install_clients(monkeypatch, failing={"id-bad"})
    result = run_collect(tmp_path)
    assert result["refresh_status"]["ok_count"] == 1
    assert result["refresh_status"]["failed_count"] == 1
    assert "SECRET_CANARY" not in json.dumps(result)


@pytest.mark.parametrize("raw", ["null", "[]", "not-json", '{"a":{"crs_profile":"p","account_id":"id","enabled":"false"}}',
    '{"a":{"crs_profile":"p","account_id":"id"},"a":{"crs_profile":"q","account_id":"id2"}}',
    json.dumps({"first": entry(), "last": entry("q", "bad/id")}),
    json.dumps({"first": entry(), "alias": entry()}),
    json.dumps({"first": entry(), "last": {**entry("q", "id-b"), "unknown": "SECRET_CANARY"}})])
def test_full_registry_rejected_before_any_io(monkeypatch, tmp_path, raw):
    monkeypatch.setenv(KEY, raw)
    calls, clients = install_clients(monkeypatch)
    public = []
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda *a: public.append(a))
    with pytest.raises(ValueError):
        collector.collect_account_limits(profiles="first", output_path=tmp_path/"never"/"out.json", home=tmp_path)
    assert not calls and not clients and not public
    assert not (tmp_path / "never").exists()


def test_empty_registry_is_authoritative(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY, "{}")
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_PROFILES", "old")
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE", "old-reader")
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS", '{"old":"old-id"}')
    calls, _ = install_clients(monkeypatch)
    result = run_collect(tmp_path)
    assert result["codex"] == [] and calls == []


def test_explicit_subset_cannot_bypass_disabled_subscription(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY, json.dumps({"paused": entry(enabled=False)}))
    calls, _ = install_clients(monkeypatch)
    with pytest.raises(ValueError):
        run_collect(tmp_path, profiles="paused")
    assert not calls


def test_cli_dry_run_and_first_write_migrate_legacy_without_policy_change(tmp_path):
    values = {"CHATGLANCE_ACCOUNT_LIMITS_PROFILES": "old", "CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE": "old-reader",
              "CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS": '{"old":"old-id"}',
              POLICY: '{"old":{"enabled":true,"threshold_percent":99}}', "CHATGLANCE_LOGIN_SECRET": "NEVER_RENDER_ME"}
    s = store(tmp_path)
    s.save_active(ChatGlanceConfig, values)
    before = s.load_active(ChatGlanceConfig)
    args = ["account-limits", "subscriptions", "add", "new", "--crs-profile", "new-reader", "--account-id", "new-id", "--json-output"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert s.load_active(ChatGlanceConfig) == before
    result = CliRunner().invoke(main, [*args, "--execute"])
    assert result.exit_code == 0, result.output
    after = s.load_active(ChatGlanceConfig)
    assert json.loads(after[KEY]) == {"old": entry("old-reader", "old-id"), "new": entry("new-reader", "new-id")}
    assert json.loads(after[POLICY])["old"] == json.loads(before[POLICY])["old"]
    assert json.loads(after[POLICY])["new"]["enabled"] is False
    assert after["CHATGLANCE_LOGIN_SECRET"] == before["CHATGLANCE_LOGIN_SECRET"]
    assert "NEVER_RENDER_ME" not in result.output


def test_named_profile_edit_does_not_activate_or_read_ambient_registry(monkeypatch, tmp_path):
    s = store(tmp_path)
    s.save_active(ChatGlanceConfig, {KEY: "{}"})
    s.save_profile(ChatGlanceConfig, "other", {KEY: "{}"})
    before = s.load_active(ChatGlanceConfig)
    monkeypatch.setenv(KEY, "poisoned-not-json")
    result = CliRunner().invoke(main, ["account-limits", "subscriptions", "--env-profile", "other", "add", "demo", "--crs-profile", "reader", "--account-id", "id-demo", "--execute"])
    assert result.exit_code == 0, result.output
    assert s.load_active(ChatGlanceConfig) == before
    assert "demo" in json.loads(s.load_profile(ChatGlanceConfig, "other")[KEY])


def test_remove_preserves_identity_and_blocks_rebinding(tmp_path):
    from chatglance.subscriptions import change_subscription, list_subscriptions
    s = store(tmp_path)
    s.save_active(ChatGlanceConfig, {KEY: json.dumps({"demo": entry()}), POLICY: '{"demo":{"enabled":true}}'})
    original_policy = s.load_active(ChatGlanceConfig)[POLICY]
    change_subscription("remove", "demo", home=tmp_path, execute=True)
    assert list_subscriptions(home=tmp_path)["subscriptions"] == []
    assert s.load_active(ChatGlanceConfig)[POLICY] == original_policy
    with pytest.raises(ValueError):
        change_subscription("add", "demo", crs_profile="different", account_id="different", home=tmp_path, execute=True)


def test_disabled_subscription_blocks_stale_control_before_reads(tmp_path):
    from chatglance.reset_control import ControlApp, ControlError
    store(tmp_path).save_active(ChatGlanceConfig, {KEY: json.dumps({"demo": entry(enabled=False)}), POLICY: '{"demo":{"enabled":true}}'})
    app = ControlApp(runtime_home=tmp_path/"runtime", public_origin="https://dashboard.example", home=tmp_path, authenticate=lambda cookie: False)
    with pytest.raises(ControlError):
        app.flags("demo")


def test_disable_enable_never_enables_automatic_use(tmp_path):
    from chatglance.subscriptions import change_subscription
    change_subscription("add", "demo", crs_profile="reader", account_id="id-demo", home=tmp_path, execute=True)
    change_subscription("disable", "demo", home=tmp_path, execute=True)
    assert not json.loads(store(tmp_path).load_active(ChatGlanceConfig)[KEY])["demo"]["enabled"]
    change_subscription("enable", "demo", home=tmp_path, execute=True)
    assert json.loads(store(tmp_path).load_active(ChatGlanceConfig)[KEY])["demo"]["enabled"]
    assert not json.loads(store(tmp_path).load_active(ChatGlanceConfig)[POLICY])["demo"]["enabled"]
