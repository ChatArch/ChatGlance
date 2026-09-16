from copy import deepcopy
from datetime import date
import json

import pytest

from chatglance import codex_collector as collector
from chatglance import account_limits
from chatglance.account_limits import (
    _render_reset_calendar,
    normalize_account_limits_data,
    render_account_limits_html,
)

OLD_TIME = "2026-09-16T07:00:00+08:00"
NOW = "2026-09-16T09:00:00+08:00"
EVENTS = [
    {"event_id": "september", "time_utc": "2026-09-12T08:00:00Z", "date_bjt": "2026-09-12", "source_url": "https://example.com/september"},
    {"event_id": "august", "time_utc": "2026-08-01T08:00:00Z", "date_bjt": "2026-08-01", "source_url": "https://example.com/august"},
    {"event_id": "july", "time_utc": "2026-07-01T08:00:00Z", "date_bjt": "2026-07-01", "source_url": "https://example.com/july"},
    {"event_id": "june", "time_utc": "2026-06-29T08:00:00Z", "date_bjt": "2026-06-29", "source_url": "https://example.com/june"},
]


def successful_reset(events=EVENTS):
    return {"source": collector.PUBLIC_RESET_SOURCE, "status": "ok", "events": deepcopy(events), "latest": deepcopy(events[0]), "confirmed_reset_count": len(events)}


@pytest.fixture
def offline_collection(tmp_path, monkeypatch):
    render_calendar = account_limits._render_reset_calendar
    monkeypatch.setattr(account_limits, "_render_reset_calendar", lambda events: render_calendar(events, current_date=date(2026, 9, 16)))
    monkeypatch.setattr(collector, "collection_settings", lambda **kw: {"reset_policies": "{}", "reset_base_url": "", "execute_resets": False})
    monkeypatch.setattr(collector, "iso_now", lambda: NOW)
    monkeypatch.setattr(collector, "profile_payload", lambda profile, timeout, **kw: {"profile": profile, "status": "ok", "windows": [], "reset_history": []})
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"generated_at": OLD_TIME, "codex": [], "codex_reset": successful_reset()}))

    def collect(**options):
        return collector.collect_account_limits(profiles="work", output_path=path, history_path=path, execute_resets=False, home=tmp_path, **options)

    return collect, path


@pytest.mark.parametrize("status", ["error", "empty"])
def test_failed_public_refresh_preserves_calendar_history(offline_collection, monkeypatch, status):
    collect, path = offline_collection
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: {"source": collector.PUBLIC_RESET_SOURCE, "status": status, "events": []})
    result = collect()
    cached = result["codex_reset"]
    assert cached["status"] == status
    assert cached["using_last_known_values"] is True
    assert cached["last_successful_at"] == OLD_TIME
    assert cached["events"] == EVENTS
    assert cached["confirmed_reset_count"] == len(EVENTS)
    assert json.loads(path.read_text())["codex_reset"] == cached
    rendered = render_account_limits_html(result)
    assert "更新失败，显示缓存" in rendered
    assert OLD_TIME in rendered
    for month in ("09", "08", "07", "06"):
        assert f"2026 年 {month} 月" in rendered


def test_repeated_failures_do_not_refresh_cache_age(offline_collection, monkeypatch):
    collect, _ = offline_collection
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: {"status": "error", "events": []})
    first = collect()
    monkeypatch.setattr(collector, "iso_now", lambda: "2026-09-16T12:00:00+08:00")
    second = collect()
    assert second["codex_reset"]["events"] == first["codex_reset"]["events"] == EVENTS
    assert second["codex_reset"]["last_successful_at"] == OLD_TIME


def test_success_replaces_cache_and_clears_stale_marker(offline_collection, monkeypatch):
    collect, _ = offline_collection
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: {"status": "error", "events": []})
    collect()
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: successful_reset(EVENTS[:1]))
    fresh = collect()["codex_reset"]
    assert fresh["status"] == "ok"
    assert fresh["using_last_known_values"] is False
    assert fresh["last_successful_at"] == NOW
    assert fresh["events"] == EVENTS[:1]


def test_explicit_skip_does_not_resurrect_cached_public_records(offline_collection, monkeypatch):
    collect, _ = offline_collection
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: pytest.fail("disabled source was fetched"))
    reset = collect(no_public_reset=True)["codex_reset"]
    assert reset["status"] == "skipped"
    assert reset["events"] == []


@pytest.mark.parametrize("previous", [[], {}, {"codex_reset": []}, {"codex_reset": {"status": "error", "events": EVENTS}}])
def test_missing_or_failed_cache_is_not_fabricated(offline_collection, monkeypatch, previous):
    collect, path = offline_collection
    path.write_text(json.dumps(previous))
    monkeypatch.setattr(collector, "fetch_public_codex_reset", lambda timeout: {"status": "error", "events": []})
    reset = collect()["codex_reset"]
    assert reset["events"] == []
    assert not reset.get("using_last_known_values")


def test_account_window_samples_never_replace_official_calendar():
    data = {"codex_reset": {"status": "error", "events": []}, "codex": [{"profile": "work", "reset_history": [{"reset_at": "2026-09-23T12:00:00+08:00", "label": "Secondary"}]}]}
    reset = normalize_account_limits_data(data)["codex_reset"]
    assert reset["events"] == []
    assert reset["used_fallback"] is False
    rendered = render_account_limits_html(data)
    assert "官方重置记录暂不可用" in rendered
    assert "账号窗口采样" not in rendered
    assert "is-reset\"" not in rendered


def test_multiple_resets_on_one_day_are_counted_as_events():
    events = [
        {"reset_at": "2026-09-08T10:00:00+08:00", "label": "First"},
        {"reset_at": "2026-09-08T12:00:00+08:00", "label": "Second"},
        {"reset_at": "2026-09-12T16:00:00+08:00", "label": "Third"},
    ]
    rendered = _render_reset_calendar(events, current_date=date(2026, 9, 16))
    assert "3 次 reset" in rendered
    assert rendered.count('class="codex-reset-day is-reset"') == 2
