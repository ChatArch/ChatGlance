"""Deterministic regressions for the independent release review findings."""
from contextlib import contextmanager
import json
import pytest
from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig
from chatglance import subscriptions, codex_collector, refresh
from chatglance.reset_control import ControlApp, ControlError
from test_subscriptions import install_clients

KEY = "CHATGLANCE_ACCOUNT_LIMITS_SUBSCRIPTIONS"
POLICY = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    for key in list(__import__("os").environ):
        if key.startswith("CHATGLANCE_ACCOUNT_LIMITS_"):
            monkeypatch.delenv(key, raising=False)


def test_new_binding_cannot_inherit_an_orphan_enabled_policy(tmp_path):
    store = EnvStore(get_paths(tmp_path).envs_dir)
    store.save_active(ChatGlanceConfig, {KEY:"{}", POLICY:'{"new":{"enabled":true}}'})
    before = store.load_active(ChatGlanceConfig)
    with pytest.raises(ValueError):
        subscriptions.change_subscription("add", "new", crs_profile="new-reader", account_id="new-id", home=tmp_path, execute=True)
    assert store.load_active(ChatGlanceConfig) == before


def test_custom_runtime_collection_and_cli_use_same_configuration_owner(tmp_path, monkeypatch):
    store = EnvStore(get_paths(tmp_path).envs_dir)
    store.save_active(ChatGlanceConfig, {KEY:json.dumps({"demo":{"crs_profile":"reader","account_id":"id-demo","enabled":True}})})
    install_clients(monkeypatch)
    calls = []
    @contextmanager
    def owner(home=None):
        calls.append(get_paths(home).home_dir)
        yield
    monkeypatch.setattr(subscriptions, "subscription_lock", owner, raising=False)
    subscriptions.change_subscription("disable", "demo", execute=True, home=tmp_path)
    # Restore tracking as fixture setup, not a second API operation under test.
    values = store.load_active(ChatGlanceConfig)
    registry = json.loads(values[KEY]); registry["demo"]["enabled"] = True
    values[KEY] = json.dumps(registry); store.save_active(ChatGlanceConfig, values)
    custom, stage = tmp_path/"custom-runtime", tmp_path/"stage"
    stage.mkdir()
    result = refresh._collect_page("account-limits", custom, stage, profiles=None,
        actual_cli_tree=False, allow_offline_regression=True,
        collection=refresh.CollectionOptions(no_public_reset=True))
    assert result.data["refresh_status"]["ok_count"] == 1
    assert calls == [tmp_path, tmp_path]


def test_legacy_control_acquires_owner_and_rechecks_first_migration(tmp_path, monkeypatch):
    store = EnvStore(get_paths(tmp_path).envs_dir)
    store.save_active(ChatGlanceConfig, {POLICY:'{"demo":{"enabled":false}}'})
    app = ControlApp(runtime_home=tmp_path/"custom-runtime", public_origin="https://dashboard.example", home=tmp_path, authenticate=lambda c: bool(c))
    _, _, revision = app.flags("demo")
    calls = []
    @contextmanager
    def owner(home=None):
        calls.append(get_paths(home).home_dir)
        values = store.load_active(ChatGlanceConfig)
        values[KEY] = json.dumps({"demo":{"crs_profile":"reader","account_id":"id-demo","enabled":False}})
        store.save_active(ChatGlanceConfig, values)
        yield
    monkeypatch.setattr(subscriptions, "subscription_lock", owner, raising=False)
    with pytest.raises(ControlError):
        app.change({"profile":"demo","scope":"account","enabled":"true","confirm":"enable","csrf":app.token("cookie"),"revision":revision}, "cookie", app.public_origin)
    assert calls == [tmp_path]
    assert json.loads(store.load_active(ChatGlanceConfig)[POLICY])["demo"]["enabled"] is False


def test_busy_control_reports_no_action_not_invalid_request(tmp_path, monkeypatch):
    app = ControlApp(runtime_home=tmp_path/"custom-runtime", public_origin="https://dashboard.example", home=tmp_path, authenticate=lambda c: bool(c))
    @contextmanager
    def busy(home=None):
        raise refresh.RefreshError("owned by another operation")
        yield
    monkeypatch.setattr(subscriptions, "subscription_lock", busy)
    result = app.use_credit({"profile":"demo","confirm":"use-one-credit","csrf":app.token("cookie")}, "cookie", app.public_origin)
    assert result["state"] == "unmet" and result["reason"] == "busy"
