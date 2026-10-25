"""Runtime maintenance helpers for a durable Glance service home."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import yaml

from .glance_config import load_yaml, patch_server_stats_mountpoints, replace_projects_page, write_yaml
from .projects import PAGE_NAME, load_inventory


@dataclass(frozen=True)
class MaintainResult:
    """Result of a runtime maintenance pass."""

    output_path: Path
    changed: bool
    backup_path: Path | None
    validated: bool
    restarted: bool


def _web_ready(host: str, port: int) -> bool:
    connection = http.client.HTTPConnection(host, port, timeout=1)
    try:
        connection.request("GET", "/")
        return connection.getresponse().status in (200, 302, 303)
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _launchd_pid(target: str) -> int:
    output = subprocess.run(
        ["/bin/launchctl", "print", target], check=True, capture_output=True, text=True, timeout=3,
    ).stdout
    state = re.search(r"^\s*state = running\s*$", output, re.MULTILINE)
    match = re.search(r"^\s*pid = ([1-9][0-9]*)\s*$", output, re.MULTILINE)
    return int(match.group(1)) if state and match else 0


def restart_user_service(service: str, runtime_home: str | Path | None = None) -> None:
    """Restart the selected Glance user service through the native manager."""

    if sys.platform == "darwin":
        if runtime_home is None:
            raise ValueError("Glance runtime home is required for launchd restart")
        from .instances import load_instance, service_identity, verify_config_pages
        requested_root = Path(runtime_home).expanduser().absolute()
        instance = load_instance(requested_root, required=False)
        root = requested_root.resolve(strict=True)
        if instance:
            verify_config_pages(root, instance)
            if service != instance.web_label:
                raise ValueError("restart target is not owned by this instance")
            owned_python = service_identity(root)["python_bin"]
        elif service != "chatarch-glance.service":
            raise ValueError("restart target must be a Glance launchd label")
        else:
            owned_python = None
        plist = Path.home() / "Library/LaunchAgents" / f"{service}.plist"
        if (plist.is_symlink() or plist.parent.is_symlink() or not plist.is_file()
                or plist.stat().st_uid != os.getuid() or plist.stat().st_mode & 0o022
                or plist.stat().st_size > 65536):
            raise ValueError("Glance LaunchAgent is missing or unsafe")
        try:
            definition = plistlib.loads(plist.read_bytes())
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
            raise ValueError("Glance LaunchAgent is invalid") from None
        if not isinstance(definition, dict):
            raise ValueError("Glance LaunchAgent is invalid")
        arguments = definition.get("ProgramArguments")
        expected = [arguments[0], "-m", "chatglance.cli", "runtime", "serve", "--runtime-home", str(root)] if (
            isinstance(arguments, list) and arguments and isinstance(arguments[0], str)
        ) else None
        executable = Path(arguments[0]) if expected else None
        if (definition.get("Label") != service or arguments != expected
                or (owned_python is not None and arguments[0] != owned_python)
                or executable is None or not executable.is_absolute() or not executable.is_file()):
            raise ValueError("Glance LaunchAgent topology does not match the runtime")
        config = yaml.safe_load((root / "config/glance.yml").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("server", {}), dict):
            raise ValueError("Glance web configuration is invalid")
        server = config.get("server", {})
        from .reset_control import validated_private_host
        host = validated_private_host(server.get("host", "127.0.0.1"))
        port = server.get("port", 8080)
        if port == "${CHATGLANCE_WEB_PORT}":
            from .portable import bridge_environment
            port = int(bridge_environment()["CHATGLANCE_WEB_PORT"])
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Glance web port is invalid")
        target = f"gui/{os.getuid()}/{service}"
        previous_pid = _launchd_pid(target)
        if not previous_pid:
            raise RuntimeError("Glance web service has no running owner")
        bootstrap = ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)]

        def replacement_ready(seconds: int) -> bool:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    current_pid = _launchd_pid(target)
                    if (current_pid and current_pid != previous_pid and _web_ready(host, port)
                            and _launchd_pid(target) == current_pid):
                        return True
                except (OSError, subprocess.SubprocessError):
                    pass
                time.sleep(0.2)
            return False

        # --wait confirms the old job has exited before the replacement can bind.
        # A timeout is not proof of completion, so never bootstrap in that case.
        subprocess.run(["/bin/launchctl", "bootout", "--wait", target],
                       check=True, capture_output=True, text=True, timeout=10)
        try:
            subprocess.run(bootstrap, check=True, capture_output=True, text=True, timeout=10)
            if replacement_ready(12):
                return
            raise RuntimeError("Glance web restart readiness was not confirmed")
        except (OSError, subprocess.SubprocessError, RuntimeError) as original_error:
            # After a completed bootout, try to restore only this verified job.
            # Keep the original failure visible even if recovery succeeds.
            recovery_error: Exception | None = None
            try:
                subprocess.run(bootstrap, check=True, capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError) as error:
                recovery_error = error
            if replacement_ready(6):
                raise RuntimeError("Glance web restart failed; service recovered and ready") from original_error
            detail = type(recovery_error).__name__ if recovery_error else "readiness unconfirmed"
            raise RuntimeError(f"Glance web restart failed; recovery failed ({detail})") from original_error
    else:
        if runtime_home is not None:
            from .instances import load_instance
            instance = load_instance(runtime_home, required=False)
            if instance and service != instance.web_label:
                raise ValueError("restart target is not owned by this instance")
        subprocess.run(
            ["systemctl", "--user", "restart", service],
            check=True, capture_output=True, text=True, timeout=45,
        )


def _is_mountpoint(path: str) -> bool:
    try:
        return subprocess.run(["findmnt", "--mountpoint", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return Path(path).is_mount()


def discover_meaningful_mountpoints() -> dict[str, str]:
    """Return meaningful local disk mountpoints for Glance server-stats.

    The dashboard should not show snap/loop/tmp/docker overlays. Keep `/` and
    include `/home` only when it is an actual separate mountpoint on this host.
    """

    mountpoints = {"/": "根分区"}
    if _is_mountpoint("/home"):
        mountpoints["/home"] = "Home"
    return mountpoints


def build_maintained_config(
    config: dict[str, Any],
    inventory: dict[str, Any],
    *,
    page_name: str = PAGE_NAME,
    mountpoints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply all chatglance-managed config transformations.

    The runtime boundary is deliberately narrow: this updates generated dashboard
    content and Glance `server-stats` disk presentation. It does not embed live
    credentials, run the Glance server, or fetch repository metadata.
    """

    updated = replace_projects_page(config, inventory, page_name=page_name)
    updated = patch_server_stats_mountpoints(updated, mountpoints or {"/": "根分区"})
    return updated


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def validate_glance_config(glance_bin: str | Path, config_path: str | Path) -> None:
    """Validate a config file with the upstream Glance binary."""

    from .portable import authenticated_environment, bridge_environment

    text = Path(config_path).read_text(encoding="utf-8")
    ancestors = Path(config_path).absolute().parents
    instance_root = next((parent for parent in ancestors if (parent / "private/instance.json").is_file()), None)
    if instance_root is not None:
        from .managed import runtime_environment
        environment = runtime_environment(instance_root, auth=True)
    elif "CHATGLANCE_AUTH_USER_" in text:
        from .managed import runtime_environment
        root = next((parent for parent in ancestors if (parent / "private/managed.json").is_file()), None)
        root = root or (Path(config_path).parent.parent if Path(config_path).parent.name == "config" else None)
        root = root or Path(glance_bin).absolute().parent.parent
        environment = runtime_environment(root)
    else:
        environment = (authenticated_environment() if "${CHATGLANCE_LOGIN_SECRET}" in text
                       else bridge_environment()) if "${CHATGLANCE_" in text else None
    subprocess.run(
        [str(glance_bin), "-config", str(config_path), "config:validate"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **({"env": environment} if environment is not None else {}),
    )


def maintain_config(
    *,
    config_path: str | Path,
    data_path: str | Path,
    output_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    validate_bin: str | Path | None = None,
    page_name: str = PAGE_NAME,
    restart_service: str | None = None,
    runtime_home: str | Path | None = None,
    mountpoints: dict[str, str] | None = None,
) -> MaintainResult:
    """Maintain a Glance config using a repository-inventory snapshot.

    If `output_path` is the same as `config_path`, the write is in-place: a
    backup is created when `backup_dir` is provided, the candidate is validated
    before replacing the live file, and an optional systemd user service restart
    runs only when the rendered config actually changed.
    """

    source = Path(config_path)
    from .instances import load_instance
    effective_root = runtime_home or (source.parent.parent if source.parent.name == "config" else None)
    if effective_root is not None and load_instance(effective_root, required=False):
        raise ValueError("runtime maintain is unavailable for read-only instances")
    output = Path(output_path) if output_path is not None else source
    config = load_yaml(source)
    inventory = load_inventory(data_path)
    updated = build_maintained_config(config, inventory, page_name=page_name, mountpoints=mountpoints)

    output.parent.mkdir(parents=True, exist_ok=True)
    from .optional_login import optional_login_enabled

    private_candidate = optional_login_enabled(config)
    if private_candidate and output.is_symlink():
        raise ValueError("optional-login runtime output must not be a symlink")
    if private_candidate:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.chatglance-", dir=output.parent)
        os.close(descriptor)
        tmp = Path(temporary_name)
    else:
        tmp = output.with_name(f".{output.name}.chatglance.tmp")
    try:
        write_yaml(tmp, updated)
        if private_candidate:
            tmp.chmod(0o600)
        if validate_bin is not None:
            validate_glance_config(validate_bin, tmp)
    except Exception:
        if private_candidate:
            tmp.unlink(missing_ok=True)
        raise
    validated = validate_bin is not None

    old_text = _read_text_if_exists(output)
    new_text = tmp.read_text(encoding="utf-8")
    changed = old_text != new_text
    backup_path: Path | None = None
    restarted = False

    if changed:
        if output.exists() and backup_dir is not None:
            backup_root = Path(backup_dir)
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_path = backup_root / f"{output.name}.{_timestamp()}.bak"
            shutil.copy2(output, backup_path)
            if private_candidate:
                backup_path.chmod(0o600)
        tmp.replace(output)
        if restart_service:
            restart_user_service(restart_service, runtime_home or source.parent.parent)
            restarted = True
    else:
        tmp.unlink(missing_ok=True)

    return MaintainResult(output_path=output, changed=changed, backup_path=backup_path, validated=validated, restarted=restarted)


def runtime_path(runtime_home: str | Path, relative_or_absolute: str | Path) -> Path:
    """Resolve a runtime-relative path without forcing callers into cwd tricks."""

    value = Path(relative_or_absolute).expanduser()
    if value.is_absolute():
        return value
    return Path(runtime_home).expanduser() / value
