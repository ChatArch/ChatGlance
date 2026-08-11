from __future__ import annotations

import json

from click.testing import CliRunner

from chatglance.cli import main
from chatglance.servers import (
    SERVER_PAGE_NAME,
    build_servers_page,
    default_candidate_aliases,
    parse_probe_output,
    replace_servers_page,
    render_servers_html,
)


def sample_status() -> dict:
    return {
        "generated_at": "2026-08-11T00:00:00Z",
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
                "collected_at": "2026-08-11T00:00:01Z",
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
    assert "展开 GPU、挂载目录和 devices" in html
    assert "挂载目录容量" in html
    assert "使用时间" in html
    assert "getdevices 摘要" in html
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
    assert default_candidate_aliases(aliases) == ["hitk.cube", "auc.cube", "tencent.am"]


def test_parse_probe_output_matches_getdevices_readonly_fields() -> None:
    output = """
@@chatglance:meta@@
hostname=hitk
user=zhihong
kernel=Linux 6.8 x86_64
ips=192.168.98.21 10.0.0.2
collected_at=2026-08-11T00:00:01Z
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
    result = runner.invoke(main, ["servers", "render-page", "--data", str(data_path), "--output", str(page_path)])
    assert result.exit_code == 0, result.output
    assert "name: 服务器" in page_path.read_text(encoding="utf-8")

    result = runner.invoke(
        main,
        ["servers", "update-config", "--data", str(data_path), "--config", str(config_path), "--output", str(output_path)],
    )
    assert result.exit_code == 0, result.output
    rendered = output_path.read_text(encoding="utf-8")
    assert "name: ChatArch" in rendered
    assert "name: 项目" in rendered
    assert "name: 服务器" in rendered
    assert "172.23.148.35" in rendered
