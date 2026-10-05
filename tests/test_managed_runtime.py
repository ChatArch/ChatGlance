"""Controlled lifecycle tests: no real systemd, network, or accounts."""

import base64
import hashlib
import json
import io
import tarfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from chatenv import EnvStore, get_paths

from chatglance.cli import main
from chatglance.config import ChatGlanceConfig
from chatglance import managed


def synthetic_runtime(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CHATARCH_HOME", str(home))
    root = home / "glance"
    (root / "config").mkdir(parents=True)
    (root / "bin").mkdir()
    config = {"server": {"host": "127.0.0.1", "port": 8080}, "pages": [{"name": "Home", "columns": []}],
              "auth": {"secret-key": base64.b64encode(bytes(range(64))).decode(), "users": {
                  "first@example.invalid": {"password-hash": "$2b$12$" + "A" * 53},
                  "second@example.invalid": {"password-hash": "$2b$12$" + "B" * 53}}}}
    (root / "config/glance.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    (root / "bin/glance").write_text("fixture")
    monkeypatch.setattr(managed, "validate_candidate", lambda *args, **kwargs: None)
    def synthetic_states(names):
        directory = tmp_path / ("user-units" if (tmp_path / "user-units").exists() else "units")
        states = {}
        for name in names:
            path = directory / name
            body = path.read_text() if path.exists() and not path.is_symlink() else ""
            command = next((line.removeprefix("ExecStart=").replace("%%", "%") for line in body.splitlines()
                            if line.startswith("ExecStart=")), "")
            states[name] = {"ActiveState": "inactive", "MainPID": "0", "UnitFileState": "disabled",
                            "FragmentPath": str(path), "DropInPaths": "", "EnvironmentFiles": "",
                            "ExecStart": "{ path=" + __import__('shlex').split(command)[0] + " ; argv[]=" + command + " ; ignore_errors=no ; }" if command else ""}
        return states
    monkeypatch.setattr(managed, "unit_states", synthetic_states)
    return root, config


def test_adopt_dry_run_and_multiple_users_preserve_snapshots(tmp_path, monkeypatch):
    root, config = synthetic_runtime(tmp_path, monkeypatch)
    before = (root / "config/glance.yml").read_bytes()
    assert managed.adopt_runtime(root)["accounts"] == 2
    assert (root / "config/glance.yml").read_bytes() == before
    assert not (root / "private").exists()
    result = managed.adopt_runtime(root, apply=True)
    assert result["applied"] and result["backup"]
    updated = (root / "config/glance.yml").read_text()
    assert config["auth"]["secret-key"] not in updated
    assert "first@example.invalid" not in updated
    values = EnvStore(get_paths().envs_dir).load_active(ChatGlanceConfig)
    assert values["CHATGLANCE_LOGIN_SECRET"] == config["auth"]["secret-key"]
    assert len(json.loads(values["CHATGLANCE_LOGIN_ACCOUNTS"])) == 2
    environment = managed.runtime_environment(root)
    assert environment["CHATGLANCE_AUTH_USER_0"] == "first@example.invalid"
    assert environment["CHATGLANCE_AUTH_HASH_1"] == "$2b$12$" + "B" * 53
    assert yaml.safe_load(updated)["pages"] == config["pages"]


def test_install_dry_run_ownership_and_schedule(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    units_dir = tmp_path / "user-units"
    plan = managed.install_runtime(root, unit_dir=units_dir, pages=("servers", "account-limits", "projects"), interval="30min")
    assert not units_dir.exists() and not (root / "private").exists()
    assert plan["scheduled"] is False
    commands = []
    monkeypatch.setattr(managed, "verify_units", lambda paths: None)
    monkeypatch.setattr(managed, "systemctl_user", lambda *args: commands.append(args))
    result = managed.install_runtime(root, unit_dir=units_dir, pages=("servers", "account-limits", "projects"), interval="30min", apply=True)
    assert result["applied"] and commands == [("daemon-reload",)]
    refresh = (units_dir / "chatarch-glance-refresh-pages.service").read_text()
    assert "runtime refresh-managed" in refresh and "--scheduled" not in refresh
    owner = managed.load_manifest(root)
    assert owner["names"]["web"] == "chatarch-glance.service"
    assert owner["pages"] == ["servers", "account-limits", "projects"]
    assert "EnvironmentFile" not in refresh
    assert managed.service_action(root, "restart")["applied"] is False
    assert commands == [("daemon-reload",)]
    with pytest.raises(ValueError):
        managed.service_action(root, "restart", units=("unowned.service",), apply=True)


def test_install_busy_and_unknown_files_fail_closed(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(managed, "unit_states", lambda names: {name: {"ActiveState": "activating"} for name in names})
    with pytest.raises(ValueError, match="busy"):
        managed.install_runtime(root, unit_dir=tmp_path / "units", pages=("projects",), apply=True)
    assert not (tmp_path / "units").exists()


def test_status_contains_only_counts_and_hashes(tmp_path, monkeypatch):
    root, config = synthetic_runtime(tmp_path, monkeypatch)
    output = json.dumps(managed.runtime_status(root))
    assert config["auth"]["secret-key"] not in output
    assert "first@example.invalid" not in output
    assert "accounts" in output and "interpreter" in output


def test_managed_cli_dry_run(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    result = CliRunner().invoke(main, ["runtime", "install", "--runtime-home", str(root), "--unit-dir", str(tmp_path / "units")])
    assert result.exit_code == 0, result.output
    assert '"applied": false' in result.output
    assert not (tmp_path / "units").exists()


def installed_runtime(tmp_path, monkeypatch, **options):
    root, config = synthetic_runtime(tmp_path, monkeypatch)
    commands = []
    active = set()
    original_states = managed.unit_states
    def states(names):
        result = original_states(names)
        for name, state in result.items():
            if name in active:
                state.update(ActiveState="active", MainPID="1234")
        return result
    def systemctl(*args):
        commands.append(args)
        if args[0] in ("start", "restart"):
            active.update(args[1:])
        elif args[0] == "stop":
            active.difference_update(args[1:])
    monkeypatch.setattr(managed, "unit_states", states)
    monkeypatch.setattr(managed, "verify_units", lambda paths: None)
    monkeypatch.setattr(managed, "systemctl_user", systemctl)
    result = managed.install_runtime(root, unit_dir=tmp_path / "units", apply=True, **options)
    return root, config, commands, result


def test_adoption_rollback_preserves_provider_policies_and_snapshot_bytes(tmp_path, monkeypatch):
    root, config = synthetic_runtime(tmp_path, monkeypatch)
    store = EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig, {"CHATGLANCE_LOGIN_ACCOUNTS": "{}", "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES": '{"fixture":{"enabled":false}}'})
    env_before = store.active_path(ChatGlanceConfig).read_bytes()
    config_before = (root / "config/glance.yml").read_bytes()
    snapshot = root / "config/existing-snapshot.yml"
    snapshot.write_bytes(b"# unchanged fixture\n")
    result = managed.adopt_runtime(root, apply=True)
    assert store.load_active(ChatGlanceConfig)["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] == '{"fixture":{"enabled":false}}'
    assert snapshot.read_bytes() == b"# unchanged fixture\n"
    managed.rollback_runtime(root, result["backup"], apply=True)
    assert store.active_path(ChatGlanceConfig).read_bytes() == env_before
    assert (root / "config/glance.yml").read_bytes() == config_before


def test_adoption_conflict_and_validation_failure_do_not_publish(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    original = (root / "config/glance.yml").read_bytes()
    store = EnvStore(get_paths().envs_dir)
    store.save_active(ChatGlanceConfig, {"CHATGLANCE_LOGIN_SECRET": "existing-fixture"})
    with pytest.raises(ValueError, match="conflict"):
        managed.adopt_runtime(root, apply=True)
    monkeypatch.setattr(managed, "validate_candidate", lambda *args: (_ for _ in ()).throw(ValueError("invalid")))
    with pytest.raises(ValueError):
        managed.adopt_runtime(root, apply=True, replace_provider=True)
    assert (root / "config/glance.yml").read_bytes() == original
    assert store.load_active(ChatGlanceConfig)["CHATGLANCE_LOGIN_SECRET"] == "existing-fixture"


def test_owned_units_preserve_schedule_and_native_refresh_contract(tmp_path, monkeypatch):
    root, _, commands, _ = installed_runtime(tmp_path, monkeypatch, pages=("servers", "account-limits", "projects"), interval="30min", scheduled=True)
    managed.install_runtime(root, apply=True)
    assert managed.load_manifest(root)["scheduled"] is True
    from chatglance import refresh
    calls = []
    monkeypatch.setattr(refresh, "refresh_runtime", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    managed.refresh_managed(root)
    assert calls[0][0][1] == ["servers", "account-limits", "projects"]
    assert calls[0][1] == {"service_name": "chatarch-glance.service", "scheduled": True}
    assert commands == [("daemon-reload",), ("daemon-reload",)]


@pytest.mark.parametrize("state", ["active", "activating", "reloading"])
def test_busy_owner_states_gate_without_publication(tmp_path, monkeypatch, state):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(managed, "unit_states", lambda names: {name: {"ActiveState": state} for name in names})
    with pytest.raises(ValueError, match="busy"):
        managed.install_runtime(root, unit_dir=tmp_path / "units", apply=True)
    assert not (tmp_path / "units").exists()


def test_unknown_units_symlinks_and_name_injection_refused(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    directory = tmp_path / "units"
    directory.mkdir()
    target = directory / managed.DEFAULT_NAMES["web"]
    target.write_text("unknown fixture")
    with pytest.raises(ValueError):
        managed.install_runtime(root, unit_dir=directory)
    assert target.read_text() == "unknown fixture"
    target.unlink()
    target.symlink_to(root / "config/glance.yml")
    with pytest.raises(ValueError, match="symlink"):
        managed.install_runtime(root, unit_dir=directory, adopt_units=True)
    for name in ("file://host/web.service", "web\n.service", "web%u.service"):
        with pytest.raises(ValueError):
            managed.install_runtime(root, names={"web": name})


def test_install_reload_failure_restores_unknown_adopted_unit(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    directory = tmp_path / "units"
    directory.mkdir()
    target = directory / managed.DEFAULT_NAMES["web"]
    target.write_text("existing reviewed fixture")
    monkeypatch.setattr(managed, "verify_units", lambda paths: None)
    attempts = []
    def fail_first_reload(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("fixture reload failed")
    monkeypatch.setattr(managed, "systemctl_user", fail_first_reload)
    with pytest.raises(ValueError, match="restored"):
        managed.install_runtime(root, unit_dir=directory, adopt_units=True, apply=True)
    assert target.read_text() == "existing reviewed fixture"
    assert not (root / managed.MANIFEST).exists()


def executable_archive(tmp_path, version):
    content = f"#!/bin/sh\n# Controlled version-only fixture, not a Go release.\nprintf '%s\\n' '{version}'\n".encode()
    archive = tmp_path / "reviewed-fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("glance")
        member.size = len(content)
        member.mode = 0o755
        bundle.addfile(member, io.BytesIO(content))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_binary_update_verification_and_rollback(tmp_path, monkeypatch):
    root, _, commands, _ = installed_runtime(tmp_path, monkeypatch)
    original = (root / "bin/glance").read_bytes()
    version = "chatarch-v0.2.0+" + "a" * 40
    archive, digest = executable_archive(tmp_path, version)
    assert not managed.update_binary(root, archive, digest, version)["applied"]
    with pytest.raises(ValueError):
        managed.update_binary(root, archive, "0" * 64, version, apply=True)
    with pytest.raises(ValueError):
        managed.update_binary(root, archive, digest, "chatarch-v0.1.0+" + "b" * 40, apply=True)
    assert (root / "bin/glance").read_bytes() == original
    result = managed.update_binary(root, archive, digest, version, apply=True, restart=True)
    provenance = json.loads((root / "bin/glance.provenance.json").read_text())
    assert provenance["source_tag"] == "chatarch-v0.2.0"
    assert provenance["source_revision"] == "a" * 40
    assert commands[-1] == ("restart", "chatarch-glance.service")
    managed.rollback_runtime(root, result["backup"], apply=True)
    assert (root / "bin/glance").read_bytes() == original
    assert not (root / "bin/glance.provenance.json").exists()


def test_corrupted_rollback_blob_refuses_all_writes(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    result = managed.adopt_runtime(root, apply=True)
    before = (root / "config/glance.yml").read_bytes()
    backup = root / "private/managed-backups" / result["backup"]
    next(backup.glob("*.blob")).write_bytes(b"corrupted fixture")
    with pytest.raises(ValueError, match="digest"):
        managed.rollback_runtime(root, result["backup"], apply=True)
    assert (root / "config/glance.yml").read_bytes() == before


def test_managed_auth_ignores_stale_inherited_login_and_indexed_keys(tmp_path, monkeypatch):
    root, config = synthetic_runtime(tmp_path, monkeypatch)
    managed.adopt_runtime(root, apply=True)
    monkeypatch.setenv("CHATGLANCE_LOGIN_SECRET", "parent-stale-fixture")
    monkeypatch.setenv("CHATGLANCE_LOGIN_ACCOUNTS", "invalid parent fixture")
    monkeypatch.setenv("CHATGLANCE_AUTH_USER_0", "parent@example.invalid")
    monkeypatch.setenv("CHATGLANCE_AUTH_HASH_7", "parent-hash-fixture")
    environment = managed.runtime_environment(root, auth=True)
    assert environment["CHATGLANCE_LOGIN_SECRET"] == config["auth"]["secret-key"]
    assert environment["CHATGLANCE_AUTH_USER_0"] == "first@example.invalid"
    assert "CHATGLANCE_AUTH_HASH_7" not in environment
    assert "parent-stale-fixture" not in json.dumps(managed.runtime_status(root))


def test_selected_dropin_requires_explicit_retirement_and_restores_on_rollback(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    directory = tmp_path / "units"
    directory.mkdir()
    unit = managed.DEFAULT_NAMES["web"]
    (directory / unit).write_text("[Service]\nExecStart=/old/fixture\n")
    dropin = directory / (unit + ".d") / "legacy.conf"
    dropin.parent.mkdir()
    dropin.write_text("[Service]\nEnvironmentFile=/fixture/legacy.env\n")
    baseline = managed.unit_states
    def effective(names):
        states = baseline(names)
        if unit in states and dropin.exists():
            states[unit]["DropInPaths"] = str(dropin)
            states[unit]["EnvironmentFiles"] = "/fixture/legacy.env"
        return states
    monkeypatch.setattr(managed, "unit_states", effective)
    monkeypatch.setattr(managed, "verify_units", lambda paths: None)
    monkeypatch.setattr(managed, "systemctl_user", lambda *args: None)
    with pytest.raises(ValueError, match="drop-ins"):
        managed.install_runtime(root, unit_dir=directory, adopt_units=True)
    result = managed.install_runtime(root, unit_dir=directory, adopt_units=True, retire_dropins=True, apply=True)
    assert not dropin.exists()
    assert managed.runtime_status(root)["effective_matches"]
    managed.rollback_runtime(root, result["backup"], apply=True)
    assert dropin.read_text() == "[Service]\nEnvironmentFile=/fixture/legacy.env\n"
    assert (directory / unit).read_text() == "[Service]\nExecStart=/old/fixture\n"


def test_import_env_preserves_policy_and_private_rollback(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    source = root / "config/legacy.env"
    source.write_text("PROFILES='fixture'\nCHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES='{\"fixture\":{\"enabled\":false}}'\nMODELS=unused\n")
    preview = managed.import_legacy_environment(root, "config/legacy.env", retire=True)
    assert preview["ignored_keys"] == ["MODELS"]
    assert source.exists()
    applied = managed.import_legacy_environment(root, "config/legacy.env", apply=True, retire=True)
    assert not source.exists()
    provider = EnvStore(get_paths().envs_dir)
    assert provider.load_active(ChatGlanceConfig)["CHATGLANCE_ACCOUNT_LIMITS_PROFILES"] == "fixture"
    assert provider.load_active(ChatGlanceConfig)["CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"] == '{"fixture":{"enabled":false}}'
    managed.rollback_runtime(root, applied["backup"], apply=True)
    assert source.exists()
    assert "CHATGLANCE_ACCOUNT_LIMITS_PROFILES" not in provider.load_active(ChatGlanceConfig)
    for source_name in ("../outside.env", "config/../../unsafe.env", "/fixture/path.env"):
        with pytest.raises(ValueError):
            managed.import_legacy_environment(root, source_name)


@pytest.mark.parametrize("failure_stage", ["enable", "start"])
def test_partial_activation_restores_owned_entries(tmp_path, monkeypatch, failure_stage):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    directory = tmp_path / "units"
    commands = []
    monkeypatch.setattr(managed, "verify_units", lambda paths: None)
    def action(*args):
        commands.append(args)
        if args[0] == failure_stage and len([command for command in commands if command[0] == failure_stage]) == 1:
            raise OSError("controlled partial fixture")
    monkeypatch.setattr(managed, "systemctl_user", action)
    with pytest.raises(ValueError, match="restored"):
        managed.install_runtime(root, unit_dir=directory, pages=("projects",), apply=True, enable=True, start=True)
    assert not (root / managed.MANIFEST).exists()
    assert not (directory / managed.DEFAULT_NAMES["web"]).exists()
    assert commands[0] == ("daemon-reload",)
    assert ("daemon-reload",) in commands[1:]


def test_binary_restart_recovery_reports_failure_and_preserves_old_bytes(tmp_path, monkeypatch):
    root, _, commands, _ = installed_runtime(tmp_path, monkeypatch)
    original = (root / "bin/glance").read_bytes()
    version = "chatarch-v0.2.0+" + "b" * 40
    archive, digest = executable_archive(tmp_path, version)
    monkeypatch.setattr(managed, "unit_states", lambda names: {name: {"ActiveState": "active" if name == managed.DEFAULT_NAMES["web"] else "inactive", "MainPID": "1234" if name == managed.DEFAULT_NAMES["web"] else "0"} for name in names})
    def restart_failure(*args):
        commands.append(args)
        if args[0] == "restart":
            raise OSError("synthetic service restart failure")
    monkeypatch.setattr(managed, "systemctl_user", restart_failure)
    with pytest.raises(ValueError, match="recovery failed"):
        managed.update_binary(root, archive, digest, version, apply=True, restart=True)
    assert (root / "bin/glance").read_bytes() == original
    assert commands.count(("restart", managed.DEFAULT_NAMES["web"])) == 2


def test_install_partial_second_enable_undoes_first_and_restores_files(tmp_path, monkeypatch):
    root, _ = synthetic_runtime(tmp_path, monkeypatch)
    directory = tmp_path / "units"
    calls = []
    monkeypatch.setattr(managed, "verify_units", lambda paths: None)
    def action(*args):
        calls.append(args)
        if args[0] == "enable" and len([item for item in calls if item[0] == "enable"]) == 2:
            raise OSError("second enable fixture")
    monkeypatch.setattr(managed, "systemctl_user", action)
    with pytest.raises(ValueError, match="restored"):
        managed.install_runtime(root, unit_dir=directory, pages=("projects",), apply=True, enable=True)
    assert ("disable", managed.DEFAULT_NAMES["web"]) in calls
    assert ("disable", managed.DEFAULT_NAMES["refresh_timer"]) in calls
    assert not (root / managed.MANIFEST).exists()
    assert not (directory / managed.DEFAULT_NAMES["web"]).exists()


def test_status_excludes_raw_effective_environment_and_fails_overlay(tmp_path, monkeypatch):
    root, _, _, _ = installed_runtime(tmp_path, monkeypatch, pages=("projects",))
    baseline = managed.unit_states
    def overlay(names):
        states = baseline(names)
        if managed.DEFAULT_NAMES["web"] in states:
            states[managed.DEFAULT_NAMES["web"]]["EnvironmentFiles"] = "/private/sentinel-password"
        return states
    monkeypatch.setattr(managed, "unit_states", overlay)
    result = managed.runtime_status(root, live=True)
    assert result["managed"] and not result["effective_matches"]
    assert "sentinel-password" not in json.dumps(result)
    runner = CliRunner().invoke(main, ["runtime", "check", "--runtime-home", str(root), "--live"])
    assert runner.exit_code != 0
    assert "sentinel-password" not in runner.output
