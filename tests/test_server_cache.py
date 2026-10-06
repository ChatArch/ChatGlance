"""Synthetic last-good identity, bootstrap, and rendering contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import yaml

from chatglance import refresh, servers
from chatglance.server_cache import (
    ServerCacheError,
    dump_last_good,
    last_good_path,
    prepare_server_refresh,
)


NOW = datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)


def inventory(*, target: str = "10.0.0.10", include: bool = True) -> dict:
    hosts = []
    if include:
        hosts.append(
            {
                "alias": "alpha.cube",
                "server_id": "srv-alpha",
                "hostname": target,
                "port": 2222,
                "user": "operator",
            }
        )
    return {"inventory": {"hosts": hosts}}


def inventory_without_ids(*, target: str = "10.0.0.10") -> dict:
    value = inventory(target=target)
    value["inventory"]["hosts"][0].pop("server_id")
    return value


def success(at: str, *, cpu: float = 12.5, ip: str = "10.0.0.10") -> dict:
    return {
        "alias": "alpha.cube",
        "display_name": "Alpha",
        "group": "cube",
        "connection_kind": "内网连接",
        "ip": ip,
        "status": "online",
        # These are remote facts, not the configured SSH target identity.
        "hostname": "remote-kernel-hostname",
        "user": "operator",
        "kernel": "Linux 6.8 synthetic",
        "collected_at": at,
        "last_reboot": "2026-10-01T00:00:00+00:00",
        "uptime_seconds": "432000",
        "cpu": {"cores": 16, "usage_percent": cpu, "load1": 0.2},
        "memory": {"total_bytes": 32000, "available_bytes": 16000, "used_percent": 50.0},
        "gpus": [{"name": "Synthetic GPU", "memory_total_mib": 8192, "memory_used_mib": 1024}],
        "disks": [{"filesystem": "/dev/vda1", "type": "ext4", "mountpoint": "/", "size_bytes": 1000, "used_bytes": 400, "available_bytes": 600, "used_percent": 40.0}],
        "devices": [{"name": "vda", "type": "disk", "size_bytes": 1000, "mountpoint": "/", "fstype": "ext4", "model": "Synthetic", "tran": "virtio"}],
        "getdevices": [{"device": "/dev/vda", "drive_type": "固态", "size": "1T", "power_on": "10 h", "logical_volume": "None", "mountpoints": "/"}],
        "note": "must never enter last-good",
    }


def failed(at: str, *, ip: str = "10.0.0.10", error: str = "timeout") -> dict:
    return {
        "alias": "alpha.cube",
        "display_name": "Alpha",
        "group": "cube",
        "connection_kind": "内网连接",
        "ip": ip,
        "status": "unreachable",
        "error": error,
        "collected_at": at,
    }


def snapshot(row: dict) -> dict:
    return {
        "generated_at": row["collected_at"],
        "count": 1,
        "online": int(row["status"] == "online"),
        "servers": [row],
    }


def commit_plan(root: Path, plan) -> bytes:
    path = last_good_path(root)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    body = dump_last_good(plan.last_good).encode()
    path.write_bytes(body)
    path.chmod(0o600)
    return body


def test_success_offline_offline_recover_preserves_every_real_data_group(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    first_at = "2026-10-05T08:00:00+00:00"
    first = prepare_server_refresh(root, snapshot(success(first_at)), inventory(), run_id="run-first", now=NOW)
    assert first.snapshot["servers"][0]["data_state"] == "fresh"
    original_cache = commit_plan(root, first)
    assert b"must never enter last-good" not in original_cache

    failed_once = prepare_server_refresh(
        root,
        snapshot(failed("2026-10-05T09:00:00+00:00")),
        inventory(),
        run_id="run-failed-1",
        now=NOW,
    )
    row = failed_once.snapshot["servers"][0]
    assert row["status"] == "unreachable"
    assert row["data_state"] == "last-good"
    assert row["last_attempt_at"] == "2026-10-05T09:00:00+00:00"
    assert row["last_observed_at"] == first_at
    assert row["last_success_at"] == first_at
    for field in ("cpu", "memory", "gpus", "disks", "devices", "getdevices", "kernel", "last_reboot", "uptime_seconds"):
        assert row[field] == success(first_at)[field]
    assert dump_last_good(failed_once.last_good).encode() == original_cache

    failed_twice = prepare_server_refresh(
        root,
        snapshot(failed("2026-10-05T10:00:00+00:00", error="unreachable")),
        inventory(),
        run_id="run-failed-2",
        now=NOW,
    )
    assert failed_twice.snapshot["servers"][0]["last_attempt_at"] == "2026-10-05T10:00:00+00:00"
    assert failed_twice.snapshot["servers"][0]["last_observed_at"] == first_at
    assert dump_last_good(failed_twice.last_good).encode() == original_cache

    recovered = prepare_server_refresh(
        root,
        snapshot(success("2026-10-05T11:00:00+00:00", cpu=77.0)),
        inventory(),
        run_id="run-recovered",
        now=NOW,
    )
    recovered_row = recovered.snapshot["servers"][0]
    assert recovered_row["data_state"] == "fresh"
    assert recovered_row["cpu"]["usage_percent"] == 77.0
    assert recovered_row["last_observed_at"] == "2026-10-05T11:00:00+00:00"
    assert recovered.last_good["servers"]["srv-alpha"]["run_id"] == "run-recovered"


def test_changed_target_and_removed_inventory_never_reuse_or_display_cache(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    plan = prepare_server_refresh(root, snapshot(success("2026-10-05T08:00:00+00:00")), inventory(), now=NOW)
    commit_plan(root, plan)

    changed = prepare_server_refresh(
        root,
        snapshot(failed("2026-10-05T09:00:00+00:00", ip="10.0.0.11")),
        inventory(target="10.0.0.11"),
        now=NOW,
    )
    row = changed.snapshot["servers"][0]
    assert row["data_state"] == "unavailable"
    assert "cpu" not in row
    assert changed.last_good["servers"] == {}

    removed = prepare_server_refresh(
        root,
        {"generated_at": "2026-10-05T10:00:00+00:00", "count": 0, "online": 0, "servers": []},
        inventory(include=False),
        now=NOW,
    )
    assert removed.snapshot["servers"] == []
    assert removed.last_good["servers"] == {}


def test_default_identity_is_deterministic_and_target_changes_are_fenced(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    first = prepare_server_refresh(
        root, snapshot(success("2026-10-05T08:00:00+00:00")), inventory_without_ids(), now=NOW
    )
    first_id = next(iter(first.last_good["servers"]))
    assert first_id.startswith("derived-")
    assert first.last_good["servers"][first_id]["identity"]["target"] == "10.0.0.10"
    commit_plan(root, first)

    repeat = prepare_server_refresh(
        root, snapshot(failed("2026-10-05T09:00:00+00:00")), inventory_without_ids(), now=NOW
    )
    assert repeat.snapshot["servers"][0]["data_state"] == "last-good"
    assert next(iter(repeat.last_good["servers"])) == first_id

    changed = prepare_server_refresh(
        root,
        snapshot(failed("2026-10-05T10:00:00+00:00", ip="10.0.0.11")),
        inventory_without_ids(target="10.0.0.11"),
        now=NOW,
    )
    assert changed.snapshot["servers"][0]["data_state"] == "unavailable"
    assert changed.last_good["servers"] == {}


def test_alias_only_inventory_resolves_reviewed_ssh_identity_and_bad_alias_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    config = {"inventory": {"aliases": ["alpha.cube", "broken.cube"]}}

    def reviewed(alias: str, _override: dict | None = None) -> dict[str, str]:
        if alias == "broken.cube":
            raise OSError("synthetic unreadable ssh config")
        return {"hostname": "10.0.0.10", "port": "2222", "user": "operator"}

    monkeypatch.setattr(servers, "ssh_target", reviewed)
    root = tmp_path / "runtime"
    first = prepare_server_refresh(root, snapshot(success("2026-10-05T08:00:00+00:00")), config, now=NOW)
    assert len(first.last_good["servers"]) == 1
    commit_plan(root, first)
    offline = prepare_server_refresh(root, snapshot(failed("2026-10-05T09:00:00+00:00")), config, now=NOW)
    assert offline.snapshot["servers"][0]["data_state"] == "last-good"


def _legacy_backup(root: Path, name: str, data: dict, *, stored_name: str = "0") -> Path:
    backup = root / "config/backups" / name
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_text(json.dumps({"data/server-status.json": stored_name}), encoding="utf-8")
    destination = backup / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data), encoding="utf-8")
    return backup


def test_bootstrap_uses_only_manifest_numeric_backup_and_remote_hostname_is_not_target(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    good = snapshot(success("2026-10-04T08:00:00+00:00"))
    good["servers"][0]["hostname"] = "fact-that-is-not-the-ssh-target"
    _legacy_backup(root, "refresh-20261004T080000000000Z", good)
    latest_failed = snapshot(failed("2026-10-05T08:00:00+00:00"))
    _legacy_backup(root, "refresh-20261005T080000000000Z", latest_failed)

    current = snapshot(failed("2026-10-05T09:00:00+00:00"))
    plan = prepare_server_refresh(root, current, inventory(), run_id="bootstrap", now=NOW)
    row = plan.snapshot["servers"][0]
    assert row["data_state"] == "last-good"
    assert row["hostname"] == "fact-that-is-not-the-ssh-target"
    assert row["last_observed_at"] == "2026-10-04T08:00:00+00:00"
    assert plan.bootstrapped_aliases == ("alpha.cube",)
    assert all(path.exists() for path in (root / "config/backups").glob("refresh-*") )


def test_bootstrap_rejects_wrong_identity_and_malicious_manifest_path(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    outside = root / "config/backups/outside.json"
    outside.parent.mkdir(parents=True)
    outside.write_text(json.dumps(snapshot(success("2026-10-05T07:00:00+00:00"))))
    malicious = root / "config/backups/refresh-20261005T080000000000Z"
    malicious.mkdir()
    (malicious / "manifest.json").write_text(json.dumps({"data/server-status.json": "../outside.json"}))
    wrong = snapshot(success("2026-10-04T08:00:00+00:00", ip="10.0.0.99"))
    _legacy_backup(root, "refresh-20261004T080000000000Z", wrong)

    plan = prepare_server_refresh(root, snapshot(failed("2026-10-05T09:00:00+00:00")), inventory(), now=NOW)
    assert plan.snapshot["servers"][0]["data_state"] == "unavailable"
    assert "cpu" not in plan.snapshot["servers"][0]


def test_explicit_legacy_identity_migration_allows_reviewed_dns_endpoint(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _legacy_backup(root, "refresh-20261004T080000000000Z", snapshot(success("2026-10-04T08:00:00+00:00")))
    config = inventory(target="alpha.internal.example")
    config["inventory"]["hosts"][0]["legacy_identities"] = [
        {"approved": True, "ip": "10.0.0.10", "port": 2222, "user": "operator"}
    ]
    plan = prepare_server_refresh(root, snapshot(failed("2026-10-05T09:00:00+00:00")), config, now=NOW)
    assert plan.snapshot["servers"][0]["data_state"] == "last-good"


def test_legacy_reverse_search_is_bounded_and_rejects_ambiguous_alias_rows(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    oldest = snapshot(success("2026-10-01T08:00:00+00:00"))
    _legacy_backup(root, "refresh-000", oldest)
    for index in range(1, 65):
        _legacy_backup(
            root,
            f"refresh-{index:03d}",
            snapshot(failed(f"2026-10-05T{index % 24:02d}:00:00+00:00")),
        )
    bounded = prepare_server_refresh(
        root,
        snapshot(failed("2026-10-05T23:30:00+00:00")),
        inventory(),
        now=NOW,
    )
    assert bounded.snapshot["servers"][0]["data_state"] == "unavailable"

    for path in (root / "config/backups").glob("refresh-*"):
        for child in path.iterdir():
            child.unlink()
        path.rmdir()
    duplicate = snapshot(success("2026-10-04T08:00:00+00:00"))
    duplicate["servers"].append(deepcopy(duplicate["servers"][0]))
    _legacy_backup(root, "refresh-ambiguous", duplicate)
    ambiguous = prepare_server_refresh(
        root,
        snapshot(failed("2026-10-05T23:30:00+00:00")),
        inventory(),
        now=NOW,
    )
    assert ambiguous.snapshot["servers"][0]["data_state"] == "unavailable"


def test_corrupt_future_and_symlink_cache_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    path = last_good_path(root)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    corrupt = prepare_server_refresh(root, snapshot(failed("2026-10-05T09:00:00+00:00")), inventory(), now=NOW)
    assert corrupt.snapshot["servers"][0]["data_state"] == "unavailable"

    path.write_text(json.dumps({"schema_version": 1, "servers": {}}), encoding="utf-8")
    with pytest.raises(ServerCacheError, match="future"):
        prepare_server_refresh(root, snapshot(success("2027-01-01T00:00:00+00:00")), inventory(), now=NOW)

    path.unlink()
    target = tmp_path / "outside.json"
    target.write_text(dump_last_good(corrupt.last_good), encoding="utf-8")
    path.symlink_to(target)
    with pytest.raises(ServerCacheError, match="symlink"):
        prepare_server_refresh(root, snapshot(failed("2026-10-05T10:00:00+00:00")), inventory(), now=NOW)


def test_native_card_keeps_offline_status_and_labels_stale_timestamps() -> None:
    row = failed("2026-10-05T09:00:00+00:00")
    row.update(success("2026-10-05T08:00:00+00:00"))
    row.update(
        {
            "status": "unreachable",
            "error": "timeout <unsafe>",
            "data_state": "last-good",
            "last_attempt_at": "2026-10-05T09:00:00+00:00",
            "last_observed_at": "2026-10-05T08:00:00+00:00",
            "last_success_at": "2026-10-05T08:00:00+00:00",
        }
    )
    rendered = servers.render_servers_html(snapshot(row))
    assert "status-unreachable" in rendered and "不可达" in rendered
    assert 'class="server-history-badge">历史数据</span>' in rendered
    assert rendered.count('class="server-history-time"') >= 2
    assert 'datetime="2026-10-05T08:00:00+00:00"' in rendered
    assert 'datetime="2026-10-05T09:00:00+00:00"' in rendered
    assert "2026-10-05 08:00:00 UTC+00:00" in rendered
    assert "flex-wrap: wrap" in rendered and "font-size: max(12px" in rendered
    assert "timeout &lt;unsafe&gt;" in rendered


def _refresh_runtime(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    for name in ("config", "data", "bin"):
        (root / name).mkdir(parents=True, exist_ok=True)
    config = {"pages": [servers.build_servers_page({"servers": []})]}
    (root / "config/glance.yml").write_text(yaml.safe_dump(config, allow_unicode=True))
    (root / "config/server-inventory.yml").write_text(yaml.safe_dump(inventory()))
    (root / "bin/glance").write_text("synthetic")
    return root


def test_last_good_is_committed_only_inside_successful_publication(tmp_path: Path, monkeypatch) -> None:
    root = _refresh_runtime(tmp_path)
    fresh = snapshot(success("2026-10-05T08:00:00+00:00"))
    monkeypatch.setattr(servers, "collect_server_status", lambda *args, **kwargs: deepcopy(fresh))
    monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: (_ for _ in ()).throw(ValueError("invalid")))
    with pytest.raises(refresh.RefreshError, match="validation"):
        refresh.refresh_runtime(root, pages=["servers"], restart=False)
    assert not last_good_path(root).exists()

    monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: None)
    result = refresh.refresh_runtime(root, pages=["servers"], restart=False)
    assert result["ok"] and last_good_path(root).is_file()
    before = last_good_path(root).read_bytes()

    newer = snapshot(success("2026-10-05T10:00:00+00:00", cpu=88.0))
    monkeypatch.setattr(servers, "collect_server_status", lambda *args, **kwargs: deepcopy(newer))
    monkeypatch.setattr(refresh, "_publish", lambda *args, **kwargs: (_ for _ in ()).throw(refresh.RefreshError("publication failed")))
    with pytest.raises(refresh.RefreshError, match="publication"):
        refresh.refresh_runtime(root, pages=["servers"], restart=False)
    assert last_good_path(root).read_bytes() == before


def test_full_refresh_success_offline_offline_recover_roundtrip_for_manual_and_scheduled(
    tmp_path: Path, monkeypatch
) -> None:
    root = _refresh_runtime(tmp_path)
    observations = iter(
        [
            snapshot(success("2026-10-05T08:00:00+00:00", cpu=10.0)),
            snapshot(failed("2026-10-05T09:00:00+00:00", error="unreachable")),
            snapshot(failed("2026-10-05T10:00:00+00:00", error="timeout")),
            snapshot(success("2026-10-05T11:00:00+00:00", cpu=90.0)),
        ]
    )
    monkeypatch.setattr(servers, "collect_server_status", lambda *args, **kwargs: deepcopy(next(observations)))
    monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: None)

    first = refresh.refresh_runtime(root, pages=["servers"], restart=False)
    first_row = json.loads((root / "data/server-status.json").read_text())["servers"][0]
    assert first["source"] == "manual" and first["ok"]
    assert first_row["cpu"]["usage_percent"] == 10.0

    second = refresh.refresh_runtime(root, pages=["servers"], restart=False)
    second_row = json.loads((root / "data/server-status.json").read_text())["servers"][0]
    assert second["source"] == "manual" and not second["ok"]
    assert second_row["status"] == "unreachable" and second_row["data_state"] == "last-good"
    assert second_row["cpu"]["usage_percent"] == 10.0
    assert second_row["last_observed_at"] == "2026-10-05T08:00:00+00:00"
    cache_after_second = last_good_path(root).read_bytes()

    third = refresh.refresh_runtime(root, pages=["servers"], restart=False, scheduled=True)
    third_row = json.loads((root / "data/server-status.json").read_text())["servers"][0]
    assert third["source"] == "scheduled" and not third["ok"]
    assert third_row["last_attempt_at"] == "2026-10-05T10:00:00+00:00"
    assert third_row["last_observed_at"] == "2026-10-05T08:00:00+00:00"
    assert third_row["cpu"]["usage_percent"] == 10.0
    assert last_good_path(root).read_bytes() == cache_after_second

    fourth = refresh.refresh_runtime(root, pages=["servers"], restart=False, scheduled=True)
    fourth_row = json.loads((root / "data/server-status.json").read_text())["servers"][0]
    assert fourth["source"] == "scheduled" and fourth["ok"]
    assert fourth_row["status"] == "online" and fourth_row["data_state"] == "fresh"
    assert fourth_row["cpu"]["usage_percent"] == 90.0
    assert fourth_row["last_observed_at"] == "2026-10-05T11:00:00+00:00"
    assert json.loads(last_good_path(root).read_text())["servers"]["srv-alpha"]["run_id"] == fourth["run_id"]


def test_browser_control_explicitly_publishes_reviewed_offline_state(tmp_path: Path, monkeypatch) -> None:
    from chatglance import page_control

    root = _refresh_runtime(tmp_path)
    observations = iter([
        snapshot(success("2026-10-05T08:00:00+00:00", cpu=41.0)),
        snapshot(failed("2026-10-05T09:00:00+00:00")),
        snapshot(failed("2026-10-05T09:00:00+00:00")),
    ])
    monkeypatch.setattr(servers, "collect_server_status", lambda *args, **kwargs: deepcopy(next(observations)))
    monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: None)
    monkeypatch.setattr(refresh, "_restart", lambda *args: None)
    refresh.refresh_runtime(root, pages=["servers"], restart=False)

    blocked = refresh.refresh_runtime(root, pages=["servers"], restart=False, allow_offline_regression=False)
    assert not blocked["ok"] and blocked["pages"][0]["status"] == "error"
    assert json.loads((root / "data/server-status.json").read_text())["servers"][0]["status"] == "online"

    app = page_control.PageControlApp(root, "https://example.invalid")
    app.active = True
    app.jobs["servers"] = {"state": "running", "run_id": "browser-offline"}
    app._run("servers", "browser-offline")
    current = json.loads((root / "data/server-status.json").read_text())["servers"][0]
    assert current["status"] == "unreachable" and current["data_state"] == "last-good"
    assert current["cpu"]["usage_percent"] == 41.0
    assert "历史数据" in (root / "data/server-page.yml").read_text()
    assert app.status("servers")["state"] == "partial"
