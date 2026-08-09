"""CLI entrypoint for chatglance."""

from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import click

from chatglance import __version__
from chatglance.glance_config import patch_disks_from_files, update_projects_page_from_files
from chatglance.projects import PAGE_NAME, build_projects_page, dump_yaml, load_inventory
from chatglance.runtime import discover_meaningful_mountpoints, maintain_config, runtime_path
from chatglance.systemd import install_user_units, render_all_units, show_user_units, systemctl_user, write_units


def _purpose(command: click.Command) -> str:
    text = command.short_help or inspect.getdoc(command.callback) or ""
    return " ".join(text.strip().split()).rstrip(".")


def _parameter_piece(parameter: click.Parameter) -> str | None:
    if getattr(parameter, "hidden", False) or parameter.name == "help":
        return None
    if isinstance(parameter, click.Argument):
        piece = parameter.name.upper().replace("_", "-")
        if not parameter.required:
            piece = f"[{piece}]"
        if parameter.nargs == -1:
            piece = f"{piece}..."
        return piece
    if not isinstance(parameter, click.Option):
        return None
    option_names = [name for name in (*parameter.opts, *parameter.secondary_opts) if name.startswith("--")]
    if not option_names:
        option_names = [name for name in (*parameter.opts, *parameter.secondary_opts) if name.startswith("-")]
    if not option_names:
        return None
    if parameter.is_flag or parameter.flag_value is not None:
        piece = "/".join(option_names)
    else:
        metavar = parameter.metavar or parameter.name.upper().replace("_", "-")
        piece = f"{'/'.join(option_names)} {metavar}"
    if not parameter.required:
        piece = f"[{piece}]"
    return piece


def _command_signature(name: str, command: click.Command) -> str:
    pieces = [piece for piece in (_parameter_piece(parameter) for parameter in command.params) if piece]
    return " ".join([name, *pieces])


def _render_command_tree(command: click.Command, name: str, prefix: str, is_last: bool, lines: list[str]) -> None:
    connector = "└── " if is_last else "├── "
    line = f"{prefix}{connector}{_command_signature(name, command)}"
    purpose = _purpose(command)
    if purpose:
        line = f"{line}  # {purpose}"
    lines.append(line)
    if not isinstance(command, click.Group):
        return
    children = [(child_name, child) for child_name, child in command.commands.items() if not child.hidden]
    child_prefix = prefix + ("    " if is_last else "│   ")
    for index, (child_name, child) in enumerate(children):
        _render_command_tree(child, child_name, child_prefix, index == len(children) - 1, lines)


def _render_cli_tree(root: click.Group) -> str:
    children = [(name, command) for name, command in root.commands.items() if not command.hidden]
    lines = [f"chatglance  # {_purpose(root)}"]
    root_options = [
        ("--help", "Show help for the current command."),
        ("--version", "Show package version."),
        ("--tree", "Print the registered CLI tree."),
    ]
    for index, (option, purpose) in enumerate(root_options):
        is_last = not children and index == len(root_options) - 1
        lines.append(f"{'└──' if is_last else '├──'} {option}  # {purpose}")
    for index, (child_name, child) in enumerate(children):
        _render_command_tree(child, child_name, "", index == len(children) - 1, lines)
    return "\n".join(lines)


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


@click.group(invoke_without_command=True, no_args_is_help=True)
@click.version_option(__version__, prog_name="chatglance")
@click.option("--tree", "show_tree", is_flag=True, is_eager=True, help="Print the registered CLI tree.")
@click.pass_context
def main(ctx: click.Context, show_tree: bool) -> None:
    """Generate and maintain ChatArch Glance dashboard config."""

    if show_tree:
        click.echo(_render_cli_tree(ctx.command))
        ctx.exit()


@main.group()
def projects() -> None:
    """Generate Glance project dashboard pages."""


@projects.command("render-page")
@click.option("--data", "data_path", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True, help="Inventory JSON generated from repository metadata.")
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), required=True, help="YAML file to write the generated Glance page object to.")
@click.option("--page-name", default=PAGE_NAME, show_default=True, help="Generated Glance page name.")
def render_projects_page(data_path: Path, output_path: Path, page_name: str) -> None:
    """Render the `项目` page YAML from inventory JSON."""

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
    """Apply generated project content and root-only Disk config once."""

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
    """Render direct Glance service plus chatglance maintenance units."""

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
