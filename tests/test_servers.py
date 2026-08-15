from __future__ import annotations

import json
from types import SimpleNamespace

from click.testing import CliRunner

import chatglance.servers as servers_module
from chatglance.cli import main
from chatglance.servers import (
    SERVER_PAGE_NAME,
    aliases_from_inventory_config,
    apply_server_inventory_config,
    build_servers_page,
    collection_options_from_inventory_config,
    default_candidate_aliases,
    host_connection_overrides_from_inventory_config,
    page_options_from_inventory_config,
    parse_probe_output,
    server_status_regressions,
    replace_servers_page,
    render_servers_html,
)


def sample_status() -> dict:
    return {
        "generated_at": "2026-08-11T08:00:00+08:00",
        "count": 1,
        "online": 1,
        "servers": [
            {
                "alias": "hitk.cube",
                "display_name": "hitk",
                "group": "cube",
                "connection_kind": "内网连接",
                "ip": "172.23.148.35",
                "status": "online",
                "hostname": "hitk",
                "user": "zhihong",
                "kernel": "Linux 6.8 x86_64",
                "collected_at": "2026-08-11T08:00:01+08:00",
                "last_reboot": "2026-08-09T20:34:56+08:00",
                "uptime_seconds": "123456",
                "cpu": {"cores": 16, "load1": 0.4, "usage_percent": 12.5},
                "memory": {"total_bytes": 34359738368, "available_bytes": 17179869184, "used_percent": 50.0},
                "disks": [
                    {
                        "filesystem": "/dev/nvme0n1p2",
                        "type": "ext4",
                        "mountpoint": "/",
                        "size_bytes": 1000,
                        "used_bytes": 250,
                        "available_bytes": 750,
                        "used_percent": 25.0,
                    }
                ],
                "devices": [
                    {
                        "name": "nvme0n1",
                        "type": "disk",
                        "size_bytes": 1000,
                        "mountpoint": "/",
                        "fstype": "ext4",
                        "model": "SSD",
                        "tran": "nvme",
                    }
                ],
                "getdevices": [
                    {
                        "device": "/dev/nvme0n1",
                        "drive_type": "固态",
                        "size": "1T",
                        "power_on": "26993 h (3.08 年)",
                        "logical_volume": "None",
                        "mountpoints": "/",
                    }
                ],
                "gpus": [],
            }
        ],
    }


def test_render_servers_html_contains_required_card_fields() -> None:
    html = render_servers_html(sample_status())
    assert "172.23.148.35" in html
    assert "NULL" in html
    assert "展开详情" in html
    assert "挂载目录容量" in html
    assert "使用时间" in html
    assert "getdevices 摘要" in html
    assert "Last Reboot=2026-08-09T20:34:56+08:00" in html
    assert "/dev/nvme0n1" in html
    assert "服务器 1 台" in html


def test_replace_servers_page_appends_third_page_without_touching_existing_pages() -> None:
    config = {
        "pages": [
            {"name": "ChatArch", "columns": []},
            {"name": "项目", "columns": []},
        ]
    }
    updated = replace_servers_page(config, sample_status())
    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目", SERVER_PAGE_NAME]
    assert updated["pages"][2]["slug"] == "servers"
    assert updated["pages"][2]["columns"][0]["widgets"][0]["type"] == "html"
    assert config["pages"] == [{"name": "ChatArch", "columns": []}, {"name": "项目", "columns": []}]


def test_default_candidate_aliases_excludes_user_excluded_targets() -> None:
    aliases = [
        "local",
        "rexpc",
        "zhihong.lean4web",
        "hitk.cube",
        "auc.cube",
        "tencent.am",
        "azure.cn",
        "essay.newaliyun",
        "rex.ctyun",
        "zhihong.tencent",
        "random.host",
    ]
    assert default_candidate_aliases(aliases) == ["hitk.cube", "auc.cube"]


def test_inventory_config_selects_hosts_and_page_options() -> None:
    config = {
        "page": {"name": "Infra", "slug": "infra", "widget_title": "Infra status"},
        "inventory": {
            "default_candidates": True,
            "aliases": ["manual.host", "local"],
            "exclude": ["auc.cube"],
            "hosts": [
                {"alias": "hitk.cube", "label": "HITK", "group": "cube"},
                {"alias": "manual.host", "label": "Manual"},
            ],
        },
        "collection": {"timeout": 30, "workers": 4},
    }
    ssh_aliases = ["auc.cube", "hitk.cube", "rexpc", "tencent.am"]
    assert aliases_from_inventory_config(config, ssh_aliases=ssh_aliases) == ["hitk.cube", "manual.host"]
    assert collection_options_from_inventory_config(config) == {"timeout": 30, "workers": 4}
    assert page_options_from_inventory_config(config) == {"page_name": "Infra", "page_slug": "infra", "widget_title": "Infra status"}
    updated = apply_server_inventory_config(sample_status(), config)
    assert updated["servers"][0]["display_name"] == "HITK"
    assert updated["servers"][0]["group"] == "cube"


def test_inventory_config_can_override_ssh_endpoint() -> None:
    config = {
        "inventory": {
            "hosts": [
                {
                    "alias": "recall.cube",
                    "hostname": "172.23.136.179",
                    "port": 3322,
                    "user": "zhihong",
                    "strict_host_key_checking": "accept-new",
                }
            ]
        }
    }
    assert host_connection_overrides_from_inventory_config(config) == {
        "recall.cube": {
            "hostname": "172.23.136.179",
            "port": "3322",
            "user": "zhihong",
            "strict_host_key_checking": "accept-new",
        }
    }


def test_collect_server_status_uses_inventory_endpoint_override(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(cmd))
        if "-G" in cmd:
            return SimpleNamespace(returncode=0, stdout="hostname 172.23.148.37\nuser zhihong\nport 3322\n", stderr="")
        assert "HostName=172.23.136.179" in cmd
        assert "Port=3322" in cmd
        assert "User=zhihong" in cmd
        assert "StrictHostKeyChecking=accept-new" in cmd
        assert "IdentitiesOnly=yes" in cmd
        return SimpleNamespace(returncode=0, stdout="probe output", stderr="")

    monkeypatch.setattr(servers_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        servers_module,
        "parse_probe_output",
        lambda alias, output, target: {
            "alias": alias,
            "display_name": alias,
            "group": "cube",
            "connection_kind": "内网连接",
            "ip": target["hostname"],
            "status": "online",
        },
    )

    data = servers_module.collect_server_status(
        ["recall.cube"],
        timeout=18,
        workers=1,
        host_overrides={
            "recall.cube": {
                "hostname": "172.23.136.179",
                "port": "3322",
                "user": "zhihong",
                "strict_host_key_checking": "accept-new",
            }
        },
    )

    assert data["online"] == 1
    assert any("HostName=172.23.136.179" in command for command in commands)


def test_server_status_regressions_detect_online_to_unreachable() -> None:
    previous = {
        "servers": [
            {"alias": "recall.cube", "status": "online"},
            {"alias": "auc.cube", "status": "online"},
        ]
    }
    current = {
        "servers": [
            {"alias": "recall.cube", "status": "unreachable"},
            {"alias": "auc.cube", "status": "online"},
        ]
    }
    assert server_status_regressions(previous, current) == ["recall.cube"]


def test_server_status_regressions_ignores_removed_aliases() -> None:
    previous = {"servers": [{"alias": "tencent.am", "status": "online"}]}
    current = {"servers": []}
    assert server_status_regressions(previous, current) == []


def test_parse_probe_output_matches_getdevices_readonly_fields() -> None:
    output = """
@@chatglance:meta@@
hostname=hitk
user=zhihong
kernel=Linux 6.8 x86_64
ips=192.168.98.21 10.0.0.2
collected_at=2026-08-11T08:00:01+08:00
last_reboot=2026-08-09T20:34:56+08:00
uptime_seconds=123456
@@chatglance:cpu@@
cores=8
loadavg=0.10 0.20 0.30 1/2 3
stat1=1 0 1 98 0 0 0 0
stat2=2 0 2 196 0 0 0 0
@@chatglance:meminfo@@
MemTotal:       1000 kB
MemAvailable:   250 kB
SwapTotal:      100 kB
SwapFree:        50 kB
@@chatglance:df@@
Filesystem Type 1B-blocks Used Available Use% Mounted on
/dev/sda1 ext4 1000 250 750 25% /
tmpfs tmpfs 100 1 99 1% /run
@@chatglance:lsblk@@
NAME="sda" TYPE="disk" SIZE="1000" MOUNTPOINT="" FSTYPE="" MODEL="SSD" TRAN="sata" ROTA="0" RM="0"
NAME="sda1" TYPE="part" SIZE="1000" MOUNTPOINT="/" FSTYPE="ext4" MODEL="" TRAN="" ROTA="0" RM="0"
NAME="loop0" TYPE="loop" SIZE="1000" MOUNTPOINT="/snap/core" FSTYPE="squashfs" MODEL="" TRAN="" ROTA="0" RM="0"
@@chatglance:readonly_devices@@
device=sda rotational=0 size=1T lvm= mountpoints=/
@@chatglance:gpu@@
@@chatglance:lspci@@
01:00.0 VGA compatible controller: NVIDIA Corporation TU104 [GeForce RTX 2070 SUPER]
01:00.1 Audio device: NVIDIA Corporation TU104 HD Audio Controller
"""
    server = parse_probe_output("hitk.cube", output, {"hostname": "172.23.148.35", "port": "22", "user": "zhihong"})
    assert server["ip"] == "172.23.148.35"
    assert len(server["gpus"]) == 1
    assert "Audio" not in server["gpus"][0]["name"]
    assert server["disks"] == [
        {
            "filesystem": "/dev/sda1",
            "type": "ext4",
            "mountpoint": "/",
            "size_bytes": 1000,
            "used_bytes": 250,
            "available_bytes": 750,
            "used_percent": 25.0,
        }
    ]
    assert [device["name"] for device in server["devices"]] == ["sda", "sda1"]
    assert server["getdevices"][0]["drive_type"] == "固态"
    assert server["last_reboot"] == "2026-08-09T20:34:56+08:00"
    assert server["uptime_seconds"] == "123456"


def test_cli_servers_render_and_update_config(tmp_path) -> None:
    data_path = tmp_path / "server-status.json"
    page_path = tmp_path / "server-page.yml"
    config_path = tmp_path / "glance.yml"
    output_path = tmp_path / "updated.yml"
    data_path.write_text(json.dumps(sample_status(), ensure_ascii=False), encoding="utf-8")
    config_path.write_text(
        "pages:\n"
        "  - name: ChatArch\n"
        "    columns: []\n"
        "  - name: 项目\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    inventory_path = tmp_path / "server-inventory.yml"
    inventory_path.write_text(
        "page:\n"
        "  name: Infra\n"
        "  slug: infra\n"
        "  widget_title: Infra status\n",
        encoding="utf-8",
    )
    result = runner.invoke(main, ["servers", "render-page", "--data", str(data_path), "--inventory-config", str(inventory_path), "--output", str(page_path)])
    assert result.exit_code == 0, result.output
    assert "name: Infra" in page_path.read_text(encoding="utf-8")
    assert "slug: infra" in page_path.read_text(encoding="utf-8")
    assert "title: Infra status" in page_path.read_text(encoding="utf-8")

    result = runner.invoke(
        main,
        [
            "servers",
            "update-config",
            "--data",
            str(data_path),
            "--inventory-config",
            str(inventory_path),
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    rendered = output_path.read_text(encoding="utf-8")
    assert "name: ChatArch" in rendered
    assert "name: 项目" in rendered
    assert "name: Infra" in rendered
    assert "slug: infra" in rendered
    assert "172.23.148.35" in rendered
