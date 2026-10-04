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
from chatglance.optional_login import build_single_origin_optional_login_config


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
    assert home["slug"] == "home" and projects["slug"] == "项目"
    assert [page["name"] for page in result["pages"]] == ["ChatArch", "项目", "服务器"]
    assert home["public"] is projects["public"] is True
    assert servers.get("public") is not True and servers["columns"] == private_config["pages"][2]["columns"]
    guest = json.dumps([home["columns"], projects["columns"]], ensure_ascii=False)
    logged_in = json.dumps([home["authenticated-columns"], projects["authenticated-columns"]], ensure_ascii=False)
    assert "private-home-widget" not in guest and "SecretRow" not in guest and "UnknownRow" not in guest
    assert '"27"' not in guest and "PublicRow" in guest and "/项目" in guest
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
        assert page["public"] is True and page["slug"] == "项目"
        assert "SecretRow" not in json.dumps(page["columns"])
        assert "PublicRow" in json.dumps(page["authenticated-columns"])
    _replace_page(initial, build_projects_page(fresh), inventory=fresh)
    assert initial["pages"][1]["public"] is True
    assert "SecretRow" not in json.dumps(initial["pages"][1]["columns"])


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
    assert yaml.safe_load(output.read_text())["pages"][1]["slug"] == "项目"
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
    assert page["public"] is True and page["slug"] == "项目"
    assert "SecretRow" not in json.dumps(page["columns"])
    assert "PublicRow" in json.dumps(page["authenticated-columns"])
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
