"""Manual redemption stays behind the authenticated, one-shot CRS control."""

import json
from io import BytesIO
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import pytest
from chatenv import EnvStore, get_paths

from chatglance.config import ChatGlanceConfig
from test_reset_control import COOKIE, ORIGIN
from chatglance.reset_control import ControlApp, ControlError


class SyntheticAccount:
    def __init__(self, name):
        self.identity = "synthetic-account-" + name
        self.used = 100
        self.seconds = 200000
        self.available = 1
        self.posts = []
        self.uncertain = False
        self.gets = 0

    def usage(self):
        self.gets += 1
        return {"rate_limit": {"primary_window": {
            "used_percent": self.used, "reset_at": time.time() + self.seconds,
            "limit_window_seconds": 604800,
        }}}

    def reset_credits(self):
        return {"available_count": self.available, "credits": [
            {"id": "card-1", "status": "available", "expires_at": "2030-01-01T00:00:00Z"}
        ] if self.available else []}

    def consume(self, request_id, *, credit_id=None, execute=False):
        assert execute and credit_id == "card-1" and self.available > 0
        self.posts.append(request_id)
        if self.uncertain:
            raise TimeoutError("private-key=DO_NOT_RENDER")
        self.available -= 1
        self.used = 0
        return {"code": "reset", "windows_reset": 1}


@pytest.fixture
def manual(tmp_path, monkeypatch):
    home = tmp_path / "home"
    runtime = tmp_path / "glance"
    (runtime / "data").mkdir(parents=True)
    (runtime / "data/account-limits.json").write_text('{"codex":[]}')
    accounts = {name: SyntheticAccount(name) for name in ("alpha", "beta")}
    store = EnvStore(get_paths(home).envs_dir)
    policies = {name: {"enabled": True, "threshold_percent": 100,
                       "min_remaining_seconds": 100000}
                for name in accounts}
    store.save_active(ChatGlanceConfig, {
        "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES": json.dumps(policies),
        "CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE": "synthetic",
        "CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS": json.dumps({name: name for name in accounts}),
    })
    from chatcrs.managed_codex import CrsManagedCodexClient
    monkeypatch.setattr(CrsManagedCodexClient, "from_profile", classmethod(
        lambda cls, profile, *, account_id, **kwargs: accounts[account_id]))
    app = ControlApp(runtime_home=runtime, home=home, public_origin=ORIGIN,
                     authenticate=lambda cookie: cookie == COOKIE)
    yield app, accounts, store, policies


def request(app, path="/?profile=alpha", cookie=COOKIE, values=None, origin=ORIGIN):
    if not app.authorized(cookie):
        return 401, json.dumps({"reason": "invalid_request"}), {}
    try:
        if values is not None:
            assert path == "/use-credit"
            return 200, json.dumps(app.use_credit(values, cookie, origin)), {"Content-Type": "application/json"}
        assert path.startswith("/?profile=")
        return 200, app.page(path.split("=", 1)[1], cookie), {}
    except ControlError as error:
        return error.status, json.dumps({"reason": "invalid_request"}), {}


def action(base, profile="alpha", **updates):
    status, body, _ = request(base, "/?profile=" + profile)
    assert status == 200
    csrf = re.search(r'name="csrf" value="([^"]+)"', body).group(1)
    return {"profile": profile, "csrf": csrf, "confirm": "use-one-credit", **updates}


def force_action(base, profile="alpha", **updates):
    return {**action(base, profile), "action": "force", "confirm": "force-one-credit", **updates}


def test_force_bypasses_business_policy_without_mutating_it(manual):
    app, accounts, store, policies = manual
    policies["alpha"].update(enabled=False, threshold_percent=100,
                             min_remaining_seconds=900000,
                             target_window_seconds=3600,
                             skip_if_forecast_24h_above=0)
    current = store.load_active(ChatGlanceConfig)
    current["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] = json.dumps(policies)
    store.save_active(ChatGlanceConfig, current)
    accounts["alpha"].used = 10
    accounts["alpha"].seconds = 60
    status, body, _ = request(app, "/use-credit", values=force_action(app))
    result = json.loads(body)
    assert status == 200 and result["reason"] == "reset_verified"
    assert result["available_count"] == 0
    assert result["windows"][0]["used_percent"] == 0
    assert len(accounts["alpha"].posts) == 1
    assert store.load_active(ChatGlanceConfig)["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] == json.dumps(policies)


def test_force_no_card_and_missing_confirmation_do_not_post(manual):
    app, accounts, _, _ = manual
    for values in (action(app, action="force"), force_action(app, confirm="use-one-credit"),
                   {key: val for key, val in force_action(app).items() if key != "confirm"}):
        assert request(app, "/use-credit", values=values)[0] == 400
    assert accounts["alpha"].gets == 0
    accounts["alpha"].available = 0
    code, body, _ = request(app, "/use-credit", values=force_action(app))
    assert code == 200 and json.loads(body)["reason"] == "no_credit"
    assert not accounts["alpha"].posts


def test_force_zero_usage_defers_to_upstream_no_reset(manual, monkeypatch):
    app, accounts, _, _ = manual
    account = accounts["alpha"]
    account.used = 0
    def no_reset(request_id, *, credit_id=None, execute=False):
        assert execute and credit_id == "card-1"
        account.posts.append(request_id)
        return {"code": "nothing_to_reset", "windows_reset": 0}
    monkeypatch.setattr(account, "consume", no_reset)
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "nothing_to_reset"
    assert result["available_count"] == 1 and result["windows"][0]["used_percent"] == 0
    assert len(account.posts) == 1


def test_force_auth_origin_replay_and_no_js(manual):
    app, accounts, _, _ = manual
    values = force_action(app)
    assert request(app, "/use-credit", values=values, cookie="")[0] == 401
    assert request(app, "/use-credit", values=values, origin="https://other.example")[0] == 403
    assert request(app, "/use-credit", values={**values, "csrf": "bad"})[0] == 403
    _, page, _ = request(app)
    form = re.search(r'<form id="manual-credit".*?</form>', page, re.S).group(0)
    native = dict(re.findall(r'<input[^>]+name="([^"]+)" value="([^"]*)"', form))
    assert 'id="force-credit" type="button" disabled' in form
    assert "强制消耗一张重置卡" in page
    assert request(app, "/use-credit", values=native)[0] == 400
    assert not accounts["alpha"].gets
    assert json.loads(request(app, "/use-credit", values=values)[1])["reason"] == "reset_verified"
    assert request(app, "/use-credit", values=values)[0] == 403
    assert len(accounts["alpha"].posts) == 1


def test_force_current_unknown_blocks_even_when_policy_is_disabled(manual):
    app, accounts, _, _ = manual
    accounts["alpha"].uncertain = True
    assert json.loads(request(app, "/use-credit", values=force_action(app))[1])["reason"] == "uncertain"
    accounts["alpha"].uncertain = False
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "blocked_pending"
    assert len(accounts["alpha"].posts) == 1


@pytest.mark.parametrize("ledger_status", ["pending", "unexpected_status"])
def test_force_old_pending_or_unknown_status_never_archives(manual, ledger_status):
    app, accounts, _, _ = manual
    from chatglance.codex_resets import _ledger_path
    accounts["alpha"].uncertain = True
    request(app, "/use-credit", values=force_action(app))
    path = _ledger_path(app.home, None)
    with sqlite3.connect(path) as db:
        old_id = db.execute("SELECT request_id FROM reset_ledger").fetchone()[0]
        db.execute("UPDATE reset_ledger SET status=?, fingerprint=?",
                   (ledger_status, json.dumps(["primary_window", time.time() - 5])))
    accounts["alpha"].uncertain = False
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "blocked_pending"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT request_id,status FROM reset_ledger").fetchone() == (old_id, ledger_status)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='reset_ledger_archive'").fetchone() is None
    assert len(accounts["alpha"].posts) == 1


def test_force_skips_resolved_cooldown_but_not_physical_credit(manual):
    app, accounts, _, _ = manual
    accounts["alpha"].available = 2
    request(app, "/use-credit", values=action(app))
    assert len(accounts["alpha"].posts) == 1
    accounts["alpha"].used = 30
    accounts["alpha"].available = 1
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "reset_verified"
    assert len(accounts["alpha"].posts) == 2


def test_force_no_reset_200_is_not_success(manual, monkeypatch):
    app, accounts, _, _ = manual
    account = accounts["alpha"]
    def no_reset(request_id, *, credit_id=None, execute=False):
        assert execute and credit_id == "card-1"
        account.posts.append(request_id)
        return {"code": "nothing_to_reset", "windows_reset": 0}
    monkeypatch.setattr(account, "consume", no_reset)
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "nothing_to_reset" and result["available_count"] == 1
    assert len(account.posts) == 1


def test_force_expired_unknown_archived_atomically(manual):
    app, accounts, _, _ = manual
    from chatglance.codex_resets import _ledger_path
    accounts["alpha"].uncertain = True
    request(app, "/use-credit", values=force_action(app))
    path = _ledger_path(app.home, None)
    with sqlite3.connect(path) as db:
        old_id = db.execute("SELECT request_id FROM reset_ledger").fetchone()[0]
        db.execute("UPDATE reset_ledger SET fingerprint=?", (json.dumps(["primary_window", time.time() - 5]),))
    accounts["alpha"].uncertain = False
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "reset_verified"
    with sqlite3.connect(path) as db:
        archived = json.loads(db.execute("SELECT record FROM reset_ledger_archive").fetchone()[0])
        current = db.execute("SELECT request_id,status FROM reset_ledger").fetchone()
    assert archived["request_id"] == old_id and archived["status"] == "uncertain"
    assert current[0] != old_id and current[1] == "reset_verified"
    assert len(accounts["alpha"].posts) == 2


def test_force_archive_failure_preserves_unknown_barrier(manual):
    app, accounts, _, _ = manual
    from chatglance.codex_resets import _ledger_path
    accounts["alpha"].uncertain = True
    request(app, "/use-credit", values=force_action(app))
    path = _ledger_path(app.home, None)
    with sqlite3.connect(path) as db:
        old_id = db.execute("SELECT request_id FROM reset_ledger").fetchone()[0]
        db.execute("UPDATE reset_ledger SET fingerprint=?", (json.dumps(["primary_window", time.time() - 5]),))
        db.execute("CREATE TABLE reset_ledger_archive (invalid TEXT)")
    accounts["alpha"].uncertain = False
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "state_error"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT request_id,status FROM reset_ledger").fetchone() == (old_id, "uncertain")
    assert len(accounts["alpha"].posts) == 1


def test_force_unknown_window_never_bypasses_unknown(manual):
    app, accounts, _, _ = manual
    accounts["alpha"].uncertain = True
    request(app, "/use-credit", values=force_action(app))
    accounts["alpha"].uncertain = False
    accounts["alpha"].seconds = -10
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] != "reset_verified"
    assert len(accounts["alpha"].posts) == 1


def test_force_storage_failure_never_posts(manual, monkeypatch):
    app, accounts, _, _ = manual
    from chatglance import codex_resets
    def fail(*args, **kwargs):
        raise OSError("private=DO_NOT_RENDER")
    monkeypatch.setattr(codex_resets, "_reserve", fail)
    result = json.loads(request(app, "/use-credit", values=force_action(app))[1])
    assert result["reason"] == "state_error"
    assert "DO_NOT_RENDER" not in str(result)
    assert not accounts["alpha"].posts


def test_force_concurrent_normal_share_pending_barrier(manual):
    app, accounts, _, _ = manual
    accounts["alpha"].uncertain = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda values: request(app, "/use-credit", values=values),
                                (action(app), force_action(app))))
    assert len(accounts["alpha"].posts) == 1
    assert {json.loads(body)["reason"] for _, body, _ in results} <= {"uncertain", "blocked_pending", "state_error"}


@pytest.mark.parametrize("profile", ["alpha", "beta"])
def test_manual_full_success_and_replay(manual, profile):
    base, accounts, _, _ = manual
    values = action(base, profile)
    status, body, headers = request(base, "/use-credit", values=values)
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert json.loads(body)["reason"] == "reset_verified"
    assert len(accounts[profile].posts) == 1
    status, body, _ = request(base, "/use-credit", values=values)
    assert status == 403 and json.loads(body)["reason"] == "invalid_request"
    assert len(accounts[profile].posts) == 1


@pytest.mark.parametrize("profile", ["alpha", "beta"])
def test_not_full_unavailable_card_and_remaining_time(manual, profile):
    base, accounts, _, _ = manual
    account = accounts[profile]
    for attribute, value, expected in [
        ("used", 99.99, "conditions_not_met"),
        ("available", 0, "no_credit"),
        ("seconds", 99999, "conditions_not_met"),
    ]:
        old = getattr(account, attribute)
        setattr(account, attribute, value)
        status, body, _ = request(base, "/use-credit", values=action(base, profile))
        assert status == 200 and json.loads(body)["reason"] == expected
        setattr(account, attribute, old)
    assert not account.posts


def test_count_without_exact_card_cannot_redeem(manual):
    base, accounts, _, _ = manual
    accounts["alpha"].reset_credits = lambda: {"available_count": 1, "credits": []}
    status, body, _ = request(base, "/use-credit", values=action(base))
    assert status == 200 and json.loads(body)["reason"] == "no_exact_credit"
    assert not accounts["alpha"].posts


def test_forecast_veto(manual, monkeypatch):
    base, accounts, store, policies = manual
    policies["alpha"]["skip_if_forecast_24h_above"] = 40
    current = store.load_active(ChatGlanceConfig)
    current["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] = json.dumps(policies)
    store.save_active(ChatGlanceConfig, current)
    import chatglance.codex_collector as collector
    from chatglance.codex_forecast import PUBLIC_RESET_SOURCE
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: {"forecast": {
        "source": PUBLIC_RESET_SOURCE, "horizon": "24h", "status": "ok",
        "source_updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "probability_24h_percent": 90,
    }})
    status, body, _ = request(base, "/use-credit", values=action(base))
    assert status == 200 and json.loads(body)["reason"] == "forecast_above_threshold"
    assert not accounts["alpha"].posts


def test_policy_is_reread_after_page_open(manual):
    base, accounts, store, policies = manual
    values = action(base)
    policies["alpha"]["min_remaining_seconds"] = 300000
    current = store.load_active(ChatGlanceConfig)
    current["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] = json.dumps(policies)
    store.save_active(ChatGlanceConfig, current)
    status, body, _ = request(base, "/use-credit", values=values)
    assert status == 200 and json.loads(body)["reason"] == "conditions_not_met"
    assert accounts["alpha"].gets == 1 and not accounts["alpha"].posts


def test_auth_csrf_confirmation_mapping_fail_before_crs(manual):
    base, accounts, store, _ = manual
    values = action(base)
    for payload, cookie, origin in [
        (values, None, ORIGIN),
        ({**values, "csrf": "bad"}, COOKIE, ORIGIN),
        ({key: val for key, val in values.items() if key != "csrf"}, COOKIE, ORIGIN),
        ({**values, "confirm": "no"}, COOKIE, ORIGIN),
        (values, COOKIE, "https://evil.invalid"),
        ({**values, "profile": "unknown"}, COOKIE, ORIGIN),
    ]:
        status, body, _ = request(base, "/use-credit", values=payload, cookie=cookie, origin=origin)
        assert status in (400, 401, 403, 404)
        assert json.loads(body)["reason"] == "invalid_request"
    current = store.load_active(ChatGlanceConfig)
    current["CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS"] = "{}"
    store.save_active(ChatGlanceConfig, current)
    status, body, _ = request(base, "/use-credit", values=action(base))
    assert status == 400 and json.loads(body)["reason"] == "invalid_request"
    assert not any(account.gets or account.posts for account in accounts.values())


def test_uncertain_and_concurrent_requests_share_ledger(manual):
    base, accounts, _, _ = manual
    accounts["alpha"].uncertain = True
    values = [action(base) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda val: request(base, "/use-credit", values=val), values))
    assert len(accounts["alpha"].posts) == 1
    assert "uncertain" in {json.loads(body)["reason"] for _, body, _ in results}
    assert {json.loads(body)["reason"] for _, body, _ in results} <= {"uncertain", "blocked_pending", "state_error"}
    assert "DO_NOT_RENDER" not in str(results)
    from chatglance.codex_resets import ResetPolicy, scan_profile
    scheduled = scan_profile("alpha", client=accounts["alpha"], home=base.home,
                             policy=ResetPolicy(enabled=True, threshold_percent=100), execute=True)
    assert scheduled["auto_reset"]["status"] == "blocked_pending"
    assert len(accounts["alpha"].posts) == 1


def test_disabled_policy_never_contacts_crs(manual):
    base, accounts, store, policies = manual
    policies["beta"]["enabled"] = False
    current = store.load_active(ChatGlanceConfig)
    current["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] = json.dumps(policies)
    store.save_active(ChatGlanceConfig, current)
    code, body, _ = request(base, "/use-credit", values=action(base, "beta"))
    assert code == 200 and json.loads(body)["reason"] == "disabled"
    assert not accounts["beta"].gets


def test_button_is_only_on_authenticated_control_and_never_posts_on_view(manual):
    base, accounts, _, _ = manual
    assert request(base, cookie=None)[0] == 401
    code, body, _ = request(base)
    assert code == 200 and 'action="use-credit"' in body
    assert 'confirm' in body and 'fetch(' in body
    assert not accounts["alpha"].posts


def test_native_form_without_javascript_cannot_use_credit(manual):
    app, accounts, _, _ = manual
    status, page, _ = request(app)
    assert status == 200
    form = re.search(r'<form id="manual-credit".*?</form>', page, re.S).group(0)
    values = dict(re.findall(r'<input[^>]+name="([^"]+)" value="([^"]*)"', form))
    status, body, _ = request(app, "/use-credit", values=values)
    assert status == 400 and json.loads(body)["reason"] == "invalid_request"
    assert "confirm" not in values and re.search(r'<button[^>]*disabled', form)
    script = re.findall(r'<script>(.*?)</script>', page, re.S)[1]
    assert script.index("form.addEventListener('submit'") < script.index("button.disabled = false")
    assert script.index("window.confirm(") < script.index("body.set('confirm', 'use-one-credit')")
    assert not accounts["alpha"].gets and not accounts["alpha"].posts


def test_http_post_route_checks_session_and_returns_redacted_json(manual, monkeypatch):
    app, accounts, _, _ = manual
    import chatglance.reset_control as module

    class NoSocketServer:
        def __init__(self, address, handler):
            self.handler = handler

    monkeypatch.setattr(module, "ThreadingHTTPServer", NoSocketServer)
    monkeypatch.setattr(module, "ControlApp", lambda **kwargs: app)
    server = module.make_control_server(runtime_home=app.runtime_home,
                                        home=app.home, public_origin=ORIGIN, port=0)

    def post(values, *, cookie=COOKIE, path="/use-credit"):
        handler = object.__new__(server.handler)
        handler.path = path
        handler.headers = {"Cookie": cookie, "Origin": ORIGIN,
                           "Content-Type": "application/x-www-form-urlencoded"}
        raw = urlencode(values).encode()
        handler.headers["Content-Length"] = str(len(raw))
        handler.rfile = BytesIO(raw)
        responses = []
        handler.respond = lambda status, body="", **kw: responses.append((status, body, kw))
        handler.do_POST()
        return responses[0]

    denied = post(action(app), cookie="")
    assert denied[0] == 401 and json.loads(denied[1])["reason"] == "invalid_request"
    bad = post({"profile": "alpha", "csrf": "bad", "confirm": "use-one-credit"})
    assert bad[0] == 403 and not accounts["alpha"].gets
    _, page, _ = request(app)
    native_form = re.search(r'<form id="manual-credit".*?</form>', page, re.S).group(0)
    native_values = dict(re.findall(r'<input[^>]+name="([^"]+)" value="([^"]*)"', native_form))
    unconfirmed = post(native_values)
    assert unconfirmed[0] == 400 and json.loads(unconfirmed[1])["reason"] == "invalid_request"
    assert not accounts["alpha"].gets and not accounts["alpha"].posts
    success = post(action(app))
    assert success[0] == 200 and success[2]["content_type"] == "application/json"
    assert json.loads(success[1])["reason"] == "reset_verified"
