"""Optional browser smoke against synthetic loopback and mocked collectors."""
import json
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from chatglance import page_control, refresh
from chatglance.projects import build_projects_page
from chatglance.servers import build_servers_page


def test_refresh_and_notes_update_owning_page_in_browser(tmp_path, monkeypatch):
    pytest.importorskip("selenium")
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select, WebDriverWait
    from selenium.webdriver.support import expected_conditions as conditions

    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    root = tmp_path / "glance"
    for folder in ("config", "data", "bin"):
        (root / folder).mkdir(parents=True)
    (root / "config/server-inventory.yml").write_text('inventory:\n  aliases: [fixture-host]\n')
    (root / "bin/glance").write_text("synthetic validator")
    projects = {"generated_at": "old-observation", "repositories": []}
    servers = {"generated_at": "old-observation", "servers": [{"alias": "fixture-host", "status": "online"}]}
    (root / "data/chatarch-projects.json").write_text(json.dumps(projects))
    (root / "data/server-status.json").write_text(json.dumps(servers))
    (root / "config/glance.yml").write_text(yaml.safe_dump({"pages": [build_projects_page(projects), build_servers_page(servers)]}, allow_unicode=True))
    monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: None)
    monkeypatch.setattr(refresh, "_restart", lambda *args: None)
    monkeypatch.setattr("chatglance.runtime.validate_glance_config", lambda *args: None)
    monkeypatch.setattr(refresh, "_collect_page", lambda key, *args, **kwargs: refresh.PageUpdate(
        key, {"generated_at": "fresh-observation", "repositories": []},
        build_projects_page({"generated_at": "fresh-observation", "repositories": []})))
    app = page_control.PageControlApp(root, "https://example.invalid")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type="text/html; charset=utf-8"):
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path in ("/projects", "/servers"):
                data = json.loads((root / "data/chatarch-projects.json").read_text())
                if target.path == "/projects":
                    card = '<div id="snapshot">' + escape(data["generated_at"]) + '</div>'
                else:
                    notes = page_control.note_entry(root, "fixture-host")
                    card = '<div id="note">' + escape(notes["note"]) + '</div>'
                key = target.path[1:]
                self.respond(200, '<!doctype html><style>:root{--color-text-highlight:#aabbcc}</style>' +
                             card + f'<iframe title="control" style="height:250px;width:100%" src="/pages/?page={key}"></iframe>')
                return
            if self.headers.get("Cookie") != "session=synthetic":
                self.respond(401, "login required")
                return
            query = parse_qs(target.query)
            if target.path == "/pages/control.js":
                self.respond(200, page_control.CONTROL_JS, "text/javascript")
            elif target.path == "/pages/status":
                self.respond(200, json.dumps(app.status(query["page"][0])), "application/json")
            elif target.path == "/pages/":
                self.respond(200, page_control.render_page(app, query["page"][0],
                             "session=synthetic", query.get("alias", [None])[0]))
            else:
                self.respond(404, "not found")

        def do_POST(self):
            if self.headers.get("Cookie") != "session=synthetic":
                self.respond(401, "login required")
                return
            size = int(self.headers.get("Content-Length", "0"))
            values = {key: value[0] for key, value in parse_qs(self.rfile.read(size).decode(), keep_blank_values=True).items()}
            if self.path == "/pages/refresh":
                result = app.start(values, "session=synthetic", self.headers.get("Origin"))
            else:
                app.verify(values, "session=synthetic", self.headers.get("Origin"))
                result = {"state": "saved", **page_control.publish_notes(root, values["alias"], values["note"], values["revision"])}
            self.respond(200, json.dumps(result), "application/json")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("sandbox denies loopback socket; run smoke outside sandbox")
    base = f"http://127.0.0.1:{server.server_port}"
    app.public_origin = base
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-proxy-server")
        options.add_argument("--user-data-dir=" + str(tmp_path / "chrome-profile"))
        driver = webdriver.Chrome(options=options)
        driver.set_window_size(375, 780)
        driver.get(base + "/projects")
        driver.add_cookie({"name": "session", "value": "synthetic"})
        driver.refresh()
        driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe"))
        driver.find_element(By.ID, "refresh-button").click()
        WebDriverWait(driver, 2).until(lambda current: "正在刷新" in current.find_element(By.ID, "refresh-status").text)
        driver.switch_to.default_content()
        WebDriverWait(driver, 6).until(lambda current: current.find_element(By.ID, "snapshot").text == "fresh-observation")
        driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe"))
        assert "刷新成功" in driver.find_element(By.ID, "refresh-status").text
        assert "fresh-observation" in driver.find_element(By.ID, "refresh-status").text
        driver.switch_to.default_content()
        driver.get(base + "/servers")
        driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe"))
        Select(driver.find_element(By.NAME, "alias")).select_by_value("fixture-host")
        driver.find_element(By.XPATH, '//button[text()="查看备注"]').click()
        WebDriverWait(driver, 3).until(lambda current: current.find_element(By.NAME, "alias").get_attribute("value") == "fixture-host")
        driver.find_element(By.NAME, "note").send_keys("Browser note")
        assert driver.execute_script("return getComputedStyle(document.body).color") == "rgb(170, 187, 204)"
        assert driver.execute_script("return getComputedStyle(document.body).overflowY") == "auto"
        driver.find_element(By.ID, "note-button").click()
        WebDriverWait(driver, 3).until(conditions.alert_is_present())
        driver.switch_to.alert.accept()
        driver.switch_to.default_content()
        WebDriverWait(driver, 5).until(lambda current: current.find_element(By.ID, "note").text == "Browser note")
    finally:
        if driver is not None:
            driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
