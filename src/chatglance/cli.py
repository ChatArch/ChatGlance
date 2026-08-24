"""CLI entrypoint for chatglance."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import click
from chatstyle import add_tree_option

from chatglance import __version__
from chatglance.account_limits import (
    ACCOUNT_LIMITS_PAGE_NAME,
    DEFAULT_PAGE_SLUG as ACCOUNT_LIMITS_DEFAULT_PAGE_SLUG,
    DEFAULT_WIDGET_TITLE as ACCOUNT_LIMITS_DEFAULT_WIDGET_TITLE,
    build_account_limits_page,
    dump_json as dump_account_limits_json,
    dump_yaml as dump_account_limits_yaml,
    load_account_limits_data,
    replace_account_limits_page,
)
from chatglance.glance_config import load_yaml, patch_disks_from_files, remove_home_widget_types, update_projects_page_from_files, write_yaml
from chatglance.projects import PAGE_NAME, build_projects_page, dump_yaml, load_inventory
from chatglance.project_inventory import RefreshOptions, refresh_project_inventory
from chatglance.runtime import discover_meaningful_mountpoints, maintain_config, runtime_path
from chatglance.servers import (
    SERVER_PAGE_NAME,
    aliases_from_inventory_config,
    apply_server_inventory_config,
    build_servers_page,
    collection_options_from_inventory_config,
    collect_server_status,
    default_candidate_aliases,
    dump_json,
    host_connection_overrides_from_inventory_config,
    load_server_inventory_config,
    load_server_status,
    page_options_from_inventory_config,
    replace_servers_page,
    server_status_regressions,
)
from chatglance.sites import (
    DEFAULT_PAGE_SLUG as SITES_DEFAULT_PAGE_SLUG,
    DEFAULT_WIDGET_TITLE as SITES_DEFAULT_WIDGET_TITLE,
    SITES_PAGE_NAME,
    apply_gatus_status,
    build_sites_page,
    dump_json as dump_sites_json,
    dump_yaml as dump_sites_yaml,
    export_site_covers,
    load_sites_data,
    load_sites_inventory,
    replace_sites_page,
)
from chatglance.systemd import install_user_units, render_all_units, show_user_units, systemctl_user, write_units


def _resolve_chatglance_bin(explicit: Path | None) -> Path:
    """Resolve the executable path that systemd should call for maintenance."""

    if explicit is not None:
        return explicit.expanduser()
    found = shutil.which("chatglance")
    if found:
        return Path(found).expanduser()
    argv0 = Path(sys.argv[0]).expanduser()
    if argv0.name == "chatglance" and (argv0.is_absolute() or argv0.exists()):
        return argv0.resolve()
    raise click.ClickException("cannot resolve chatglance executable; pass --chatglance-bin explicitly")


def _raise_systemd_error(exc: subprocess.CalledProcessError) -> NoReturn:
    stderr = (exc.stderr or "").strip()
    stdout = (exc.stdout or "").strip()
    detail = stderr or stdout or f"exit status {exc.returncode}"
    raise click.ClickException(detail) from exc


@click.group(name="chatglance", invoke_without_command=True, no_args_is_help=True)
@click.version_option(__version__, prog_name="chatglance")
@add_tree_option(renderer_options={"root_name": "chatglance"})
def main() -> None:
    """Generate and maintain ChatArch Glance dashboard config."""


@main.group()
def projects() -> None:
    """Generate Glance project dashboard pages."""


@projects.command("collect")
@click.option("--owner", default="ChatArch", show_default=True, help="GitHub organization or owner to inventory.")
@click.option("--repo-list-json", type=click.Path(path_type=Path, dir_okay=False, exists=True), help="Existing ChatGH repo-list JSON to enrich instead of calling ChatGH.")
@click.option("--baseline-data", type=click.Path(path_type=Path, dir_okay=False, exists=True), help="Prior project inventory JSON whose reviewed categories should be preserved.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Inventory JSON path to write.")
@click.option("--uvx-bin", default="uvx", show_default=True, help="uvx executable used to install latest PyPI packages for actual CLI tree collection.")
@click.option("--limit", default=500, show_default=True, type=int, help="Maximum repositories to request from ChatGH.")
@click.option("--workers", default=12, show_default=True, type=int, help="Parallel GitHub contents workers for manifest reads.")
@click.option("--timeout", default=12, show_default=True, type=int, help="Per-file GitHub contents timeout in seconds.")
@click.option("--actual-cli-tree/--no-actual-cli-tree", default=False, show_default=True, help="Install latest PyPI packages with uvx and classify from each entrypoint's actual CLI tree.")
@click.option("--cli-tree-timeout", default=90, show_default=True, type=int, help="Per-entrypoint uvx/CLI tree timeout in seconds.")
def collect_projects(
    owner: str,
    repo_list_json: Path | None,
    baseline_data: Path | None,
    output_path: Path,
    uvx_bin: str,
    limit: int,
    workers: int,
    timeout: int,
    actual_cli_tree: bool,
    cli_tree_timeout: int,
) -> None:
    """Write refreshed project inventory JSON from read-only GitHub metadata."""

    inventory = refresh_project_inventory(
        output_path=output_path,
        repo_list_json=repo_list_json,
        baseline_data=baseline_data,
        options=RefreshOptions(
            owner=owner,
            limit=limit,
            workers=workers,
            timeout=timeout,
            uvx_bin=uvx_bin,
            collect_actual_cli_trees=actual_cli_tree,
            cli_tree_timeout=cli_tree_timeout,
        ),
    )
    counts_obj = inventory.get("counts")
    counts = counts_obj if isinstance(counts_obj, dict) else {}
    repo_count = counts.get("visible_repos", 0)
    open_prs = counts.get("total_open_prs", 0)
    open_issues = counts.get("total_open_issues", 0)
    actual_trees = counts.get("with_actual_cli_tree", 0)
    actual_business = counts.get("with_actual_cli_business_commands", 0)
    click.echo(
        " ".join(
            [
                f"wrote {output_path}",
                f"generated_at={inventory.get('generated_at')}",
                f"repos={repo_count}",
                f"open_prs={open_prs}",
                f"open_issues={open_issues}",
                f"actual_cli_trees={actual_trees}",
                f"actual_cli_business={actual_business}",
            ]
        )
    )


@projects.command("render-page")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Inventory JSON generated from repository metadata.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="YAML file to write the generated Glance page object to.")
@click.option("--page-name", default=PAGE_NAME, show_default=True, help="Generated Glance page name.")
def render_projects_page(data_path: Path, output_path: Path, page_name: str) -> None:
    """Write the `项目` page YAML from inventory JSON."""

    data = load_inventory(data_path)
    page = build_projects_page(data, page_name=page_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_yaml(page), encoding="utf-8")
    click.echo(f"wrote {output_path}")


@projects.command("update-config")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Inventory JSON generated from repository metadata.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing Glance YAML config.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output path for the updated Glance YAML config.")
@click.option("--page-name", default=PAGE_NAME, show_default=True, help="Generated Glance page name.")
def update_projects_config(data_path: Path, config_path: Path, output_path: Path, page_name: str) -> None:
    """Write a config copy with the generated project page replaced."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    update_projects_page_from_files(config_path, data_path, output_path, page_name=page_name)
    click.echo(f"wrote {output_path}")


@main.group()
def disks() -> None:
    """Patch Glance server-stats disk display."""


@disks.command("root-only")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing Glance YAML config.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output path for the patched Glance YAML config.")
@click.option("--mountpoint", default="/", show_default=True, help="Only mountpoint to display.")
@click.option("--name", "mount_name", default="根分区", show_default=True, help="Display name for the mountpoint.")
def root_only_disk(config_path: Path, output_path: Path, mountpoint: str, mount_name: str) -> None:
    """Write a config copy that hides default snap/loop mountpoints."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    patch_disks_from_files(config_path, output_path, mountpoint=mountpoint, name=mount_name)
    click.echo(f"wrote {output_path}")


@main.group()
def home() -> None:
    """Patch ChatArch home-page widgets."""


@home.command("remove-widget")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing Glance YAML config.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output path for the patched Glance YAML config.")
@click.option("--type", "widget_types", multiple=True, required=True, help="Glance widget type to remove from the ChatArch home page. Repeat for multiple types.")
@click.option("--home-page-name", default="ChatArch", show_default=True, help="Home page name to patch.")
def remove_home_widget(config_path: Path, output_path: Path, widget_types: tuple[str, ...], home_page_name: str) -> None:
    """Write a config copy with unavailable home-page widgets removed."""

    config = load_yaml(config_path)
    updated = remove_home_widget_types(config, set(widget_types), home_page_name=home_page_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(output_path, updated)
    click.echo(f"wrote {output_path} removed={','.join(widget_types)}")


@main.group()
def servers() -> None:
    """Collect and render the `服务器` Glance page."""


@servers.command("candidates")
@click.option("--config", "ssh_config", type=click.Path(path_type=Path, dir_okay=False), help="SSH config to scan. Defaults to ~/.ssh/config.")
@click.option("--inventory-config", type=click.Path(path_type=Path, dir_okay=False, exists=True), help="Infra/server inventory YAML. When set, print configured aliases.")
def server_candidates(ssh_config: Path | None, inventory_config: Path | None) -> None:
    """Print selected server aliases without probing hosts."""

    from chatglance.servers import dedupe_aliases_by_target, ssh_config_aliases

    ssh_aliases = ssh_config_aliases(ssh_config) if ssh_config else None
    if inventory_config:
        config = load_server_inventory_config(inventory_config)
        aliases = aliases_from_inventory_config(config, ssh_aliases=ssh_aliases)
    else:
        aliases = default_candidate_aliases(ssh_aliases)
    aliases = dedupe_aliases_by_target(aliases)
    for alias in aliases:
        click.echo(alias)


@servers.command("collect")
@click.option("--alias", "aliases", multiple=True, help="SSH alias to collect. Repeat for multiple servers.")
@click.option("--inventory-config", type=click.Path(path_type=Path, dir_okay=False, exists=True), help="Infra/server inventory YAML with aliases, exclusions, labels, timeout, and workers.")
@click.option("--default-candidates/--no-default-candidates", default=False, show_default=True, help="Use ChatGlance's default SSH-config candidate filter when --alias is omitted.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output server-status JSON path.")
@click.option("--timeout", default=None, type=int, help="Per-host SSH probe timeout in seconds. Overrides inventory config.")
@click.option("--workers", default=None, type=int, help="Parallel read-only SSH workers. Overrides inventory config.")
def collect_servers(aliases: tuple[str, ...], inventory_config: Path | None, default_candidates: bool, output_path: Path, timeout: int | None, workers: int | None) -> None:
    """Write a server-status JSON snapshot from read-only SSH probes."""

    selected = list(aliases)
    config: dict | None = None
    if inventory_config:
        config = load_server_inventory_config(inventory_config)
        selected.extend(aliases_from_inventory_config(config))
    if not selected and default_candidates:
        selected = default_candidate_aliases()
    if not selected:
        raise click.ClickException("pass --alias, use --inventory-config, or use --default-candidates")
    options = collection_options_from_inventory_config(config or {})
    host_overrides = host_connection_overrides_from_inventory_config(config or {})
    data = collect_server_status(
        selected,
        timeout=timeout or options["timeout"],
        workers=workers or options["workers"],
        host_overrides=host_overrides,
    )
    if config:
        data = apply_server_inventory_config(data, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_json(data), encoding="utf-8")
    click.echo(f"wrote {output_path} count={data.get('count', 0)} online={data.get('online', 0)}")


@servers.command("validate-refresh")
@click.option("--previous", "previous_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing server-status JSON snapshot.")
@click.option("--next", "next_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Newly collected server-status JSON snapshot.")
@click.option("--allow-offline-regression", is_flag=True, help="Allow replacing an online host with a non-online status.")
def validate_servers_refresh(previous_path: Path, next_path: Path, allow_offline_regression: bool) -> None:
    """Validate a refresh snapshot without modifying either input."""

    previous = load_server_status(previous_path)
    current = load_server_status(next_path)
    regressions = server_status_regressions(previous, current)
    if regressions and not allow_offline_regression:
        aliases = ",".join(regressions)
        raise click.ClickException(f"server refresh would mark previously online hosts non-online: {aliases}")
    click.echo(f"server-refresh-valid regressions={len(regressions)}")


@servers.command("render-page")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Server-status JSON snapshot.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="YAML file to write the generated Glance page object to.")
@click.option("--inventory-config", type=click.Path(path_type=Path, dir_okay=False, exists=True), help="Infra/server inventory YAML. Supplies page name/slug/title when present.")
@click.option("--page-name", default=None, help=f"Generated Glance page name. Defaults to inventory config or {SERVER_PAGE_NAME}.")
@click.option("--page-slug", default=None, help="Generated Glance page slug. Defaults to inventory config or servers.")
@click.option("--widget-title", default=None, help="Generated Glance HTML widget title. Defaults to inventory config or 服务器状态.")
def render_servers_page(data_path: Path, output_path: Path, inventory_config: Path | None, page_name: str | None, page_slug: str | None, widget_title: str | None) -> None:
    """Write the `服务器` page YAML from server-status JSON."""

    config = load_server_inventory_config(inventory_config) if inventory_config else {}
    page_options = page_options_from_inventory_config(config)
    data = load_server_status(data_path)
    page = build_servers_page(
        data,
        page_name=page_name or page_options["page_name"],
        page_slug=page_slug or page_options["page_slug"],
        widget_title=widget_title or page_options["widget_title"],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_yaml(page), encoding="utf-8")
    click.echo(f"wrote {output_path}")


@servers.command("update-config")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Server-status JSON snapshot.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing Glance YAML config.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output path for the updated Glance YAML config.")
@click.option("--inventory-config", type=click.Path(path_type=Path, dir_okay=False, exists=True), help="Infra/server inventory YAML. Supplies page name/slug/title when present.")
@click.option("--page-name", default=None, help=f"Generated Glance page name. Defaults to inventory config or {SERVER_PAGE_NAME}.")
@click.option("--page-slug", default=None, help="Generated Glance page slug. Defaults to inventory config or servers.")
@click.option("--widget-title", default=None, help="Generated Glance HTML widget title. Defaults to inventory config or 服务器状态.")
def update_servers_config(data_path: Path, config_path: Path, output_path: Path, inventory_config: Path | None, page_name: str | None, page_slug: str | None, widget_title: str | None) -> None:
    """Write a config copy with the generated server page replaced."""

    inventory = load_server_inventory_config(inventory_config) if inventory_config else {}
    page_options = page_options_from_inventory_config(inventory)
    data = load_server_status(data_path)
    config = load_yaml(config_path)
    updated = replace_servers_page(
        config,
        data,
        page_name=page_name or page_options["page_name"],
        page_slug=page_slug or page_options["page_slug"],
        widget_title=widget_title or page_options["widget_title"],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(output_path, updated)
    click.echo(f"wrote {output_path}")


@main.group()
def sites() -> None:
    """Collect and render the `网站服务` Glance page."""


@sites.command("collect")
@click.option("--inventory-config", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Reviewed website-service inventory YAML.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output site-services JSON path.")
@click.option("--gatus-db", type=click.Path(path_type=Path, dir_okay=False), help="Optional Gatus sqlite DB used to attach latest local monitor status.")
def collect_sites(inventory_config: Path, output_path: Path, gatus_db: Path | None) -> None:
    """Write reviewed site cards and optional Uptime status to JSON."""

    data = load_sites_inventory(inventory_config)
    if gatus_db:
        data = apply_gatus_status(data, gatus_db)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_sites_json(data), encoding="utf-8")
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    click.echo(
        " ".join(
            [
                f"wrote {output_path}",
                f"generated_at={data.get('generated_at')}",
                f"sites={counts.get('sites', 0)}",
                f"healthy={counts.get('healthy', 0)}",
                f"monitored={counts.get('monitored', 0)}",
            ]
        )
    )


@sites.command("render-page")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Site-services JSON generated from reviewed inventory.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="YAML file to write the generated Glance page object to.")
@click.option("--page-name", default=SITES_PAGE_NAME, show_default=True, help="Generated Glance page name.")
@click.option("--page-slug", default=SITES_DEFAULT_PAGE_SLUG, show_default=True, help="Generated Glance page slug.")
@click.option("--widget-title", default=SITES_DEFAULT_WIDGET_TITLE, show_default=True, help="Generated Glance HTML widget title.")
def render_sites_page(data_path: Path, output_path: Path, page_name: str, page_slug: str, widget_title: str) -> None:
    """Write the `网站服务` page YAML from site-services JSON."""

    data = load_sites_data(data_path)
    page = build_sites_page(data, page_name=page_name, page_slug=page_slug, widget_title=widget_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_sites_yaml(page), encoding="utf-8")
    click.echo(f"wrote {output_path}")


@sites.command("export-covers")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Site-services JSON generated from reviewed inventory.")
@click.option("--output-dir", type=click.Path(path_type=Path, file_okay=False), required=True, help="Directory where generated SVG covers are written.")
@click.option("--public-base-url", help="Optional public base URL to attach as cover_url values in the updated JSON.")
@click.option("--updated-data", type=click.Path(path_type=Path, dir_okay=False), help="Optional output JSON path with cover_url values attached.")
def export_sites_covers(data_path: Path, output_dir: Path, public_base_url: str | None, updated_data: Path | None) -> None:
    """Write SVG covers and an optional updated inventory JSON."""

    data = load_sites_data(data_path)
    updated = export_site_covers(data, output_dir, public_base_url=public_base_url)
    if updated_data:
        updated_data.parent.mkdir(parents=True, exist_ok=True)
        updated_data.write_text(dump_sites_json(updated), encoding="utf-8")
    count = len([item for item in updated.get("sites", []) if isinstance(item, dict)])
    click.echo(f"wrote {count} covers to {output_dir}")


@sites.command("update-config")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Site-services JSON generated from reviewed inventory.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing Glance YAML config.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output path for the updated Glance YAML config.")
@click.option("--page-name", default=SITES_PAGE_NAME, show_default=True, help="Generated Glance page name.")
@click.option("--page-slug", default=SITES_DEFAULT_PAGE_SLUG, show_default=True, help="Generated Glance page slug.")
@click.option("--widget-title", default=SITES_DEFAULT_WIDGET_TITLE, show_default=True, help="Generated Glance HTML widget title.")
def update_sites_config(data_path: Path, config_path: Path, output_path: Path, page_name: str, page_slug: str, widget_title: str) -> None:
    """Write a config copy with the generated website-services page replaced."""

    data = load_sites_data(data_path)
    config = load_yaml(config_path)
    updated = replace_sites_page(config, data, page_name=page_name, page_slug=page_slug, widget_title=widget_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(output_path, updated)
    click.echo(f"wrote {output_path}")


@main.group("account-limits")
def account_limits() -> None:
    """Render the `订阅详情` Glance page."""


@account_limits.command("json")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Raw account-limits JSON to normalize and redact.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output normalized account-limits JSON path.")
def normalize_account_limits_json(data_path: Path, output_path: Path) -> None:
    """Write normalized, redacted account/quota JSON."""

    data = load_account_limits_data(data_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_account_limits_json(data), encoding="utf-8")
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    click.echo(
        " ".join(
            [
                f"wrote {output_path}",
                f"generated_at={data.get('generated_at')}",
                f"accounts={counts.get('accounts', 0)}",
                f"codex_profiles={counts.get('codex_profiles', 0)}",
                f"codex_windows={counts.get('codex_windows', 0)}",
            ]
        )
    )


@account_limits.command("render-page")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Account-limits JSON generated from account/quota collectors.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="YAML file to write the generated Glance page object to.")
@click.option("--page-name", default=ACCOUNT_LIMITS_PAGE_NAME, show_default=True, help="Generated Glance page name.")
@click.option("--page-slug", default=ACCOUNT_LIMITS_DEFAULT_PAGE_SLUG, show_default=True, help="Generated Glance page slug.")
@click.option("--widget-title", default=ACCOUNT_LIMITS_DEFAULT_WIDGET_TITLE, show_default=True, help="Generated Glance HTML widget title.")
def render_account_limits_page(data_path: Path, output_path: Path, page_name: str, page_slug: str, widget_title: str) -> None:
    """Write the `订阅详情` page YAML from account-limits JSON."""

    data = load_account_limits_data(data_path)
    page = build_account_limits_page(data, page_name=page_name, page_slug=page_slug, widget_title=widget_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_account_limits_yaml(page), encoding="utf-8")
    click.echo(f"wrote {output_path}")


@account_limits.command("update-config")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Account-limits JSON generated from account/quota collectors.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Existing Glance YAML config.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Output path for the updated Glance YAML config.")
@click.option("--page-name", default=ACCOUNT_LIMITS_PAGE_NAME, show_default=True, help="Generated Glance page name.")
@click.option("--page-slug", default=ACCOUNT_LIMITS_DEFAULT_PAGE_SLUG, show_default=True, help="Generated Glance page slug.")
@click.option("--widget-title", default=ACCOUNT_LIMITS_DEFAULT_WIDGET_TITLE, show_default=True, help="Generated Glance HTML widget title.")
def update_account_limits_config(data_path: Path, config_path: Path, output_path: Path, page_name: str, page_slug: str, widget_title: str) -> None:
    """Write a config copy with the generated account-limits page replaced."""

    data = load_account_limits_data(data_path)
    config = load_yaml(config_path)
    updated = replace_account_limits_page(config, data, page_name=page_name, page_slug=page_slug, widget_title=widget_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(output_path, updated)
    click.echo(f"wrote {output_path}")


@main.group()
def runtime() -> None:
    """Maintain a durable Glance service runtime."""


@runtime.command("maintain")
@click.option("--runtime-home", type=click.Path(path_type=Path, file_okay=False), default=Path("~/.chatarch/glance"), show_default=True, help="Durable Glance service home.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False), default=Path("config/glance.yml"), show_default=True, help="Runtime-relative or absolute Glance YAML config.")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False), default=Path("data/chatarch-projects.json"), show_default=True, help="Runtime-relative or absolute repository inventory JSON.")
@click.option("--backup-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("config/backups"), show_default=True, help="Runtime-relative or absolute backup directory for in-place writes.")
@click.option("--page-name", default=PAGE_NAME, show_default=True, help="Generated Glance page name.")
@click.option("--validate/--no-validate", default=True, show_default=True, help="Validate the candidate config with the upstream Glance binary before replacing it.")
@click.option("--glance-bin", type=click.Path(path_type=Path, dir_okay=False), default=Path("bin/glance"), show_default=True, help="Runtime-relative or absolute Glance binary used for config validation.")
@click.option("--restart-service", default=None, help="systemd user service to restart only if the rendered config changed.")
def maintain_runtime(runtime_home: Path, config_path: Path, data_path: Path, backup_dir: Path, page_name: str, validate: bool, glance_bin: Path, restart_service: str | None) -> None:
    """Update runtime config atomically and optionally restart a service."""

    runtime_home = runtime_home.expanduser()
    config = runtime_path(runtime_home, config_path)
    data = runtime_path(runtime_home, data_path)
    backups = runtime_path(runtime_home, backup_dir) if backup_dir else None
    binary = runtime_path(runtime_home, glance_bin) if validate else None
    mountpoints = discover_meaningful_mountpoints()
    result = maintain_config(
        config_path=config,
        data_path=data,
        output_path=config,
        backup_dir=backups,
        validate_bin=binary,
        page_name=page_name,
        restart_service=restart_service,
        mountpoints=mountpoints,
    )
    click.echo(
        " ".join(
            [
                f"output={result.output_path}",
                f"changed={str(result.changed).lower()}",
                f"validated={str(result.validated).lower()}",
                f"restarted={str(result.restarted).lower()}",
                f"mountpoints={','.join(mountpoints)}",
                f"backup={result.backup_path or '-'}",
            ]
        )
    )


@runtime.command("render-systemd")
@click.option("--runtime-home", type=click.Path(path_type=Path, file_okay=False), default=Path("~/.chatarch/glance"), show_default=True, help="Durable Glance service home.")
@click.option("--chatglance-bin", type=click.Path(path_type=Path, dir_okay=False), required=True, help="Absolute path to the chatglance executable used by the maintenance oneshot.")
@click.option("--service-name", default="chatarch-glance.service", show_default=True, help="Main Glance user service name.")
@click.option("--maintenance-service-name", default="chatarch-glance-maintenance.service", show_default=True, help="Generated oneshot maintenance service name.")
@click.option("--timer-name", default="chatarch-glance-maintenance.timer", show_default=True, help="Generated maintenance timer name.")
@click.option("--interval", default="30min", show_default=True, help="systemd OnUnitActiveSec interval for the maintenance timer.")
@click.option("--output-dir", type=click.Path(path_type=Path, file_okay=False), help="Directory to write unit files. Omit to print them.")
def render_systemd(runtime_home: Path, chatglance_bin: Path, service_name: str, maintenance_service_name: str, timer_name: str, interval: str, output_dir: Path | None) -> None:
    """Print user units or write them to an output directory."""

    units = render_all_units(
        runtime_home=runtime_home.expanduser(),
        chatglance_bin=chatglance_bin.expanduser(),
        service_name=service_name,
        maintenance_service_name=maintenance_service_name,
        timer_name=timer_name,
        interval=interval,
    )
    if output_dir:
        paths = write_units(output_dir.expanduser(), units)
        for path in paths:
            click.echo(f"wrote {path}")
        return
    click.echo(f"# {units.service_name}\n{units.service}")
    click.echo(f"# {units.maintenance_service_name}\n{units.maintenance_service}")
    click.echo(f"# {units.timer_name}\n{units.timer}")


@runtime.command("install-systemd")
@click.option("--runtime-home", type=click.Path(path_type=Path, file_okay=False), default=Path("~/.chatarch/glance"), show_default=True, help="Durable Glance service home.")
@click.option("--chatglance-bin", type=click.Path(path_type=Path, dir_okay=False), help="Absolute path to the chatglance executable used by the maintenance oneshot. Defaults to PATH lookup.")
@click.option("--output-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("~/.config/systemd/user"), show_default=True, help="User systemd unit directory.")
@click.option("--service-name", default="chatarch-glance.service", show_default=True, help="Main Glance user service name.")
@click.option("--maintenance-service-name", default="chatarch-glance-maintenance.service", show_default=True, help="Generated oneshot maintenance service name.")
@click.option("--timer-name", default="chatarch-glance-maintenance.timer", show_default=True, help="Generated maintenance timer name.")
@click.option("--interval", default="30min", show_default=True, help="systemd OnUnitActiveSec interval for the maintenance timer.")
@click.option("--verify/--no-verify", default=True, show_default=True, help="Run systemd-analyze --user verify before daemon-reload.")
@click.option("--enable/--no-enable", default=True, show_default=True, help="Enable the Glance service and maintenance timer for user login.")
@click.option("--start/--no-start", default=False, show_default=True, help="Start the Glance service and maintenance timer after installation.")
def install_systemd(
    runtime_home: Path,
    chatglance_bin: Path | None,
    output_dir: Path,
    service_name: str,
    maintenance_service_name: str,
    timer_name: str,
    interval: str,
    verify: bool,
    enable: bool,
    start: bool,
) -> None:
    """Install, verify, enable, and optionally start user-level systemd units."""

    binary = _resolve_chatglance_bin(chatglance_bin)
    try:
        result = install_user_units(
            runtime_home=runtime_home.expanduser(),
            chatglance_bin=binary,
            output_dir=output_dir.expanduser(),
            service_name=service_name,
            maintenance_service_name=maintenance_service_name,
            timer_name=timer_name,
            interval=interval,
            verify=verify,
            enable=enable,
            start=start,
        )
    except subprocess.CalledProcessError as exc:
        _raise_systemd_error(exc)
    click.echo(
        " ".join(
            [
                f"wrote={','.join(str(path) for path in result.paths)}",
                f"verified={str(result.verified).lower()}",
                f"daemon_reloaded={str(result.daemon_reloaded).lower()}",
                f"enabled={','.join(result.enabled_units) or '-'}",
                f"started={','.join(result.started_units) or '-'}",
            ]
        )
    )


@runtime.command("start")
@click.option("--service-name", default="chatarch-glance.service", show_default=True, help="Main Glance user service name.")
@click.option("--timer-name", default="chatarch-glance-maintenance.timer", show_default=True, help="Maintenance timer name.")
@click.option("--timer/--no-timer", default=True, show_default=True, help="Start the maintenance timer together with the main service.")
def start_runtime(service_name: str, timer_name: str, timer: bool) -> None:
    """Start the current Glance page through systemd user units."""

    units = [service_name]
    if timer:
        units.append(timer_name)
    try:
        systemctl_user("start", *units)
    except subprocess.CalledProcessError as exc:
        _raise_systemd_error(exc)
    click.echo(f"started={','.join(units)}")


@runtime.command("status")
@click.option("--service-name", default="chatarch-glance.service", show_default=True, help="Main Glance user service name.")
@click.option("--timer-name", default="chatarch-glance-maintenance.timer", show_default=True, help="Maintenance timer name.")
def status_runtime(service_name: str, timer_name: str) -> None:
    """Show safe systemd user status for the Glance service and timer."""

    try:
        status = show_user_units(service_name, timer_name)
    except subprocess.CalledProcessError as exc:
        _raise_systemd_error(exc)
    click.echo(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
