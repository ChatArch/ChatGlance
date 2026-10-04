"""One-instance guest layout with authenticated-only replacements."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any, Mapping

from .access import CandidateWriteError, _absolute_path, _safe_output_directory, _regular_target_or_missing, _stage_bytes, _fsync_directory, build_public_home_page
from .projects import PAGE_NAME, build_projects_page


def _pages(config: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pages = config.get("pages")
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise ValueError("Glance config must contain mapping pages")
    homes = [page for page in pages if page.get("name") == "ChatArch"]
    projects = [page for page in pages if page.get("name") == PAGE_NAME]
    if len(homes) != 1 or len(projects) != 1:
        raise ValueError("optional login requires exactly one ChatArch and one 项目 page")
    return homes[0], projects[0]


def optional_login_enabled(config: Mapping[str, Any]) -> bool:
    """Identify the trusted page layout, never an inventory audience hint."""

    pages = config.get("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    matches = [page for page in pages if isinstance(page, dict) and page.get("name") in {"ChatArch", PAGE_NAME}]
    if not any(page.get("public") is True or "authenticated-columns" in page for page in matches):
        return False
    home, projects = _pages(config)
    modes = [page.get("public") is True and isinstance(page.get("authenticated-columns"), list) and bool(page["authenticated-columns"]) for page in (home, projects)]
    if any(modes) and not all(modes):
        raise ValueError("incomplete optional-login page layout")
    if all(modes):
        _safe_shared_config(config)
        if config.get("document") or config.get("branding") or config.get("theme"):
            raise ValueError("optional-login shared global content is not reviewed")
        if any(page.get("head-widgets") for page in (home, projects)):
            raise ValueError("public page head-widgets cannot be retained safely")
        if home.get("columns") != build_public_home_page(projects_slug=projects.get("slug") or PAGE_NAME)["columns"]:
            raise ValueError("optional-login guest home layout is not reviewed")
        if any(page.get("public") is True for page in pages if page not in (home, projects)):
            raise ValueError("additional public pages require explicit review")
        return True
    if any(page.get("public") is True or "authenticated-columns" in page for page in (home, projects)):
        raise ValueError("incomplete optional-login page layout")
    return False


def _safe_shared_config(config: Mapping[str, Any]) -> None:
    if not isinstance(config.get("auth"), dict) or not isinstance(config["auth"].get("users"), dict) or not config["auth"]["users"]:
        raise ValueError("single-origin optional login requires configured auth users")
    document = config.get("document") or {}
    if not isinstance(document, dict) or document.get("head"):
        raise ValueError("private document head cannot be shared with guests")
    server = config.get("server") or {}
    if not isinstance(server, dict) or server.get("assets-path"):
        raise ValueError("private server assets-path cannot be shared with guests")


def _project_page(inventory: dict[str, Any], existing: Mapping[str, Any]) -> dict[str, Any]:
    guest = build_projects_page(inventory, audience="public")
    authenticated = build_projects_page(inventory)
    result = _page_metadata(existing)
    result["slug"] = existing.get("slug") or PAGE_NAME
    result["public"] = True
    result["columns"] = guest["columns"]
    result["authenticated-columns"] = authenticated["columns"]
    return result


def _page_metadata(page: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"name", "slug", "width", "desktop-navigation-width", "show-mobile-header", "hide-desktop-navigation", "center-vertically"}
    return {key: deepcopy(value) for key, value in page.items() if key in allowed}


def build_single_origin_optional_login_config(config: Mapping[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    """Prepare a private candidate; never expose it as a guest asset."""

    _safe_shared_config(config)
    home, projects = _pages(config)
    if home.get("head-widgets") or projects.get("head-widgets"):
        raise ValueError("public page head-widgets cannot be retained safely")
    existing_mode = optional_login_enabled(config)
    updated = {key: deepcopy(config[key]) for key in ("auth", "server") if key in config}
    updated["pages"] = deepcopy(config["pages"])
    for page in updated["pages"]:
        if page["name"] == "ChatArch":
            original_columns = home["authenticated-columns"] if existing_mode else home.get("columns")
            if not isinstance(original_columns, list) or not original_columns:
                raise ValueError("home needs authenticated columns")
            page.clear()
            page.update(_page_metadata(home))
            page["columns"] = build_public_home_page(projects_slug=projects.get("slug") or PAGE_NAME)["columns"]
            page["authenticated-columns"] = deepcopy(original_columns)
            page["public"] = True
            page.pop("head-widgets", None)
        elif page["name"] == PAGE_NAME:
            page.clear()
            page.update(_project_page(inventory, projects))
        else:
            page["public"] = False
    return updated


def write_optional_login_candidate(output: str | Path, text: str, *, protected_paths: tuple[str | Path, ...]) -> Path:
    """Atomically publish one mode-0600 private candidate to an explicit path."""

    try:
        target = _absolute_path(output)
        if not _safe_output_directory(target.parent) or not _regular_target_or_missing(target):
            raise CandidateWriteError("optional-login candidate target is unsafe")
        for protected in protected_paths:
            source = _absolute_path(protected)
            if source == target or source.resolve(strict=False) == target.resolve(strict=False) or (target.exists() and source.exists() and os.path.samefile(target, source)):
                raise CandidateWriteError("input and output paths must be distinct")
        temporary = _stage_bytes(target.parent, text.encode("utf-8"), "optional-login")
        try:
            if not _regular_target_or_missing(target):
                raise CandidateWriteError("optional-login candidate target is unsafe")
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return target
    except CandidateWriteError:
        raise
    except (OSError, UnicodeError, RuntimeError) as exc:
        raise CandidateWriteError("could not write optional-login candidate") from exc
