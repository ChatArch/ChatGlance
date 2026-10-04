"""Opt-in CRS server ownership; fixtures never access real OAuth/accounts."""
from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest

from chatglance import codex_collector as collector
from chatglance import codex_resets as resets
from chatglance.config import ChatGlanceConfig, collection_settings
from test_codex_resets import FakeClient, NOW

PROFILE_KEY = "CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE"
ACCOUNTS_KEY = "CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS"


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    for key in (PROFILE_KEY, ACCOUNTS_KEY, "CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", "{}")
    monkeypatch.setenv("CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL", "https://legacy.example/backend-api")
    monkeypatch.setattr(resets.time, "time", lambda: NOW)


def configure(monkeypatch, mapping=None):
    monkeypatch.setenv(PROFILE_KEY, "managed")
    monkeypatch.setenv(ACCOUNTS_KEY, json.dumps(mapping if mapping is not None else {"work": "account-01"}))


def install_managed_fixture(monkeypatch, *, client=None, error=None):
    calls = []
    client = client or FakeClient()
    module = ModuleType("chatcrs.managed_codex")

    class Managed:
        @classmethod
        def from_profile(cls, crs_profile="default", *, account_id, home=None, timeout=20, require_management_key=False):
            calls.append({"crs_profile": crs_profile, "account_id": account_id, "home": home, "timeout": timeout, "require_management_key": require_management_key})
            if error is not None:
                raise error
            client.identity = "https://relay.example#" + account_id
            client.token_service = "CRS"
            return client

    module.CrsManagedCodexClient = Managed
    monkeypatch.setitem(sys.modules, "chatcrs.managed_codex", module)
    local_calls = []

    def forbid_local(*args, **kwargs):
        local_calls.append((args, kwargs))
        raise AssertionError("local OAuth must not be reached")

    monkeypatch.setattr(resets.CodexClient, "from_profile", forbid_local)
    return client, calls, local_calls


def collect(tmp_path, **kwargs):
    options = dict(profiles="work", output_path=tmp_path / "snapshot.json", home=tmp_path,
                   no_public_reset=True, execute_resets=False)
    options.update(kwargs)
    return collector.collect_account_limits(**options)


def test_crs_settings_registered_and_resolved(monkeypatch, tmp_path):
    configure(monkeypatch)
    fields = ChatGlanceConfig.get_fields()
    assert fields[PROFILE_KEY].desc and fields[ACCOUNTS_KEY].desc
    settings = collection_settings(home=tmp_path)
    assert settings["crs_profile"] == "managed"
    assert json.loads(settings["crs_accounts"]) == {"work": "account-01"}


def test_selected_crs_mode_uses_only_remote_factory(monkeypatch, tmp_path):
    configure(monkeypatch)
    client, calls, local_calls = install_managed_fixture(monkeypatch)
    result = collect(tmp_path, timeout=11)
    assert result["refresh_status"]["status"] == "ok"
    assert result["codex"][0]["token_service"] == "CRS"
    assert calls == [{"crs_profile": "managed", "account_id": "account-01", "home": tmp_path, "timeout": 11, "require_management_key": True}]
    assert local_calls == []
    assert client.posts == []
    assert "legacy.example" not in json.dumps(result)


@pytest.mark.parametrize("value", ["not-json", "null", "[]", '{"work":null}', '{"work":4}', '{"work":""}',
                                   '{"other":"account-02"}', '{"work":"account-01","work":"account-02"}'])
def test_invalid_mapping_fails_before_provider_or_public_network(monkeypatch, tmp_path, value):
    configure(monkeypatch)
    monkeypatch.setenv(ACCOUNTS_KEY, value)
    _, calls, local_calls = install_managed_fixture(monkeypatch)
    public_calls = []
    def public_snapshot(*args):
        public_calls.append(args)
        return {"status": "ok", "events": [], "forecast": None}
    monkeypatch.setattr(collector, "fetch_public_codex_reset", public_snapshot)
    with pytest.raises(ValueError, match="CRS"):
        collect(tmp_path, no_public_reset=False)
    assert calls == local_calls == public_calls == []


@pytest.mark.parametrize("invalid", ["bad/id", "bad?query", "bad#fragment", "bad%2Fid", ":bad", "账号", "a" * 129, "bad id", "bad\ninside"])
@pytest.mark.parametrize("execute", [False, True])
def test_later_invalid_account_aborts_entire_batch_before_any_io(monkeypatch, tmp_path, invalid, execute):
    configure(monkeypatch, {"first": "account-01", "second": invalid})
    client, calls, local = install_managed_fixture(monkeypatch)
    public = []
    def forecast(*args):
        public.append(args)
        return {"status": "ok", "events": [], "forecast": None}
    monkeypatch.setattr(collector, "fetch_public_codex_reset", forecast)
    with pytest.raises(ValueError, match="CRS"):
        collect(tmp_path, profiles="first second", no_public_reset=False, execute_resets=execute,
                reset_policies='{"first":{"enabled":true},"second":{"enabled":true}}')
    assert calls == local == public == client.posts == []
    assert not (tmp_path / "snapshot.json").exists()


@pytest.mark.parametrize("account", ["A", "1", "a" * 128, "account:X_2.3-4"])
def test_valid_account_id_grammar_is_preserved_without_normalizing(monkeypatch, tmp_path, account):
    configure(monkeypatch, {"work": account})
    _, calls, _ = install_managed_fixture(monkeypatch)
    assert collect(tmp_path)["refresh_status"]["status"] == "ok"
    assert calls[0]["account_id"] == account


def test_manual_crs_collection_preserves_enabled_policy_without_consumption(monkeypatch, tmp_path):
    configure(monkeypatch)
    client, _, local = install_managed_fixture(monkeypatch)
    result = collect(tmp_path, reset_policies='{"work":{"enabled":true}}', execute_resets=False)
    row = result["codex"][0]
    assert row["status"] == "ok"
    assert row["auto_reset"]["policy"]["enabled"] is True
    assert row["auto_reset"]["status"] == "dry_run"
    assert not client.posts and not local


def test_crs_scheduled_policy_uses_existing_consume_and_readback_guards(monkeypatch, tmp_path):
    configure(monkeypatch)
    client, _, local = install_managed_fixture(monkeypatch)
    result = collect(tmp_path, reset_policies='{"work":{"enabled":true}}', execute_resets=True)
    row = result["codex"][0]
    assert len(client.posts) == 1
    assert row["auto_reset"]["status"] == "reset_verified"
    assert row["reset_credits"]["available_count"] == 1
    assert row["token_service"] == "CRS"
    assert not local


def test_remote_uncertainty_blocks_same_account_alias(monkeypatch, tmp_path):
    configure(monkeypatch, {"work": "account-01", "alias": "account-01"})
    client, _, local = install_managed_fixture(monkeypatch, client=FakeClient("timeout"))
    result = collect(tmp_path, profiles="work alias", reset_policies='{"work":{"enabled":true},"alias":{"enabled":true}}', execute_resets=True)
    assert len(client.posts) == 1
    assert [r["auto_reset"]["status"] for r in result["codex"]] == ["uncertain", "blocked_pending"]
    assert not local


def test_remote_auth_failure_is_safe_and_does_not_fallback(monkeypatch, tmp_path):
    configure(monkeypatch)
    _, calls, local_calls = install_managed_fixture(monkeypatch, error=RuntimeError("token=NEVER_RENDER"))
    result = collect(tmp_path, execute_resets=True, reset_policies='{"work":{"enabled":true}}')
    row = result["codex"][0]
    assert row["status"] == "error"
    assert row["token_service"] == "CRS"
    assert row["auto_reset"]["reason"] == "client_unavailable"
    assert "CRS" in row["error"] and "NEVER_RENDER" not in json.dumps(row)
    assert len(calls) == 1 and not local_calls


def test_missing_managed_adapter_is_truthful_not_local_fallback(monkeypatch, tmp_path):
    configure(monkeypatch)
    _, _, local_calls = install_managed_fixture(monkeypatch)
    monkeypatch.setitem(sys.modules, "chatcrs.managed_codex", ModuleType("chatcrs.managed_codex"))
    result = collect(tmp_path)
    row = result["codex"][0]
    assert row["token_service"] == "CRS" and row["status"] == "error"
    assert "CRS" in row["error"] and not local_calls


def test_unconfigured_crs_keeps_existing_codex_profile_behavior(monkeypatch, tmp_path):
    calls = []
    def local(profile, **kwargs):
        calls.append(profile)
        return FakeClient()
    monkeypatch.setattr(resets.CodexClient, "from_profile", local)
    result = collect(tmp_path)
    assert calls == ["work"]
    assert result["codex"][0]["token_service"] == "Codex"
    assert result["codex"][0]["status"] == "ok"


def test_crs_configuration_reads_typed_store_and_process_override(monkeypatch, tmp_path):
    from chatenv import EnvStore, get_paths
    store = EnvStore(get_paths(tmp_path).envs_dir)
    store.save_active(ChatGlanceConfig, {PROFILE_KEY: "stored-service", ACCOUNTS_KEY: '{"work":"account-01"}'})
    settings = collection_settings(home=tmp_path)
    assert settings["crs_profile"] == "stored-service"
    monkeypatch.setenv(PROFILE_KEY, "process-service")
    assert collection_settings(home=tmp_path)["crs_profile"] == "process-service"


def test_explicit_crs_source_without_factory_never_resolves_local_oauth(monkeypatch, tmp_path):
    _, _, local_calls = install_managed_fixture(monkeypatch)
    row = resets.scan_profile("work", token_service="CRS", home=tmp_path, now=NOW)
    assert row["status"] == "error" and row["token_service"] == "CRS"
    assert local_calls == []


def test_remote_failure_keeps_cached_display_but_never_uses_it_for_policy(monkeypatch, tmp_path):
    configure(monkeypatch)
    client, _, local_calls = install_managed_fixture(monkeypatch)
    first = collect(tmp_path)
    previous = tmp_path / "history.json"
    previous.write_text(json.dumps(first))
    install_managed_fixture(monkeypatch, error=RuntimeError("secret=NEVER_RENDER"))
    second = collect(tmp_path, history_path=previous, execute_resets=True,
                     reset_policies='{"work":{"enabled":true}}')
    row = second["codex"][0]
    assert row["status"] == "error" and row["using_last_known_values"] is True
    assert row["token_service"] == "CRS"
    assert row["windows"] == first["codex"][0]["windows"]
    assert row["auto_reset"]["status"] == "query_failed"
    assert row["auto_reset"]["last_action"] is None
    assert not client.posts and not local_calls
    assert "NEVER_RENDER" not in json.dumps(second)
