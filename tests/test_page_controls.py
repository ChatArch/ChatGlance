"""Synthetic page-control contract, without network collectors or real credentials."""
import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from chatglance import page_control
from chatglance.projects import build_projects_page
from chatglance.servers import build_servers_page
from chatglance import refresh
from chatglance import servers
from chatglance.reset_control import ControlApp, ControlError
import yaml


def test_rendered_pages_have_private_control_and_canonical_slug():
    inventory = {"repositories": []}
    private = build_projects_page(inventory)
    public = build_projects_page(inventory, audience="public")
    assert private["slug"] == public["slug"] == "projects"
    overview = private["columns"][0]["widgets"]
    assert len(overview) == 1 and overview[0]["type"] == "bookmarks" and overview[0]["title"] == "概览"
    assert overview[0]["header-controls-url"] == "/_chatglance/reset-policy/pages/?page=projects&view=icon"
    assert "header-controls-url" not in public["columns"][0]["widgets"][0]
    assert "/_chatglance/reset-policy/pages/" not in str(public)
    servers_page = build_servers_page({"servers": []})
    assert len(servers_page["columns"][0]["widgets"]) == 1
    assert "view=icon" in servers_page["columns"][0]["widgets"][0]["source"]
    assert "服务器刷新与备注" not in str(servers_page)


def test_compact_page_views_validate_alias_and_do_not_write(tmp_path):
    root = tmp_path / "glance"
    (root / "config").mkdir(parents=True)
    (root / "config/server-inventory.yml").write_text('inventory:\n  aliases: ["a&b", other]\n')
    app = page_control.PageControlApp(root, "https://example.invalid")
    icon = page_control.render_page(app, "projects", "cookie", view="icon")
    assert icon.count('id="refresh-button"') == 1
    assert 'type="button"' in icon and 'role="status"' in icon and '<svg' in icon
    assert '<textarea' not in icon and '<select' not in icon and '<p ' not in icon
    with pytest.raises(page_control.PageControlError):
        page_control.render_page(app, "servers", "cookie", view="note", alias="missing")
    for page, view, alias in [("projects", "note", "a&b"), ("servers", "note", None),
                              ("servers", "icon", "a&b"), ("servers", "invalid", None)]:
        with pytest.raises(page_control.PageControlError):
            page_control.render_page(app, page, "cookie", alias=alias, view=view)
    page_control.save_note(root, "a&b", '<img src=x onerror="unsafe">', "0")
    note = page_control.render_page(app, "servers", "cookie", alias="a&b", view="note")
    assert 'value="a&amp;b"' in note and 'value="1"' in note
    assert '&lt;img src=x onerror=&quot;unsafe&quot;&gt;' in note and '<img src=x' not in note
    assert '<select' not in note and 'id="refresh-button"' not in note
    assert not (root / "data").exists()


def test_server_names_open_only_matching_notes():
    source = servers.render_servers_html({"servers": [
        {"alias": "alpha+1", "display_name": "Alpha"},
        {"alias": "beta&2", "display_name": "Beta"},
    ]})
    assert source.count('class="server-title" popovertarget=') == 2
    assert source.count('class="server-note-popover" popover') == 2
    assert source.count('view=note&amp;alias=alpha%2B1') == 1
    assert source.count('view=note&amp;alias=beta%262') == 1
    assert 'popovertarget="server-note-0"' in source and 'popovertarget="server-note-1"' in source
    assert '展开详情' in source and '<select' not in source


def test_notes_cas_and_overlay(tmp_path):
    root = tmp_path / "glance"
    (root / "config").mkdir(parents=True)
    (root / "config/server-inventory.yml").write_text('inventory:\n  aliases: [fixture-host]\n')
    assert page_control.save_note(root, "fixture-host", '<b>安全</b>', "0")
    with pytest.raises(page_control.PageControlError):
        page_control.save_note(root, "fixture-host", "lost edit", "0")
    with pytest.raises(page_control.PageControlError):
        page_control.save_note(root, "unconfigured", "invalid", "0")
    data = {"generated_at": "observed", "servers": [{"alias": "fixture-host"}]}
    overlay = page_control.overlay_notes(root, data)
    assert overlay["generated_at"] == "observed"
    assert overlay["servers"][0]["note"] == '<b>安全</b>'
    assert '&lt;b&gt;安全&lt;/b&gt;' in str(build_servers_page(overlay))
    assert '<b>安全</b>' not in str(build_servers_page(overlay))
    assert (root / "private/server-notes.json").stat().st_mode & 0o777 == 0o600
    assert page_control.note_entry(root, "fixture-host")["revision"] == "1"
    page_control.save_note(root, "fixture-host", "", "1")
    assert page_control.note_entry(root, "fixture-host") == {"note": "", "revision": "2"}


def test_note_save_publishes_existing_snapshot_without_collection(tmp_path, monkeypatch):
    root = tmp_path / "glance"
    for folder in ("config", "data", "bin"):
        (root / folder).mkdir(parents=True)
    (root / "config/server-inventory.yml").write_text('inventory:\n  aliases: [fixture-host]\n')
    (root / "bin/glance").write_text("synthetic")
    config = root / "config/glance.yml"
    config.write_text(yaml.safe_dump({"pages": [build_servers_page({"servers": []})]}))
    observed = "2026-10-05T08:00:00+00:00"
    data = {"generated_at": observed, "count": 1, "servers": [{"alias": "fixture-host", "status": "online"}]}
    (root / "data/server-status.json").write_text(json.dumps(data))
    restarts = []
    monkeypatch.setattr('chatglance.runtime.validate_glance_config', lambda *args: None)
    monkeypatch.setattr(refresh, "_restart", lambda service: restarts.append(service))
    assert page_control.publish_notes(root, "fixture-host", "Operator <note>", "0")["revision"] == "1"
    assert restarts == ["chatarch-glance.service"]
    assert json.loads((root / "data/server-status.json").read_text()) == data
    published = (root / "data/server-page.yml").read_text()
    assert observed in published and "Operator &lt;note&gt;" in published
    assert "Operator <note>" not in published

    monkeypatch.setattr(servers, "collect_server_status", lambda *args, **kwargs: data)
    monkeypatch.setattr(servers, "ssh_target", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic unresolved alias")))
    update = refresh._collect_page("servers", root, tmp_path, profiles=None, actual_cli_tree=False,
                                   allow_offline_regression=False, scheduled=False, collection=refresh.CollectionOptions())
    assert "Operator &lt;note&gt;" in str(update.page)
    assert data["servers"][0] == {"alias": "fixture-host", "status": "online"}
    assert update.data["servers"][0]["data_state"] == "fresh"
    assert update.data["servers"][0]["last_attempt_at"] == observed


def test_note_validation_failure_does_not_save_note(tmp_path, monkeypatch):
    root = tmp_path / "glance"
    for folder in ("config", "data", "bin"):
        (root / folder).mkdir(parents=True)
    (root / "config/server-inventory.yml").write_text('inventory:\n  aliases: [fixture-host]\n')
    (root / "config/glance.yml").write_text(yaml.safe_dump({"pages": [build_servers_page({"servers": []})]}))
    (root / "bin/glance").write_text("synthetic")
    (root / "data/server-status.json").write_text(json.dumps({"servers": [{"alias": "fixture-host"}]}))

    def fail_validation(*args):
        raise ValueError("synthetic invalid candidate")

    monkeypatch.setattr('chatglance.runtime.validate_glance_config', fail_validation)
    with pytest.raises(ValueError, match="synthetic invalid candidate"):
        page_control.publish_notes(root, "fixture-host", "draft", "0")
    assert page_control.note_entry(root, "fixture-host") == {"note": "", "revision": "0"}


def test_note_publication_failure_keeps_old_note_revision(tmp_path, monkeypatch):
    root = tmp_path / "glance"
    for folder in ("config", "data", "bin"):
        (root / folder).mkdir(parents=True)
    (root / "config/server-inventory.yml").write_text('inventory:\n  aliases: [fixture-host]\n')
    (root / "config/glance.yml").write_text(yaml.safe_dump({"pages": [build_servers_page({"servers": []})]}))
    (root / "bin/glance").write_text("synthetic")
    (root / "data/server-status.json").write_text(json.dumps({"servers": [{"alias": "fixture-host"}]}))
    monkeypatch.setattr('chatglance.runtime.validate_glance_config', lambda *args: None)
    def fail_publication(*args):
        raise OSError("synthetic publication failure")
    monkeypatch.setattr(refresh, "_publish", fail_publication)
    with pytest.raises(OSError, match="publication failure"):
        page_control.publish_notes(root, "fixture-host", "draft", "0")
    assert page_control.note_entry(root, "fixture-host") == {"note": "", "revision": "0"}


def test_stale_running_status_is_not_reported_as_success(tmp_path):
    root = tmp_path / "glance"
    root.mkdir()
    app = page_control.PageControlApp(root, "https://example.invalid")
    app.jobs["projects"] = {"state": "running", "started_at": "synthetic"}
    app._save()
    assert page_control.PageControlApp(root, "https://example.invalid").status("projects")["state"] == "interrupted"


def test_token_is_single_use_cookie_bound_and_origin_checked(tmp_path):
    root = tmp_path / "glance"
    root.mkdir()
    app = page_control.PageControlApp(root, "https://example.invalid")
    values = {"csrf": app.token("session=one")}
    with pytest.raises(page_control.PageControlError):
        app.verify(values, "session=one", "https://evil.invalid")
    with pytest.raises(page_control.PageControlError):
        app.verify(values, "session=two", "https://example.invalid")
    with pytest.raises(page_control.PageControlError):
        app.verify(values, "session=one", "https://example.invalid")
    values = {"csrf": app.token("session=one")}
    app.verify(values, "session=one", "https://example.invalid")
    with pytest.raises(page_control.PageControlError):
        app.verify(values, "session=one", "https://example.invalid")


def test_reset_token_pruning_cannot_resurrect_consumed_token(tmp_path):
    app = ControlApp(runtime_home=tmp_path, home=tmp_path, public_origin="https://example.invalid",
                     authenticate=lambda cookie: cookie == "session=synthetic")
    original = app.token("session=synthetic")
    snapshot_taken, resume = threading.Event(), threading.Event()
    consumer_started, consumed = threading.Event(), threading.Event()

    class PausedTokens(dict):
        def items(self):
            snapshot = list(super().items())
            snapshot_taken.set()
            assert resume.wait(3)
            return snapshot

    app.tokens = PausedTokens(app.tokens)

    def consume():
        consumer_started.set()
        app.consume_token("session=synthetic", original)
        consumed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pruning = pool.submit(app.token, "session=synthetic")
        try:
            assert snapshot_taken.wait(2)
            consuming = pool.submit(consume)
            assert consumer_started.wait(2)
            assert not consumed.wait(.05)
        finally:
            resume.set()
        pruning.result(timeout=3)
        consuming.result(timeout=3)
    with pytest.raises(ControlError, match="失效"):
        app.consume_token("session=synthetic", original)


def test_page_refresh_is_explicit_and_single_flight(tmp_path, monkeypatch):
    runtime = tmp_path / "glance"
    (runtime / "config").mkdir(parents=True)
    (runtime / "config/server-inventory.yml").write_text('inventory:\n  aliases: [fixture-host]\n')
    started, release = threading.Event(), threading.Event()
    calls = []

    def fake_refresh(*args, **kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(3)
        return {"ok": True, "pages": [{"status": "ok", "generated_at": "observed"}]}

    monkeypatch.setattr('chatglance.refresh.refresh_runtime', fake_refresh)
    app = page_control.PageControlApp(runtime, "https://example.invalid")
    cookie = "session=valid"
    page = page_control.render_page(app, "projects", cookie)
    assert not calls
    assert 'type="button"' in page
    with pytest.raises(page_control.PageControlError):
        app.start({"page": "projects", "action": "refresh", "csrf": app.token(cookie)}, cookie, "https://evil.invalid")
    try:
        values = {"page": "projects", "action": "refresh", "csrf": app.token(cookie)}
        accepted = app.start(values, cookie, "https://example.invalid")
        assert accepted["state"] == "running" and accepted["run_id"]
        assert started.wait(2)
        assert app.status("projects")["state"] == "running"
        assert app.start({**values, "csrf": app.token(cookie)}, cookie, "https://example.invalid")["state"] == "busy"
        release.set()
        for _ in range(100):
            if app.status("projects")["state"] != "running":
                break
            threading.Event().wait(.01)
        assert app.status("projects")["state"] == "success"
        assert app.status("projects")["observed_at"] == "observed"
        assert app.status("projects")["run_id"] == accepted["run_id"]
        assert calls == [{"pages": ["projects"], "scheduled": False, "actual_cli_tree": False,
                          "runtime_home": runtime, "source": "browser", "run_id": accepted["run_id"],
                          "allow_offline_regression": None}]
    finally:
        release.set()


def test_scheduler_lock_reports_busy_without_queuing(tmp_path, monkeypatch):
    root = tmp_path / "glance"
    root.mkdir()
    app = page_control.PageControlApp(root, "https://example.invalid")
    calls = []
    monkeypatch.setattr(refresh, "refresh_runtime", lambda *args, **kwargs: calls.append(kwargs))
    with refresh._refresh_lock(root):
        result = app.start({"page": "servers", "action": "refresh", "csrf": app.token("cookie")},
                           "cookie", "https://example.invalid")
    assert result["state"] == "busy" and result["run_id"]
    status = app.status("servers")
    assert not calls and {key: status[key] for key in ("state", "run_id", "finished_at")} == {
        "state": "busy", "run_id": result["run_id"], "finished_at": status["finished_at"]
    }
    assert status["last_success_at"] is None


@pytest.mark.parametrize("kind,terminal", [("refresh", "success"), ("refresh", "partial"),
                                          ("refresh", "error"), ("refresh", "busy"),
                                          ("refresh", "immediate-busy"), ("note", "saved")])
def test_control_script_updates_status_and_refreshes_owner(tmp_path, kind, terminal):
    if not shutil.which("node"):
        pytest.skip("node is not available")
    script = """
const vm = require('node:vm');
const events = [];
const buttons = {};
const status = {dataset: {}, setAttribute() {}, set textContent(value) { events.push(value); }};
const refreshButton = {disabled: false, getAttribute() { return '项目手动刷新：空闲'; },
  setAttribute(_name, value) { events.push(value); },
  addEventListener(_name, callback) { buttons['refresh-button'] = callback; }};
const form = {dataset: {state: 'idle',runId:'',lastSuccessAt:'',lastObservedAt:''}, action: '/pages/' + KIND, values: KIND === 'refresh'
  ? {page: 'projects', csrf: 'synthetic'}
  : {alias: 'fixture-host', note: 'saved', csrf: 'synthetic'}};
const document = {getElementById(id) {
  if (id === 'refresh-button') return KIND === 'refresh' ? refreshButton : null;
  if (id === 'note-button') return {
    addEventListener(_name, callback) { buttons[id] = callback; }, disabled: false
  };
  if (id === 'refresh' || id === 'note') return form;
  if (id === 'refresh-status' || id === 'note-status') return status;
  return null;
}};
const location = {origin: 'https://example.invalid', href: 'https://example.invalid/pages/',
  reload() { events.push('iframe-reload'); }};
const parent = {location: {href: 'https://example.invalid/' + (KIND === 'note' ? 'servers' : 'projects'),
  reload() { events.push('parent-reload'); }}};
const fetch = async url => ({ok: true, json: async () =>
  String(url).includes('status') ? {state: TERMINAL, run_id:'this-run', observed_at: '2026-10-04T11:00:00Z'}
  : {run_id:'this-run',state: KIND === 'note' ? 'saved' : TERMINAL === 'immediate-busy' ? 'busy' : 'running'}});
class FormData { constructor() { return Object.entries(form.values); } }
vm.runInNewContext(SOURCE, {document, location, window: {parent}, parent, fetch,
  FormData, URL, URLSearchParams, AbortController, clearTimeout:()=>{},
  setTimeout: callback => Promise.resolve().then(callback)});
buttons[KIND === 'note' ? 'note-button' : 'refresh-button']();
setTimeout(() => console.log(JSON.stringify(events)), 50);
"""
    script = (script.replace('KIND', json.dumps(kind)).replace('TERMINAL', json.dumps(terminal))
              .replace('SOURCE', json.dumps(page_control.CONTROL_JS)))
    env = {**os.environ, "CHATARCH_HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    result = subprocess.run(["node", "-e", script], env=env, capture_output=True, text=True, timeout=4)
    assert result.returncode == 0, result.stderr
    events = json.loads(result.stdout)
    if kind == "refresh":
        assert any(value.startswith("正在刷新") for value in events), events
        if terminal in {"error", "busy", "immediate-busy"}:
            assert any(("刷新失败" if terminal == "error" else "已有刷新任务") in value for value in events)
        else:
            assert any("成功" in value for value in events)
    assert ("parent-reload" in events) == (terminal not in {"error", "busy", "immediate-busy"})
    assert "iframe-reload" not in events
