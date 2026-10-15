import json
import os
import stat
import subprocess
from pathlib import Path

from click.testing import CliRunner
import pytest
import yaml

from chatglance.cli import main
from chatglance.glance_config import replace_projects_page
from chatglance.runtime import build_maintained_config
from chatglance.refresh import _replace_page
from chatglance.projects import build_projects_page
from chatglance.optional_login import build_single_origin_optional_login_config, optional_login_enabled


@pytest.fixture
def inventory():
    return {"repositories": [
        {"name": "PublicRow", "private": False, "html_url": "https://github.com/ChatArch/PublicRow", "open_prs": 1},
        {"name": "SecretRow", "private": True, "html_url": "https://github.com/ChatArch/SecretRow", "open_prs": 27},
        {"name": "UnknownRow", "html_url": "https://github.com/ChatArch/UnknownRow", "open_prs": 17},
    ], "counts": {"visible_repos": 3}}


@pytest.fixture
def private_config():
    return {"auth": {"secret-key": "synthetic-secret", "users": {"tester": {"password": "synthetic-password"}}},
            "server": {"host": "127.0.0.1", "port": 8456, "proxied": True},
            "document": {"head": ""}, "branding": {"logo-text": "SecretBrand"},
            "pages": [
                {"name": "ChatArch", "slug": "home", "columns": [{"size": "full", "widgets": [{"type": "bookmarks", "title": "private-home-widget", "groups": []}]}]},
                {"name": "项目", "slug": "项目", "columns": [{"size": "full", "widgets": [{"type": "bookmarks", "title": "old-private-project", "groups": []}]}]},
                {"name": "服务器", "slug": "servers", "columns": [{"size": "full", "widgets": [{"type": "bookmarks", "title": "private-servers", "groups": []}]}]},
            ]}


def test_single_origin_optional_login_contract(private_config, inventory):
    result = build_single_origin_optional_login_config(private_config, inventory)
    home, projects, servers = result["pages"]
    assert result["auth"] == private_config["auth"]
    assert result["server"] == private_config["server"]
    assert "SecretBrand" not in json.dumps(result)
    assert home["slug"] == "home" and projects["slug"] == "projects"
    assert [page["name"] for page in result["pages"]] == ["ChatArch", "项目", "服务器"]
    assert home["public"] is projects["public"] is True
    assert servers.get("public") is not True and servers["columns"] == private_config["pages"][2]["columns"]
    guest = json.dumps([home["columns"], projects["columns"]], ensure_ascii=False)
    logged_in = json.dumps([home["authenticated-columns"], projects["authenticated-columns"]], ensure_ascii=False)
    assert "private-home-widget" not in guest and "SecretRow" not in guest and "UnknownRow" not in guest
    assert '"27"' not in guest and "PublicRow" in guest and "/projects" in guest
    assert "private-home-widget" in logged_in and "SecretRow" in logged_in and "UnknownRow" in logged_in
    assert "Private" in logged_in and "Unknown" in logged_in and "Public" in logged_in
    assert private_config["pages"][0].get("public") is None


@pytest.mark.parametrize("mutation", [
    lambda cfg: cfg.pop("auth"),
    lambda cfg: cfg["pages"][0].update({"head-widgets": [{"type": "text", "content": "secret-head"}]}),
    lambda cfg: cfg["pages"][1].update({"head-widgets": [{"type": "text", "content": "secret-head"}]}),
    lambda cfg: cfg["document"].update({"head": "private global"}),
    lambda cfg: cfg["server"].update({"assets-path": "/private/assets"}),
])
def test_rejects_unsafe_guest_shared_content(private_config, inventory, mutation):
    mutation(private_config)
    with pytest.raises(ValueError):
        build_single_origin_optional_login_config(private_config, inventory)


def test_maintenance_and_refresh_keep_optional_login(private_config, inventory):
    initial = build_single_origin_optional_login_config(private_config, inventory)
    fresh = {**inventory, "repositories": inventory["repositories"][:1]}
    for updated in (replace_projects_page(initial, fresh), build_maintained_config(initial, fresh)):
        page = updated["pages"][1]
        assert page["public"] is True and page["slug"] == "projects"
        assert "SecretRow" not in json.dumps(page["columns"])
        assert "PublicRow" in json.dumps(page["authenticated-columns"])
    _replace_page(initial, build_projects_page(fresh), inventory=fresh)
    assert initial["pages"][1]["public"] is True
    assert "SecretRow" not in json.dumps(initial["pages"][1]["columns"])


@pytest.fixture
def reviewed_four_bookmarks(private_config, inventory):
    config = build_single_origin_optional_login_config(private_config, inventory)
    links = config["pages"][0]["columns"][0]["widgets"][0]["groups"][0]["links"]
    links[1:1] = [
        {"title": "Public Editor", "url": "https://editor.example.org/public", "description": "Public browser editor", "icon": "si:code"},
        {"title": "Public Docs", "url": "https://docs.example.org/guide", "description": "Public documentation", "icon": "si:book"},
    ]
    links[3] = {"title": "Organization Source", "url": "https://code.example.org/team", "description": "Public organization code", "icon": "si:github"}
    return config


def test_reviewed_four_bookmarks_survive_detection_project_refresh_and_maintenance(reviewed_four_bookmarks, inventory):
    from copy import deepcopy
    original = deepcopy(reviewed_four_bookmarks)
    fresh = {**inventory, "repositories": inventory["repositories"][:1]}
    assert optional_login_enabled(reviewed_four_bookmarks) is True
    candidates = [
        build_single_origin_optional_login_config(reviewed_four_bookmarks, fresh),
        replace_projects_page(reviewed_four_bookmarks, fresh),
        build_maintained_config(reviewed_four_bookmarks, fresh),
    ]
    assembled = deepcopy(reviewed_four_bookmarks)
    _replace_page(assembled, build_projects_page(fresh), inventory=fresh)
    candidates.append(assembled)
    for candidate in candidates:
        assert candidate["pages"][0]["columns"] == original["pages"][0]["columns"]
        assert candidate["pages"][0]["authenticated-columns"] == original["pages"][0]["authenticated-columns"]
        assert [p["name"] for p in candidate["pages"]] == [p["name"] for p in original["pages"]]
        guest = json.dumps(candidate["pages"][1]["columns"])
        authenticated = json.dumps(candidate["pages"][1]["authenticated-columns"])
        assert "SecretRow" not in guest and "UnknownRow" not in guest
        assert "PublicRow" in guest and "PublicRow" in authenticated
    assert reviewed_four_bookmarks == original


@pytest.mark.parametrize("unsafe", [
    "javascript:alert(1)", "http://editor.example.org/", "https://user:pass@editor.example.org/",
    "https://192.168.1.4/", "https://127.0.0.1/", "https://127.1/", "https://localhost/",
    "https://editor.local/", "https://editor.example.org:8443/",
    "https://editor.example.org/?token=secret", "//editor.example.org/",
    "https://[fd00::1]/", "https://editor.example.org/\x00hidden",
])
def test_reviewed_bookmarks_reject_unsafe_url(reviewed_four_bookmarks, unsafe):
    reviewed_four_bookmarks["pages"][0]["columns"][0]["widgets"][0]["groups"][0]["links"][1]["url"] = unsafe
    with pytest.raises(ValueError, match="guest home"):
        optional_login_enabled(reviewed_four_bookmarks)


@pytest.mark.parametrize("mutation", [
    lambda w: w.update({"content": "unreviewed"}),
    lambda w: w["groups"][0].update({"private": "unreviewed"}),
    lambda w: w["groups"][0]["links"][1].update({"target": "_blank"}),
    lambda w: w["groups"][0]["links"][1].update({"title": "<script>"}),
    lambda w: w["groups"][0]["links"].append({"title": "Extra", "url": "https://extra.example.org/", "description": "More", "icon": "si:github"}),
])
def test_reviewed_bookmarks_reject_unreviewed_extra_content(reviewed_four_bookmarks, mutation):
    widget = reviewed_four_bookmarks["pages"][0]["columns"][0]["widgets"][0]
    mutation(widget)
    with pytest.raises(ValueError, match="guest home"):
        optional_login_enabled(reviewed_four_bookmarks)


def test_reviewed_home_canonicalizes_only_legacy_project_link(reviewed_four_bookmarks, inventory):
    from copy import deepcopy
    reviewed_four_bookmarks["pages"][1]["slug"] = "legacy-projects"
    links = reviewed_four_bookmarks["pages"][0]["columns"][0]["widgets"][0]["groups"][0]["links"]
    links[0]["url"] = "/legacy-projects"
    remaining = deepcopy(links[1:])
    assert optional_login_enabled(reviewed_four_bookmarks)
    for candidate in (replace_projects_page(reviewed_four_bookmarks, inventory),
                      build_single_origin_optional_login_config(reviewed_four_bookmarks, inventory)):
        new_links = candidate["pages"][0]["columns"][0]["widgets"][0]["groups"][0]["links"]
        assert new_links[0]["url"] == "/projects" and new_links[1:] == remaining


def test_native_refresh_preserves_reviewed_four_bookmarks(tmp_path, reviewed_four_bookmarks, inventory, monkeypatch):
    from copy import deepcopy
    from chatglance import refresh as pipeline
    root = tmp_path / "runtime"
    for name in ("config", "data", "bin"):
        (root / name).mkdir(parents=True)
    config_path = root / "config/glance.yml"
    config_path.write_text(yaml.safe_dump(reviewed_four_bookmarks, allow_unicode=True))
    (root / "bin/glance").write_text("synthetic validator")
    (root / "data/chatarch-projects.json").write_text(json.dumps(inventory))
    fresh = {**inventory, "repositories": inventory["repositories"][:1]}
    before = deepcopy(reviewed_four_bookmarks["pages"][0])
    monkeypatch.setattr(pipeline, "_collect_page", lambda key, *args, **kwargs: pipeline.PageUpdate(key, fresh, build_projects_page(fresh)))
    monkeypatch.setattr(pipeline, "validate_glance_config", lambda *args: None)
    result = pipeline.refresh_runtime(root, pages=["projects"], restart=False)
    assert result["ok"] is True and result["published"] is True
    updated = yaml.safe_load(config_path.read_text())["pages"]
    assert updated[0] == before
    assert "SecretRow" not in json.dumps(updated[1]["columns"])
    assert "PublicRow" in json.dumps(updated[1]["authenticated-columns"])


def test_empty_private_config_still_adds_projects_page():
    inventory = {"repositories": []}
    result = replace_projects_page({}, inventory)
    assert result == {"pages": [build_projects_page(inventory)]}


def test_optional_login_detection_rejects_malformed_page_settings():
    with pytest.raises(ValueError, match="pages"):
        replace_projects_page({"pages": None}, {"repositories": []})
    with pytest.raises(ValueError, match="optional login"):
        replace_projects_page({"pages": [{"name": "ChatArch", "public": True}]}, {"repositories": []})


@pytest.mark.parametrize("change", [
    lambda config: config["pages"][0].update({"columns": config["pages"][0]["authenticated-columns"]}),
    lambda config: config["pages"][2].update({"public": True}),
    lambda config: config.update({"branding": {"logo-text": "private-brand"}}),
    lambda config: config["pages"][1].pop("authenticated-columns"),
])
def test_refresh_refuses_drifted_guest_contract(private_config, inventory, change):
    result = build_single_origin_optional_login_config(private_config, inventory)
    change(result)
    with pytest.raises(ValueError):
        replace_projects_page(result, inventory)


def test_maintenance_updates_private_server_widget_inside_authenticated_columns(private_config, inventory):
    private_config["pages"][0]["columns"][0]["widgets"].append({"type": "server-stats", "servers": [{"type": "local", "name": "synthetic"}]})
    initial = build_single_origin_optional_login_config(private_config, inventory)
    maintained = build_maintained_config(initial, inventory)
    server = maintained["pages"][0]["authenticated-columns"][0]["widgets"][1]["servers"][0]
    assert server["mountpoints"] == {"/": {"name": "根分区", "hide": False}}
    assert "server-stats" not in json.dumps(maintained["pages"][0]["columns"])


def test_candidate_cli_private_output_and_errors(tmp_path, private_config, inventory):
    config = tmp_path / "input.yml"
    data = tmp_path / "input.json"
    output = tmp_path / "candidate.yml"
    config.write_text(yaml.safe_dump(private_config, allow_unicode=True))
    data.write_text(json.dumps(inventory))
    runner = CliRunner()
    args = ["access", "render-single-origin-optional-login", "--config", str(config), "--inventory", str(data), "--output", str(output)]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "synthetic-secret" not in result.output and "SecretRow" not in result.output
    assert yaml.safe_load(output.read_text())["pages"][1]["slug"] == "projects"
    alias = runner.invoke(main, args[:-1] + [str(config)])
    assert alias.exit_code != 0 and config.read_text() == yaml.safe_dump(private_config, allow_unicode=True)
    assert "synthetic-secret" not in alias.output
    output.unlink()
    output.symlink_to(data)
    assert runner.invoke(main, args).exit_code != 0


def _configured_glance_binary() -> Path:
    configured = os.environ.get("CHATGLANCE_TEST_GLANCE_BIN")
    if configured is None:
        pytest.skip("set CHATGLANCE_TEST_GLANCE_BIN to run core config:validate integration")
    binary = Path(configured)
    assert binary.is_file() and os.access(binary, os.X_OK), "CHATGLANCE_TEST_GLANCE_BIN must name an executable file"
    return binary


def test_explicit_invalid_core_binary_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATGLANCE_TEST_GLANCE_BIN", str(tmp_path / "missing-glance"))
    with pytest.raises(AssertionError, match="CHATGLANCE_TEST_GLANCE_BIN"):
        _configured_glance_binary()


def test_candidate_passes_core_config_validate(tmp_path, private_config, inventory):
    core = _configured_glance_binary()
    output = tmp_path / "candidate.yml"
    output.write_text(yaml.safe_dump(build_single_origin_optional_login_config(private_config, inventory), allow_unicode=True))
    output.chmod(0o600)
    result = subprocess.run([str(core), "-config", str(output), "config:validate"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_project_update_and_maintain_entrypoints(tmp_path, private_config, inventory):
    from chatglance.runtime import maintain_config

    source = tmp_path / "input.yml"
    snapshot = tmp_path / "inventory.json"
    output = tmp_path / "updated.yml"
    source.write_text(yaml.safe_dump(build_single_origin_optional_login_config(private_config, inventory), allow_unicode=True))
    snapshot.write_text(json.dumps(inventory))
    result = CliRunner().invoke(main, ["projects", "update-config", "--data", str(snapshot), "--config", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert yaml.safe_load(output.read_text())["pages"][1]["public"] is True
    alias = CliRunner().invoke(main, ["projects", "update-config", "--data", str(snapshot), "--config", str(source), "--output", str(source)])
    assert alias.exit_code != 0 and "synthetic-secret" not in alias.output
    maintained = maintain_config(config_path=output, data_path=snapshot, output_path=output)
    assert maintained.output_path == output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "SecretRow" not in json.dumps(yaml.safe_load(output.read_text())["pages"][1]["columns"])


def test_native_refresh_projects_retains_optional_columns(tmp_path, private_config, inventory, monkeypatch):
    from chatglance import refresh as pipeline

    root = tmp_path / "runtime"
    for name in ("config", "data", "bin"):
        (root / name).mkdir(parents=True)
    source = root / "config/glance.yml"
    source.write_text(yaml.safe_dump(build_single_origin_optional_login_config(private_config, inventory), allow_unicode=True))
    source.chmod(0o600)
    (root / "bin/glance").write_text("synthetic validator")
    (root / "data/chatarch-projects.json").write_text(json.dumps(inventory))
    fresh = {**inventory, "repositories": inventory["repositories"][:1]}
    monkeypatch.setattr(pipeline, "_collect_page", lambda key, *args, **kwargs: pipeline.PageUpdate(key, fresh, build_projects_page(fresh)))
    monkeypatch.setattr(pipeline, "validate_glance_config", lambda *args: None)
    result = pipeline.refresh_runtime(root, pages=["projects"], restart=False)
    assert result["ok"] is True
    page = yaml.safe_load(source.read_text())["pages"][1]
    assert page["public"] is True and page["slug"] == "projects"
    assert "SecretRow" not in json.dumps(page["columns"])
    assert "PublicRow" in json.dumps(page["authenticated-columns"])
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
