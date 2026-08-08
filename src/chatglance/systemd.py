"""systemd unit rendering for chatglance-managed Glance runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SystemdUnits:
    """Rendered systemd user units for a Glance runtime."""

    service_name: str
    service: str
    maintenance_service_name: str
    maintenance_service: str
    timer_name: str
    timer: str


def _path(value: str | Path) -> str:
    return str(Path(value).expanduser())


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
ExecStart={_path(binary)} -config {_path(config)}
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
ExecStart={_path(chatglance_bin)} runtime maintain --runtime-home {_path(home)} --restart-service {restart_service}
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

    root = Path(output_dir)
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
