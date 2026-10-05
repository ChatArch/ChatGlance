"""Small, manifest-owned user-service lifecycle for installed ChatGlance."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

import yaml
from chatenv import EnvStore, get_paths

from . import __version__
from .config import ChatGlanceConfig
from .portable import BRIDGE_KEYS, _safe_directory, authenticated_environment, bridge_environment, install_verified_binary, runtime_home
from .systemd import _portable_arg, systemctl_user, user_systemd_dir, verify_user_units


MANIFEST = "private/managed.json"
DEFAULT_NAMES = {
    "web": "chatarch-glance.service",
    "refresh": "chatarch-glance-refresh-pages.service",
    "refresh_timer": "chatarch-glance-refresh-pages.timer",
    "controls": "chatglance-reset-controls.service",
    "maintenance": "chatarch-glance-maintenance.service",
    "maintenance_timer": "chatarch-glance-maintenance.timer",
}
BUSY_STATES = {"activating", "active", "reloading", "deactivating"}
AUTH_KEYS = {"CHATGLANCE_LOGIN_SECRET", "CHATGLANCE_LOGIN_USER", "CHATGLANCE_LOGIN_PASSWORD_HASH", "CHATGLANCE_LOGIN_ACCOUNTS"}


def _safe_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("managed path contains a symlink")
    if path.exists() and not path.is_file():
        raise ValueError("managed target is not a regular file")


def _bytes(path: Path) -> bytes | None:
    _safe_path(path)
    return path.read_bytes() if path.exists() else None


def _hash(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _atomic(path: Path, content: bytes, mode: int = 0o600) -> None:
    _safe_path(path)
    _safe_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".managed-", dir=path.parent)
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        staged.chmod(mode)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def load_manifest(root: str | Path, *, required: bool = True) -> dict:
    root = runtime_home(root)
    raw = _bytes(root / MANIFEST)
    if raw is None:
        if required:
            raise ValueError("runtime is not managed; run runtime install first")
        return {}
    manifest = json.loads(raw)
    if manifest.get("schema") != 1 or manifest.get("runtime_home") != str(root):
        raise ValueError("runtime ownership manifest is invalid")
    names = manifest.get("names", {})
    for role, name in names.items():
        _unit_name(name, timer=role.endswith("timer"))
    if set(names) != set(DEFAULT_NAMES) or len(set(names.values())) != len(names):
        raise ValueError("runtime unit ownership is invalid")
    unit_dir = Path(manifest["unit_dir"])
    if not unit_dir.is_absolute():
        raise ValueError("unit ownership directory must be absolute")
    for name, item in manifest.get("units", {}).items():
        if name not in names.values() or item.get("path") != str(unit_dir / name):
            raise ValueError("unit path does not match ownership")
    roles = ["web"] + (["refresh", "refresh_timer"] if manifest.get("pages") else [])
    roles += ["controls"] if manifest.get("controls") else []
    roles += ["maintenance", "maintenance_timer"] if manifest.get("maintenance") else []
    if set(manifest.get("units", {})) != {names[role] for role in roles}:
        raise ValueError("unit ownership does not match selected topology")
    return manifest


def _unit_name(name: str, *, timer: bool = False) -> str:
    suffix = "timer" if timer else "service"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\." + suffix, name):
        raise ValueError("invalid owned unit name")
    return name


def _home(root: Path) -> Path:
    manifest = load_manifest(root, required=False)
    home = Path(manifest.get("chatenv_home") or get_paths().home_dir)
    if not home.is_absolute():
        raise ValueError("typed provider home must be absolute")
    _safe_path(home / "envs" / "ownership-check")
    return home


@contextmanager
def effective_home(root: str | Path):
    home = str(_home(runtime_home(root)))
    previous = os.environ.get("CHATARCH_HOME")
    os.environ["CHATARCH_HOME"] = home
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CHATARCH_HOME", None)
        else:
            os.environ["CHATARCH_HOME"] = previous


def runtime_environment(root: str | Path, *, auth: bool = False, values: dict | None = None) -> dict[str, str]:
    root = runtime_home(root)
    home = _home(root)
    environment = bridge_environment(home=home)
    for key in tuple(environment):
        if key in AUTH_KEYS or re.fullmatch(r"CHATGLANCE_AUTH_(?:USER|HASH)_[0-9]+", key):
            environment.pop(key)
    provider = EnvStore(get_paths(home).envs_dir).load_active(ChatGlanceConfig)
    environment.update({key: provider[key] for key in AUTH_KEYS if provider.get(key)})
    if values is not None:
        environment.update({key: str(value) for key, value in values.items() if key in BRIDGE_KEYS})
    environment["CHATARCH_HOME"] = str(home)
    account_text = environment.get("CHATGLANCE_LOGIN_ACCOUNTS", "{}")
    accounts = json.loads(account_text)
    if not isinstance(accounts, dict) or len(accounts) > 100:
        raise ValueError("invalid typed login account map")
    for index, entry in accounts.items():
        if not re.fullmatch(r"[0-9]{1,3}", index) or not isinstance(entry, dict):
            raise ValueError("invalid typed login account entry")
        checked = authenticated_environment(home=home, environ={
            **environment, "CHATGLANCE_LOGIN_USER": entry.get("username", ""),
            "CHATGLANCE_LOGIN_PASSWORD_HASH": entry.get("password_hash", ""),
        })
        environment[f"CHATGLANCE_AUTH_USER_{index}"] = checked["CHATGLANCE_LOGIN_USER"]
        environment[f"CHATGLANCE_AUTH_HASH_{index}"] = checked["CHATGLANCE_LOGIN_PASSWORD_HASH"]
    if auth and not accounts:
        environment = authenticated_environment(home=home, environ=environment)
    return environment


def validate_candidate(binary: Path, config: Path, environment: dict[str, str]) -> None:
    try:
        subprocess.run([str(binary), "-config", str(config), "config:validate"], env=environment,
                       check=True, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Go config validation failed ({type(exc).__name__})") from None


def unit_states(names) -> dict[str, dict[str, str]]:
    result = {}
    for name in names:
        completed = subprocess.run(["systemctl", "--user", "show", name, "-pActiveState", "-pSubState", "-pMainPID",
                                    "-pFragmentPath", "-pDropInPaths", "-pEnvironmentFiles", "-pExecStart", "-pUnitFileState", "--no-pager"],
                                   capture_output=True, text=True, timeout=15)
        if completed.returncode or len(completed.stdout) > 65536 or "ActiveState=" not in completed.stdout:
            raise ValueError("unable to establish owned unit state")
        result[name] = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    return result


def _effective(name: str, directory: Path, expected: str, state: dict, *, retiring: bool = False) -> list[Path]:
    if "FragmentPath" not in state or "DropInPaths" not in state or "EnvironmentFiles" not in state or "ExecStart" not in state:
        raise ValueError("unable to inspect effective unit ownership")
    fragment = state["FragmentPath"]
    if fragment != str(directory / name):
        raise ValueError("unexpected effective unit fragment")
    paths = []
    raw = state["DropInPaths"].strip()
    if raw:
        prefix = str(directory / (name + ".d")) + "/"
        if not raw.startswith(prefix):
            raise ValueError("unreviewed unit drop-in path")
        selected = re.findall(re.escape(prefix) + r"[A-Za-z0-9_.-]+\.conf(?=$| )", raw)
        if " ".join(selected) != raw:
            raise ValueError("unreviewed unit drop-in path")
        for path_text in selected:
            path = Path(path_text)
            if not path_text.startswith(prefix) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.conf", path.name):
                raise ValueError("unreviewed unit drop-in path")
            _bytes(path)
            paths.append(path)
        if not retiring:
            raise ValueError("effective unit has unreviewed drop-ins")
    if not retiring:
        if state["EnvironmentFiles"].strip():
            raise ValueError("effective unit retains an EnvironmentFile")
        desired = expected.split("ExecStart=", 1)[1].splitlines()[0].replace("%%", "%") if "ExecStart=" in expected else ""
        actual = state["ExecStart"]
        match = re.search(r"argv\[\]=(.+?)(?:\s;|\s*})", actual)
        path_match = re.search(r"(?:^\{|;)\s*path=(.+?)(?:\s;|\s*})", actual)
        desired_argv = shlex.split(desired) if desired else []
        executable = path_match.group(1).strip() if path_match else ""
        if executable.startswith(('"', "'")):
            parsed_path = shlex.split(executable)
            executable = parsed_path[0] if len(parsed_path) == 1 else ""
        if desired_argv and (not match or shlex.split(match.group(1)) != desired_argv
                             or executable != desired_argv[0]):
            raise ValueError("unexpected effective ExecStart")
    return paths


def _idle(names) -> None:
    states = unit_states(names)
    if any(state.get("ActiveState") in BUSY_STATES for state in states.values()):
        raise ValueError("refresh/maintenance owner is busy; retry after its lifecycle finishes")


def verify_units(paths) -> None:
    verify_user_units(paths)


def _transaction(root: Path, payloads: dict[Path, bytes | None], *, modes: dict[Path, int] | None = None,
                 expected: dict[Path, bytes | None] | None = None) -> str:
    before = {path: _bytes(path) for path in payloads}
    if expected is not None and any(before[path] != content for path, content in expected.items()):
        raise ValueError("managed source changed before backup")
    identifier = uuid.uuid4().hex
    backup = root / "private/managed-backups" / identifier
    _safe_directory(backup)
    (root / "private").chmod(0o700)
    backup.chmod(0o700)
    records = []
    for index, (path, content) in enumerate(before.items()):
        entry = {"path": str(path), "before": _hash(content), "after": _hash(payloads[path]),
                 "mode": path.stat().st_mode & 0o777 if content is not None else (modes or {}).get(path, 0o600)}
        if content is not None:
            blob = f"{index}.blob"
            _atomic(backup / blob, content)
            entry["blob"] = blob
        records.append(entry)
    _atomic(backup / "rollback.json", json.dumps({"schema": 1, "files": records}, indent=2).encode())
    replaced = []
    try:
        for path, content in payloads.items():
            if _bytes(path) != before[path]:
                raise ValueError("managed input changed before publication")
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _atomic(path, content, (modes or {}).get(path, 0o600))
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            if before[path] is None:
                path.unlink(missing_ok=True)
            else:
                _atomic(path, before[path], next(entry["mode"] for entry in records if entry["path"] == str(path)))
        raise
    return identifier


def _render(root: Path, names: dict, python: Path, pages: tuple, interval: str, controls: bool, maintenance: bool) -> dict[str, str]:
    command = f"{_portable_arg(python)} -m chatglance.cli"
    replacements = {"COMMAND": command, "RUNTIME": _portable_arg(root), "INTERVAL": interval,
                    "REFRESH_UNIT": names["refresh"], "MAINTENANCE_UNIT": names["maintenance"]}
    roles = ["web"] + (["refresh", "refresh_timer"] if pages else []) + (["controls"] if controls else [])
    if maintenance:
        roles += ["maintenance", "maintenance_timer"]
    resources = {"refresh_timer": "refresh.timer", "maintenance_timer": "maintenance.timer"}
    rendered = {}
    for role in roles:
        text = files("chatglance").joinpath("resources", resources.get(role, role + ".service")).read_text()
        for key, value in replacements.items():
            text = text.replace(f"@@{key}@@", value)
        rendered[names[role]] = text
    return rendered


def install_runtime(root=None, *, unit_dir=None, pages=None, interval=None, controls=None, maintenance=None,
                    names: dict | None = None, python_bin=None, scheduled=None, adopt_units=False,
                    retire_dropins=False, apply=False, enable=False, start=False) -> dict:
    root = runtime_home(root)
    previous = load_manifest(root, required=False)
    names = {**DEFAULT_NAMES, **previous.get("names", {}), **(names or {})}
    for role, name in names.items():
        if role not in DEFAULT_NAMES:
            raise ValueError("invalid managed unit role")
        _unit_name(name, timer=role.endswith("timer"))
    if len(set(names.values())) != len(names):
        raise ValueError("owned unit names must be unique")
    settings = bridge_environment(home=_home(root))
    configured_pages = tuple(part for part in re.split(r"[\s,]+", settings.get("CHATGLANCE_REFRESH_PAGES", "")) if part)
    pages = tuple(previous.get("pages", configured_pages) if pages is None else pages)
    if any(page not in ("projects", "servers", "sites", "account-limits") for page in pages):
        raise ValueError("invalid managed refresh page")
    interval = interval or previous.get("interval", settings.get("CHATGLANCE_REFRESH_INTERVAL", "30min"))
    if not re.fullmatch(r"[1-9][0-9]*(?:s|min|h|d)", interval):
        raise ValueError("invalid managed cadence")
    scheduled = previous.get("scheduled", False) if scheduled is None else scheduled
    controls = previous.get("controls", False) if controls is None else controls
    maintenance = previous.get("maintenance", False) if maintenance is None else maintenance
    directory = Path(unit_dir or previous.get("unit_dir") or user_systemd_dir()).expanduser().absolute()
    python = Path(python_bin or sys.executable).expanduser()
    if not python.is_absolute() or not python.is_file():
        raise ValueError("installed Python interpreter must be an absolute regular file")
    bodies = _render(root, names, python, pages, interval, controls, maintenance)
    if previous and (set(previous["units"]) - set(bodies) or directory != Path(previous["unit_dir"])):
        raise ValueError("cannot abandon owned units; stop and retain the existing topology before changing ownership")
    manifest = {"schema": 1, "runtime_home": str(root), "chatenv_home": previous.get("chatenv_home", str(get_paths().home_dir)),
                "unit_dir": str(directory), "names": names, "pages": list(pages), "interval": interval,
                "scheduled": bool(scheduled), "controls": bool(controls), "maintenance": bool(maintenance),
                "interpreter": str(python), "package_version": __version__, "units": {
                    name: {"path": str(directory / name), "sha256": _hash(body.encode())} for name, body in bodies.items()}}
    result = {"applied": False, "units": list(bodies), "pages": list(pages), "interval": interval, "scheduled": bool(scheduled)}
    if (enable or start) and not apply:
        raise ValueError("enable/start require --apply")
    selected_dropins = {}
    prior_states = {}
    for name in bodies:
        target = directory / name
        existing = _bytes(target)
        known = previous.get("units", {}).get(name)
        if existing is not None and not adopt_units and (not known or known["sha256"] != _hash(existing)):
            raise ValueError("existing unit is not owned or was modified; use explicit --adopt-units after review")
        if existing is not None:
            state = unit_states([name])[name]
            prior_states[name] = state
            selected_dropins[name] = _effective(name, directory, bodies[name], state, retiring=True)
            if selected_dropins[name] and not retire_dropins:
                raise ValueError("unit drop-ins require explicit --retire-dropins after review")
    for alternative in ("chatglance-portable.service", "chatarch-glance.service"):
        if alternative != names["web"] and (directory / alternative).exists():
            raise ValueError("another Glance owner exists; adopt its existing unit name instead of creating duplicates")
    if not apply:
        return result
    from .refresh import _refresh_lock
    with _refresh_lock(root):
        _idle([names["refresh"], names["maintenance"]])
        environment = runtime_environment(root, auth=controls)
        if controls:
            origin = urlsplit(environment.get("CHATGLANCE_PUBLIC_ORIGIN", ""))
            if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
                raise ValueError("authenticated controls require a reviewed HTTPS origin")
        validate_candidate(root / "bin/glance", root / "config/glance.yml", environment)
        private = root / "private"
        _safe_directory(private)
        private.chmod(0o700)
        with tempfile.TemporaryDirectory(prefix="unit-review-", dir=private) as temporary:
            staged = []
            for name, body in bodies.items():
                path = Path(temporary) / name
                path.write_text(body)
                staged.append(path)
            verify_units(staged)
        payloads = {directory / name: body.encode() for name, body in bodies.items()}
        for paths in selected_dropins.values():
            payloads.update({path: None for path in paths})
        payloads[root / MANIFEST] = json.dumps(manifest, indent=2, sort_keys=True).encode()
        backup = _transaction(root, payloads, modes={directory / name: 0o644 for name in bodies})
        active = [names["web"]] + ([names["refresh_timer"]] if pages else [])
        active += [names["controls"]] if controls else []
        active += [names["maintenance_timer"]] if maintenance else []
        newly_enabled = []
        newly_started = []
        try:
            systemctl_user("daemon-reload")
            effective = unit_states(bodies)
            for name, body in bodies.items():
                _effective(name, directory, body, effective[name])
            for name in active:
                state = prior_states.get(name, {})
                if enable and state.get("UnitFileState") not in ("enabled", "enabled-runtime"):
                    newly_enabled.append(name)
                    systemctl_user("enable", name)
                if start and state.get("ActiveState") != "active":
                    newly_started.append(name)
                    systemctl_user("start", name)
        except Exception as original:
            problems = []
            for name in reversed(newly_started):
                try:
                    systemctl_user("stop", name)
                except Exception:
                    problems.append("new entry stop")
            for name in reversed(newly_enabled):
                try:
                    systemctl_user("disable", name)
                except Exception:
                    problems.append("new entry disable")
            try:
                rollback_runtime(root, backup, apply=True, reload=False, lock=False)
                systemctl_user("daemon-reload")
            except Exception:
                problems.append("file restore/reload")
            for name, state in prior_states.items():
                if state.get("ActiveState") == "active":
                    try:
                        if unit_states([name])[name].get("ActiveState") != "active":
                            systemctl_user("restart", name)
                        if unit_states([name])[name].get("ActiveState") != "active":
                            problems.append("old entry recovery")
                    except Exception:
                        problems.append("old entry recovery")
            if problems:
                raise ValueError("installation failed; rollback/recovery incomplete (" + ", ".join(problems) + ")") from original
            raise ValueError("installation failed; files and prior unit states restored") from original
    return {**result, "applied": True, "backup": backup, "enabled": enable, "started": start}


def adopt_runtime(root=None, *, apply=False, replace_provider=False, public_origin=None, control_port=None) -> dict:
    root = runtime_home(root)
    if root.parent != _home(root):
        raise ValueError("login adoption requires runtime inside the selected typed-provider home")
    config_path = root / "config/glance.yml"
    original = _bytes(config_path)
    if original is None:
        raise ValueError("runtime config is missing")
    config = yaml.safe_load(original)
    auth = config.get("auth") or {}
    users = auth.get("users") or {}
    if not isinstance(users, dict) or not users:
        raise ValueError("adoption requires existing Go login users")
    if auth.get("secret-key") == "${CHATGLANCE_LOGIN_SECRET}":
        return {"applied": False, "accounts": len(users), "already_adopted": True}
    values = {"CHATGLANCE_LOGIN_SECRET": str(auth.get("secret-key", ""))}
    accounts = {}
    candidate = deepcopy(config)
    migrated_users = {}
    for index, (username, account) in enumerate(users.items()):
        if not isinstance(account, dict) or account.get("password") or not account.get("password-hash"):
            raise ValueError("adoption requires bcrypt hashes, never plaintext passwords")
        authenticated_environment(environ={**values, "CHATGLANCE_LOGIN_USER": username,
                                           "CHATGLANCE_LOGIN_PASSWORD_HASH": account["password-hash"]})
        accounts[str(index)] = {"username": username, "password_hash": account["password-hash"]}
        migrated_users[f"${{CHATGLANCE_AUTH_USER_{index}}}"] = {**account, "password-hash": f"${{CHATGLANCE_AUTH_HASH_{index}}}"}
    values["CHATGLANCE_LOGIN_ACCOUNTS"] = json.dumps(accounts, separators=(",", ":"))
    candidate["auth"] = {**auth, "secret-key": "${CHATGLANCE_LOGIN_SECRET}", "users": migrated_users}
    server = candidate.get("server", {})
    port = server.get("port", 8080)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("adoption requires a reviewed numeric web port")
    values["CHATGLANCE_WEB_PORT"] = str(port)
    server["port"] = "${CHATGLANCE_WEB_PORT}"
    if public_origin is not None:
        origin = urlsplit(public_origin)
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            raise ValueError("public origin must be an exact HTTPS origin")
        values["CHATGLANCE_PUBLIC_ORIGIN"] = public_origin
    if control_port is not None:
        if not 1 <= control_port <= 65535:
            raise ValueError("invalid controls port")
        values["CHATGLANCE_CONTROL_PORT"] = str(control_port)
    store = EnvStore(get_paths(_home(root)).envs_dir)
    old_values = store.load_active(ChatGlanceConfig)
    provider_path = store.active_path(ChatGlanceConfig)
    provider_original = _bytes(provider_path)
    for key, value in values.items():
        existing = old_values.get(key)
        if key == "CHATGLANCE_LOGIN_ACCOUNTS" and existing == "{}":
            existing = None
        if existing and existing != value and not replace_provider:
            raise ValueError("existing typed provider value conflicts; authorize --replace-provider after review")
    result = {"applied": False, "accounts": len(accounts), "provider_keys": list(values), "pages": len(config.get("pages", []))}
    if not apply:
        return result
    from .refresh import _refresh_lock
    with _refresh_lock(root):
        private = root / "private"
        _safe_directory(private)
        private.chmod(0o700)
        with tempfile.TemporaryDirectory(prefix="auth-import-", dir=private) as temporary:
            staged = Path(temporary)
            config_text = yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False)
            candidate_path = staged / "glance.yml"
            candidate_path.write_text(config_text)
            candidate_path.chmod(0o600)
            environment = runtime_environment(root, values={**old_values, **values})
            validate_candidate(root / "bin/glance", candidate_path, environment)
            staged_store = EnvStore(staged / "envs")
            rendered_env = staged_store.save_active(ChatGlanceConfig, {**old_values, **values}).read_bytes()
            if _bytes(config_path) != original or store.load_active(ChatGlanceConfig) != old_values:
                raise ValueError("source config/provider changed during validation")
            backup = _transaction(root, {provider_path: rendered_env, config_path: config_text.encode()},
                                  expected={provider_path: provider_original, config_path: original})
    return {**result, "applied": True, "backup": backup}


def import_legacy_environment(root, source: str, *, apply=False, replace_provider=False, retire=False) -> dict:
    root = runtime_home(root)
    relative = Path(source)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("legacy input must be runtime-relative")
    path = root / relative
    if len(relative.parts) != 2 or relative.parts[0] not in ("config", "private") or not re.fullmatch(r"[A-Za-z0-9_.-]+\.env", relative.name):
        raise ValueError("legacy input must be a named private/config env file")
    original = _bytes(path)
    if original is None or len(original) > 65536:
        raise ValueError("legacy input missing or too large")
    schema = {field.env_key for field in ChatGlanceConfig.get_fields().values()}
    imported = {}
    ignored = []
    for line in original.decode("utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", line.strip())
        if not match:
            raise ValueError("invalid literal legacy environment line")
        key, value = match.groups()
        key = "CHATGLANCE_ACCOUNT_LIMITS_PROFILES" if key == "PROFILES" else key
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if "'" in value or "\n" in value or "\r" in value or "`" in value or "$(" in value or "${" in value:
            raise ValueError("legacy input contains unsafe expansion/quoting")
        if key in schema:
            if key in imported and imported[key] != value:
                raise ValueError("duplicate conflicting legacy setting")
            imported[key] = value
        else:
            ignored.append(key)
    store = EnvStore(get_paths(_home(root)).envs_dir)
    previous = store.load_active(ChatGlanceConfig)
    provider_path = store.active_path(ChatGlanceConfig)
    provider_before = _bytes(provider_path)
    for key, value in imported.items():
        if previous.get(key) and previous[key] != value and not replace_provider:
            raise ValueError("typed provider conflict; review --replace-provider")
    merged = {**previous, **imported}
    if any(merged.get(key) for key in AUTH_KEYS) and merged.get("CHATGLANCE_LOGIN_SECRET"):
        runtime_environment(root, auth=True, values=merged)
    result = {"applied": False, "imported_keys": sorted(imported), "ignored_keys": sorted(set(ignored)), "retire": retire}
    if not apply:
        return result
    from .refresh import _refresh_lock
    with _refresh_lock(root):
        if _bytes(path) != original or _bytes(provider_path) != provider_before:
            raise ValueError("legacy source/provider changed")
        private = root / "private"
        _safe_directory(private)
        private.chmod(0o700)
        with tempfile.TemporaryDirectory(prefix="import-env-", dir=private) as temporary:
            rendered = EnvStore(Path(temporary) / "envs").save_active(ChatGlanceConfig, merged).read_bytes()
        if EnvStore.load_path(store, provider_path) != previous:
            raise ValueError("typed provider changed")
        payloads = {provider_path: rendered}
        if retire:
            payloads[path] = None
        backup = _transaction(root, payloads, expected={provider_path: provider_before, **({path: original} if retire else {})})
        readback = store.load_active(ChatGlanceConfig)
        if any(readback.get(key) != value for key, value in imported.items()):
            rollback_runtime(root, backup, apply=True, reload=False, lock=False)
            raise ValueError("typed provider readback failed; restored input")
    return {**result, "applied": True, "backup": backup}


def service_action(root, action: str, *, units=(), apply=False) -> dict:
    if action not in {"start", "stop", "restart"}:
        raise ValueError("invalid managed service action")
    root = runtime_home(root)
    manifest = load_manifest(root)
    defaults = [name for name in manifest["units"] if name not in (manifest["names"]["refresh"], manifest["names"]["maintenance"])]
    selected = list(units or defaults)
    if any(name not in manifest["units"] for name in selected):
        raise ValueError("service action targets an unowned unit")
    if not apply:
        return {"applied": False, "action": action, "units": selected}
    from .refresh import _refresh_lock
    with _refresh_lock(root):
        _idle([manifest["names"]["refresh"], manifest["names"]["maintenance"]])
        for name in selected:
            item = manifest["units"][name]
            if _hash(_bytes(Path(item["path"]))) != item["sha256"]:
                raise ValueError("owned unit changed; inspect before operating")
        systemctl_user(action, *selected)
    return {"applied": True, "action": action, "units": selected}


def runtime_status(root=None, *, live=False, validate=False) -> dict:
    root = runtime_home(root)
    manifest = load_manifest(root, required=False)
    config_bytes = _bytes(root / "config/glance.yml")
    config = yaml.safe_load(config_bytes) if config_bytes else {}
    auth = config.get("auth") or {}
    binary = root / "bin/glance"
    provenance_bytes = _bytes(root / "bin/glance.provenance.json")
    provenance = json.loads(provenance_bytes) if provenance_bytes else {}
    safe_provenance = {key: provenance.get(key) for key in ("version", "source_tag", "source_revision", "archive_sha256", "binary_sha256")}
    units = {}
    for name, entry in manifest.get("units", {}).items():
        content = _bytes(Path(entry["path"]))
        units[name] = {"sha256": _hash(content), "matches": _hash(content) == entry["sha256"],
                       "exec_start": next((line.removeprefix("ExecStart=") for line in (content or b"").decode().splitlines() if line.startswith("ExecStart=")), None)
                       if _hash(content) == entry["sha256"] else None}
    effective = unit_states(units) if units else {}
    effective_matches = bool(units)
    for name, entry in manifest.get("units", {}).items():
        try:
            _effective(name, Path(manifest["unit_dir"]), (_bytes(Path(entry["path"])) or b"").decode(), effective[name])
        except (ValueError, KeyError, UnicodeError):
            effective_matches = False
    result = {"package_version": __version__, "package_path": str(Path(__file__).parent), "interpreter": sys.executable,
              "runtime_home": str(root), "managed": bool(manifest), "binary": safe_provenance,
              "binary_sha256": _hash(_bytes(binary)), "config_sha256": _hash(config_bytes),
              "accounts": len(auth.get("users") or {}), "auth_environment_backed": auth.get("secret-key") == "${CHATGLANCE_LOGIN_SECRET}",
              "pages": len(config.get("pages", [])), "selected_pages": manifest.get("pages", []),
              "cadence": manifest.get("interval"), "scheduled": manifest.get("scheduled", False), "units": units,
              "effective_matches": effective_matches}
    result["binary_matches"] = bool(provenance.get("binary_sha256")) and result["binary_sha256"] == provenance["binary_sha256"]
    environment = runtime_environment(root)
    ports = {"web": environment.get("CHATGLANCE_WEB_PORT", "8080"), "controls": environment.get("CHATGLANCE_CONTROL_PORT", "5679")}
    if any(not str(port).isdigit() or not 1 <= int(port) <= 65535 for port in ports.values()):
        raise ValueError("invalid runtime port setting")
    result["ports"] = {key: int(value) for key, value in ports.items()}
    if live and units:
        result["live_units"] = {name: {key: state.get(key) for key in ("ActiveState", "SubState", "MainPID", "UnitFileState")}
                                for name, state in effective.items()}
    if validate:
        try:
            observed = subprocess.run([str(binary), "--version"], capture_output=True, text=True, check=True,
                                      timeout=5, env={"PATH": "/usr/bin:/bin"}).stdout.strip()
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise ValueError("installed binary version could not be verified") from None
        if not re.fullmatch(r"chatarch-v[0-9]+\.[0-9]+\.[0-9]+\+[0-9a-f]{40}", observed):
            raise ValueError("installed binary is not a maintained version")
        result["observed_binary_version"] = observed
        result["binary_matches"] = result["binary_matches"] and observed == provenance.get("version")
        validate_candidate(binary, root / "config/glance.yml", environment)
        result["config_validated"] = True
    return result


def rollback_runtime(root, backup: str, *, apply=False, reload=True, lock=True) -> dict:
    root = runtime_home(root)
    if not re.fullmatch(r"[a-f0-9]{32}", backup):
        raise ValueError("invalid managed backup identifier")
    manifest = load_manifest(root, required=False)
    directory = root / "private/managed-backups" / backup
    record = json.loads(_bytes(directory / "rollback.json"))
    allowed = {root / "config/glance.yml", root / "bin/glance", root / "bin/glance.provenance.json", root / MANIFEST,
               EnvStore(get_paths(_home(root)).envs_dir).active_path(ChatGlanceConfig)}
    allowed.update(Path(entry["path"]) for entry in manifest.get("units", {}).values())
    for name in manifest.get("units", {}):
        dropin_dir = Path(manifest["unit_dir"]) / (name + ".d")
        if dropin_dir.is_dir() and not dropin_dir.is_symlink():
            allowed.update(path for path in dropin_dir.glob("*.conf") if re.fullmatch(r"[A-Za-z0-9_.-]+\.conf", path.name))
    entries = record["files"]
    restored = {}
    for entry in entries:
        target = Path(entry["path"])
        if target.parent in (root / "config", root / "private") and re.fullmatch(r"[A-Za-z0-9_.-]+\.env", target.name):
            allowed.add(target)
        for name in manifest.get("units", {}):
            if target.parent == Path(manifest["unit_dir"]) / (name + ".d") and re.fullmatch(r"[A-Za-z0-9_.-]+\.conf", target.name):
                allowed.add(target)
        if target not in allowed or _hash(_bytes(target)) != entry["after"]:
            raise ValueError("rollback target is unowned or changed")
        if entry.get("blob"):
            if not re.fullmatch(r"[0-9]+\.blob", entry["blob"]):
                raise ValueError("invalid rollback blob path")
            content = _bytes(directory / entry["blob"])
            if content is None or _hash(content) != entry["before"]:
                raise ValueError("rollback backup digest mismatch")
            restored[target] = content
    if not apply:
        return {"applied": False, "backup": backup, "files": len(entries)}
    if lock:
        from .refresh import _refresh_lock
        with _refresh_lock(root):
            if manifest:
                _idle([manifest["names"]["refresh"], manifest["names"]["maintenance"]])
            return rollback_runtime(root, backup, apply=True, reload=reload, lock=False)
    for entry in reversed(entries):
        target = Path(entry["path"])
        if entry.get("blob"):
            _atomic(target, restored[target], entry["mode"])
        else:
            target.unlink(missing_ok=True)
    if reload and manifest:
        systemctl_user("daemon-reload")
    return {"applied": True, "backup": backup, "files": len(entries)}


def update_binary(root, archive, sha256, version, *, apply=False, restart=False) -> dict:
    root = runtime_home(root)
    manifest = load_manifest(root)
    if not apply:
        return {"applied": False, "expected_version": version, "restart": restart}
    from .refresh import _refresh_lock
    with _refresh_lock(root):
        _idle([manifest["names"]["refresh"], manifest["names"]["maintenance"]])
        private = root / "private"
        _safe_directory(private)
        with tempfile.TemporaryDirectory(prefix="binary-update-", dir=private) as temporary:
            staged = Path(temporary)
            binary = install_verified_binary(archive, sha256, staged, version=version)
            validate_candidate(binary, root / "config/glance.yml", runtime_environment(root))
            backup = _transaction(root, {root / "bin/glance": binary.read_bytes(),
                                        root / "bin/glance.provenance.json": (staged / "bin/glance.provenance.json").read_bytes()},
                                  modes={root / "bin/glance": 0o755})
        if restart:
            web = manifest["names"]["web"]
            was_active = unit_states([web])[web].get("ActiveState") == "active"
            try:
                systemctl_user("restart", web)
                if unit_states([web])[web].get("ActiveState") != "active":
                    raise ValueError("updated web failed active-state readback")
            except Exception as original:
                try:
                    rollback_runtime(root, backup, apply=True, reload=False, lock=False)
                except Exception:
                    raise ValueError("binary restart failed; old binary restore failed") from original
                if was_active:
                    try:
                        systemctl_user("restart", web)
                        recovered = unit_states([web])[web]
                        if recovered.get("ActiveState") != "active" or not recovered.get("MainPID", "0").isdigit() or int(recovered["MainPID"]) <= 0:
                            raise ValueError("old web recovery readback failed")
                    except Exception:
                        raise ValueError("binary restored; previously active web recovery failed") from original
                raise ValueError("binary restored; restart failed; old web state recovered") from original
    return {"applied": True, "version": version, "backup": backup, "restarted": restart}


def refresh_managed(root):
    root = runtime_home(root)
    manifest = load_manifest(root)
    if not manifest["pages"]:
        raise ValueError("no managed refresh pages were selected")
    from .refresh import refresh_runtime
    with effective_home(root):
        return refresh_runtime(root, manifest["pages"], service_name=manifest["names"]["web"], scheduled=manifest["scheduled"])


def maintain_managed(root):
    root = runtime_home(root)
    manifest = load_manifest(root)
    if not manifest["maintenance"]:
        raise ValueError("managed maintenance is not enabled")
    _idle([manifest["names"]["refresh"]])
    from .refresh import _refresh_lock
    from .runtime import maintain_config
    with effective_home(root), _refresh_lock(root):
        result = maintain_config(config_path=root / "config/glance.yml", data_path=root / "data/chatarch-projects.json",
                                 validate_bin=root / "bin/glance", restart_service=manifest["names"]["web"])
    return {"changed": result.changed, "validated": result.validated, "restarted": result.restarted}
