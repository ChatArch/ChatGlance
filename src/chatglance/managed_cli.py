"""Thin Click adapters for the manifest-owned lifecycle APIs."""

import json
from pathlib import Path
import subprocess

import click
import yaml


def _emit(function, *args, **kwargs):
    try:
        result = function(*args, **kwargs)
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError, yaml.YAMLError) as error:
        raise click.ClickException(f"managed lifecycle failed ({type(error).__name__}); review configuration/ownership") from None
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def register(group):
    runtime_path = click.Path(path_type=Path, file_okay=False)

    @group.command("install")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--unit-dir", type=runtime_path, help="User-unit destination; stored in the ownership manifest.")
    @click.option("--python-bin", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--page", "pages", multiple=True, type=click.Choice(["projects", "servers", "sites", "account-limits"]))
    @click.option("--interval", help="Preserve prior cadence or default to 30min.")
    @click.option("--scheduled/--no-scheduled", default=None, help="Explicit scheduled account policy execution; off on first install.")
    @click.option("--controls/--no-controls", default=None)
    @click.option("--maintenance/--no-maintenance", default=None)
    @click.option("--web-unit", help="Adopt an existing web service name.")
    @click.option("--refresh-unit", help="Adopt an existing refresh service name.")
    @click.option("--refresh-timer", help="Adopt an existing refresh timer name.")
    @click.option("--controls-unit", help="Adopt an existing control service name.")
    @click.option("--maintenance-unit", help="Adopt an existing maintenance service name.")
    @click.option("--maintenance-timer", help="Adopt an existing maintenance timer name.")
    @click.option("--adopt-units", is_flag=True, help="Authorize replacement of reviewed existing selected units.")
    @click.option("--retire-dropins", is_flag=True, help="Back up and retire selected owned-unit drop-ins after review.")
    @click.option("--apply", "--yes", is_flag=True, help="Verify, back up, install and daemon-reload; otherwise plan only.")
    @click.option("--enable", is_flag=True, help="Enable owned entry units only when applying.")
    @click.option("--start", is_flag=True, help="Start owned entry units only when applying.")
    def install(runtime_home, unit_dir, python_bin, pages, interval, scheduled, controls, maintenance,
                web_unit, refresh_unit, refresh_timer, controls_unit, maintenance_unit, maintenance_timer,
                adopt_units, retire_dropins, apply, enable, start):
        """Plan or atomically install the managed user-service bundle."""
        from .managed import install_runtime
        names = {role: name for role, name in {
            "web": web_unit, "refresh": refresh_unit, "refresh_timer": refresh_timer, "controls": controls_unit,
            "maintenance": maintenance_unit, "maintenance_timer": maintenance_timer,
        }.items() if name is not None}
        _emit(install_runtime, runtime_home, unit_dir=unit_dir, python_bin=python_bin, pages=pages or None,
              interval=interval, scheduled=scheduled, controls=controls, maintenance=maintenance, names=names,
              adopt_units=adopt_units, retire_dropins=retire_dropins, apply=apply, enable=enable, start=start)

    @group.command("import-env")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--file", "source", required=True, help="A reviewed config/NAME.env or private/NAME.env path relative to runtime.")
    @click.option("--replace-provider", is_flag=True, help="Authorize typed-provider conflicts explicitly.")
    @click.option("--retire", is_flag=True, help="Privately back up and remove the reviewed source after typed readback.")
    @click.option("--apply", "--yes", is_flag=True)
    def import_env(runtime_home, source, replace_provider, retire, apply):
        """Import supported literal legacy settings into typed ChatEnv."""
        from .managed import import_legacy_environment
        _emit(import_legacy_environment, runtime_home, source, replace_provider=replace_provider, retire=retire, apply=apply)

    @group.command("adopt")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--public-origin", help="Exact reviewed HTTPS public origin, never credentials.")
    @click.option("--control-port", type=click.IntRange(1, 65535))
    @click.option("--replace-provider", is_flag=True, help="Authorize replacement of conflicting typed login values.")
    @click.option("--apply", "--yes", is_flag=True, help="Migrate secrets after Go validation; otherwise safe counts only.")
    def adopt(runtime_home, public_origin, control_port, replace_provider, apply):
        """Import existing login accounts into typed ChatEnv without losing pages."""
        from .managed import adopt_runtime
        _emit(adopt_runtime, runtime_home, public_origin=public_origin, control_port=control_port,
              replace_provider=replace_provider, apply=apply)

    @group.command("check")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--live", is_flag=True, help="Also read bounded owned-unit state and PIDs.")
    def check(runtime_home, live):
        """Validate Go config and report installed-code, binary and owned-file evidence."""
        from .managed import runtime_status
        result = _emit(runtime_status, runtime_home, live=live, validate=True)
        if not result.get("managed") or not result.get("binary_matches", False) or not result.get("effective_matches") or any(not item["matches"] for item in result["units"].values()):
            raise click.exceptions.Exit(1)

    @group.command("update")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--archive", required=True, type=click.Path(path_type=Path, exists=True, dir_okay=False))
    @click.option("--sha256", required=True)
    @click.option("--binary-version", required=True)
    @click.option("--restart", is_flag=True, help="Restart only the owned web service after checked publication.")
    @click.option("--apply", "--yes", is_flag=True)
    def update(runtime_home, archive, sha256, binary_version, restart, apply):
        """Plan or verify and update Go binary with private rollback backups."""
        from .managed import update_binary
        _emit(update_binary, runtime_home, archive, sha256, binary_version, restart=restart, apply=apply)

    @group.command("rollback")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--backup", required=True, help="Managed backup identifier, never an arbitrary path.")
    @click.option("--apply", "--yes", is_flag=True)
    def rollback(runtime_home, backup, apply):
        """Plan or restore unchanged managed files from a private backup."""
        from .managed import rollback_runtime
        _emit(rollback_runtime, runtime_home, backup, apply=apply)

    @group.command("stop")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--unit", "units", multiple=True, help="Restrict to an owned unit name.")
    @click.option("--apply", "--yes", is_flag=True)
    def stop(runtime_home, units, apply):
        """Plan or stop only manifest-owned runtime entries."""
        from .managed import service_action
        _emit(service_action, runtime_home, "stop", units=units, apply=apply)

    @group.command("restart")
    @click.option("--runtime-home", type=runtime_path)
    @click.option("--unit", "units", multiple=True, help="Restrict to an owned unit name.")
    @click.option("--apply", "--yes", is_flag=True)
    def restart(runtime_home, units, apply):
        """Plan or restart only manifest-owned runtime entries."""
        from .managed import service_action
        _emit(service_action, runtime_home, "restart", units=units, apply=apply)

    @group.command("refresh-managed")
    @click.option("--runtime-home", type=runtime_path)
    def refresh(runtime_home):
        """Run the owned schedule through the shared native refresh pipeline."""
        from .managed import refresh_managed
        result = _emit(refresh_managed, runtime_home)
        if not result["ok"]:
            raise click.exceptions.Exit(1)

    @group.command("maintain-managed")
    @click.option("--runtime-home", type=runtime_path)
    def maintain(runtime_home):
        """Run opt-in maintenance only while the native collector is idle."""
        from .managed import maintain_managed
        _emit(maintain_managed, runtime_home)
