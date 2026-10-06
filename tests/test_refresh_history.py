"""Unified refresh journal, crash evidence, rotation, config, and CLI contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import threading

from click.testing import CliRunner
import pytest
import yaml

from chatglance.cli import main
from chatglance.config import ChatGlanceConfig, history_settings
from chatglance import page_control
from chatglance import refresh
from chatglance.refresh_history import (
    DEFAULT_MAX_BYTES,
    DEFAULT_RETENTION_DAYS,
    RefreshHistory,
    RefreshHistoryError,
    history_root,
    list_refresh_runs,
    prune_refresh_history,
    record_rejected_run,
    show_refresh_run,
)


UTC = timezone.utc


def runtime(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    for folder in ("config", "data", "bin"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "bin/glance").write_text("synthetic", encoding="utf-8")
    (root / "config/glance.yml").write_text(
        yaml.safe_dump({"pages": [{"name": "网站服务", "slug": "sites", "columns": []}]}, allow_unicode=True),
        encoding="utf-8",
    )
    (root / "data/site-services.json").write_text('{"generated_at":"old","sites":[]}', encoding="utf-8")
    return root


def fake_collection(monkeypatch, *, partial: bool = False, fail: bool = False) -> None:
    def collect(key, *args, **kwargs):
        if fail:
            raise RuntimeError("Bearer TOP-SECRET access_token=NEVER-JOURNAL")
        return refresh.PageUpdate(
            key,
            {"generated_at": "2026-10-05T08:00:00+00:00", "counts": {"visible": 2}},
            {"name": "网站服务", "slug": "sites", "columns": []},
            partial=partial,
        )

    monkeypatch.setattr(refresh, "_collect_page", collect)
    monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: None)
    monkeypatch.setattr(refresh, "_restart", lambda *args: None)


def all_history_text(root: Path) -> str:
    base = history_root(root)
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in base.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def test_explicit_native_api_source_is_supported(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    record = record_rejected_run(root, "native", ["sites"], error_type="busy")
    assert record["source"] == "native" and record["status"] == "busy"


@pytest.mark.parametrize(
    "partial,fail,expected",
    [(False, False, "success"), (True, False, "partial"), (False, True, "failed")],
)
def test_native_manual_and_scheduled_runs_share_allowlisted_journal(
    tmp_path: Path, monkeypatch, partial: bool, fail: bool, expected: str
) -> None:
    root = runtime(tmp_path)
    fake_collection(monkeypatch, partial=partial, fail=fail)
    result = refresh.refresh_runtime(root, pages=["sites"], restart=False, scheduled=partial)

    assert result["run_id"]
    assert result["source"] == ("scheduled" if partial else "manual")
    record = show_refresh_run(root, result["run_id"])
    assert record["status"] == expected
    assert record["source"] == result["source"]
    assert record["pages"][0]["page"] == "sites"
    assert record["pages"][0]["status"] == ("error" if fail else "partial" if partial else "ok")
    assert set(record["pages"][0]) <= {"page", "status", "error_type", "counts", "generated_at"}
    assert record["phases"]["validation"] == ("skipped" if fail else "passed")
    assert record["phases"]["publication"] == ("skipped" if fail else "published")
    assert record["phases"]["restart"] == "disabled"
    assert record["finished_at"] and record["elapsed_ms"] >= 0
    assert "TOP-SECRET" not in all_history_text(root)
    assert "NEVER-JOURNAL" not in all_history_text(root)
    latest = json.loads((history_root(root) / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == result["run_id"]
    if fail:
        assert not (history_root(root) / "snapshots" / f'{result["run_id"]}.json').exists()
    else:
        assert (history_root(root) / "snapshots" / f'{result["run_id"]}.json').is_file()


@pytest.mark.parametrize(
    "phase,error_type,published",
    [
        ("validation", "validation_error", False),
        ("publication", "publication_error", False),
        ("restart", "restart_error", True),
    ],
)
def test_validation_publication_and_restart_exceptions_have_truthful_terminal_status(
    tmp_path: Path, monkeypatch, phase: str, error_type: str, published: bool
) -> None:
    root = runtime(tmp_path)
    fake_collection(monkeypatch)
    if phase == "validation":
        monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: (_ for _ in ()).throw(RuntimeError("SECRET validation stderr")))
    elif phase == "publication":
        monkeypatch.setattr(refresh, "_publish", lambda *args: (_ for _ in ()).throw(refresh.RefreshError("SECRET publication detail")))
    else:
        monkeypatch.setattr(
            refresh,
            "_restart",
            lambda *args: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["systemctl"], stderr="Cookie: SECRET")),
        )

    with pytest.raises(refresh.RefreshError):
        refresh.refresh_runtime(root, pages=["sites"], restart=phase == "restart")
    record = list_refresh_runs(root, limit=1)[0]
    assert record["status"] == "failed"
    assert record["error_type"] == error_type
    assert record["published"] is published
    assert record["phases"][phase] == "failed"
    assert "SECRET" not in all_history_text(root)
    assert "Cookie" not in all_history_text(root)


class SyntheticInterruption(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["validation", "publication", "restart"])
def test_interruption_checkpoints_preserve_known_lifecycle_facts(
    tmp_path: Path, monkeypatch, boundary: str
) -> None:
    root = runtime(tmp_path)
    fake_collection(monkeypatch)
    if boundary == "validation":
        monkeypatch.setattr(refresh, "validate_glance_config", lambda *args: (_ for _ in ()).throw(SyntheticInterruption()))
    elif boundary == "publication":
        monkeypatch.setattr(refresh, "_publish", lambda *args: (_ for _ in ()).throw(SyntheticInterruption()))
    else:
        monkeypatch.setattr(refresh, "_restart", lambda *args: (_ for _ in ()).throw(SyntheticInterruption()))

    with pytest.raises(SyntheticInterruption):
        refresh.refresh_runtime(root, pages=["sites"], restart=boundary == "restart", run_id=f"interrupt-{boundary}")
    record = json.loads((history_root(root) / "runs" / f"interrupt-{boundary}.json").read_text())
    assert record["pages"][0]["page"] == "sites"
    assert record["phases"]["collection"] == "completed"
    if boundary == "validation":
        assert record["phases"] == {"collection": "completed", "validation": "running", "publication": "pending", "restart": "pending"}
    elif boundary == "publication":
        assert record["phases"]["validation"] == "passed"
        assert record["phases"]["publication"] == "running"
        assert record["published"] is None and record["changed"] is None
    else:
        assert record["phases"]["publication"] in {"published", "unchanged"}
        assert record["published"] is True and record["changed"] is True
        assert record["phases"]["restart"] == "running" and record["restarted"] is None


def test_recovery_marks_only_the_inflight_phase_interrupted(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    history = RefreshHistory(root)
    run_id = history.start("manual", ["sites"], run_id="stale-publication")
    history.checkpoint(
        run_id, pages=[{"page": "sites", "status": "ok"}], collection="completed",
        validation="passed", publication="running", changed=None, published=None,
    )
    history._release_owner_lease(run_id)
    recovery = history.start("manual", ["sites"], run_id="recovery-writer")
    recovered = show_refresh_run(root, run_id)
    assert recovered["phases"] == {
        "collection": "completed", "validation": "passed",
        "publication": "interrupted", "restart": "not_started",
    }
    assert recovered["published"] is None and recovered["changed"] is None
    history.finish(recovery, status="failed", error_type="collection_error")


@pytest.mark.parametrize(
    "source,scheduled,run_id,fixture,message",
    [
        ("manual", False, "config-missing", "missing", "runtime config is missing"),
        ("scheduled", True, "config-malformed", "malformed", "runtime config is malformed"),
        ("browser", False, "config-badtype", "badtype", "runtime config must contain pages"),
        ("manual", False, "config-empty", "empty", "no configured generated pages to refresh"),
    ],
)
def test_configuration_failures_are_journaled_with_requested_run_id(
    tmp_path: Path, source: str, scheduled: bool, run_id: str, fixture: str, message: str
) -> None:
    root = runtime(tmp_path)
    config = root / "config/glance.yml"
    if fixture == "missing":
        config.unlink()
    elif fixture == "malformed":
        config.write_text("pages: [\n", encoding="utf-8")
    elif fixture == "badtype":
        config.write_text("pages: wrong\n", encoding="utf-8")
    else:
        config.write_text("pages: []\n", encoding="utf-8")
    with pytest.raises(refresh.RefreshError, match=message):
        refresh.refresh_runtime(root, source=source, scheduled=scheduled, restart=False, run_id=run_id)
    record = show_refresh_run(root, run_id)
    assert record["source"] == source and record["status"] == "failed"
    assert record["error_type"] == "configuration_error"
    assert record["phases"] == {
        "collection": "not_started", "validation": "not_started",
        "publication": "not_started", "restart": "not_started",
    }
    assert record["pages"] == []


@pytest.mark.parametrize("kwargs,message", [
    ({"pages": ["invalid"]}, "unknown refresh page"),
    ({"pages": ["sites"], "source": "invalid"}, "unknown refresh source"),
])
def test_invalid_page_or_source_is_rejected_before_journal_side_effects(
    tmp_path: Path, kwargs: dict, message: str
) -> None:
    root = runtime(tmp_path)
    with pytest.raises(refresh.RefreshError, match=message):
        refresh.refresh_runtime(root, **kwargs)
    assert not history_root(root).exists()


def test_native_busy_rejection_is_a_run_and_does_not_clobber_active_record(tmp_path: Path, monkeypatch) -> None:
    root = runtime(tmp_path)
    fake_collection(monkeypatch)
    history = RefreshHistory(root)
    with refresh._refresh_lock(root) as lock_path:
        active_id = history.start("scheduled", ["sites"])
        history.acquired(active_id, lock_path)
        with pytest.raises(refresh.RefreshError, match="running"):
            refresh.refresh_runtime(root, pages=["sites"], restart=False)
        active = show_refresh_run(root, active_id)
        assert active["status"] == "running"
    records = list_refresh_runs(root)
    busy = next(record for record in records if record["run_id"] != active_id)
    assert busy["status"] == "busy" and busy["error_type"] == "busy"
    assert show_refresh_run(root, active_id)["status"] == "running"


def test_browser_latest_state_and_journal_use_the_same_run_id(tmp_path: Path, monkeypatch) -> None:
    root = runtime(tmp_path)
    (root / "config/server-inventory.yml").write_text("inventory:\n  aliases: [fixture]\n", encoding="utf-8")
    fake_collection(monkeypatch)
    app = page_control.PageControlApp(root, "https://example.invalid")
    cookie = "session=synthetic"
    started = app.start(
        {"page": "projects", "action": "refresh", "csrf": app.token(cookie)},
        cookie,
        "https://example.invalid",
    )
    assert started["run_id"]
    for _ in range(200):
        status = app.status("projects")
        if status["state"] != "running":
            break
        threading.Event().wait(0.005)
    assert status["state"] == "success"
    assert status["run_id"] == started["run_id"]
    record = show_refresh_run(root, started["run_id"])
    assert record["source"] == "browser" and record["status"] == "success"


def test_browser_busy_rejection_is_journaled_with_its_status_run_id(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    app = page_control.PageControlApp(root, "https://example.invalid")
    cookie = "session=synthetic"
    with refresh._refresh_lock(root):
        result = app.start(
            {"page": "servers", "action": "refresh", "csrf": app.token(cookie)},
            cookie,
            "https://example.invalid",
        )
    assert result["state"] == "busy" and result["run_id"]
    assert app.status("servers")["run_id"] == result["run_id"]
    record = show_refresh_run(root, result["run_id"])
    assert record["source"] == "browser" and record["status"] == "busy"


def test_browser_process_restart_recovers_terminal_state_from_same_run_id(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    history = RefreshHistory(root)
    run_id = history.start("browser", ["projects"])
    history.finish(
        run_id,
        status="success",
        pages=[{"page": "projects", "status": "ok", "generated_at": "2026-10-05T08:00:00+00:00"}],
        validation="passed",
        publication="unchanged",
        restart="skipped",
    )
    old = page_control.PageControlApp(root, "https://example.invalid")
    old.jobs["projects"] = {"state": "running", "run_id": run_id, "started_at": "synthetic"}
    old._save()

    recovered = page_control.PageControlApp(root, "https://example.invalid").status("projects")
    assert recovered["state"] == "success"
    assert recovered["run_id"] == run_id
    assert recovered["observed_at"] == "2026-10-05T08:00:00+00:00"


def test_crash_recovery_requires_pid_start_and_actual_lock_evidence(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    history = RefreshHistory(root)
    with refresh._refresh_lock(root) as lock_path:
        active_id = history.start("scheduled", ["sites"])
        history.acquired(active_id, lock_path)
        contender = history.start("manual", ["sites"])
        assert show_refresh_run(root, active_id)["status"] == "running"
        history.finish(contender, status="busy", error_type="busy")
    orphan = history_root(root) / "active-orphan-run.lock"
    orphan.write_text("", encoding="utf-8")
    orphan.chmod(0o600)
    # The PID still exists, but the exact refresh lock is no longer held.  A
    # subsequent writer may therefore recover the prior run as interrupted.
    recovery = history.start("manual", ["sites"])
    assert not orphan.exists()
    assert show_refresh_run(root, active_id)["status"] == "interrupted"
    assert show_refresh_run(root, active_id)["error_type"] == "interrupted"
    # A real owner may be between refresh-lock release and its terminal journal
    # write while the contender recovers it. Its exact PID/start identity may
    # still replace that provisional interrupted state with the truthful error.
    history.finish(active_id, status="failed", error_type="collection_error")
    assert show_refresh_run(root, active_id)["status"] == "failed"
    history.finish(recovery, status="failed", error_type="collection_error")


def test_concurrent_rejected_runs_are_unique_and_mode_safe(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: record_rejected_run(root, "browser", ["servers"], error_type="busy"), range(24)))
    assert len({record["run_id"] for record in records}) == 24
    assert len(list_refresh_runs(root)) == 24
    base = history_root(root)
    assert base.stat().st_mode & 0o777 == 0o700
    assert (base / "runs").stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (base / "runs").glob("*.json"))
    assert list(base.glob("active-*.lock")) == []


def test_history_paths_reject_symlinks_and_traversal(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "private").mkdir()
    (root / "private/refresh-history").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RefreshHistoryError, match="symlink"):
        record_rejected_run(root, "manual", ["sites"], error_type="busy")
    assert list(outside.iterdir()) == []

    (root / "private/refresh-history").unlink()
    record = record_rejected_run(root, "manual", ["sites"], error_type="busy")
    with pytest.raises(RefreshHistoryError):
        show_refresh_run(root, "../../private/server-notes")
    assert show_refresh_run(root, record["run_id"])["run_id"] == record["run_id"]


def _finished(
    root: Path,
    run_id: str,
    when: datetime,
    *,
    published: bool = False,
    status: str = "success",
) -> dict:
    history = RefreshHistory(root, now=lambda: when)
    history.start("manual", ["sites"], run_id=run_id)
    return history.finish(
        run_id,
        status=status,
        pages=[{"page": "sites", "status": "ok", "generated_at": when.isoformat(), "counts": {"sites": 1}}],
        validation="passed",
        publication="published" if published else "unchanged",
        restart="disabled",
        changed=published,
        published=published,
    )


def test_prune_preview_then_apply_bounds_age_and_aggregate_bytes_with_protections(tmp_path: Path, monkeypatch) -> None:
    root = runtime(tmp_path)
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(RefreshHistory, "_automatic_prune", lambda self: None)
    _finished(root, "old-unprotected", now - timedelta(days=90))
    _finished(root, "last-published", now - timedelta(days=40), published=True)
    _finished(root, "last-good-run", now - timedelta(days=35))
    _finished(root, "newer-unprotected", now - timedelta(days=2))
    _finished(root, "future-run", now + timedelta(days=2))
    active = RefreshHistory(root, now=lambda: now).start("scheduled", ["sites"], run_id="active-run")
    assert active == "active-run"

    last_good = root / "private/server-last-good.json"
    last_good.write_text(json.dumps({"schema_version": 1, "servers": {"srv": {"run_id": "last-good-run"}}}), encoding="utf-8")
    last_good.chmod(0o600)
    malformed = history_root(root) / "runs/malformed-owner.json"
    malformed.write_text(json.dumps({"owner": "someone-else", "run_id": "malformed-owner"}), encoding="utf-8")

    preview = prune_refresh_history(root, retention_days=30, max_bytes=1, apply=False, now=now)
    assert preview["applied"] is False
    assert "old-unprotected" in preview["delete_run_ids"]
    assert "newer-unprotected" in preview["delete_run_ids"]  # byte cap, despite age
    assert {"active-run", "future-run", "last-good-run", "last-published"}.issubset(set(preview["protected_run_ids"]))
    assert (history_root(root) / "runs/old-unprotected.json").exists()
    assert malformed.exists()
    assert preview["before_bytes"] >= sum(path.stat().st_size for path in (history_root(root) / "runs").glob("*.json"))

    applied = prune_refresh_history(root, retention_days=30, max_bytes=1, apply=True, now=now)
    assert applied["applied"] is True
    assert not (history_root(root) / "runs/old-unprotected.json").exists()
    assert not (history_root(root) / "snapshots/old-unprotected.json").exists()
    assert malformed.exists()
    assert not (history_root(root) / ".trash").exists()
    for protected in ("active-run", "future-run", "last-good-run", "last-published"):
        assert (history_root(root) / "runs" / f"{protected}.json").exists()


def test_prune_counts_and_converges_owned_orphan_snapshots_without_touching_unsafe_files(
    tmp_path: Path, monkeypatch
) -> None:
    root = runtime(tmp_path)
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(RefreshHistory, "_automatic_prune", lambda self: None)
    _finished(root, "orphan-old", now - timedelta(days=90), published=True)
    _finished(root, "lastgood-protected", now - timedelta(days=60), published=True)
    _finished(root, "latest-protected", now - timedelta(days=1), published=True)
    orphan_run = history_root(root) / "runs/orphan-old.json"
    orphan_snapshot = history_root(root) / "snapshots/orphan-old.json"
    orphan_size = orphan_snapshot.stat().st_size
    orphan_run.unlink()  # synthetic interruption after the run file was removed
    (history_root(root) / "runs/lastgood-protected.json").unlink()
    (history_root(root) / "runs/latest-protected.json").unlink()
    (root / "private/server-last-good.json").write_text(
        json.dumps({"schema_version": 1, "servers": {"srv": {"run_id": "lastgood-protected"}}}), encoding="utf-8"
    )
    unowned = history_root(root) / "snapshots/unowned.json"
    unowned.write_text('{"owner":"someone-else"}', encoding="utf-8")
    unsafe = history_root(root) / "snapshots/unsafe.json"
    unsafe.symlink_to(unowned)
    legacy = root / "config/backups/refresh-legacy"
    legacy.mkdir(parents=True)
    (legacy / "0").write_text("legacy", encoding="utf-8")

    preview = prune_refresh_history(root, retention_days=30, max_bytes=10**9, apply=False, now=now)
    assert preview["before_bytes"] >= orphan_size
    assert "orphan-old" in preview["delete_run_ids"]
    applied = prune_refresh_history(root, retention_days=30, max_bytes=10**9, apply=True, now=now)
    assert "orphan-old" in applied["delete_run_ids"] and not orphan_snapshot.exists()
    repeated = prune_refresh_history(root, retention_days=30, max_bytes=10**9, apply=True, now=now)
    assert "orphan-old" not in repeated["delete_run_ids"]
    assert (history_root(root) / "snapshots/latest-protected.json").exists()
    assert (history_root(root) / "snapshots/lastgood-protected.json").exists()
    assert unowned.exists() and unsafe.is_symlink() and (legacy / "0").exists()


def test_typed_history_defaults_validation_and_automatic_prune(tmp_path: Path, monkeypatch) -> None:
    fields = ChatGlanceConfig.get_fields()
    assert fields["CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS"].default == "30"
    assert fields["CHATGLANCE_REFRESH_HISTORY_MAX_BYTES"].default == str(256 * 1024 * 1024)
    assert history_settings(home=tmp_path) == {
        "retention_days": DEFAULT_RETENTION_DAYS,
        "max_bytes": DEFAULT_MAX_BYTES,
    }
    monkeypatch.setenv("CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS", "0")
    with pytest.raises(ValueError, match="RETENTION"):
        history_settings(home=tmp_path)
    monkeypatch.setenv("CHATGLANCE_REFRESH_HISTORY_RETENTION_DAYS", "30")
    monkeypatch.setenv("CHATGLANCE_REFRESH_HISTORY_MAX_BYTES", "not-an-int")
    with pytest.raises(ValueError, match="MAX_BYTES"):
        history_settings(home=tmp_path)

    root = runtime(tmp_path / "auto")
    fake_collection(monkeypatch)
    calls = []
    monkeypatch.delenv("CHATGLANCE_REFRESH_HISTORY_MAX_BYTES", raising=False)
    monkeypatch.setattr("chatglance.refresh_history.prune_refresh_history", lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    refresh.refresh_runtime(root, pages=["sites"], restart=False)
    assert calls and calls[-1][1]["apply"] is True


def test_runtime_history_cli_is_thin_readonly_and_prune_requires_apply(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    record = record_rejected_run(root, "manual", ["sites"], error_type="busy")
    runner = CliRunner()
    listed = runner.invoke(main, ["runtime", "history", "list", "--runtime-home", str(root)])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["run_id"] == record["run_id"]
    shown = runner.invoke(main, ["runtime", "history", "show", record["run_id"], "--runtime-home", str(root)])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["status"] == "busy"

    before = (history_root(root) / "runs" / f'{record["run_id"]}.json').read_bytes()
    preview = runner.invoke(
        main,
        ["runtime", "history", "prune", "--runtime-home", str(root), "--retention-days", "1", "--max-bytes", "1"],
    )
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["applied"] is False
    assert (history_root(root) / "runs" / f'{record["run_id"]}.json').read_bytes() == before


def test_list_and_show_are_readonly_even_for_unlocked_running_record(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    history = RefreshHistory(root)
    run_id = history.start("manual", ["sites"])
    run_path = history_root(root) / "runs" / f"{run_id}.json"
    before = run_path.read_bytes()
    assert list_refresh_runs(root)[0]["effective_status"] == "running"
    assert show_refresh_run(root, run_id)["effective_status"] == "running"
    assert run_path.read_bytes() == before
