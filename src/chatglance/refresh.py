"""Package-owned collection and transactional dashboard publication."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Sequence

import yaml
from chatenv import get_paths
from .runtime import validate_glance_config

PAGE_SPECS = {
    "projects": ("项目", "chatarch-projects.json", "projects-page.yml"),
    "servers": ("服务器", "server-status.json", "server-page.yml"),
    "sites": ("网站服务", "site-services.json", "site-services-page.yml"),
    "account-limits": ("订阅详情", "account-limits.json", "account-limits-page.yml"),
}
PAGE_KEYS = tuple(PAGE_SPECS)


class RefreshError(RuntimeError):
    """Safe operational failure; live snapshots remain available."""


@dataclass
class PageUpdate:
    key: str
    data: dict[str, Any]
    page: dict[str, Any]
    extra_files: dict[str, str] = field(default_factory=dict)
    partial: bool = False


@dataclass(frozen=True)
class CollectionOptions:
    """Non-secret collector inputs; credentials stay with ChatEnv/providers."""

    projects_owner: str | None = None
    project_workers: int = 4
    uvx_bin: str = "uvx"
    cli_tree_timeout: int = 90
    server_inventory: Path | None = None
    sites_inventory: Path | None = None
    gatus_db: Path | None = None
    account_timeout: int = 60
    reset_timeout: int = 20
    no_public_reset: bool = False
    reset_base_url: str | None = None


def default_runtime_home() -> Path:
    return Path(get_paths().home_dir) / "glance"


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RefreshError("snapshot must be a JSON object")
    return value


@contextmanager
def _refresh_lock(root: Path):
    try:
        import fcntl
    except ImportError as exc:
        raise RefreshError("manual refresh requires POSIX file locking") from exc
    (root / "logs").mkdir(parents=True, exist_ok=True)
    with (root / "logs/refresh-live-pages.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RefreshError("another refresh is running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _configured_pages(config: dict[str, Any], root: Path, collection: CollectionOptions) -> list[str]:
    identities = {key: {key, spec[0]} for key, spec in PAGE_SPECS.items()}
    inventory = collection.server_inventory or root / "config/server-inventory.yml"
    if inventory.exists():
        from .servers import load_server_inventory_config, page_options_from_inventory_config
        options = page_options_from_inventory_config(load_server_inventory_config(inventory))
        identities["servers"].update([options["page_name"], options["page_slug"]])
    selected = []
    for page in config.get("pages", []):
        for key, names in identities.items():
            if page.get("name") in names or page.get("slug") in names:
                if key not in selected:
                    selected.append(key)
    return selected


def _replace_page(config: dict[str, Any], page: dict[str, Any]) -> None:
    matches = [i for i, old in enumerate(config["pages"]) if old.get("name") == page.get("name") or (page.get("slug") and old.get("slug") == page["slug"])]
    if len(matches) > 1:
        raise RefreshError("duplicate page identity in runtime config")
    if matches:
        config["pages"][matches[0]] = page
    else:
        config["pages"].append(page)


def _preserve_same_version_trees(data: dict, previous: dict) -> None:
    """Reuse immutable released-version CLI evidence, never another version."""
    old = {item.get("name"): item for item in previous.get("repositories", [])}
    for item in data.get("repositories", []):
        prior = old.get(item.get("name"), {})
        version = (item.get("version") or {}).get("value")
        cli = item.get("cli") or {}
        prior_cli = prior.get("cli") or {}
        if (version and version == (prior.get("version") or {}).get("value")
                and item.get("package") == prior.get("package")
                and cli.get("commands") == prior_cli.get("commands")
                and isinstance(prior_cli.get("actual_tree"), dict)):
            cli["actual_tree"] = deepcopy(prior_cli["actual_tree"])
            cli["actual_tree"]["cached_from"] = previous.get("generated_at")
    trees = [(item.get("cli") or {}).get("actual_tree") or {} for item in data.get("repositories", [])]
    data.setdefault("counts", {})["with_actual_cli_tree"] = sum(tree.get("status") == "ok" for tree in trees)
    data["counts"]["with_actual_cli_business_commands"] = sum(int(tree.get("business_command_count") or 0) > 0 for tree in trees)


def _cli_report(data: dict) -> str:
    output = io.StringIO()
    fields = ["name", "category_label", "category", "version", "version_source", "entrypoint_count", "entrypoints", "actual_tree_status", "actual_business_command_count", "actual_business_commands", "description"]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for item in sorted(data.get("repositories", []), key=lambda value: str(value.get("name", "")).lower()):
        cli, version = item.get("cli") or {}, item.get("version") or {}
        tree = cli.get("actual_tree") or {}
        commands = cli.get("commands") or []
        writer.writerow({"name": item.get("name", ""), "category_label": item.get("category_label", ""), "category": item.get("category", ""), "version": version.get("value", ""), "version_source": version.get("source", ""), "entrypoint_count": len(commands), "entrypoints": ",".join(commands), "actual_tree_status": tree.get("status", ""), "actual_business_command_count": tree.get("business_command_count", ""), "actual_business_commands": ",".join(tree.get("business_commands") or []), "description": " ".join(str(item.get("description", "")).split())})
    return output.getvalue()


def _collect_page(key: str, root: Path, stage: Path, *, profiles: Sequence[str] | None, actual_cli_tree: bool, allow_offline_regression: bool, scheduled: bool = False, collection: CollectionOptions | None = None) -> PageUpdate:
    collection = collection or CollectionOptions()
    previous_path = root / "data" / PAGE_SPECS[key][1]
    previous = _json(previous_path)
    if key == "account-limits":
        from .codex_collector import collect_account_limits, parse_profiles
        from .config import collection_settings
        from .account_limits import build_account_limits_page
        configured = collection_settings().get("profiles", "")
        selected = list(profiles or parse_profiles(configured) or [item["profile"] for item in previous.get("codex", []) if item.get("profile")])
        if not selected:
            raise RefreshError("no configured account profiles")
        data = collect_account_limits(
            profiles=selected, output_path=stage / "account-limits.json",
            history_path=previous_path if previous_path.exists() else None,
            timeout=collection.account_timeout, reset_timeout=collection.reset_timeout,
            no_public_reset=collection.no_public_reset, reset_base_url=collection.reset_base_url,
            execute_resets=scheduled,
        )
        partial = bool(data.get("refresh_status", {}).get("failed_count")) or data.get("codex_reset", {}).get("status") not in {"ok", "skipped"}
        return PageUpdate(key, data, build_account_limits_page(data), partial=partial)
    if key == "sites":
        from .sites import load_sites_inventory, apply_gatus_status, build_sites_page
        data = load_sites_inventory(collection.sites_inventory or root / "config/site-services.yml")
        database = collection.gatus_db or root.parent / "uptime-gatus/data/gatus.db"
        if database.exists():
            data = apply_gatus_status(data, database)
        return PageUpdate(key, data, build_sites_page(data))
    if key == "servers":
        from .servers import (load_server_inventory_config, aliases_from_inventory_config, collection_options_from_inventory_config, host_connection_overrides_from_inventory_config, collect_server_status, apply_server_inventory_config, page_options_from_inventory_config, build_servers_page, server_status_regressions)
        inventory = load_server_inventory_config(collection.server_inventory or root / "config/server-inventory.yml")
        aliases = aliases_from_inventory_config(inventory)
        if not aliases:
            raise RefreshError("no configured servers")
        options = collection_options_from_inventory_config(inventory)
        data = collect_server_status(aliases, timeout=options["timeout"], workers=options["workers"], host_overrides=host_connection_overrides_from_inventory_config(inventory))
        data = apply_server_inventory_config(data, inventory)
        if previous and server_status_regressions(previous, data) and not allow_offline_regression:
            raise RefreshError("server offline regression; previous snapshot retained")
        return PageUpdate(key, data, build_servers_page(data, **page_options_from_inventory_config(inventory)))
    from .project_inventory import RefreshOptions, refresh_project_inventory
    from .projects import build_projects_page
    owner = collection.projects_owner or (previous.get("source") or {}).get("owner") or "ChatArch"
    overrides = root / "config/project-category-overrides.json"
    baseline = overrides if overrides.exists() else previous_path if previous_path.exists() else None
    data = refresh_project_inventory(output_path=stage / "projects.json", baseline_data=baseline, options=RefreshOptions(owner=owner, workers=collection.project_workers, collect_actual_cli_trees=actual_cli_tree, uvx_bin=collection.uvx_bin, cli_tree_timeout=collection.cli_tree_timeout))
    if not actual_cli_tree:
        _preserve_same_version_trees(data, previous)
    return PageUpdate(key, data, build_projects_page(data), {"project-cli-tree-report.tsv": _cli_report(data)})


def _restart(service: str) -> None:
    subprocess.run(["systemctl", "--user", "restart", service], check=True, capture_output=True, text=True, timeout=45)


def _publish(root: Path, stage: Path, payloads: dict[Path, str]) -> str | None:
    changed = {path: text for path, text in payloads.items() if not path.exists() or path.read_text(encoding="utf-8") != text}
    if not changed:
        return None
    backup = root / "config/backups" / ("refresh-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir(parents=True, mode=0o700)
    saved, prepared, replaced = {}, {}, []
    for index, (path, text) in enumerate(changed.items()):
        if path.exists():
            saved[path] = backup / str(index)
            shutil.copy2(path, saved[path])
        temporary = stage / f"publish-{index}"
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
        prepared[path] = temporary
    (backup / "manifest.json").write_text(json.dumps({str(path.relative_to(root)): saved[path].name if path in saved else None for path in changed}, indent=2), encoding="utf-8")
    try:
        for path, temporary in prepared.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, path)
            replaced.append(path)
    except OSError as exc:
        for path in reversed(replaced):
            if path in saved:
                restore = stage / "restore"
                shutil.copy2(saved[path], restore)
                os.replace(restore, path)
            else:
                path.unlink(missing_ok=True)
        raise RefreshError("publication failed; restored previous artifacts") from exc
    return str(backup)


def refresh_runtime(runtime_home: str | Path | None = None, pages: Sequence[str] = (), *, glance_bin: str | Path | None = None, restart: bool = True, service_name: str = "chatarch-glance.service", profiles: Sequence[str] | None = None, actual_cli_tree: bool | None = None, allow_offline_regression: bool | None = None, scheduled: bool = False, collection: CollectionOptions | None = None) -> dict[str, Any]:
    """Collect configured pages; only explicit scheduled mode may execute policy.

    Failed pages retain their previous snapshots; successful and cached partial
    pages are validated and published together. Partial results return ok=False.
    """
    selected = list(dict.fromkeys(pages))
    if any(key not in PAGE_SPECS for key in selected):
        raise RefreshError("unknown refresh page")
    if type(scheduled) is not bool:
        raise RefreshError("scheduled must be boolean")
    collection = collection or CollectionOptions()
    actual_cli_tree = scheduled if actual_cli_tree is None else actual_cli_tree
    allow_offline_regression = scheduled if allow_offline_regression is None else allow_offline_regression
    root = Path(runtime_home).expanduser().resolve() if runtime_home is not None else default_runtime_home()
    config_path = root / "config/glance.yml"
    if not config_path.is_file():
        raise RefreshError("runtime config is missing; configure Glance first")
    validator = Path(glance_bin).expanduser() if glance_bin is not None else root / "bin/glance"
    if not validator.is_file():
        raise RefreshError("Glance validator is missing; pass --glance-bin")
    with _refresh_lock(root):
        initial = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(initial, dict) or not isinstance(initial.get("pages"), list):
            raise RefreshError("runtime config must contain pages")
        selected = selected or _configured_pages(initial, root, collection)
        if not selected:
            raise RefreshError("no configured generated pages to refresh")
        staging = root / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="refresh-", dir=staging) as temporary:
            stage = Path(temporary)
            updates, rows = [], []
            for key in selected:
                try:
                    update = _collect_page(key, root, stage, profiles=profiles, actual_cli_tree=actual_cli_tree, allow_offline_regression=allow_offline_regression, scheduled=scheduled, collection=collection)
                    counts = update.data.get("counts", {})
                    details = {}
                    if key == "servers":
                        counts = {"servers": update.data.get("count", 0), "online": update.data.get("online", 0)}
                    elif key == "account-limits":
                        status = update.data.get("refresh_status", {})
                        counts = {"profiles": len(update.data.get("codex", [])), "ok": status.get("ok_count", 0), "failed": status.get("failed_count", 0)}
                        details = {"failed_profiles": status.get("failed_profiles", []), "calendar_status": update.data.get("codex_reset", {}).get("status"), "calendar_cached": bool(update.data.get("codex_reset", {}).get("using_last_known_values"))}
                    rows.append({"page": key, "status": "partial" if update.partial else "ok", "generated_at": update.data.get("generated_at"), "counts": counts, **details})
                    updates.append(update)
                except Exception as exc:
                    # Raw upstream exceptions can contain tokens, headers or URLs.
                    rows.append({"page": key, "status": "error", "error_type": type(exc).__name__, "message": "collection failed; live artifacts unchanged"})
            result = {"ok": all(row["status"] == "ok" for row in rows), "runtime_home": str(root), "pages": rows, "changed": False, "restarted": False, "reset_execution": scheduled and "account-limits" in selected, "backup_dir": None}
            if not updates:
                return result
            # Rebase onto the latest config so unrelated edits made during slow
            # collection are retained, then reject a race during validation.
            before = config_path.read_text(encoding="utf-8")
            config = yaml.safe_load(before)
            payloads = {}
            for update in updates:
                _replace_page(config, update.page)
                _, data_name, page_name = PAGE_SPECS[update.key]
                payloads[root / "data" / data_name] = json.dumps(update.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                payloads[root / "data" / page_name] = yaml.safe_dump(update.page, allow_unicode=True, sort_keys=False)
                for name, text in update.extra_files.items():
                    payloads[root / "data" / name] = text
            payloads[config_path] = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
            candidate = stage / "glance.yml"
            candidate.write_text(payloads[config_path], encoding="utf-8")
            candidate.chmod(0o600)
            try:
                validate_glance_config(validator, candidate)
            except Exception as exc:
                raise RefreshError("candidate validation failed; live artifacts unchanged") from exc
            if config_path.read_text(encoding="utf-8") != before:
                raise RefreshError("runtime config changed during validation; retry refresh")
            result["backup_dir"] = _publish(root, stage, payloads)
            result["changed"] = result["backup_dir"] is not None
            if result["changed"] and restart:
                try:
                    _restart(service_name)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise RefreshError("artifacts published, but service restart failed") from exc
                result["restarted"] = True
            return result
