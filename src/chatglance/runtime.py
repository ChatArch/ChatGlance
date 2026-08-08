"""Runtime maintenance helpers for a durable Glance service home."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .glance_config import load_yaml, patch_server_stats_root_only, replace_projects_page, write_yaml
from .projects import PAGE_NAME, load_inventory


@dataclass(frozen=True)
class MaintainResult:
    """Result of a runtime maintenance pass."""

    output_path: Path
    changed: bool
    backup_path: Path | None
    validated: bool
    restarted: bool


def build_maintained_config(config: dict[str, Any], inventory: dict[str, Any], *, page_name: str = PAGE_NAME) -> dict[str, Any]:
    """Apply all chatglance-managed config transformations.

    The runtime boundary is deliberately narrow: this updates generated dashboard
    content and Glance `server-stats` disk presentation. It does not embed live
    credentials, run the Glance server, or fetch repository metadata.
    """

    updated = replace_projects_page(config, inventory, page_name=page_name)
    updated = patch_server_stats_root_only(updated)
    return updated


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def validate_glance_config(glance_bin: str | Path, config_path: str | Path) -> None:
    """Validate a config file with the upstream Glance binary."""

    subprocess.run(
        [str(glance_bin), "-config", str(config_path), "config:validate"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
) -> MaintainResult:
    """Maintain a Glance config using a repository-inventory snapshot.

    If `output_path` is the same as `config_path`, the write is in-place: a
    backup is created when `backup_dir` is provided, the candidate is validated
    before replacing the live file, and an optional systemd user service restart
    runs only when the rendered config actually changed.
    """

    source = Path(config_path)
    output = Path(output_path) if output_path is not None else source
    config = load_yaml(source)
    inventory = load_inventory(data_path)
    updated = build_maintained_config(config, inventory, page_name=page_name)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.chatglance.tmp")
    write_yaml(tmp, updated)

    if validate_bin is not None:
        validate_glance_config(validate_bin, tmp)
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
        tmp.replace(output)
        if restart_service:
            subprocess.run(["systemctl", "--user", "restart", restart_service], check=True)
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
