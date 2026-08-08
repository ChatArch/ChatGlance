"""Safe Glance YAML config transformations for chatglance."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from .projects import LEGACY_PAGE_NAMES, PAGE_NAME, build_projects_page, dump_yaml, load_inventory


def load_yaml(path: str | Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Glance config must be a YAML mapping")
    return data


def write_yaml(path: str | Path, data: dict[str, Any]) -> None:
    Path(path).write_text(dump_yaml(data), encoding="utf-8")


def replace_projects_page(config: dict[str, Any], inventory: dict[str, Any], *, page_name: str = PAGE_NAME) -> dict[str, Any]:
    """Return a config copy where the generated projects page is replaced.

    This function does not mutate the input mapping. It removes old generated page
    names and then replaces/appends the current `page_name` page.
    """

    updated = deepcopy(config)
    pages = updated.setdefault("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    legacy_names = set(LEGACY_PAGE_NAMES) | {page_name}
    pages[:] = [page for page in pages if not (isinstance(page, dict) and page.get("name") in legacy_names)]
    pages.append(build_projects_page(inventory, page_name=page_name))
    return updated


def iter_widgets(value: Any) -> Iterator[dict[str, Any]]:
    """Yield Glance widget mappings recursively from pages/columns/groups."""

    if isinstance(value, dict):
        if "type" in value:
            yield value
        for key in ("widgets", "columns"):
            nested = value.get(key)
            if isinstance(nested, list):
                for item in nested:
                    yield from iter_widgets(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_widgets(item)


def patch_server_stats_root_only(
    config: dict[str, Any],
    *,
    mountpoint: str = "/",
    name: str = "根分区",
    hide_swap: bool = True,
) -> dict[str, Any]:
    """Return a config copy where all server-stats widgets show only one mountpoint.

    Glance's `mountpoints` entries name configured mountpoints, but without
    `hide-mountpoints-by-default: true` Glance can still render all default OS
    mountpoints, including snap/loop mounts. This helper sets both fields.
    """

    updated = deepcopy(config)
    for widget in iter_widgets(updated.get("pages", [])):
        if widget.get("type") != "server-stats":
            continue
        widget["hide-mountpoints-by-default"] = True
        servers = widget.get("servers")
        if not isinstance(servers, list):
            # A bare local server-stats widget can exist; keep it safe by adding
            # a local server entry rather than leaving defaults visible.
            servers = [{"type": "local", "name": "local"}]
            widget["servers"] = servers
        for server in servers:
            if not isinstance(server, dict):
                continue
            server["hide-swap"] = bool(hide_swap)
            server["hide-mountpoints-by-default"] = True
            server["mountpoints"] = {mountpoint: {"name": name}}
    return updated


def update_projects_page_from_files(config_path: str | Path, data_path: str | Path, output_path: str | Path, *, page_name: str = PAGE_NAME) -> Path:
    config = load_yaml(config_path)
    inventory = load_inventory(data_path)
    updated = replace_projects_page(config, inventory, page_name=page_name)
    write_yaml(output_path, updated)
    return Path(output_path)


def patch_disks_from_files(config_path: str | Path, output_path: str | Path, *, mountpoint: str = "/", name: str = "根分区") -> Path:
    config = load_yaml(config_path)
    updated = patch_server_stats_root_only(config, mountpoint=mountpoint, name=name)
    write_yaml(output_path, updated)
    return Path(output_path)
