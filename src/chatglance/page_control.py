"""Authenticated page refresh and private server annotations."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
from html import escape
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import time

import yaml


class PageControlError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _private_dir(root):
    path = Path(root) / "private"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise PageControlError("私有状态目录不可用", 503)
    except OSError as error:
        raise PageControlError("私有状态目录不可用", 503) from error
    path.chmod(0o700)
    return path


def _atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".page-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _notes_lock(root):
    with (_private_dir(root) / "server-notes.lock").open("a") as handle:
        handle_path = Path(handle.name)
        handle_path.chmod(0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _notes(root):
    path = _private_dir(root) / "server-notes.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PageControlError("备注数据不可用", 503)
    return data


def _aliases(root):
    from .servers import aliases_from_inventory_config, load_server_inventory_config
    config = load_server_inventory_config(Path(root) / "config/server-inventory.yml")
    return set(aliases_from_inventory_config(config))


def note_entry(root, alias):
    if alias not in _aliases(root):
        raise PageControlError("服务器不在当前配置中", 404)
    with _notes_lock(root):
        entry = _notes(root).get(alias, {})
    return {"note": entry.get("note", ""), "revision": str(entry.get("revision", 0))}


def save_note(root, alias, note, revision):
    if not isinstance(alias, str) or alias not in _aliases(root):
        raise PageControlError("服务器不在当前配置中", 404)
    if not isinstance(note, str) or len(note) > 2000 or len(note.encode("utf-8")) > 4096 or "\x00" in note:
        raise PageControlError("备注过长或含无效字符")
    with _notes_lock(root):
        notes = _notes(root)
        current = notes.get(alias, {})
        if revision != str(current.get("revision", 0)):
            raise PageControlError("备注已被其他编辑更新，请重新加载", 409)
        notes[alias] = {"note": note, "revision": int(revision) + 1}
        _atomic_json(_private_dir(root) / "server-notes.json", notes)
    return True


def overlay_notes(root, data):
    with _notes_lock(root):
        notes = _notes(root)
    result = deepcopy(data)
    for server in result.get("servers", []):
        if isinstance(server, dict):
            server["note"] = notes.get(server.get("alias"), {}).get("note", "")
    return result


def publish_notes(root, alias, note, revision):
    from .refresh import _json, _publish, _refresh_lock, _restart
    from .runtime import validate_glance_config
    from .servers import build_servers_page, load_server_inventory_config, page_options_from_inventory_config
    from .refresh import _replace_page

    root = Path(root)
    with _refresh_lock(root):
        config_path = root / "config/glance.yml"
        before = config_path.read_text(encoding="utf-8")
        config = yaml.safe_load(before)
        data = _json(root / "data/server-status.json")
        if not data or not isinstance(config, dict) or not isinstance(config.get("pages"), list):
            raise PageControlError("服务器快照不可用", 503)
        entry = note_entry(root, alias)
        if entry["revision"] != revision:
            raise PageControlError("备注已被其他编辑更新，请重新加载", 409)
        display = overlay_notes(root, data)
        for server in display.get("servers", []):
            if server.get("alias") == alias:
                server["note"] = note
        page = build_servers_page(display, **page_options_from_inventory_config(
            load_server_inventory_config(root / "config/server-inventory.yml")))
        _replace_page(config, page)
        (root / "staging").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / "staging") as directory:
            stage = Path(directory)
            candidate = stage / "glance.yml"
            text = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
            candidate.write_text(text, encoding="utf-8")
            candidate.chmod(0o600)
            validate_glance_config(root / "bin/glance", candidate)
            if config_path.read_text(encoding="utf-8") != before:
                raise PageControlError("配置已变化，请重试", 409)
            if not isinstance(note, str) or len(note) > 2000 or len(note.encode("utf-8")) > 4096 or "\x00" in note:
                raise PageControlError("备注过长或含无效字符")
            with _notes_lock(root):
                notes = _notes(root)
                if str(notes.get(alias, {}).get("revision", 0)) != revision:
                    raise PageControlError("备注已被其他编辑更新，请重新加载", 409)
                notes[alias] = {"note": note, "revision": int(revision) + 1}
                changed = _publish(root, stage, {
                    _private_dir(root) / "server-notes.json": json.dumps(notes, ensure_ascii=False) + "\n",
                    config_path: text,
                    root / "data/server-page.yml": yaml.safe_dump(page, allow_unicode=True, sort_keys=False),
                })
            if changed:
                _restart("chatarch-glance.service")
    return note_entry(root, alias)


class PageControlApp:
    def __init__(self, root, public_origin):
        self.root = Path(root)
        self.public_origin = public_origin
        self.lock = threading.RLock()
        self.tokens = {}
        self.jobs = {key: {"state": "idle"} for key in ("projects", "servers")}
        self.active = False
        self.status_path = _private_dir(root) / "page-refresh.json"
        if self.status_path.exists():
            try:
                saved = json.loads(self.status_path.read_text(encoding="utf-8"))
                for key in self.jobs:
                    if isinstance(saved.get(key), dict):
                        self.jobs[key] = saved[key]
                        if self.jobs[key].get("state") == "running":
                            run_id = self.jobs[key].get("run_id")
                            try:
                                from .refresh_history import show_refresh_run
                                record = show_refresh_run(self.root, run_id)
                                effective = record.get("effective_status")
                                if effective != "running":
                                    state = {
                                        "success": "success",
                                        "partial": "partial",
                                        "busy": "busy",
                                        "failed": "error",
                                        "interrupted": "interrupted",
                                    }.get(effective, "interrupted")
                                    page = next((row for row in record.get("pages", []) if row.get("page") == key), {})
                                    self.jobs[key] = {
                                        "state": state,
                                        "run_id": run_id,
                                        "observed_at": page.get("generated_at"),
                                        "finished_at": record.get("finished_at"),
                                    }
                            except Exception:
                                self.jobs[key]["state"] = "interrupted"
            except (OSError, ValueError, AttributeError):
                pass

    def _save(self):
        _atomic_json(self.status_path, self.jobs)

    def token(self, cookie):
        with self.lock:
            self.tokens = {key: value for key, value in self.tokens.items() if value[1] > time.monotonic()}
            if len(self.tokens) >= 128:
                self.tokens.pop(next(iter(self.tokens)))
            token = secrets.token_urlsafe(24)
            import hashlib
            self.tokens[token] = (hashlib.sha256(cookie.encode()).digest(), time.monotonic() + 600)
            return token

    def verify(self, values, cookie, origin):
        import hashlib
        import hmac
        if origin != self.public_origin:
            raise PageControlError("拒绝跨站操作", 403)
        with self.lock:
            entry = self.tokens.pop(values.get("csrf", ""), None)
        if not entry or entry[1] <= time.monotonic() or not hmac.compare_digest(entry[0], hashlib.sha256(cookie.encode()).digest()):
            raise PageControlError("操作凭据已失效，请刷新", 403)

    def status(self, page):
        if page not in self.jobs:
            raise PageControlError("页面不存在", 404)
        with self.lock:
            return dict(self.jobs[page])

    def start(self, values, cookie, origin):
        from .refresh import RefreshError, _refresh_lock
        from .refresh_history import RefreshHistoryError, new_run_id, record_rejected_run
        if set(values) != {"page", "action", "csrf"} or values.get("action") != "refresh":
            raise PageControlError("操作参数不完整")
        page = values["page"]
        if page not in self.jobs:
            raise PageControlError("页面不存在", 404)
        self.verify(values, cookie, origin)
        run_id = new_run_id()

        def rejected_busy():
            try:
                record_rejected_run(self.root, "browser", [page], error_type="busy", run_id=run_id)
            except RefreshHistoryError as error:
                raise PageControlError("刷新历史不可用", 503) from error
            return {"state": "busy", "run_id": run_id}

        with self.lock:
            if self.active:
                if self.jobs[page]["state"] != "running":
                    self.jobs[page] = {"state": "busy", "run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat()}
                    self._save()
                return rejected_busy()
            try:
                with _refresh_lock(self.root):
                    pass
            except RefreshError as error:
                if "another refresh is running" in str(error):
                    self.jobs[page] = {"state": "busy", "run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat()}
                    self._save()
                    return rejected_busy()
                raise
            self.active = True
            self.jobs[page] = {"state": "running", "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat()}
            try:
                self._save()
                threading.Thread(target=self._run, args=(page, run_id), daemon=True).start()
            except Exception:
                self.active = False
                self.jobs[page] = {"state": "error", "run_id": run_id}
                self._save()
                try:
                    from .refresh_history import record_rejected_run
                    record_rejected_run(self.root, "browser", [page], error_type="internal_error", run_id=run_id)
                except Exception:
                    pass
                raise
            return dict(self.jobs[page])

    def _run(self, page, run_id):
        from .refresh import RefreshError, refresh_runtime
        try:
            result = refresh_runtime(runtime_home=self.root, pages=[page], scheduled=False, actual_cli_tree=False,
                                     source="browser", run_id=run_id,
                                     allow_offline_regression=True if page == "servers" else None)
            row = result["pages"][0]
            state = "success" if result["ok"] else "partial" if row["status"] == "partial" else "error"
            status = {"state": state, "run_id": result.get("run_id", run_id), "observed_at": row.get("generated_at")}
        except RefreshError as error:
            status = {"state": "busy" if "another refresh is running" in str(error) else "error", "run_id": run_id}
        except Exception:
            status = {"state": "error", "run_id": run_id}
        with self.lock:
            status["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.jobs[page] = status
            self.active = False
            self._save()


def render_page(app, page, cookie, alias=None, feedback="", *, view="icon"):
    if view not in {"icon", "note"} or (view == "icon" and alias is not None) or (view == "note" and (page != "servers" or not alias)):
        raise PageControlError("页面不存在", 404)
    status = app.status(page)
    state = {"idle": "尚未手动刷新", "running": "正在刷新，请稍候", "success": "刷新成功", "partial": "部分成功", "error": "刷新失败，旧数据仍可用", "busy": "已有定时刷新在运行", "interrupted": "刷新中断，请重试"}.get(status["state"], "状态不可用")
    if view == "icon":
        label = f'{"项目" if page == "projects" else "服务器"}手动刷新：{feedback or state}'
        body = (f'<form id="refresh" method="post" action="refresh"><input type="hidden" name="csrf" value="{app.token(cookie)}">'
                f'<input type="hidden" name="page" value="{page}">'
                f'<button type="button" id="refresh-button" title="{escape(label, quote=True)}" aria-label="{escape(label, quote=True)}" {"disabled" if status["state"] == "running" else ""}>'
                '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 6.2M20 4v7h-7" stroke-linecap="round" stroke-linejoin="round"/></svg></button></form>'
                f'<span id="refresh-status" role="status" aria-live="polite" class="sr-only">{escape(feedback or state)}</span>')
        style = ('<style>*{box-sizing:border-box}html,body{width:28px;height:28px;margin:0;overflow:hidden;background:transparent}'
                 'form{margin:0}button{display:grid;place-items:center;width:28px;height:28px;padding:4px;border:0;border-radius:6px;'
                 'background:transparent;color:var(--color-text-highlight,#ddd);cursor:pointer}button:hover{background:rgba(128,128,128,.15)}'
                 'button:focus-visible{outline:2px solid var(--color-primary,#8bb9ff);outline-offset:-2px}'
                 'button:disabled{opacity:.6;cursor:wait}button:disabled svg{animation:spin 1s linear infinite}'
                 'svg{width:20px;height:20px}@keyframes spin{to{transform:rotate(360deg)}}'
                 '.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}</style>')
    else:
        entry = note_entry(app.root, alias)
        body = (f'<form id="note" method="post" action="note"><input type="hidden" name="csrf" value="{app.token(cookie)}">'
                f'<input type="hidden" name="alias" value="{escape(alias, quote=True)}"><input type="hidden" name="revision" value="{escape(entry["revision"], quote=True)}">'
                f'<textarea name="note" aria-label="{escape(alias, quote=True)} 的备注" maxlength="2000">{escape(entry["note"])}</textarea>'
                '<button type="button" id="note-button">保存备注（清空即删除）</button><button type="button" id="note-cancel">取消</button></form>'
                f'<p id="note-status" role="status" aria-live="polite">{escape(feedback)}</p>')
        style = ('<style>*{box-sizing:border-box}body{font:13px/1.4 system-ui,sans-serif;margin:0;padding:4px;'
                 'color:var(--color-text-highlight,#ddd);background:var(--color-widget-background,#1b1b20)}'
                 'form{display:flex;gap:8px;flex-wrap:wrap}textarea{width:100%;min-height:90px;max-height:115px;resize:vertical}'
                 'button,textarea{font:inherit;color:inherit;background:transparent;border:1px solid var(--color-separator,#666);border-radius:5px;padding:5px}'
                 'button{cursor:pointer}p{margin:6px 0;overflow-wrap:anywhere}</style>')
    return '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width">' + style + body + '<script src="./control.js"></script></html>'


CONTROL_JS = """(() => {
  try {
    if (window.parent !== window && parent.document && parent.getComputedStyle &&
        new URL(parent.location.href).origin === location.origin) {
      const host = parent.getComputedStyle(parent.document.documentElement);
      for (const key of ['--color-text-highlight', '--color-widget-background', '--color-separator', '--color-primary']) {
        const value = host.getPropertyValue(key);
        if (value) document.documentElement.style.setProperty(key, value);
      }
      // Transparent child canvases can still paint white in Chrome's light scheme.
      // Match the actual host canvas for the icon, without hard-coded theme colors.
      if (document.getElementById('refresh-button')) {
        const canvas = parent.getComputedStyle(parent.document.body).backgroundColor;
        document.documentElement.style.backgroundColor = canvas;
        document.body.style.backgroundColor = canvas;
      }
    }
  } catch (_) {}
  const refreshStatus = document.getElementById('refresh-status');
  const refreshButton = document.getElementById('refresh-button');
  const setRefreshStatus = message => {
    if (!refreshStatus) return;
    refreshStatus.textContent = message;
    refreshButton.title = refreshButton.getAttribute('aria-label').split('：')[0] + '：' + message;
    refreshButton.setAttribute('aria-label', refreshButton.title);
  };
  const reloadOwner = page => {
    try {
      if (window.parent !== window && parent.location &&
          new URL(parent.location.href).origin === location.origin &&
          new URL(parent.location.href).pathname.replace(/\\/$/, '') === '/' + page) {
        parent.location.reload();
        return;
      }
    } catch (_) {}
    location.reload();
  };
  const pollRefresh = page => {
    const poll = async () => {
      try {
        const response = await fetch('./status?page=' + encodeURIComponent(page), {credentials: 'same-origin'});
        if (!response.ok) throw Error('刷新状态不可用，请重新加载核对');
        const status = await response.json();
        if (status.state === 'running') { setTimeout(poll, 1500); return; }
        setRefreshStatus(({success: '刷新成功', partial: '部分成功', busy: '已有刷新任务，请稍后重试',
          error: '刷新失败，旧数据仍可用', interrupted: '刷新中断，请重试'})[status.state] || '状态不可用');
        if (status.state === 'success' || status.state === 'partial') reloadOwner(page);
        else refreshButton.disabled = false;
      } catch (error) { setRefreshStatus(error.message); refreshButton.disabled = false; }
    };
    setTimeout(poll, 1500);
  };
  if (refreshButton && refreshButton.disabled) {
    const page = document.querySelector('#refresh input[name="page"]').value;
    pollRefresh(page);
  }
  const cancel = document.getElementById('note-cancel');
  if (cancel) cancel.addEventListener('click', () => {
    try { window.frameElement.closest('[popover]').hidePopover(); } catch (_) {}
  });
  for (const [id, formId, action] of [
    ['refresh-button', 'refresh', 'refresh'], ['note-button', 'note', 'save']
  ]) {
    const button = document.getElementById(id);
    if (!button) continue;
    button.addEventListener('click', async () => {
      button.disabled = true;
      const form = document.getElementById(formId);
      const values = new URLSearchParams(new FormData(form));
      values.set('action', action);
      if (action === 'refresh') setRefreshStatus('正在刷新，请稍候…');
      try {
        const response = await fetch(form.action, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: values
        });
        const result = await response.json().catch(() => ({error: '操作未完成，请刷新核对'}));
        if (!response.ok) throw Error(result.error || '操作失败，请重新加载');
        if (result.state === 'running') {
          pollRefresh(values.get('page'));
        } else if (result.state === 'busy') {
          setRefreshStatus('已有刷新任务，请稍后重试');
          button.disabled = false;
        } else if (action === 'save' && result.state === 'saved') {
          document.getElementById('note-status').textContent = '备注已保存';
          reloadOwner('servers');
        } else {
          throw Error('操作状态不可用，请重新加载核对');
        }
      } catch (error) {
        if (action === 'refresh') setRefreshStatus(error.message);
        else document.getElementById('note-status').textContent = error.message;
        button.disabled = false;
      }
    });
  }
})();"""
