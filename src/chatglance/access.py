"""Detached public projections for split-audience Glance dashboards."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import ipaddress
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

from .projects import PAGE_NAME, build_projects_page, project_public_inventory


JsonMapping = dict[str, Any]
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_public_server(server: Mapping[str, Any]) -> JsonMapping:
    """Validate and detach an explicit Glance public server mapping."""

    if not isinstance(server, Mapping):
        raise ValueError("public server must be a mapping with only `host` and `port`")
    if set(server) != {"host", "port"}:
        raise ValueError("public server must contain only `host` and `port`")

    host = server.get("host")
    port = server.get("port")
    if not isinstance(host, str) or not host or host != host.strip():
        raise ValueError("public server host must be a non-empty plain hostname or IP address")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in host):
        raise ValueError("public server host must be a non-empty plain hostname or IP address")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or host.lower() != "localhost" and any(not _HOST_LABEL.fullmatch(label) for label in host.split(".")):
            raise ValueError("public server host must be a non-empty plain hostname or IP address")

    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("public server port must be an integer from 1 to 65535")
    return {"host": host, "port": port}


class CandidateWriteError(Exception):
    """A redacted candidate-path, staging, publication, or rollback error."""


def _absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _safe_output_directory(directory: Path) -> bool:
    try:
        for candidate in (directory, *directory.parents):
            candidate_stat = candidate.lstat()
            if stat.S_ISLNK(candidate_stat.st_mode):
                return False
        return stat.S_ISDIR(directory.lstat().st_mode)
    except OSError:
        return False


def _regular_target_or_missing(path: Path) -> bool:
    try:
        target_stat = path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return stat.S_ISREG(target_stat.st_mode)


def preflight_public_candidate_paths(
    config_output: str | Path,
    inventory_output: str | Path,
    *,
    protected_paths: tuple[str | Path, ...] = (),
) -> tuple[Path, Path]:
    """Validate candidate destinations without following output symlinks."""

    try:
        config_path = _absolute_path(config_output)
        inventory_path = _absolute_path(inventory_output)
        if config_path == inventory_path:
            raise CandidateWriteError("public candidate output paths must be distinct")
        if config_path.parent != inventory_path.parent:
            raise CandidateWriteError("public candidate outputs must share the same directory")
        if not _safe_output_directory(config_path.parent):
            raise CandidateWriteError("public candidate output directory is invalid")
        if not _regular_target_or_missing(config_path) or not _regular_target_or_missing(inventory_path):
            raise CandidateWriteError("public candidate targets must be regular files or absent")
        if config_path.exists() and inventory_path.exists() and os.path.samefile(config_path, inventory_path):
            raise CandidateWriteError("public candidate output paths must be distinct")

        for protected in protected_paths:
            protected_path = _absolute_path(protected)
            if protected_path in {config_path, inventory_path}:
                raise CandidateWriteError("input and output paths must all be distinct")
            for output in (config_path, inventory_path):
                if output.exists() and protected_path.exists() and os.path.samefile(output, protected_path):
                    raise CandidateWriteError("input and output paths must all be distinct")
                if protected_path.resolve(strict=False) == output.resolve(strict=False):
                    raise CandidateWriteError("input and output paths must all be distinct")
        return config_path, inventory_path
    except CandidateWriteError:
        raise
    except (OSError, RuntimeError) as exc:
        raise CandidateWriteError("could not validate public candidate paths") from exc


def _stage_bytes(directory: Path, body: bytes, label: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".chatglance-{label}-", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("candidate target is not regular")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_public_candidates(
    config_output: str | Path,
    config_text: str,
    inventory_output: str | Path,
    inventory_text: str,
    *,
    protected_paths: tuple[str | Path, ...] = (),
) -> tuple[Path, Path]:
    """Stage and publish a mode-0600 candidate pair with rollback."""

    config_path, inventory_path = preflight_public_candidate_paths(
        config_output,
        inventory_output,
        protected_paths=protected_paths,
    )
    directory = config_path.parent
    targets = (config_path, inventory_path)
    staged: list[Path] = []
    backups: dict[Path, Path] = {}
    previous_modes: dict[Path, int] = {}
    replaced: list[Path] = []
    try:
        prepared: dict[Path, Path] = {}
        for target, text, label in (
            (config_path, config_text, "config"),
            (inventory_path, inventory_text, "inventory"),
        ):
            temporary = _stage_bytes(directory, text.encode("utf-8"), label)
            prepared[target] = temporary
            staged.append(temporary)
        for index, target in enumerate(targets):
            if target.exists():
                target_stat = target.lstat()
                if not stat.S_ISREG(target_stat.st_mode):
                    raise OSError("candidate target changed during staging")
                previous_modes[target] = stat.S_IMODE(target_stat.st_mode)
                backup = _stage_bytes(directory, _read_regular_bytes(target), f"backup-{index}")
                backups[target] = backup
                staged.append(backup)

        for target in targets:
            replaced.append(target)
            os.replace(prepared[target], target)
        _fsync_directory(directory)
    except (OSError, UnicodeError) as exc:
        rollback_failed = False
        for target in reversed(replaced):
            try:
                backup = backups.get(target)
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
                    os.chmod(target, previous_modes[target], follow_symlinks=False)
            except OSError:
                rollback_failed = True
        if replaced:
            try:
                _fsync_directory(directory)
            except OSError:
                rollback_failed = True
        message = "could not publish public candidates; previous candidates restored"
        if rollback_failed:
            message = "could not publish public candidates; rollback failed"
        raise CandidateWriteError(message) from exc
    finally:
        for temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return config_path, inventory_path


def build_public_home_page() -> JsonMapping:
    """Return the explicit static home used by the anonymous dashboard."""

    return {
        "name": "ChatArch",
        "columns": [
            {
                "size": "full",
                "widgets": [
                    {
                        "type": "bookmarks",
                        "title": "ChatArch 公开入口",
                        "groups": [
                            {
                                "title": "公开内容",
                                "links": [
                                    {
                                        "title": "公开项目",
                                        "url": "/projects",
                                        "description": "浏览 ChatArch 公开项目",
                                        "icon": "si:github",
                                    },
                                    {
                                        "title": "ChatArch 公共源码",
                                        "url": "https://github.com/ChatArch",
                                        "description": "查看 GitHub 上的公开源码",
                                        "icon": "si:github",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def build_public_glance_config(
    config: Mapping[str, Any],
    full_inventory: Mapping[str, Any],
    *,
    server: Mapping[str, Any] | None = None,
) -> JsonMapping:
    """Return a minimal detached anonymous Glance config.

    The private config is used only as validated input to the transformation. No
    global setting, existing home widget, runtime server value, or non-public page
    is inherited implicitly.
    """

    if not isinstance(config, Mapping):
        raise ValueError("Glance config must be a mapping")
    pages = config.get("pages")
    if pages is not None and not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    if not isinstance(full_inventory, Mapping):
        raise ValueError("full inventory must be a mapping")

    projects_page = build_projects_page(dict(full_inventory), page_name=PAGE_NAME, audience="public")
    projects_page["slug"] = "projects"
    public_config: JsonMapping = {
        "pages": [build_public_home_page(), projects_page],
    }
    if server is not None:
        public_config = {"server": validate_public_server(server), **public_config}
    return deepcopy(public_config)


__all__ = [
    "CandidateWriteError",
    "build_public_glance_config",
    "build_public_home_page",
    "preflight_public_candidate_paths",
    "project_public_inventory",
    "validate_public_server",
    "write_public_candidates",
]
