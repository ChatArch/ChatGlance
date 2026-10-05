"""Portable resource bootstrap, verified binary installation and Go process bridge."""

from __future__ import annotations

import base64
import binascii
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from chatenv import EnvStore, get_paths

from .config import ChatGlanceConfig


RESOURCES = {
    "glance.yml": "config/glance.yml",
    "server-inventory.yml": "config/server-inventory.yml",
    "site-services.yml": "config/site-services.yml",
    "reverse-proxy.example.conf": "config/reverse-proxy.example.conf",
    "start.sh": "scripts/start.sh",
    "install.sh": "scripts/install.sh",
    "refresh.sh": "scripts/refresh.sh",
}


def runtime_home(home: str | Path | None = None) -> Path:
    """Use the active ChatArch home unless an explicit runtime home was supplied."""
    return Path(home).expanduser().absolute() if home is not None else Path(get_paths().home_dir) / "glance"


def _safe_directory(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("runtime path contains a symlink")
    if path.exists() and not path.is_dir():
        raise ValueError("runtime directory is not a directory")
    path.mkdir(parents=True, exist_ok=True)


def _create(path: Path, content: bytes, mode: int = 0o644) -> bool:
    _safe_directory(path.parent)
    if path.is_symlink():
        raise ValueError("runtime target is a symlink")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    except FileExistsError:
        if not path.is_file():
            raise ValueError("runtime target is not a regular file") from None
        return False
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
    return True


def initialize(home: str | Path | None = None, *, with_auth: bool = False) -> list[Path]:
    """Materialize non-secret starter resources without replacing existing artifacts."""
    root = runtime_home(home)
    if with_auth:
        authenticated_environment()
        existing = root / "config/glance.yml"
        if existing.is_symlink():
            raise ValueError("runtime target is a symlink")
        if existing.exists() and (
            not existing.is_file() or not all(marker in existing.read_text(encoding="utf-8") for marker in (
                "${CHATGLANCE_LOGIN_SECRET}", "${CHATGLANCE_LOGIN_USER}", "${CHATGLANCE_LOGIN_PASSWORD_HASH}",
            ))
        ):
            raise ValueError("existing config has no environment-backed login; review migration before retrying")
    created = []
    for source, target in RESOURCES.items():
        destination = root / target
        content = files("chatglance").joinpath("resources", source).read_bytes()
        if source == "glance.yml" and with_auth:
            content += ("auth:\n  secret-key: ${CHATGLANCE_LOGIN_SECRET}\n"
                        '  users:\n    "${CHATGLANCE_LOGIN_USER}":\n'
                        "      password-hash: ${CHATGLANCE_LOGIN_PASSWORD_HASH}\n").encode()
        if _create(destination, content,
                   0o755 if source.endswith(".sh") else 0o644):
            created.append(destination)
    for directory in ("data", "logs", "staging", "bin"):
        _safe_directory(root / directory)
    for name, value in {
        "chatarch-projects.json": {"repositories": [], "generated_at": None},
        "server-status.json": {"servers": [], "generated_at": None},
        "site-services.json": {"sites": [], "generated_at": None},
        "account-limits.json": {"accounts": [], "generated_at": None},
    }.items():
        destination = root / "data" / name
        if _create(destination, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()):
            created.append(destination)
    return created


def install_verified_binary(archive: str | Path, sha256: str, home: str | Path | None = None, *, version: str) -> Path:
    """Install only a caller-supplied verified tar archive; never select a release."""
    if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256):
        raise ValueError("expected SHA256 must be 64 hex characters")
    if not re.fullmatch(r"chatarch-v[0-9]+\.[0-9]+\.[0-9]+\+[0-9a-f]{40}", version):
        raise ValueError("maintained binary version must include a 40-hex revision")
    source = Path(archive)
    if source.is_symlink() or not source.is_file():
        raise ValueError("archive must be a regular local file")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256.lower():
        raise ValueError("archive SHA256 mismatch")
    root = runtime_home(home)
    destination = root / "bin/glance"
    metadata = root / "bin/glance.provenance.json"
    if destination.exists() or destination.is_symlink() or metadata.exists() or metadata.is_symlink():
        raise ValueError("binary or provenance already exists; refusing to replace")
    with tarfile.open(source, "r:*") as bundle:
        members = bundle.getmembers()
        if len(members) != 1 or members[0].name not in ("glance", "./glance") or not members[0].isfile():
            raise ValueError("archive must contain only a regular glance executable")
        member = members[0]
        if member.size > 128 * 1024 * 1024 or member.size == 0:
            raise ValueError("invalid binary size")
        stream = bundle.extractfile(member)
        if stream is None:
            raise ValueError("missing binary")
        with tempfile.TemporaryDirectory(prefix="chatglance-verify-") as temporary:
            verified = Path(temporary) / "glance"
            with verified.open("wb") as output:
                remaining = member.size
                binary_digest = hashlib.sha256()
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("truncated binary")
                    output.write(chunk)
                    binary_digest.update(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(verified, 0o755)
            try:
                observed = subprocess.run([str(verified), "--version"], capture_output=True, text=True,
                                          timeout=5, check=True, env={"PATH": "/usr/bin:/bin"}).stdout.strip()
            except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
                raise ValueError(f"reviewed executable version check failed ({type(exc).__name__})") from None
            if observed != version:
                raise ValueError("maintained binary version mismatch")
            provenance = {
                "source": "verified local archive", "source_tag": version.split("+", 1)[0],
                "source_revision": version.split("+", 1)[1], "version": observed,
                "archive_sha256": digest.hexdigest(), "binary_sha256": binary_digest.hexdigest(),
            }
            _safe_directory(destination.parent)
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".glance-", delete=False) as output:
                staged = Path(output.name)
                try:
                    with verified.open("rb") as binary_stream:
                        for chunk in iter(lambda: binary_stream.read(1024 * 1024), b""):
                            output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                    os.chmod(staged, 0o755)
                    if not _create(metadata, (json.dumps(provenance, sort_keys=True) + "\n").encode()):
                        raise ValueError("provenance already exists")
                    try:
                        os.link(staged, destination, follow_symlinks=False)
                    except Exception:
                        metadata.unlink(missing_ok=True)
                        raise
                finally:
                    staged.unlink(missing_ok=True)
    return destination


BRIDGE_KEYS = (
    "CHATGLANCE_LOGIN_SECRET", "CHATGLANCE_LOGIN_PASSWORD_HASH", "CHATGLANCE_LOGIN_USER",
    "CHATGLANCE_LOGIN_ACCOUNTS",
    "CHATGLANCE_PUBLIC_ORIGIN", "CHATGLANCE_WEB_PORT", "CHATGLANCE_CONTROL_PORT",
    "CHATGLANCE_PROJECTS_OWNER", "CHATGLANCE_REFRESH_PAGES", "CHATGLANCE_REFRESH_INTERVAL",
    "CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH",
)


def bridge_environment(*, home: str | Path | None = None, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Read typed ChatEnv without exposing values in config files or arguments."""
    try:
        active = EnvStore(get_paths(home).envs_dir).load_active(ChatGlanceConfig)
    except (ValueError, OSError):
        active = {}
    result = dict(os.environ if environ is None else environ)
    for key in BRIDGE_KEYS:
        if key not in result and active.get(key):
            result[key] = str(active[key])
    result.setdefault("CHATGLANCE_WEB_PORT", "8080")
    return result


def portable_settings(*, home: str | Path | None = None, environ: dict[str, str] | None = None) -> dict[str, object]:
    """Resolve reviewed, non-secret owner and non-consuming schedule defaults."""
    values = bridge_environment(home=home, environ=environ)
    pages = tuple(part for part in re.split(r"[\s,]+", values.get("CHATGLANCE_REFRESH_PAGES", "").strip()) if part)
    if any(page not in ("projects", "servers", "sites") for page in pages):
        raise ValueError("configured refresh pages must be projects, servers or sites")
    interval = values.get("CHATGLANCE_REFRESH_INTERVAL", "30min")
    if not re.fullmatch(r"[1-9][0-9]*(?:min|h|d)", interval):
        raise ValueError("invalid configured refresh interval")
    owner = values.get("CHATGLANCE_PROJECTS_OWNER", "").strip()
    if owner and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
        raise ValueError("invalid configured project owner")
    return {"owner": owner, "pages": pages, "interval": interval}


def authenticated_environment(*, home: str | Path | None = None, environ: dict[str, str] | None = None) -> dict[str, str]:
    result = bridge_environment(home=home, environ=environ)
    if not all(result.get(key) for key in ("CHATGLANCE_LOGIN_SECRET", "CHATGLANCE_LOGIN_PASSWORD_HASH", "CHATGLANCE_LOGIN_USER")):
        raise ValueError("login requires configured signing secret, password hash and username")
    if not result["CHATGLANCE_LOGIN_PASSWORD_HASH"].startswith(("$2a$", "$2b$", "$2y$")):
        raise ValueError("login password hash must be bcrypt")
    if not re.fullmatch(r"\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}", result["CHATGLANCE_LOGIN_PASSWORD_HASH"]):
        raise ValueError("login password hash must be a complete bcrypt hash")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+@-]{2,49}", result["CHATGLANCE_LOGIN_USER"]):
        raise ValueError("login username must be a safe 3-50 character name or email")
    secret = result["CHATGLANCE_LOGIN_SECRET"]
    try:
        decoded = base64.b64decode(secret, validate=True)
    except (ValueError, binascii.Error):
        decoded = b""
    if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != secret:
        raise ValueError("login signing secret must be canonical base64 of exactly 64 bytes")
    try:
        port = int(result["CHATGLANCE_WEB_PORT"])
    except (ValueError, KeyError) as exc:
        raise ValueError("invalid web port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("invalid web port")
    return result


def serve(home: str | Path | None = None) -> None:
    """Exec the installed Go server with secrets in child environment only."""
    root = runtime_home(home)
    config = root / "config/glance.yml"
    binary = root / "bin/glance"
    if binary.is_symlink() or not binary.is_file() or config.is_symlink() or not config.is_file():
        raise ValueError("runtime binary/config missing or unsafe")
    content = config.read_text(encoding="utf-8")
    if "CHATGLANCE_AUTH_USER_" in content or (root / "private/managed.json").exists():
        from .managed import runtime_environment
        environment = runtime_environment(root, auth="CHATGLANCE_LOGIN_SECRET" in content)
    else:
        environment = authenticated_environment() if "CHATGLANCE_LOGIN_SECRET" in content else bridge_environment()
    try:
        port = int(environment["CHATGLANCE_WEB_PORT"])
    except ValueError as exc:
        raise ValueError("invalid web port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("invalid web port")
    os.execve(str(binary), [str(binary), "-config", str(config)], environment)
