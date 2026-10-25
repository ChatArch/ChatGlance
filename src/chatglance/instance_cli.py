"""Thin, plan-first CLI for read-only named Glance instances."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sys

import click

from .instances import (InstanceSpec, configure_instance, initialize_instance,
                        load_instance, render_launchd_instance, set_instance_login)
from .page_modules import MODULES


def _emit(action, *args, **kwargs):
    try:
        result = action(*args, **kwargs)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


def register(runtime):
    runtime_path = click.Path(path_type=Path, file_okay=False)
    page_type = click.Choice(tuple(MODULES))

    @runtime.group("instance")
    def instance():
        """Plan and manage isolated read-only Glance runtimes."""

    @instance.command("init")
    @click.option("--runtime-home", type=runtime_path, required=True)
    @click.option("--name", required=True)
    @click.option("--env-profile", required=True)
    @click.option("--page", "pages", multiple=True, type=page_type, required=True)
    @click.option("--account", "accounts", multiple=True)
    @click.option("--host", required=True)
    @click.option("--port", type=click.IntRange(1, 65535), required=True)
    @click.option("--origin", required=True, help="Path-free HTTPS public origin.")
    @click.option("--interval-seconds", type=click.IntRange(60, 86400), default=1800, show_default=True)
    @click.option("--python-bin", type=click.Path(path_type=Path, dir_okay=False), help="Exact installed interpreter for owned launchd service.")
    @click.option("--glance-bin", type=click.Path(path_type=Path, dir_okay=False), help="Absolute shared installed Go binary; defaults to runtime bin/glance.")
    @click.option("--apply", is_flag=True, help="Create the private instance runtime; default is a plan.")
    def init(runtime_home, name, env_profile, pages, accounts, host, port, origin, interval_seconds, python_bin, glance_bin, apply):
        """Assemble selected native pages and a secret-free ownership manifest."""
        try:
            spec = InstanceSpec(name=name, env_profile=env_profile, pages=pages, accounts=accounts,
                                host=host, port=port, origin=origin, interval_seconds=interval_seconds,
                                python_bin=str(python_bin) if python_bin else None,
                                glance_bin=str(glance_bin) if glance_bin else None)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None
        _emit(initialize_instance, runtime_home, spec, apply=apply)

    @instance.command("show")
    @click.option("--runtime-home", type=runtime_path, required=True)
    def show(runtime_home):
        """Show the secret-free instance selection and owned service labels."""
        from .instances import service_identity
        _emit(lambda: {"spec": asdict(load_instance(runtime_home)), "service": service_identity(runtime_home)})

    @instance.command("configure")
    @click.option("--runtime-home", type=runtime_path, required=True)
    @click.option("--page", "pages", multiple=True, type=page_type)
    @click.option("--account", "accounts", multiple=True)
    @click.option("--host")
    @click.option("--port", type=click.IntRange(1, 65535))
    @click.option("--origin")
    @click.option("--interval-seconds", type=click.IntRange(60, 86400))
    @click.option("--python-bin", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--glance-bin", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--apply", is_flag=True, help="Publish the selected definition; default is a plan.")
    def configure(runtime_home, pages, accounts, host, port, origin, interval_seconds, python_bin, glance_bin, apply):
        """Enable or disable modules and accounts in the same named profile."""
        def action():
            old = load_instance(runtime_home)
            values = asdict(old)
            selected_pages = pages or old.pages
            values.update(pages=selected_pages, accounts=accounts or (() if "account-limits" not in selected_pages else old.accounts),
                          host=host or old.host, port=port or old.port,
                          origin=origin or old.origin, interval_seconds=interval_seconds or old.interval_seconds,
                          python_bin=str(python_bin) if python_bin else old.python_bin,
                          glance_bin=str(glance_bin) if glance_bin else old.glance_bin)
            return configure_instance(runtime_home, InstanceSpec(**values), apply=apply)
        _emit(action)

    @instance.command("set-login")
    @click.option("--runtime-home", type=runtime_path, required=True)
    @click.option("--username", required=True, help="Single Glance login username.")
    @click.option("--password-env", help="Name of an environment variable containing the password; never its value.")
    @click.option("--password-stdin", is_flag=True, help="Read password from standard input.")
    @click.option("--apply", is_flag=True, help="Save bcrypt hash and new session key to the named ChatEnv profile.")
    def set_login(runtime_home, username, password_env, password_stdin, apply):
        """Provision native Go login without accepting a plaintext password argument."""
        if password_env and password_stdin:
            raise click.ClickException("choose one password input")
        if password_env:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", password_env) or password_env not in os.environ:
                raise click.ClickException("password environment variable is unavailable")
            password = os.environ[password_env]
        elif password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        _emit(set_instance_login, runtime_home, username=username, password=password, apply=apply)

    @instance.command("render-launchd")
    @click.option("--runtime-home", type=runtime_path, required=True)
    @click.option("--python-bin", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--output-dir", type=runtime_path, help="Existing review directory, never LaunchAgents directly.")
    @click.option("--apply", is_flag=True, help="Write review templates; default lists their names only.")
    def render_launchd(runtime_home, python_bin, output_dir, apply):
        """Render owned native serve and refresh launchd templates for review."""
        def action():
            units = render_launchd_instance(runtime_home, python_bin=python_bin)
            result = {"applied": False, "platform": "macOS launchd", "units": list(units)}
            if not apply:
                return result
            if output_dir is None or output_dir.is_symlink() or not output_dir.is_dir():
                raise ValueError("an existing safe output directory is required")
            for name in units:
                if (output_dir / name).exists() or (output_dir / name).is_symlink():
                    raise ValueError("template destination already exists")
            written = []
            try:
                for name, body in units.items():
                    path = output_dir / name
                    with path.open("xb") as stream:
                        stream.write(body)
                    path.chmod(0o600)
                    written.append(path)
            except OSError:
                for path in written:
                    path.unlink(missing_ok=True)
                raise
            return {**result, "applied": True}
        _emit(action)
