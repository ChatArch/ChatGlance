"""systemd user-unit rendering and installation for chatglance-managed Glance runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Iterable
import re
import sys


@dataclass(frozen=True)
class SystemdUnits:
    """Rendered systemd user units for a Glance runtime."""

    service_name: str
    service: str
    maintenance_service_name: str
    maintenance_service: str
    timer_name: str
    timer: str


@dataclass(frozen=True)
class UserSystemdInstallResult:
    """Result of writing and optionally activating systemd user units."""

    paths: tuple[Path, ...]
    verified: bool
    daemon_reloaded: bool
    enabled_units: tuple[str, ...]
    started_units: tuple[str, ...]


def _path(value: str | Path) -> str:
    return str(Path(value).expanduser())


def _systemd_arg(value: str | Path) -> str:
    """Render a single systemd ExecStart argument.

    For the ChatArch runtime paths this is normally a plain absolute path. The
    small quoting branch keeps generated units valid if a user-level install path
    contains spaces while avoiding shell-style quoting in path directives such as
    WorkingDirectory=.
    """

    text = _path(value)
    if any(char in text for char in " \t\""):
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    return text


def _portable_arg(value: str | Path) -> str:
    text = str(value)
    if not text or any(char in text for char in "\r\n\0"):
        raise ValueError("invalid systemd argument")
    text = text.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return '"' + text + '"'


def render_portable_units(
    *, runtime_home: str | Path, python_bin: str | Path | None = None,
    pages: tuple[str, ...] | None = None, interval: str | None = None, controls: bool = False,
) -> dict[str, str]:
    """Review-only user units; no registration or activation."""
    root = Path(runtime_home).expanduser().absolute()
    executable = Path(python_bin or sys.executable).expanduser()
    if not executable.is_absolute() or not root.is_absolute():
        raise ValueError("absolute entry paths required")
    if pages is None or interval is None:
        from .portable import portable_settings
        defaults = portable_settings()
        pages = defaults["pages"] if pages is None else pages
        interval = defaults["interval"] if interval is None else interval
    if not re.fullmatch(r"[0-9]+(?:min|h|d)", interval):
        raise ValueError("invalid timer interval")
    if any(page not in ("projects", "servers", "sites") for page in pages):
        raise ValueError("portable timer supports only non-account pages")
    command = f"{_portable_arg(executable)} -m chatglance.cli"
    home = _portable_arg(root)
    units = {
        "chatglance-portable.service": (
            "[Unit]\nDescription=Portable Glance loopback server\n\n[Service]\nType=simple\n"
            f"ExecStart={command} runtime serve --runtime-home {home}\nRestart=on-failure\n\n"
            "[Install]\nWantedBy=default.target\n"
        ),
    }
    if pages:
        units["chatglance-portable-refresh.service"] = (
            "[Unit]\nDescription=Portable Glance non-consuming page refresh\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart={command} refresh --run-source scheduled --runtime-home {home} --service-name chatglance-portable.service "
            + " ".join(pages) + "\n"
        )
        units["chatglance-portable-refresh.timer"] = (
            "[Unit]\nDescription=Portable Glance page refresh schedule\n\n[Timer]\n"
            f"OnUnitActiveSec={interval}\nUnit=chatglance-portable-refresh.service\n\n"
            "[Install]\nWantedBy=timers.target\n"
        )
    if controls:
        units["chatglance-portable-controls.service"] = (
            "[Unit]\nDescription=Optional authenticated Glance controls\n\n"
            "[Service]\nType=simple\n"
            f"ExecStart={command} runtime controls --runtime-home {home}\n"
            "Restart=on-failure\n\n[Install]\nWantedBy=default.target\n"
        )
    return units


def write_portable_units(output_dir: str | Path, units: dict[str, str]) -> list[Path]:
    """Write new review units only, refusing symlinks and existing files."""
    from .portable import _create

    root = Path(output_dir).expanduser().absolute()
    paths = []
    for name, content in units.items():
        if name not in {"chatglance-portable.service", "chatglance-portable-refresh.service",
                        "chatglance-portable-refresh.timer", "chatglance-portable-controls.service"}:
            raise ValueError("invalid portable unit name")
        target = root / name
        if not _create(target, content.encode()):
            raise ValueError("unit already exists; review before replacing")
        paths.append(target)
    return paths


def user_systemd_dir() -> Path:
    """Return the current user's systemd unit directory."""

    return Path("~/.config/systemd/user").expanduser()


def render_glance_service(
    *,
    runtime_home: str | Path,
    glance_bin: str | Path = "bin/glance",
    config_path: str | Path = "config/glance.yml",
    description: str = "ChatArch Glance dashboard",
) -> str:
    """Render the long-running Glance service unit.

    This intentionally starts the upstream Glance binary directly. `chatglance`
    is not a Python wrapper around the server process.
    """

    home = Path(runtime_home).expanduser()
    binary = Path(glance_bin)
    if not binary.is_absolute():
        binary = home / binary
    config = Path(config_path)
    if not config.is_absolute():
        config = home / config
    return f"""[Unit]
Description={description}
After=network-online.target

[Service]
Type=simple
WorkingDirectory={_path(home)}
ExecStart={_systemd_arg(binary)} -config {_systemd_arg(config)}
Restart=always
RestartSec=5
StandardOutput=append:{_path(home / 'logs/glance.stdout.log')}
StandardError=append:{_path(home / 'logs/glance.stderr.log')}

[Install]
WantedBy=default.target
"""


def render_maintenance_service(
    *,
    runtime_home: str | Path,
    chatglance_bin: str | Path,
    restart_service: str = "chatarch-glance.service",
    description: str = "Maintain ChatArch Glance generated config",
) -> str:
    """Render a oneshot maintenance unit that applies generated content.

    The unit calls `chatglance runtime maintain`, validates with the Glance
    binary, and restarts the Glance user service only when the rendered config
    changed.
    """

    home = Path(runtime_home).expanduser()
    return f"""[Unit]
Description={description}
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={_path(home)}
ExecStart={_systemd_arg(chatglance_bin)} runtime maintain --runtime-home {_systemd_arg(home)} --restart-service {restart_service}
"""


def render_timer(
    *,
    timer_unit: str = "chatarch-glance-maintenance.service",
    interval: str = "30min",
    description: str = "Run ChatArch Glance maintenance periodically",
) -> str:
    """Render a periodic systemd user timer for the maintenance oneshot."""

    return f"""[Unit]
Description={description}

[Timer]
OnBootSec=5min
OnUnitActiveSec={interval}
Persistent=true
Unit={timer_unit}

[Install]
WantedBy=timers.target
"""


def render_all_units(
    *,
    runtime_home: str | Path,
    chatglance_bin: str | Path,
    service_name: str = "chatarch-glance.service",
    maintenance_service_name: str = "chatarch-glance-maintenance.service",
    timer_name: str = "chatarch-glance-maintenance.timer",
    interval: str = "30min",
) -> SystemdUnits:
    """Render the recommended user-service topology for a Glance runtime."""

    return SystemdUnits(
        service_name=service_name,
        service=render_glance_service(runtime_home=runtime_home),
        maintenance_service_name=maintenance_service_name,
        maintenance_service=render_maintenance_service(
            runtime_home=runtime_home,
            chatglance_bin=chatglance_bin,
            restart_service=service_name,
        ),
        timer_name=timer_name,
        timer=render_timer(timer_unit=maintenance_service_name, interval=interval),
    )


def write_units(output_dir: str | Path, units: SystemdUnits) -> list[Path]:
    """Write rendered units to an output directory."""

    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    paths = [
        root / units.service_name,
        root / units.maintenance_service_name,
        root / units.timer_name,
    ]
    contents = [units.service, units.maintenance_service, units.timer]
    for path, content in zip(paths, contents, strict=True):
        path.write_text(content, encoding="utf-8")
    return paths


def _run(args: Iterable[str | Path]) -> subprocess.CompletedProcess[str]:
    """Run a systemd command while preserving stderr for Click to surface."""

    return subprocess.run([str(arg) for arg in args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def verify_user_units(paths: Iterable[str | Path], *, systemd_analyze_bin: str | Path = "systemd-analyze") -> None:
    """Verify rendered systemd user units before activation."""

    _run([systemd_analyze_bin, "--user", "verify", *paths])


def systemctl_user(*args: str | Path, systemctl_bin: str | Path = "systemctl") -> subprocess.CompletedProcess[str]:
    """Run `systemctl --user` with captured output."""

    return _run([systemctl_bin, "--user", *args])


def install_user_units(
    *,
    runtime_home: str | Path,
    chatglance_bin: str | Path,
    output_dir: str | Path | None = None,
    service_name: str = "chatarch-glance.service",
    maintenance_service_name: str = "chatarch-glance-maintenance.service",
    timer_name: str = "chatarch-glance-maintenance.timer",
    interval: str = "30min",
    verify: bool = True,
    enable: bool = True,
    start: bool = False,
    systemd_analyze_bin: str | Path = "systemd-analyze",
    systemctl_bin: str | Path = "systemctl",
) -> UserSystemdInstallResult:
    """Install and optionally enable/start the recommended user units.

    This is deliberately user-level only: files are written under
    `~/.config/systemd/user` by default and commands use `systemctl --user`.
    """

    units = render_all_units(
        runtime_home=runtime_home,
        chatglance_bin=chatglance_bin,
        service_name=service_name,
        maintenance_service_name=maintenance_service_name,
        timer_name=timer_name,
        interval=interval,
    )
    paths = tuple(write_units(output_dir or user_systemd_dir(), units))
    if verify:
        verify_user_units(paths, systemd_analyze_bin=systemd_analyze_bin)
    systemctl_user("daemon-reload", systemctl_bin=systemctl_bin)
    enabled_units: tuple[str, ...] = ()
    started_units: tuple[str, ...] = ()
    if enable:
        enabled_units = (units.service_name, units.timer_name)
        systemctl_user("enable", *enabled_units, systemctl_bin=systemctl_bin)
    if start:
        started_units = (units.service_name, units.timer_name)
        systemctl_user("start", *started_units, systemctl_bin=systemctl_bin)
    return UserSystemdInstallResult(
        paths=paths,
        verified=verify,
        daemon_reloaded=True,
        enabled_units=enabled_units,
        started_units=started_units,
    )


def show_user_units(*unit_names: str, systemctl_bin: str | Path = "systemctl") -> dict[str, dict[str, str]]:
    """Return safe `systemctl --user show` fields for units."""

    fields = ["Id", "LoadState", "ActiveState", "SubState", "UnitFileState", "FragmentPath", "MainPID"]
    result: dict[str, dict[str, str]] = {}
    for unit_name in unit_names:
        completed = systemctl_user(
            "show",
            unit_name,
            *(f"-p{field}" for field in fields),
            "--no-pager",
            systemctl_bin=systemctl_bin,
        )
        values: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        result[unit_name] = values
    return result
