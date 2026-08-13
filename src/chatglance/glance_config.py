"""Safe Glance YAML config transformations for chatglance."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, Mapping, cast

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
    names and then inserts the current `page_name` page immediately after the
    `ChatArch` home page when present. That keeps the live navigation stable as
    `ChatArch`, `项目`, `服务器` instead of appending generated content after newer
    pages.
    """

    updated = deepcopy(config)
    pages = updated.setdefault("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    legacy_names = set(LEGACY_PAGE_NAMES) | {page_name}
    pages[:] = [page for page in pages if not (isinstance(page, dict) and page.get("name") in legacy_names)]
    new_page = build_projects_page(inventory, page_name=page_name)
    insert_at = next((index + 1 for index, page in enumerate(pages) if isinstance(page, dict) and page.get("name") == "ChatArch"), None)
    if insert_at is None:
        pages.append(new_page)
    else:
        pages.insert(insert_at, new_page)
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


def _remove_widget_types_from_sequence(values: list[Any], widget_types: set[str]) -> list[Any]:
    cleaned: list[Any] = []
    for item in values:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        if item.get("type") in widget_types:
            continue
        new_item = deepcopy(item)
        for key in ("widgets", "columns"):
            nested = new_item.get(key)
            if isinstance(nested, list):
                new_item[key] = _remove_widget_types_from_sequence(nested, widget_types)
        cleaned.append(new_item)
    return cleaned


def remove_home_widget_types(
    config: dict[str, Any],
    widget_types: set[str],
    *,
    home_page_name: str = "ChatArch",
) -> dict[str, Any]:
    """Return a config copy with selected widget types removed from the home page.

    This is intentionally narrow: it only modifies the ChatArch home page, and it
    recurses through Glance columns/groups without touching other pages.
    """

    updated = deepcopy(config)
    pages = updated.get("pages")
    if not isinstance(pages, list):
        return updated
    for page in pages:
        if not isinstance(page, dict) or page.get("name") != home_page_name:
            continue
        for key in ("widgets", "columns"):
            nested = page.get(key)
            if isinstance(nested, list):
                page[key] = _remove_widget_types_from_sequence(nested, widget_types)
        break
    return updated


def patch_server_stats_mountpoints(
    config: dict[str, Any],
    mountpoints: Mapping[str, str],
    *,
    hide_swap: bool = True,
) -> dict[str, Any]:
    """Return a config copy where server-stats shows only selected disks.

    Glance's `mountpoints` entries can name configured mountpoints, but when
    `hide-mountpoints-by-default: true` is set, each mountpoint that should be
    visible must explicitly set `hide: false`. Without that, Glance hides even
    the configured `/` entry and the Disk card renders `n/a`.
    """

    if not mountpoints:
        raise ValueError("at least one mountpoint is required")

    updated = deepcopy(config)
    visible_mountpoints = {path: {"name": label, "hide": False} for path, label in mountpoints.items()}
    for widget in iter_widgets(updated.get("pages", [])):
        if widget.get("type") != "server-stats":
            continue
        # `hide-mountpoints-by-default` is a local-server property in Glance's
        # schema. Keep it off the widget itself so the rendered YAML mirrors the
        # upstream examples and avoids relying on ignored keys.
        widget.pop("hide-mountpoints-by-default", None)
        servers = widget.get("servers")
        if not isinstance(servers, list):
            # A bare local server-stats widget can exist; keep it safe by adding
            # a local server entry rather than leaving defaults visible.
            servers = [{"type": "local", "name": "local"}]
            widget["servers"] = servers
        for server_value in servers:
            if not isinstance(server_value, dict):
                continue
            server = cast(dict[str, Any], server_value)
            server["hide-swap"] = bool(hide_swap)
            server["hide-mountpoints-by-default"] = True
            server["mountpoints"] = deepcopy(visible_mountpoints)
    return updated


def patch_server_stats_root_only(
    config: dict[str, Any],
    *,
    mountpoint: str = "/",
    name: str = "根分区",
    hide_swap: bool = True,
) -> dict[str, Any]:
    """Return a config copy where server-stats shows only one mountpoint."""

    return patch_server_stats_mountpoints(config, {mountpoint: name}, hide_swap=hide_swap)


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
