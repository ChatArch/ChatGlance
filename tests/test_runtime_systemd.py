from pathlib import Path

import yaml
from click.testing import CliRunner

from chatglance.cli import main
from chatglance.runtime import build_maintained_config, maintain_config
from chatglance.systemd import render_all_units
from test_projects import sample_inventory


def test_build_maintained_config_applies_project_page_and_disk_patch():
    config = {
        "pages": [
            {"name": "ChatArch", "columns": [{"size": "small", "widgets": [{"type": "server-stats", "servers": [{"type": "local", "name": "rexpc"}]}]}]},
            {"name": "ChatArch Projects"},
        ]
    }

    updated = build_maintained_config(config, sample_inventory())
    rendered = yaml.safe_dump(updated, allow_unicode=True, sort_keys=False)

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目"]
    assert "按名称" not in rendered
    widget = updated["pages"][0]["columns"][0]["widgets"][0]
    assert widget["hide-mountpoints-by-default"] is True
    assert widget["servers"][0]["mountpoints"] == {"/": {"name": "根分区"}}


def test_maintain_config_writes_backup_only_when_changed(tmp_path: Path):
    config_path = tmp_path / "glance.yml"
    data_path = tmp_path / "chatarch-projects.json"
    backup_dir = tmp_path / "backups"
    config_path.write_text(
        yaml.safe_dump({"pages": [{"name": "ChatArch Projects"}]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    import json

    data_path.write_text(json.dumps(sample_inventory()), encoding="utf-8")

    first = maintain_config(config_path=config_path, data_path=data_path, backup_dir=backup_dir)
    second = maintain_config(config_path=config_path, data_path=data_path, backup_dir=backup_dir)

    assert first.changed is True
    assert first.backup_path is not None and first.backup_path.exists()
    assert second.changed is False
    assert second.backup_path is None
    assert "项目" in config_path.read_text(encoding="utf-8")


def test_runtime_maintain_cli_uses_runtime_paths(tmp_path: Path):
    runtime_home = tmp_path / "glance"
    (runtime_home / "config").mkdir(parents=True)
    (runtime_home / "data").mkdir(parents=True)
    (runtime_home / "config/glance.yml").write_text(
        yaml.safe_dump({"pages": [{"name": "ChatArch Projects"}]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    import json

    (runtime_home / "data/chatarch-projects.json").write_text(json.dumps(sample_inventory()), encoding="utf-8")

    result = CliRunner().invoke(main, ["runtime", "maintain", "--runtime-home", str(runtime_home), "--no-validate"])

    assert result.exit_code == 0, result.output
    assert "changed=true" in result.output
    assert "validated=false" in result.output
    assert "项目" in (runtime_home / "config/glance.yml").read_text(encoding="utf-8")


def test_render_systemd_keeps_glance_service_direct_and_maintenance_oneshot():
    units = render_all_units(runtime_home="/srv/glance", chatglance_bin="/venv/bin/chatglance")

    assert "ExecStart=/srv/glance/bin/glance -config /srv/glance/config/glance.yml" in units.service
    assert "Type=simple" in units.service
    assert "ExecStart=/venv/bin/chatglance runtime maintain --runtime-home /srv/glance" in units.maintenance_service
    assert "--restart-service chatarch-glance.service" in units.maintenance_service
    assert "OnUnitActiveSec=30min" in units.timer
