"""Authenticated controls change configuration, never redeem a real card."""

import importlib
import importlib.util
import json
import re
import threading
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request

import pytest
from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig

ORIGIN = "https://dashboard.example.invalid"
COOKIE = "session=synthetic-valid"
POLICIES = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"
EXECUTE = "CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE"


@pytest.fixture
def control(tmp_path, monkeypatch):
    assert importlib.util.find_spec("chatglance.reset_control"), (
        "control server missing"
    )
    api = importlib.import_module("chatglance.reset_control")
    monkeypatch.delenv(POLICIES, raising=False)
    monkeypatch.delenv(EXECUTE, raising=False)
    home = tmp_path / "home"
    runtime = tmp_path / "glance"
    (runtime / "data").mkdir(parents=True)
    (runtime / "data/account-limits.json").write_text(
        json.dumps(
            {"codex": [{"profile": "demo", "account_name": "Demo", "status": "ok"}]}
        )
    )
    store = EnvStore(get_paths(home).envs_dir)
    store.save_active(
        ChatGlanceConfig,
        {
            POLICIES: json.dumps(
                {
                    "demo": {
                        "enabled": True,
                        "threshold_percent": 95,
                        "min_remaining_seconds": 129600,
                    }
                }
            ),

            "CHATGLANCE_GITHUB_TOKEN": "synthetic-do-not-display",
        },
    )

    def diagnose(row, policy, **kw):
        return {
            "profile": row["profile"],
            "business_eligible": False,
            "automatic_allowed": False,
            "business_reason": "conditions_not_met",
            "observed_at": "2027-01-01T00:00:00Z",
            "controls": {
                "account_enabled": policy.enabled,
                "execute_enabled": kw["execute_enabled"],
            },
            "checks": [
                {
                    "key": "used_percent",
                    "label": "周额度",
                    "state": "fail",
                    "value": 71,
                    "rule": "至少95%",
                }
            ],
        }

    server = api.make_control_server(
        runtime_home=runtime,
        home=home,
        public_origin=ORIGIN,
        port=0,
        authenticate=lambda cookie: cookie == COOKIE,
        diagnose=diagnose,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, store, "http://127.0.0.1:" + str(server.server_port)
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive()


def request(base, path="/?profile=demo", cookie=COOKIE, values=None, origin=ORIGIN):
    headers = {}
    if cookie is not None:
        headers["Cookie"] = cookie
    data = None
    if values is not None:
        data = urllib.parse.urlencode(values).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        if origin is not None:
            headers["Origin"] = origin

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with opener.open(
            urllib.request.Request(base + path, headers=headers, data=data), timeout=3
        ) as response:
            return response.status, response.read().decode(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(), dict(error.headers)


def form(base, **updates):
    code, body, _ = request(base)
    assert code == 200
    values = {
        key: re.search(r'name="' + key + r'" value="([^"]+)"', body).group(1)
        for key in ("csrf", "revision")
    }
    values.update(profile="demo", scope="account", enabled="false")
    values.update(updates)
    return values


def test_anonymous_and_unprotected_upstream_fail_closed(control):
    server, store, base = control
    assert request(base, cookie=None)[0] == 401
    assert request(base, cookie="forged")[0] == 401
    server.control_app.authenticate = lambda _: True
    assert request(base)[0] == 401
    assert EXECUTE not in store.load_active(ChatGlanceConfig)


def test_authenticated_dialog_distinguishes_business_and_manual_state(control):
    _, _, base = control
    code, body, headers = request(base)
    assert (
        code == 200
        and "业务条件" in body
        and "自动用卡" in body
        and "总开关" not in body
    )
    assert "71%" in body and "至少95%" in body
    assert '<aside class="reset-forecast' in body
    assert "synthetic-do-not-display" not in body and COOKIE not in body
    assert headers.get("Cache-Control") == "no-store"
    assert "frame-ancestors 'self'" in headers.get("Content-Security-Policy", "")


def test_control_page_uses_saved_refresh_time_not_the_render_clock(control):
    server, _, base = control
    observed = "2027-01-15T08:00:00+00:00"
    (server.control_app.runtime_home / "data/account-limits.json").write_text(
        json.dumps({"codex": [{"profile": "demo", "status": "ok", "observed_at": observed}]})
    )
    captured = {}

    def diagnose(row, policy, **kwargs):
        captured["now"] = kwargs["now"]
        return {
            "profile": row["profile"], "business_eligible": False,
            "automatic_allowed": False, "business_reason": "conditions_not_met",
            "observed_at": observed,
            "controls": {"account_enabled": policy.enabled, "execute_enabled": kwargs["execute_enabled"]},
            "checks": [{"key": "used_percent", "label": "周额度", "state": "fail", "value": 71, "rule": "至少95%"}],
        }

    server.control_app.diagnose = diagnose
    code, body, _ = request(base)
    assert code == 200
    assert captured["now"] == datetime.fromisoformat(observed).replace(tzinfo=timezone.utc).timestamp()
    assert "上次计划检查" in body


@pytest.mark.parametrize("origin", [None, "https://evil.example.invalid"])
def test_cross_origin_write_is_denied(control, origin):
    _, store, base = control
    assert request(base, "/toggle", values=form(base), origin=origin)[0] == 403
    assert (
        json.loads(store.load_active(ChatGlanceConfig)[POLICIES])["demo"]["enabled"]
        is True
    )


def test_csrf_missing_wrong_and_replay_are_denied(control):
    _, _, base = control
    values = form(base)
    assert request(base, "/toggle", values={**values, "csrf": "wrong"})[0] == 403
    assert request(base, "/toggle", values=values)[0] == 303
    assert request(base, "/toggle", values=values)[0] == 403


def test_account_toggle_preserves_global_and_other_fields(control):
    _, store, base = control
    assert request(base, "/toggle", values=form(base))[0] == 303
    saved = store.load_active(ChatGlanceConfig)
    policy = json.loads(saved[POLICIES])["demo"]
    assert policy == {
        "enabled": False,
        "threshold_percent": 95,
        "min_remaining_seconds": 129600,
    }
    assert (
        EXECUTE not in saved
        and saved["CHATGLANCE_GITHUB_TOKEN"] == "synthetic-do-not-display"
    )
    assert (
        request(base, "/toggle", values=form(base, enabled="true", confirm="enable"))[0]
        == 303
    )
    assert (
        json.loads(store.load_active(ChatGlanceConfig)[POLICIES])["demo"]["enabled"]
        is True
    )
    assert EXECUTE not in store.load_active(ChatGlanceConfig)


def test_account_enable_requires_confirmation_and_global_actions_are_removed(control):
    _, store, base = control
    assert (
        request(base, "/toggle", values=form(base, enabled="true"))[0]
        == 400
    )
    assert EXECUTE not in store.load_active(ChatGlanceConfig)
    assert (
        request(
            base,
            "/toggle",
            values=form(base, scope="global", enabled="true", confirm="enable"),
        )[0]
        == 400
    )
    assert EXECUTE not in store.load_active(ChatGlanceConfig)


def test_stale_revision_does_not_overwrite_newer_config(control):
    _, store, base = control
    values = form(base)
    current = store.load_active(ChatGlanceConfig)
    policies = json.loads(current[POLICIES])
    policies["demo"]["threshold_percent"] = 97
    current[POLICIES] = json.dumps(policies)
    store.save_active(ChatGlanceConfig, current)
    assert request(base, "/toggle", values=values)[0] == 409
    assert (
        json.loads(store.load_active(ChatGlanceConfig)[POLICIES])["demo"]["enabled"]
        is True
    )


def test_invalid_profile_and_non_boolean_are_rejected(control):
    _, _, base = control
    assert request(base, "/?profile=unknown")[0] == 404
    assert request(base, "/toggle", values=form(base, enabled="maybe"))[0] == 400


def test_error_links_work_under_the_served_no_script_csp(control):
    _, _, base = control
    code, body, _ = request(base, cookie=None)
    assert code == 401 and "javascript:" not in body and "/account-limits" in body


def test_upstream_error_is_not_evidence_of_an_auth_challenge(tmp_path, monkeypatch):
    import io

    api = importlib.import_module("chatglance.reset_control")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/glance.yml").write_text(
        "server: {host: 127.0.0.1, port: 5678}\nauth: {users: {demo: {}}, secret-key: synthetic}\n"
    )

    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Upstream:
        def open(self, request, timeout):
            if not request.get_header("Cookie"):
                raise urllib.error.HTTPError(
                    request.full_url, 500, "unavailable", {}, io.BytesIO()
                )
            return Reply()

    monkeypatch.setattr(api, "build_opener", lambda *a: Upstream())
    app = api.ControlApp(
        runtime_home=tmp_path, public_origin=ORIGIN, home=tmp_path / "home"
    )
    assert app.authorized(COOKIE) is False


def test_live_switch_writes_change_unified_readiness_not_business_facts(control):
    server, _, base = control

    def ready_business(row, policy, **kw):
        return {
            'profile': row['profile'], 'business_eligible': True,
            'automatic_allowed': policy.enabled and kw['execute_enabled'],
            'controls': {'account_enabled': policy.enabled, 'execute_enabled': kw['execute_enabled']},
            'checks': [{'key': 'used_percent', 'label': '使用率', 'state': 'pass', 'value': 99, 'rule': '至少95%'}],
        }

    server.control_app.diagnose = ready_business
    assert 'data-automation="ready"' in request(base)[1]
    assert request(base, '/toggle', values=form(base, enabled='false'))[0] == 303
    page = request(base)[1]
    assert 'data-automation="paused"' in page
    assert 'data-check="account" data-state="fail"' in page
    assert 'data-check="used_percent" data-state="pass"' in page
    assert '业务条件已满足' in page
    assert request(base, '/toggle', values=form(base, enabled='true', confirm='enable'))[0] == 303
    assert 'data-automation="ready"' in request(base)[1]


def test_wildcard_bind_is_not_supported(tmp_path):
    assert importlib.util.find_spec("chatglance.reset_control"), (
        "control server missing"
    )
    api = importlib.import_module("chatglance.reset_control")
    with pytest.raises(api.ControlError):
        api.make_control_server(
            runtime_home=tmp_path, public_origin=ORIGIN, host="0.0.0.0", port=0
        )
