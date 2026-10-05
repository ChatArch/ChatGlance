"""Portable runtime stays isolated, review-only, and fail-closed."""

import base64
import hashlib
import io
import json
import tarfile
import zipfile

import pytest
from click.testing import CliRunner

from chatglance.cli import main
from chatglance.portable import authenticated_environment, bridge_environment, initialize, install_verified_binary, portable_settings
from chatglance.systemd import render_portable_units, write_portable_units


def test_init_is_local_and_preserves_existing_and_empty_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    root = tmp_path / "home/glance"
    created = initialize()
    assert created and (root / "config/glance.yml").is_file()
    assert "127.0.0.1" in (root / "config/glance.yml").read_text()
    assert (root / "config/server-inventory.yml").read_text().count("hosts: []") == 1
    assert json.loads((root / "data/server-status.json").read_text())["servers"] == []
    assert json.loads((root / "data/chatarch-projects.json").read_text())["repositories"] == []
    (root / "data/chatarch-projects.json").write_text("preserved")
    assert initialize() == []
    assert (root / "data/chatarch-projects.json").read_text() == "preserved"
    assert not (root / "bin/glance").exists()
    assert not (tmp_path / "home/.config").exists()


def test_init_refuses_symlink_without_following_it(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "config").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        initialize(root)
    assert not (tmp_path / "glance.yml").exists()


def test_bridge_precedence_and_no_secret_in_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    env = bridge_environment(environ={"CHATGLANCE_LOGIN_SECRET": "process"})
    assert env["CHATGLANCE_LOGIN_SECRET"] == "process"
    with pytest.raises(ValueError, match="login requires"):
        authenticated_environment(environ={})
    with pytest.raises(ValueError, match="login requires"):
        initialize(tmp_path / "auth", with_auth=True)
    assert not (tmp_path / "auth").exists()
    valid = {"CHATGLANCE_LOGIN_SECRET": base64.b64encode(bytes(range(64))).decode(),
             "CHATGLANCE_LOGIN_USER": "owner@example.invalid", "CHATGLANCE_LOGIN_PASSWORD_HASH": "$2b$12$" + "A" * 53}
    assert authenticated_environment(environ=valid)["CHATGLANCE_LOGIN_USER"] == "owner@example.invalid"
    for bad in ("s" * 40, base64.b64encode(bytes(range(32))).decode(), valid["CHATGLANCE_LOGIN_SECRET"] + "\n"):
        with pytest.raises(ValueError, match="signing secret"):
            authenticated_environment(environ={**valid, "CHATGLANCE_LOGIN_SECRET": bad})
    with pytest.raises(ValueError, match="username"):
        authenticated_environment(environ={**valid, "CHATGLANCE_LOGIN_USER": "bad:\nuser"})
    monkeypatch.setattr("chatglance.portable.authenticated_environment", lambda: valid)
    initialize(tmp_path / "auth", with_auth=True)
    text = (tmp_path / "auth/config/glance.yml").read_text()
    assert "${CHATGLANCE_LOGIN_SECRET}" in text
    assert '"${CHATGLANCE_LOGIN_USER}"' in text
    assert valid["CHATGLANCE_LOGIN_SECRET"] not in text and "password:" not in text
    initialize(tmp_path / "plain")
    with pytest.raises(ValueError, match="existing config"):
        initialize(tmp_path / "plain", with_auth=True)
    assert "secret-key" not in (tmp_path / "plain/config/glance.yml").read_text()
    assert initialize(tmp_path / "auth", with_auth=True) == []


def test_verified_archive_and_unsafe_members(tmp_path):
    archive = tmp_path / "glance.tar.gz"
    version = "chatarch-v0.1.0+" + "a" * 40
    with tarfile.open(archive, "w:gz") as stream:
        payload = f"#!/bin/sh\nprintf '%s\\n' '{version}'\n".encode()
        member = tarfile.TarInfo("glance")
        member.size = len(payload)
        stream.addfile(member, io.BytesIO(payload))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="mismatch"):
        install_verified_binary(archive, "0" * 64, tmp_path / "root", version=version)
    assert not (tmp_path / "root").exists()
    with pytest.raises(ValueError, match="version mismatch"):
        install_verified_binary(archive, checksum, tmp_path / "root", version="chatarch-v0.1.0+" + "b" * 40)
    assert not (tmp_path / "root").exists()
    binary = install_verified_binary(archive, checksum, tmp_path / "root", version=version)
    assert binary.read_bytes() == payload
    provenance = json.loads((binary.parent / "glance.provenance.json").read_text())
    assert provenance["version"] == version and provenance["binary_sha256"] == hashlib.sha256(payload).hexdigest()
    assert provenance["source_tag"] == "chatarch-v0.1.0" and provenance["source_revision"] == "a" * 40
    with pytest.raises(ValueError, match="already exists"):
        install_verified_binary(archive, checksum, tmp_path / "root", version=version)
    (tmp_path / "existing/bin").mkdir(parents=True)
    (tmp_path / "existing/bin/glance.provenance.json").write_text("unknown")
    with pytest.raises(ValueError, match="already exists"):
        install_verified_binary(archive, checksum, tmp_path / "existing", version=version)
    assert (tmp_path / "existing/bin/glance.provenance.json").read_text() == "unknown"
    broken = tmp_path / "broken.tar"
    with tarfile.open(broken, "w") as stream:
        payload = b"not an executable"
        member = tarfile.TarInfo("glance")
        member.size = len(payload)
        stream.addfile(member, io.BytesIO(payload))
    with pytest.raises(ValueError, match="executable version check failed"):
        install_verified_binary(broken, hashlib.sha256(broken.read_bytes()).hexdigest(), tmp_path / "broken-home", version=version)
    assert not (tmp_path / "broken-home").exists()
    unsafe = tmp_path / "unsafe.tar"
    with tarfile.open(unsafe, "w") as stream:
        member = tarfile.TarInfo("../glance")
        member.size = 1
        stream.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="only a regular"):
        install_verified_binary(unsafe, hashlib.sha256(unsafe.read_bytes()).hexdigest(), tmp_path / "other", version=version)


def test_binary_publish_rolls_back_metadata_on_link_failure(tmp_path, monkeypatch):
    from chatglance import portable

    version = "chatarch-v0.1.0+" + "a" * 40
    payload = f"#!/bin/sh\necho '{version}'\n".encode()
    archive = tmp_path / "fixture.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("glance")
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    monkeypatch.setattr(portable.os, "link", lambda *args, **kwargs: (_ for _ in ()).throw(FileExistsError("simulated collision")))
    root = tmp_path / "runtime"
    with pytest.raises(FileExistsError):
        install_verified_binary(archive, hashlib.sha256(archive.read_bytes()).hexdigest(), root, version=version)
    assert not (root / "bin/glance").exists()
    assert not (root / "bin/glance.provenance.json").exists()


def test_portable_units_are_opt_in_and_escape_paths(tmp_path):
    units = render_portable_units(runtime_home=tmp_path / "a % b", python_bin=tmp_path / "python", pages=("projects", "servers"))
    assert "chatglance-portable-refresh.timer" in units
    assert "--service-name chatglance-portable.service projects servers" in units["chatglance-portable-refresh.service"]
    assert "--no-restart" not in units["chatglance-portable-refresh.service"]
    assert "account-limits" not in str(units)
    assert "a %% b" in units["chatglance-portable.service"]
    with pytest.raises(ValueError):
        render_portable_units(runtime_home=tmp_path, interval="1min\nExecStart=evil")
    with pytest.raises(ValueError):
        render_portable_units(runtime_home=tmp_path, pages=("account-limits",))
    with pytest.raises(ValueError):
        render_portable_units(runtime_home=tmp_path / "bad\nExecStart=evil")
    with pytest.raises(ValueError):
        render_portable_units(runtime_home=tmp_path, python_bin="./python")


def test_portable_settings_feed_cli_and_units_without_network(tmp_path, monkeypatch):
    from chatenv import EnvStore

    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    for name in ("CHATGLANCE_PROJECTS_OWNER", "CHATGLANCE_REFRESH_PAGES", "CHATGLANCE_REFRESH_INTERVAL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(EnvStore, "load_active", lambda self, cls: {
        "CHATGLANCE_PROJECTS_OWNER": "ExampleOrg", "CHATGLANCE_REFRESH_PAGES": "projects, sites",
        "CHATGLANCE_REFRESH_INTERVAL": "45min",
    })
    assert portable_settings()["owner"] == "ExampleOrg"
    units = render_portable_units(runtime_home=tmp_path / "glance")
    assert "projects sites" in units["chatglance-portable-refresh.service"]
    assert "OnUnitActiveSec=45min" in units["chatglance-portable-refresh.timer"]
    with pytest.raises(ValueError, match="refresh pages"):
        portable_settings(environ={"CHATGLANCE_REFRESH_PAGES": "account-limits"})
    captured = []
    monkeypatch.setattr("chatglance.cli.refresh_project_inventory", lambda **kwargs: captured.append(kwargs["options"].owner) or {"counts": {}})
    runner = CliRunner()
    for args in ([], ["--owner", "ExplicitOrg"]):
        result = runner.invoke(main, ["projects", "collect", "--output", str(tmp_path / "inventory.json"), *args])
        assert result.exit_code == 0, result.output
    assert captured == ["ExampleOrg", "ExplicitOrg"]
    render = runner.invoke(main, ["runtime", "render-portable", "--runtime-home", str(tmp_path / "glance")])
    assert render.exit_code == 0 and "projects sites" in render.output


def test_portable_unit_writer_preserves_existing_and_symlinks(tmp_path):
    unit = {"chatglance-portable.service": "review\n"}
    directory = tmp_path / "units"
    assert write_portable_units(directory, unit) == [directory / "chatglance-portable.service"]
    with pytest.raises(ValueError, match="already exists"):
        write_portable_units(directory, unit)
    assert (directory / "chatglance-portable.service").read_text() == "review\n"
    other = tmp_path / "other"
    other.mkdir()
    (other / "chatglance-portable.service").symlink_to(directory / "chatglance-portable.service")
    with pytest.raises(ValueError, match="symlink"):
        write_portable_units(other, unit)


def test_proxy_example_has_same_origin_controls_and_nonlooping_redirect():
    from importlib.resources import files

    text = files("chatglance").joinpath("resources/reverse-proxy.example.conf").read_text()
    assert "server_name example.invalid" in text
    assert "location ^~ /_chatglance/reset-policy/" in text
    assert "proxy_pass http://127.0.0.1:5679/" in text
    assert "proxy_pass http://127.0.0.1:8080" in text
    assert "location = /项目 { return 308 /projects; }" in text
    assert "location = /projects {" not in text


def test_child_only_secret_and_validator_bridge(tmp_path, monkeypatch):
    from chatglance import portable, runtime

    root = tmp_path / "glance"
    initialize(root)
    (root / "bin/glance").write_bytes(b"fixture")
    calls = []
    monkeypatch.setattr(portable.os, "execve", lambda path, args, env: calls.append((path, args, env)))
    monkeypatch.setattr(portable, "bridge_environment", lambda: {"CHATGLANCE_WEB_PORT": "8080", "CHATGLANCE_LOGIN_SECRET": "test-secret"})
    portable.serve(root)
    assert calls[0][2]["CHATGLANCE_LOGIN_SECRET"] == "test-secret"
    assert "test-secret" not in str(calls[0][1])
    assert "test-secret" not in (root / "config/glance.yml").read_text()
    monkeypatch.setattr(runtime.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(portable, "authenticated_environment", lambda: {"CHATGLANCE_LOGIN_SECRET": "test-secret", "CHATGLANCE_WEB_PORT": "8080"})
    (root / "config/glance.yml").write_text("auth:\n  secret-key: ${CHATGLANCE_LOGIN_SECRET}\n")
    runtime.validate_glance_config(root / "bin/glance", root / "config/glance.yml")
    assert calls[-1][1]["env"]["CHATGLANCE_LOGIN_SECRET"] == "test-secret"
    assert "test-secret" not in str(calls[-1][0])


def test_control_authenticator_resolves_port_without_bypassing_go(tmp_path, monkeypatch):
    from chatglance import portable, reset_control

    initialize(tmp_path)
    config = tmp_path / "config/glance.yml"
    config.write_text("server:\n  host: 127.0.0.1\n  port: ${CHATGLANCE_WEB_PORT}\nauth:\n  secret-key: ${CHATGLANCE_LOGIN_SECRET}\n  users:\n    ${CHATGLANCE_LOGIN_USER}: {}\n")
    monkeypatch.setattr(portable, "bridge_environment", lambda: {"CHATGLANCE_WEB_PORT": "18080"})
    assert callable(reset_control.glance_authenticator(tmp_path))
    monkeypatch.setattr(portable, "bridge_environment", lambda: {"CHATGLANCE_WEB_PORT": "invalid"})
    with pytest.raises(reset_control.ControlError):
        reset_control.glance_authenticator(tmp_path)


def test_real_cli_portable_tree_and_init(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    runner = CliRunner()
    for option in ("--tree", "--tree-brief"):
        tree = runner.invoke(main, [option])
        assert tree.exit_code == 0
        assert "install-binary" in tree.output and "render-portable" in tree.output
    created = runner.invoke(main, ["runtime", "init"])
    assert created.exit_code == 0, created.output
    assert (tmp_path / "glance/config/glance.yml").exists()


def test_wheel_includes_installed_resources(tmp_path):
    import shutil
    import subprocess
    import sys

    source = tmp_path / "source"
    source.mkdir()
    shutil.copytree(__import__("pathlib").Path(__file__).resolve().parents[1] / "src", source / "src")
    shutil.copy2(__import__("pathlib").Path(__file__).resolve().parents[1] / "pyproject.toml", source / "pyproject.toml")
    shutil.copy2(__import__("pathlib").Path(__file__).resolve().parents[1] / "README.md", source / "README.md")
    build = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(tmp_path / "dist")],
        cwd=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    assert build.returncode == 0
    with zipfile.ZipFile(next((tmp_path / "dist").glob("*.whl"))) as wheel:
        names = set(wheel.namelist())
        for name in ("glance.yml", "server-inventory.yml", "site-services.yml", "reverse-proxy.example.conf", "start.sh", "install.sh", "refresh.sh"):
            assert "chatglance/resources/" + name in names
