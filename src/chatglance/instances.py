"""Private, read-only Glance instances sharing the installed collectors and Go binary."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from copy import deepcopy
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import sys
import tempfile
from urllib.parse import urlsplit

from chatenv import EnvStore, get_paths
import yaml

from .config import ChatGlanceConfig, named_profile_values
from .page_modules import MODULES, render_page
from .subscriptions import parse_subscriptions

MANIFEST = Path("private/instance.json")
OWNER_MARKER = Path("private/instance-owned")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _safe_root(root: str | Path) -> Path:
    source = Path(root).expanduser()
    if not source.is_absolute() or ".." in source.parts:
        raise ValueError("instance runtime must be a clean absolute path")
    path = source.absolute()
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError("instance runtime must be a non-root absolute path")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("instance runtime path contains a symlink")
    return path


@dataclass(frozen=True)
class InstanceSpec:
    name: str
    env_profile: str
    pages: tuple[str, ...]
    accounts: tuple[str, ...] = ()
    host: str = "127.0.0.1"
    port: int = 8080
    origin: str = ""
    read_only: bool = True
    interval_seconds: int = 1800
    python_bin: str | None = None
    glance_bin: str | None = None

    def __post_init__(self) -> None:
        from .reset_control import validated_private_host
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise ValueError("invalid instance name")
        if (not isinstance(self.env_profile, str) or not _NAME.fullmatch(self.env_profile)
                or self.env_profile == "default"):
            raise ValueError("an explicit non-default named ChatGlance profile is required")
        if (not isinstance(self.pages, (tuple, list)) or not self.pages
                or any(not isinstance(page, str) or page not in MODULES for page in self.pages)
                or len(set(self.pages)) != len(self.pages)):
            raise ValueError("instance pages must be distinct known modules")
        if (not isinstance(self.accounts, (tuple, list))
                or any(not isinstance(label, str) or not _LABEL.fullmatch(label) for label in self.accounts)
                or len(set(self.accounts)) != len(self.accounts)):
            raise ValueError("invalid account label selection")
        if ("account-limits" in self.pages) != bool(self.accounts):
            raise ValueError("account-limits requires a nonempty account subset, and other pages cannot set accounts")
        if type(self.read_only) is not bool or not self.read_only:
            raise ValueError("only read-only instances are supported")
        if validated_private_host(self.host) != self.host:
            raise ValueError("invalid instance host")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("invalid instance port")
        try:
            parsed = urlsplit(self.origin)
            origin_port = parsed.port
        except (TypeError, ValueError) as exc:
            raise ValueError("instance origin must be a path-free HTTPS origin") from exc
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or not parsed.netloc
                or (origin_port is not None and not 1 <= origin_port <= 65535)):
            raise ValueError("instance origin must be a path-free HTTPS origin")
        if type(self.interval_seconds) is not int or not 60 <= self.interval_seconds <= 86400:
            raise ValueError("instance refresh interval must be 60-86400 seconds")
        if self.python_bin is not None and (not isinstance(self.python_bin, str) or not Path(self.python_bin).is_absolute()):
            raise ValueError("instance interpreter must be an absolute path")
        if self.glance_bin is not None and (not isinstance(self.glance_bin, str) or not Path(self.glance_bin).is_absolute()
                or ".." in Path(self.glance_bin).parts):
            raise ValueError("shared Glance binary must be an absolute clean path")
        object.__setattr__(self, "pages", tuple(self.pages))
        object.__setattr__(self, "accounts", tuple(self.accounts))

    @property
    def web_label(self) -> str:
        return f"chatarch-glance.{self.name}.service"

    @property
    def refresh_label(self) -> str:
        return f"chatarch-glance.{self.name}.refresh"


def _profile(spec: InstanceSpec, *, home: str | Path | None = None) -> dict:
    values = named_profile_values(spec.env_profile, home=home)
    if spec.accounts:
        registry = parse_subscriptions(values.get("CHATGLANCE_ACCOUNT_LIMITS_SUBSCRIPTIONS"))
        if registry is None or any(label not in registry or not registry[label]["enabled"]
                                   or registry[label].get("removed") for label in spec.accounts):
            raise ValueError("instance accounts must be enabled tracked subscriptions in its named profile")
    return values


def _manifest_payload(root: Path, spec: InstanceSpec, *, chatenv_home: str | Path | None = None) -> dict:
    return {"schema": 1, "runtime_home": str(root), "spec": asdict(spec),
            "chatenv_home": str(chatenv_home or get_paths().home_dir),
            "service": {"web_label": spec.web_label, "refresh_label": spec.refresh_label,
                        "python_bin": spec.python_bin or sys.executable}}


def load_instance(root: str | Path, *, required: bool = True) -> InstanceSpec | None:
    root = Path(root).expanduser().absolute()
    path = root / MANIFEST
    marker = root / OWNER_MARKER
    if not path.exists() and not path.is_symlink() and not marker.exists() and not marker.is_symlink() and not required:
        return None
    root = _safe_root(root)
    if (root / "private").is_symlink():
        raise ValueError("instance private directory is unsafe")
    if (marker.is_symlink() or not marker.is_file() or marker.stat().st_mode & 0o077
            or marker.read_text(encoding="utf-8") != str(root) + "\n"):
        raise ValueError("instance ownership marker is missing or unsafe")
    if path.is_symlink():
        raise ValueError("instance manifest is unsafe")
    if not path.exists():
        raise ValueError("instance manifest is missing")
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("instance manifest is unsafe")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        spec = InstanceSpec(**raw["spec"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("instance manifest is invalid") from exc
    service = raw.get("service")
    home = raw.get("chatenv_home")
    if (raw.get("schema") != 1 or raw.get("runtime_home") != str(root)
            or not isinstance(home, str) or not Path(home).is_absolute() or ".." in Path(home).parts
            or any(part.is_symlink() for part in (Path(home), *Path(home).parents))
            or not isinstance(service, dict)
            or set(service) != {"web_label", "refresh_label", "python_bin"}
            or service["web_label"] != spec.web_label or service["refresh_label"] != spec.refresh_label
            or not isinstance(service["python_bin"], str) or not Path(service["python_bin"]).is_absolute()
            or (spec.python_bin is not None and service["python_bin"] != spec.python_bin)):
        raise ValueError("instance ownership does not match runtime")
    children = [root / name for name in ("config", "config/backups", "data", "staging", "logs", "bin")]
    children += [root / "config/glance.yml", root / "bin/glance"]
    if "servers" in spec.pages:
        children.append(root / "config/server-inventory.yml")
    if "sites" in spec.pages:
        children.append(root / "config/site-services.yml")
    for key in spec.pages:
        children.extend((root / "data" / MODULES[key].snapshot, root / "data" / MODULES[key].page_file))
    if any(child.is_symlink() for child in children):
        raise ValueError("instance runtime contains an unsafe symlink")
    backups = root / "config/backups"
    if backups.exists() and not backups.is_dir():
        raise ValueError("instance backup directory is unsafe")
    return spec


def service_identity(root: str | Path) -> dict:
    load_instance(root)
    return json.loads((_safe_root(root) / MANIFEST).read_text(encoding="utf-8"))["service"]


def instance_home(root: str | Path) -> Path:
    load_instance(root)
    return Path(json.loads((_safe_root(root) / MANIFEST).read_text(encoding="utf-8"))["chatenv_home"])


def instance_binary(root: str | Path, spec: InstanceSpec | None = None) -> Path:
    root = _safe_root(root)
    spec = spec or load_instance(root)
    binary = Path(spec.glance_bin) if spec.glance_bin else root / "bin/glance"
    if any(part.is_symlink() for part in (binary, *binary.parents)):
        raise ValueError("instance Go binary path is unsafe")
    return binary


def _empty_snapshot(key: str) -> dict:
    return {"projects": {"repositories": [], "generated_at": None},
            "servers": {"servers": [], "count": 0, "online": 0, "generated_at": None},
            "sites": {"sites": [], "generated_at": None},
            "account-limits": {"accounts": [], "codex": [], "generated_at": None,
                               "codex_reset": {"status": "skipped", "events": []},
                               "reset_control_path": "", "resources": []}}[key]


def scope_account_data(data: dict, accounts: tuple[str, ...]) -> dict:
    """Prune every account-bearing snapshot field to the authorized labels."""
    selected = set(accounts)
    result = {key: deepcopy(data[key]) for key in ("generated_at", "collector_version", "codex_reset") if key in data}
    result["codex"] = []
    for row in data.get("codex", []):
        if isinstance(row, dict) and row.get("profile") in selected:
            scoped = deepcopy(row)
            if isinstance(scoped.get("reset_history"), list):
                scoped["reset_history"] = [item for item in scoped["reset_history"] if isinstance(item, dict)
                                            and item.get("profile") in selected]
            result["codex"].append(scoped)
    result["accounts"] = [deepcopy(row) for row in data.get("accounts", []) if isinstance(row, dict)
                          and (row.get("profile") or row.get("account_name")) in selected]
    result["reset_control_path"] = ""
    resources = []
    for resource in data.get("resources", []):
        if isinstance(resource, dict):
            resources.append({**deepcopy(resource), "profiles": [label for label in resource.get("profiles", []) if label in selected]})
    result["resources"] = resources
    status = data.get("refresh_status")
    if isinstance(status, dict):
        result["refresh_status"] = {**deepcopy(status),
            "profiles_total": len(result["codex"]),
            "ok_profiles": [p for p in status.get("ok_profiles", []) if p in selected],
            "failed_profiles": [p for p in status.get("failed_profiles", []) if p in selected]}
        result["refresh_status"]["ok_count"] = len(result["refresh_status"]["ok_profiles"])
        result["refresh_status"]["failed_count"] = len(result["refresh_status"]["failed_profiles"])
        failed = result["refresh_status"]["failed_profiles"]
        result["refresh_status"]["status"] = "ok" if not failed else "partial" if result["refresh_status"]["ok_profiles"] else "error"
        result["refresh_status"]["message"] = "all profiles refreshed" if not failed else "failed_profiles=" + ",".join(failed)
    reset = result.get("codex_reset")
    if isinstance(reset, dict) and isinstance(reset.get("events"), list):
        reset["events"] = [item for item in reset["events"] if not isinstance(item, dict)
                           or "profile" not in item or item["profile"] in selected]
    return result


def _server_definition(spec: InstanceSpec) -> dict:
    return {"host": spec.host, "port": spec.port, "proxied": True}


def _auth_definition(*, raw: bool = False) -> dict:
    credential = ({"password": "${CHATGLANCE_LOGIN_PASSWORD_YAML}"} if raw else
                  {"password-hash": "${CHATGLANCE_LOGIN_PASSWORD_HASH}"})
    return {"secret-key": "${CHATGLANCE_LOGIN_SECRET}",
            "users": {"${CHATGLANCE_LOGIN_USER}": credential}}


def _raw_auth(root: Path) -> bool:
    config = yaml.safe_load((root / "config/glance.yml").read_text(encoding="utf-8"))
    return config["auth"] == _auth_definition(raw=True)


def _assembled(root: Path, spec: InstanceSpec, *, existing: bool, raw_auth: bool) -> tuple[dict, dict[str, dict]]:
    snapshots = {}
    for key in spec.pages:
        path = root / "data" / MODULES[key].snapshot
        if path.is_symlink():
            raise ValueError("instance snapshot is unsafe")
        data = json.loads(path.read_text(encoding="utf-8")) if existing and path.is_file() else _empty_snapshot(key)
        snapshots[key] = scope_account_data(data, spec.accounts) if key == "account-limits" else data
    config = {"server": _server_definition(spec),
              "pages": [render_page(key, snapshots[key], allow_controls=False) for key in spec.pages],
              "auth": _auth_definition(raw=raw_auth)}
    return config, snapshots


def verify_config_pages(root: str | Path, spec: InstanceSpec | None = None) -> None:
    root = _safe_root(root)
    spec = spec or load_instance(root)
    path = root / "config/glance.yml"
    if path.is_symlink() or not path.is_file():
        raise ValueError("instance config is missing or unsafe")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    pages = config.get("pages") if isinstance(config, dict) else None
    if (not isinstance(pages, list) or len(pages) != len(spec.pages)
            or any(not isinstance(page, dict) or page.get("slug") != key
                   or page.get("name") != MODULES[key].name for page, key in zip(pages, spec.pages))):
        raise ValueError("instance config pages do not match its allowlist")
    if set(config) != {"server", "pages", "auth"}:
        raise ValueError("instance config contains unreviewed global content")
    server = config["server"]
    expected_server = _server_definition(spec)
    if (not isinstance(server, dict) or set(server) != set(expected_server)
            or any(type(server[key]) is not type(value) or server[key] != value
                   for key, value in expected_server.items())
            or config["auth"] not in (_auth_definition(), _auth_definition(raw=True))):
        raise ValueError("instance config native server or login does not match its manifest")


def initialize_instance(root: str | Path, spec: InstanceSpec, *, apply: bool = False) -> dict:
    root = _safe_root(root)
    if not isinstance(spec, InstanceSpec):
        raise ValueError("invalid instance specification")
    instance_binary(root, spec)
    main_root = (Path(get_paths().home_dir) / "glance").absolute()
    if root == main_root or main_root in root.parents or root == Path(get_paths().home_dir).absolute():
        raise ValueError("instance runtime collides with the default site")
    if root.exists() or root.is_symlink() or not root.parent.is_dir():
        raise ValueError("instance runtime already exists or parent is unavailable")
    result = {"applied": False, "runtime_home": str(root), "name": spec.name,
              "pages": list(spec.pages), "accounts": list(spec.accounts), "web_label": spec.web_label}
    if not apply:
        return result
    values = _profile(spec)
    config, snapshots = _assembled(root, spec, existing=False,
                                   raw_auth="CHATGLANCE_LOGIN_PASSWORD" in values)
    stage = Path(tempfile.mkdtemp(prefix=".chatglance-instance-", dir=root.parent))
    try:
        for directory in ("private", "config", "data", "bin", "logs", "staging"):
            (stage / directory).mkdir(mode=0o700)
        (stage / MANIFEST).write_text(json.dumps(_manifest_payload(root, spec), indent=2) + "\n", encoding="utf-8")
        (stage / MANIFEST).chmod(0o600)
        (stage / OWNER_MARKER).write_text(str(root) + "\n", encoding="utf-8")
        (stage / OWNER_MARKER).chmod(0o600)
        (stage / "config/glance.yml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        (stage / "config/glance.yml").chmod(0o600)
        for key, data in snapshots.items():
            (stage / "data" / MODULES[key].snapshot).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (stage / "data" / MODULES[key].page_file).write_text(yaml.safe_dump(config["pages"][list(spec.pages).index(key)], allow_unicode=True, sort_keys=False), encoding="utf-8")
        if root.exists() or root.is_symlink():
            raise ValueError("instance runtime now exists")
        os.replace(stage, root)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {**result, "applied": True}


def configure_instance(root: str | Path, spec: InstanceSpec, *, apply: bool = False) -> dict:
    root = _safe_root(root)
    if not isinstance(spec, InstanceSpec):
        raise ValueError("invalid instance specification")
    instance_binary(root, spec)
    old = load_instance(root)
    if spec.name != old.name or spec.env_profile != old.env_profile:
        raise ValueError("instance identity and named profile cannot change in place")
    _profile(spec, home=instance_home(root))
    if apply:
        from .refresh import _refresh_lock
        with _refresh_lock(root):
            return _configure_instance(root, spec, apply=True)
    return _configure_instance(root, spec, apply=False)


def _configure_instance(root: Path, spec: InstanceSpec, *, apply: bool) -> dict:
    old = load_instance(root)
    home = instance_home(root)
    if spec.name != old.name or spec.env_profile != old.env_profile:
        raise ValueError("instance identity and named profile cannot change in place")
    values = _profile(spec, home=home)
    verify_config_pages(root, old)
    config, snapshots = _assembled(root, spec, existing=True,
                                   raw_auth="CHATGLANCE_LOGIN_PASSWORD" in values)
    result = {"applied": False, "runtime_home": str(root), "pages": list(spec.pages), "accounts": list(spec.accounts)}
    if not apply:
        return result
    payloads = {root / MANIFEST: json.dumps(_manifest_payload(root, spec, chatenv_home=home), indent=2) + "\n",
                root / "config/glance.yml": yaml.safe_dump(config, allow_unicode=True, sort_keys=False)}
    for key, data in snapshots.items():
        payloads[root / "data" / MODULES[key].snapshot] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        payloads[root / "data" / MODULES[key].page_file] = yaml.safe_dump(config["pages"][list(spec.pages).index(key)], allow_unicode=True, sort_keys=False)
    with tempfile.TemporaryDirectory(prefix=".instance-configure-", dir=root / "staging") as temporary:
        stage = Path(temporary)
        previous = {path: path.read_bytes() if path.exists() else None for path in payloads}
        for index, (path, body) in enumerate(payloads.items()):
            if path.is_symlink() or not path.parent.is_dir():
                raise ValueError("instance target is unsafe")
            prepared = stage / str(index)
            prepared.write_text(body, encoding="utf-8")
            prepared.chmod(0o600)
        replaced = []
        try:
            for index, path in enumerate(payloads):
                os.replace(stage / str(index), path)
                replaced.append(path)
        except OSError:
            for path in reversed(replaced):
                old_bytes = previous[path]
                if old_bytes is None:
                    path.unlink(missing_ok=True)
                else:
                    restore = stage / "restore"
                    restore.write_bytes(old_bytes)
                    restore.chmod(0o600)
                    os.replace(restore, path)
            raise
    return {**result, "applied": True}


def set_instance_login(root: str | Path, *, username: str, password: str, apply: bool = False) -> dict:
    from .portable import authenticated_environment, validate_native_password
    from .refresh import _publish, _refresh_lock
    root = _safe_root(root)
    spec = load_instance(root)
    home = instance_home(root)
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+@-]{2,49}", username):
        raise ValueError("invalid login username")
    validate_native_password(password)
    values = _profile(spec, home=home)
    result = {"applied": False, "runtime_home": str(root), "env_profile": spec.env_profile,
              "username": username}
    if not apply:
        return result
    with _refresh_lock(root):
        spec = load_instance(root)
        verify_config_pages(root, spec)
        values = _profile(spec, home=instance_home(root))
        updated = dict(values)
        updated.pop("CHATGLANCE_LOGIN_PASSWORD_HASH", None)
        updated.pop("CHATGLANCE_LOGIN_PASSWORD_YAML", None)
        updated.update({"CHATGLANCE_LOGIN_USER": username,
                        "CHATGLANCE_LOGIN_PASSWORD": password,
                        "CHATGLANCE_LOGIN_SECRET": base64.b64encode(secrets.token_bytes(64)).decode("ascii"),
                        "CHATGLANCE_LOGIN_ACCOUNTS": "{}"})
        authenticated_environment(environ={"CHATGLANCE_WEB_PORT": str(spec.port), **updated}, strict=True)
        store = EnvStore(get_paths(home).envs_dir)
        config_path = root / "config/glance.yml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["auth"] = _auth_definition(raw=True)
        try:
            store.save_profile(ChatGlanceConfig, spec.env_profile, updated)
            if store.load_profile(ChatGlanceConfig, spec.env_profile).get("CHATGLANCE_LOGIN_PASSWORD") != password:
                raise ValueError("login password did not round-trip through ChatEnv")
            with tempfile.TemporaryDirectory(prefix=".instance-login-", dir=root / "staging") as temporary:
                _publish(root, Path(temporary), {config_path: yaml.safe_dump(config, allow_unicode=True, sort_keys=False)}, instance=True)
        except Exception:
            store.save_profile(ChatGlanceConfig, spec.env_profile, values)
            raise
    return {**result, "applied": True}


def instance_environment(root: str | Path, *, auth: bool = True) -> dict[str, str]:
    from .portable import authenticated_environment
    spec = load_instance(root)
    verify_config_pages(root, spec)
    home = instance_home(root)
    values = _profile(spec, home=home)
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    environment["CHATARCH_HOME"] = str(home)
    environment["CHATGLANCE_WEB_PORT"] = str(spec.port)
    environment["CHATGLANCE_PUBLIC_ORIGIN"] = spec.origin
    raw = _raw_auth(_safe_root(root))
    for key in ("CHATGLANCE_LOGIN_USER", "CHATGLANCE_LOGIN_PASSWORD_HASH", "CHATGLANCE_LOGIN_PASSWORD", "CHATGLANCE_LOGIN_SECRET"):
        if values.get(key):
            environment[key] = str(values[key])
    if values.get("CHATGLANCE_LOGIN_ACCOUNTS", "{}") not in ("", "{}"):
        raise ValueError("instance login must contain exactly one user")
    if raw and not values.get("CHATGLANCE_LOGIN_PASSWORD"):
        raise ValueError("instance native raw login password is missing")
    if not raw and values.get("CHATGLANCE_LOGIN_PASSWORD"):
        raise ValueError("instance raw login requires its native password template")
    return authenticated_environment(environ=environment, strict=True) if auth or raw else environment


def render_launchd_instance(root: str | Path, *, python_bin: Path | None = None) -> dict[str, bytes]:
    root = _safe_root(root)
    spec = load_instance(root)
    service = service_identity(root)
    python = Path(python_bin or service["python_bin"])
    if str(python) != service["python_bin"] or not python.is_absolute() or not python.is_file():
        raise ValueError("instance interpreter does not match owned service identity")
    web = {"Label": spec.web_label,
           "ProgramArguments": [str(python), "-m", "chatglance.cli", "runtime", "serve", "--runtime-home", str(root)],
           "RunAtLoad": True, "KeepAlive": True}
    refresh = {"Label": spec.refresh_label,
               "ProgramArguments": [str(python), "-m", "chatglance.cli", "refresh", "--runtime-home", str(root)],
               "StartInterval": spec.interval_seconds, "RunAtLoad": False}
    return {f"{spec.web_label}.plist": plistlib.dumps(web),
            f"{spec.refresh_label}.plist": plistlib.dumps(refresh)}
