"""Subscription mutations and consuming controls share one publication owner."""
from contextlib import contextmanager
import json

from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig
from chatglance.reset_control import ControlApp, ControlError
from chatglance import refresh
import pytest

KEY = "CHATGLANCE_ACCOUNT_LIMITS_SUBSCRIPTIONS"
POLICY = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"


def test_control_rechecks_tracking_after_acquiring_publication_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delenv(POLICY, raising=False)
    store = EnvStore(get_paths(tmp_path).envs_dir)
    row = {"crs_profile": "reader", "account_id": "id-demo", "enabled": True}
    store.save_active(ChatGlanceConfig, {KEY: json.dumps({"demo": row}), POLICY: '{"demo":{"enabled":true}}'})
    app = ControlApp(runtime_home=tmp_path/"glance", public_origin="https://dashboard.example", home=tmp_path, authenticate=lambda c: bool(c))
    calls = []
    @contextmanager
    def owner(root):
        calls.append(root)
        values = store.load_active(ChatGlanceConfig)
        values[KEY] = json.dumps({"demo": {**row, "enabled": False}})
        store.save_active(ChatGlanceConfig, values)
        yield root
    monkeypatch.setattr(refresh, "_refresh_lock", owner)
    # If the control reads before ownership it would call this old client path.
    monkeypatch.setattr(__import__("chatglance.codex_collector", fromlist=["x"]), "_managed_client_options", lambda *a: pytest.fail("stale subscription used"))
    with pytest.raises(ControlError):
        app.use_credit({"profile": "demo", "csrf": app.token("cookie"), "confirm": "use-one-credit"}, "cookie", app.public_origin)
    assert calls == [tmp_path/"glance"]


def test_registry_policy_toggle_reloads_under_same_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delenv(POLICY, raising=False)
    store = EnvStore(get_paths(tmp_path).envs_dir)
    row = {"crs_profile": "reader", "account_id": "id-demo", "enabled": True}
    store.save_active(ChatGlanceConfig, {KEY: json.dumps({"demo": row}), POLICY: '{"demo":{"enabled":false}}'})
    app = ControlApp(runtime_home=tmp_path/"glance", public_origin="https://dashboard.example", home=tmp_path, authenticate=lambda c: bool(c))
    _, _, revision = app.flags("demo")
    calls = []
    @contextmanager
    def owner(root):
        calls.append(root)
        yield root
    monkeypatch.setattr(refresh, "_refresh_lock", owner)
    app.change({"profile":"demo", "scope":"account", "enabled":"true", "csrf":app.token("cookie"), "revision":revision,"confirm":"enable"}, "cookie", app.public_origin)
    assert calls == [tmp_path/"glance"]
