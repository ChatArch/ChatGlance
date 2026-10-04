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
    assert "/_chatglance/reset-policy/pages/?page=projects" in str(private)
    assert "/_chatglance/reset-policy/pages/" not in str(public)
    assert "/_chatglance/reset-policy/pages/?page=servers" in str(build_servers_page({"servers": []}))


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
    data = {"generated_at": "old-observation", "count": 1, "servers": [{"alias": "fixture-host", "status": "online"}]}
    (root / "data/server-status.json").write_text(json.dumps(data))
    restarts = []
    monkeypatch.setattr('chatglance.runtime.validate_glance_config', lambda *args: None)
    monkeypatch.setattr(refresh, "_restart", lambda service: restarts.append(service))
    assert page_control.publish_notes(root, "fixture-host", "Operator <note>", "0")["revision"] == "1"
    assert restarts == ["chatarch-glance.service"]
    assert json.loads((root / "data/server-status.json").read_text()) == data
    published = (root / "data/server-page.yml").read_text()
    assert "old-observation" in published and "Operator &lt;note&gt;" in published
    assert "Operator <note>" not in published

    monkeypatch.setattr(servers, "collect_server_status", lambda *args, **kwargs: data)
    update = refresh._collect_page("servers", root, tmp_path, profiles=None, actual_cli_tree=False,
                                   allow_offline_regression=False, scheduled=False, collection=refresh.CollectionOptions())
    assert "Operator &lt;note&gt;" in str(update.page)
    assert update.data == data


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
        assert app.start(values, cookie, "https://example.invalid")["state"] == "running"
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
        assert calls == [{"pages": ["projects"], "scheduled": False, "actual_cli_tree": False, "runtime_home": runtime}]
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
    assert result == {"state": "busy"}
    assert not calls and app.status("servers")["state"] == "busy"


@pytest.mark.parametrize("kind,terminal", [("refresh", "success"), ("refresh", "partial"),
                                          ("refresh", "error"), ("note", "saved")])
def test_control_script_updates_status_and_refreshes_owner(tmp_path, kind, terminal):
    if not shutil.which("node"):
        pytest.skip("node is not available")
    script = """
const vm = require('node:vm');
const events = [];
const buttons = {};
const status = {set textContent(value) { events.push(value); }};
const form = {action: '/pages/' + KIND, values: KIND === 'refresh'
  ? {page: 'projects', csrf: 'synthetic'}
  : {alias: 'fixture-host', note: 'saved', csrf: 'synthetic'}};
const document = {getElementById(id) {
  if (id === 'refresh-button' || id === 'note-button') return {
    addEventListener(_name, callback) { buttons[id] = callback; }, disabled: false
  };
  if (id === 'refresh' || id === 'note') return form;
  if (id === 'refresh-status') return status;
  return null;
}};
const location = {origin: 'https://example.invalid', href: 'https://example.invalid/pages/',
  reload() { events.push('iframe-reload'); }};
const parent = {location: {href: 'https://example.invalid/' + (KIND === 'note' ? 'servers' : 'projects'),
  reload() { events.push('parent-reload'); }}};
const fetch = async url => ({ok: true, json: async () =>
  String(url).includes('status') ? {state: TERMINAL, observed_at: '2026-10-04T11:00:00Z'}
  : {state: KIND === 'note' ? 'saved' : 'running'}});
class FormData { constructor() { return Object.entries(form.values); } }
vm.runInNewContext(SOURCE, {document, location, window: {parent}, parent, fetch,
  FormData, URL, URLSearchParams, alert: message => events.push(message),
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
        assert events[0].startswith("正在刷新"), events
        if terminal in {"success", "partial"}:
            assert any("2026-10-04T11:00:00Z" in value for value in events)
    assert events[-1] == ("iframe-reload" if terminal == "error" else "parent-reload"), events
