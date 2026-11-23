from __future__ import annotations

import os
import time
from datetime import date, datetime

import yaml

from chatglance.account_limits import (
    ACCOUNT_LIMITS_PAGE_NAME,
    BEIJING_TIMEZONE,
    _render_reset_calendar,
    update_home_reset_calendar,
    build_account_limits_page,
    normalize_account_limits_data,
    render_account_limits_html,
    replace_account_limits_page,
)


def sample_account_limits_data() -> dict:
    return {
        "generated_at": "2026-08-12T13:55:00+08:00",
        "accounts": [
            {
                "profile": "default",
                "model": "gpt-5.5",
                "source": "crs-key-info",
                "account_id": "117b0568-70e9-4caf-8e10-451dd7760ac3",
                "account_name": "wzh",
                "permissions": ["openai"],
                "rate_limit": {"window": 0, "requests": 0},
                "usage": {"total_requests": 1786, "daily_requests": 0, "monthly_requests": 0, "total_all_tokens": 200671051},
            },
            {
                "profile": "wzh",
                "model": "gpt-5.5",
                "source": "crs-key-info",
                "account_id": "117b0568-70e9-4caf-8e10-451dd7760ac3",
                "account_name": "wzh",
                "permissions": ["openai"],
                "rate_limit": {"window": 0, "requests": 0},
                "usage": {"total_requests": 1786, "daily_requests": 0, "monthly_requests": 0, "total_all_tokens": 200671051},
            },
            {
                "profile": "apple",
                "model": "gpt-5.4",
                "source": "crs-key-info",
                "account_id": "28907796-890a-48b3-a1c9-af0d9734f8d9",
                "account_name": "openai",
                "permissions": ["openai"],
                "rate_limit": {"window": 0, "requests": 0},
                "usage": {"total_requests": 64963, "daily_requests": 285, "monthly_requests": 8022, "total_all_tokens": 9114096948},
            },
        ],
        "codex": [
            {
                "profile": "default",
                "account_id": "acct-codex",
                "account_name": "wzh Codex",
                "plan": "Pro",
                "status": "ok",
                "windows": [
                    {
                        "label": "Primary",
                        "used_percent": 12.5,
                        "reset_at": "2026-08-12T18:30:00+08:00",
                        "window_minutes": 300,
                    },
                    {
                        "label": "Secondary",
                        "used_percent": 3,
                        "reset_at": "2026-08-18T09:00:00+08:00",
                        "window_minutes": 10080,
                    },
                ],
                "details": ["Credits balance: unlimited"],
            }
        ],
        "codex_reset": {
            "source": "https://codexreset.org/",
            "confirmed_reset_count": 2,
            "latest": {
                "event_id": "2086972933566857393",
                "time_utc": "2026-08-11T00:28:16Z",
                "time_bjt": "2026-08-11 08:28:16 +0800",
                "date_bjt": "2026-08-11",
                "source_url": "https://x.com/thsottiaux/status/2086972933566857393",
            },
            "events": [
                {
                    "event_id": "2086972933566857393",
                    "time_utc": "2026-08-11T00:28:16Z",
                    "time_bjt": "2026-08-11 08:28:16 +0800",
                    "date_bjt": "2026-08-11",
                    "scope": "All paid ChatGPT Work and Codex users",
                    "source_url": "https://x.com/thsottiaux/status/2086972933566857393",
                },
                {
                    "event_id": "2079351779206668512",
                    "time_utc": "2026-08-01T03:32:00Z",
                    "time_bjt": "2026-08-01 11:32:00 +0800",
                    "date_bjt": "2026-08-01",
                    "scope": "All paid ChatGPT Work and Codex users",
                    "source_url": "https://x.com/thsottiaux/status/2079351779206668512",
                },
            ],
        },
        "secrets": {
            "api_key": "«redacted:sk-…»",
            "access_token": "access-secret",
            "cookie": "session-secret",
        },
    }


def test_normalize_account_limits_dedupes_crs_accounts_and_counts_codex_windows() -> None:
    normalized = normalize_account_limits_data(sample_account_limits_data())

    assert normalized["counts"] == {
        "accounts": 2,
        "codex_profiles": 1,
        "codex_windows": 2,
        "codex_reset_events": 2,
    }
    assert normalized["codex_reset"]["source"] == "https://codexreset.org/"
    assert normalized["refresh_status"]["status"] == "ok"
    wzh = normalized["accounts"][0]
    assert wzh["account_name"] == "wzh"
    assert wzh["profiles"] == ["default", "wzh"]
    assert wzh["models"] == ["gpt-5.5"]


def test_render_account_limits_html_shows_current_usage_and_reset_dates_without_secrets() -> None:
    html = render_account_limits_html(sample_account_limits_data())

    assert "订阅详情" in html
    assert "账号额度" not in html
    assert "default, wzh" not in html
    assert "1,786" not in html
    assert "64,963" not in html
    assert "Codex" in html
    assert "使用额度" in html
    assert "重置时间" in html
    assert "Primary" not in html
    assert "Secondary" not in html
    assert "12.5%" in html
    assert "2026-08-12 18:30" in html
    assert "2026-08-18 09:00" not in html
    assert "«redacted:sk-…»" not in html
    assert "access-secret" not in html
    assert "session-secret" not in html


def test_render_account_limits_html_escapes_subscription_tag() -> None:
    data = sample_account_limits_data()
    data["codex"][0]["subscription_tag"] = "Pro & <safe>"

    html = render_account_limits_html(data)

    assert 'class="account-plan-tag">Pro &amp; &lt;safe&gt;</span>' in html
    assert "Pro & <safe>" not in html


def test_render_account_limits_html_prioritizes_accounts_over_reset_calendar() -> None:
    html = render_account_limits_html(sample_account_limits_data())

    assert "账号使用额度" in html
    assert "Codex 官方重置日历" not in html
    assert '<section class="codex-reset-panel"' not in html
    assert "codex-account-card-grid" in html
    assert "暂无 reset 记录" not in html


def test_home_calendar_replaces_original_slot_and_removes_owned_bookmark() -> None:
    owned = {"type": "bookmarks", "title": "订阅概览", "groups": [{"links": [{"url": "/account-limits"}]}]}
    config = {"pages": [{"name": "ChatArch", "columns": [
        {"size": "small", "widgets": [{"type": "bookmarks", "title": "订阅概览", "groups": []}]},
        {"size": "full", "widgets": [{"type": "calendar", "first-day-of-week": "monday"}, owned,
            {"type": "bookmarks", "title": "公开入口"}]},
    ]}]}
    data = {"codex_reset": {"status": "ok", "events": [{
        "event_id": "confirmed-1", "time_bjt": "2026-11-22 10:30:00 +0800",
        "date_bjt": "2026-11-22", "scope": "Confirmed Codex reset",
    }]}}
    updated = update_home_reset_calendar(config, data)
    columns = updated["pages"][0]["columns"]
    widgets = columns[1]["widgets"]
    assert [w["type"] for w in widgets] == ["calendar", "html", "bookmarks"]
    assert widgets[0]["first-day-of-week"] == "monday"
    assert widgets[0]["css-class"] == "codex-reset-native-calendar"
    assert 'class="codex-reset-markers"' in widgets[1]["source"]
    assert '2026-11-22' in widgets[1]["source"] and "Confirmed Codex reset" in widgets[1]["source"]
    assert "codex-calendar-month-switcher" not in widgets[1]["source"]
    assert columns[0]["widgets"][0]["title"] == "订阅概览"
    assert update_home_reset_calendar(updated, data) == updated
    assert config["pages"][0]["columns"][1]["widgets"][0]["type"] == "calendar"


def test_home_calendar_shows_current_month_without_inventing_events() -> None:
    config = {"pages": [{"name": "ChatArch", "columns": [{"size": "small", "widgets": [{"type": "calendar"}]}]}]}
    updated = update_home_reset_calendar(config, {"codex_reset": {"status": "error", "events": []}})
    widgets = updated["pages"][0]["columns"][0]["widgets"]
    assert [w["type"] for w in widgets] == ["calendar", "html"]
    assert "官方重置记录暂不可用" in widgets[1]["source"]
    assert "codex-calendar-month-switcher" not in widgets[1]["source"]
    assert "预计" not in widgets[1]["source"]


def test_home_calendar_shows_account_window_predictions_not_official_confirmation() -> None:
    config = {"pages": [{"name": "ChatArch", "columns": [{"size": "small", "widgets": [{"type": "calendar"}]}]}]}
    data = {"codex_reset": {"status": "error", "events": []}, "codex": [{
        "profile": "account-a", "windows": [{"name": "primary_window", "window_seconds": 604800,
            "reset_at": "2026-11-29T03:00:00+08:00", "used_percent": 70}],
    }]}
    updated = update_home_reset_calendar(config, data)
    source = updated["pages"][0]["columns"][0]["widgets"][1]["source"]
    assert "账号窗口预计重置（非官方确认）" in source
    assert "account-a" in source and "2026-11-29" in source
    assert 'codex-reset-forecast' in source
    assert '已确认重置记录' not in source


def test_native_calendar_marker_data_is_private_and_escaped() -> None:
    import html as html_module
    import json
    import re

    config = {"pages": [{"name": "ChatArch", "public": True,
                         "columns": [{"size": "small", "widgets": [{"type": "bookmarks", "groups": []}]}],
                         "authenticated-columns": [{"size": "small", "widgets": [
                             {"type": "calendar", "first-day-of-week": "monday"}]}]}]}
    data = {"codex_reset": {"status": "ok", "events": [{
        "time_bjt": "2026-11-29 08:30:00 +0800", "scope": "Confirmed <script>alert(1)</script>",
    }]}, "codex": [{"profile": "a-account", "windows": [{
        "window_seconds": 604800, "reset_at": "2099-12-01T09:00:00+08:00",
    }]}]}
    result = update_home_reset_calendar(config, data)
    marker = result["pages"][0]["authenticated-columns"][0]["widgets"][1]["source"]
    payload_match = re.search(r'data-days="([^"]+)"', marker)
    assert payload_match is not None
    days = json.loads(html_module.unescape(payload_match.group(1)))
    assert days["2026-11-29"]["official"] == ["Confirmed <script>alert(1)</script>"]
    assert days["2099-12-01"]["forecast"] == ["a-account · 7天窗口"]
    assert "<script>alert(1)</script>" not in marker
    assert "a-account" not in json.dumps(result["pages"][0]["columns"])
    assert "a-account" not in result["document"]["head"]


def test_render_account_limits_html_hides_public_reset_event_details() -> None:
    data = sample_account_limits_data()
    data["codex_reset"]["latest"] = {
        "time_utc": "2026-08-11T00:28:16Z",
        "time_bjt": "2026-08-11 08:28:16 +0800",
        "date_bjt": "2026-08-11",
    }
    data["codex_reset"]["events"].insert(0, {
        "event_id": "2091400000000000000",
        "time_utc": "2026-08-24T00:46:51Z",
        "time_bjt": "2026-08-24 08:46:51 +0800",
        "date_bjt": "2026-08-24",
        "scope": "Paid Codex users",
        "source_url": "https://x.com/thsottiaux/status/2091400000000000000",
    })

    html = render_account_limits_html(data)

    assert "Codex 官方重置日历" not in html
    assert "2026-08-24 08:46:51 +0800" not in html
    assert "2091400000000000000" not in html


def test_build_account_limits_page_creates_wide_html_page() -> None:
    page = build_account_limits_page(sample_account_limits_data())

    assert page["name"] == ACCOUNT_LIMITS_PAGE_NAME
    assert page["slug"] == "account-limits"
    assert page["width"] == "wide"
    assert page["columns"][0]["widgets"][0]["type"] == "html"
    assert page["columns"][0]["widgets"][0]["title"] == "订阅详情"


def test_replace_account_limits_page_appends_after_sites_page_and_removes_old_slug() -> None:
    config = {
        "pages": [
            {"name": "ChatArch"},
            {"name": "项目"},
            {"name": "服务器", "slug": "servers"},
            {"name": "网站服务", "slug": "sites"},
            {"name": "旧账号额度", "slug": "account-limits", "old": True},
        ]
    }

    updated = replace_account_limits_page(config, sample_account_limits_data())

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目", "服务器", "网站服务", "订阅详情"]
    assert updated["pages"][-1]["slug"] == "account-limits"
    assert config["pages"][-1]["old"] is True


def test_replace_account_limits_page_removes_old_account_quota_name_after_subscription_rename() -> None:
    config = {
        "pages": [
            {"name": "ChatArch"},
            {"name": "账号额度", "slug": "old-account-quota", "old": True},
            {"name": "订阅详情", "slug": "account-limits", "old": True},
        ]
    }

    updated = replace_account_limits_page(config, sample_account_limits_data())

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "订阅详情"]
    assert updated["pages"][-1]["slug"] == "account-limits"
    rendered = yaml.safe_dump(updated, allow_unicode=True, sort_keys=False)
    assert "使用额度" in rendered
    assert "重置时间" in rendered
    assert "default, wzh" not in rendered
    assert "gpt-5.5" not in rendered
    assert "«redacted:sk-…»" not in rendered


def test_render_account_limits_html_uses_beijing_time_when_host_timezone_is_utc(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        data = sample_account_limits_data()
        html = render_account_limits_html(data)

        assert "2026-08-12 18:30" in html
        assert "2026-08-18 09:00" not in html
    finally:
        monkeypatch.delenv("TZ", raising=False)
        if hasattr(time, "tzset"):
            time.tzset()


def test_render_account_limits_html_converts_top_refresh_time_to_beijing() -> None:
    data = sample_account_limits_data()
    data["generated_at"] = "2026-08-14T03:42:07Z"

    html = render_account_limits_html(data)

    assert "数据观测：2026-08-14T11:42:07+08:00" in html
    assert "2026-08-14T03:42:07Z" not in html


def test_render_account_limits_html_is_idempotent_for_normalized_data() -> None:
    normalized = normalize_account_limits_data(sample_account_limits_data())

    html = render_account_limits_html(normalized)

    assert "使用额度" in html
    assert "重置时间" in html
    assert "2026-08-12 18:30" in html
    assert "2026-08-18 09:00" not in html


def test_normalize_account_limits_accepts_chatcrs_display_rows_shape() -> None:
    data = {
        "generated_at": "2026-08-12T13:31:19+08:00",
        "rows": [
            {
                "profile": "default",
                "model": "gpt-5.5",
                "id": "117b0568-70e9-4caf-8e10-451dd7760ac3",
                "name": "wzh",
                "permissions": ["openai"],
                "rate_limit": {"window": 0, "requests": 0},
                "requests_total": 1786,
                "requests_daily": 0,
                "requests_monthly": 0,
                "all_tokens_total": 200671051,
            },
            {
                "profile": "wzh",
                "model": "gpt-5.5",
                "id": "117b0568-70e9-4caf-8e10-451dd7760ac3",
                "name": "wzh",
                "permissions": ["openai"],
                "rate_limit": {"window": 0, "requests": 0},
                "requests_total": 1786,
                "requests_daily": 0,
                "requests_monthly": 0,
                "all_tokens_total": 200671051,
            },
        ],
        "codex": [
            {
                "profile": "default",
                "status": "error",
                "error_type": "AuthError",
                "error": "No Codex credentials stored. Run hermes auth to authenticate.",
            }
        ],
    }

    normalized = normalize_account_limits_data(data)
    html = render_account_limits_html(data)

    assert normalized["counts"] == {
        "accounts": 1,
        "codex_profiles": 1,
        "codex_windows": 0,
        "codex_reset_events": 0,
    }
    assert normalized["accounts"][0]["profiles"] == ["default", "wzh"]
    assert normalized["accounts"][0]["usage"]["total_requests"] == 1786
    assert normalized["accounts"][0]["usage"]["total_all_tokens"] == 200671051
    assert "No Codex credentials stored" in html
    assert "AuthError" in html


def test_render_account_limits_html_publishes_partial_probe_status_without_secrets() -> None:
    data = sample_account_limits_data()
    data["refresh_status"] = {
        "status": "partial",
        "profiles_total": 2,
        "ok_count": 1,
        "failed_count": 1,
        "ok_profiles": ["allis"],
        "failed_profiles": ["73-wzh"],
    }
    data["codex"] = [
        data["codex"][0],
        {
            "profile": "73-wzh",
            "account_name": "73-wzh",
            "status": "error",
            "credential_status": "invalid_or_expired",
            "error_type": "CodexProbeError",
            "error": "Error: OpenAI OAuth refresh failed: status=401 access_token=secret-value",
            "using_last_known_values": True,
            "last_successful_at": "2026-08-23T01:21:19+08:00",
            "windows": [
                {
                    "label": "Primary",
                    "used_percent": 88.8,
                    "reset_at": "2026-08-25T10:00:00+08:00",
                    "window_minutes": 300,
                }
            ],
        },
    ]

    normalized = normalize_account_limits_data(data)
    html = render_account_limits_html(data)

    assert normalized["refresh_status"]["status"] == "partial"
    assert normalized["refresh_status"]["failed_profiles"] == ["73-wzh"]
    assert "采集状态：部分失败" in html
    assert "成功 1/2" in html
    assert "73-wzh" in html
    assert "已失效 / 需重新登录" in html
    assert "88.8%" in html
    assert "保留上次成功值：2026-08-23T01:21:19+08:00" in html
    assert "status=401" in html
    assert "secret-value" not in html
    assert "access_token" not in html


def test_render_account_limits_html_omits_empty_crs_account_placeholder() -> None:
    data = sample_account_limits_data()
    data["accounts"] = []

    html = render_account_limits_html(data)

    assert "暂无 CRS account 数据" not in html
    assert '<table class="limit-table">' not in html
    assert "Codex" in html


def test_render_account_limits_html_uses_compact_codex_card_titles_without_repeated_profile_plan() -> None:
    data = sample_account_limits_data()
    data["codex"][0]["profile"] = "73-wzh"
    data["codex"][0]["account_name"] = "73-wzh"
    data["codex"][0]["plan"] = "Codex"

    html = render_account_limits_html(data)

    assert "Codex · 73-wzh" not in html
    assert "73-wzh · Codex" not in html
    assert "<h3>73-wzh</h3>" in html


def test_render_account_limits_html_uses_single_month_calendar_card_and_account_card_grid() -> None:
    data = sample_account_limits_data()
    data["codex_reset"]["events"].append(
        {
            "event_id": "previous-month",
            "time_bjt": "2026-07-20 09:00:00 +0800",
            "date_bjt": "2026-07-20",
            "scope": "Previous reset",
            "source_url": "https://x.com/example/status/previous-month",
        }
    )
    html = render_account_limits_html(data)

    assert 'class="account-limits-resource-layout"' in html
    assert 'class="codex-reset-panel"' not in html
    assert 'class="codex-accounts-panel"' in html
    assert 'class="codex-calendar-card"' not in html
    assert 'class="codex-account-card-grid"' in html
    assert 'class="codex-account-card site-style-card"' in html
    assert 'class="codex-reset-carousel"' not in html
    assert 'class="codex-account-list"' not in html
    assert 'class="limit-progress"' in html
    assert "使用额度" in html
    assert "重置时间" in html
    assert "Previous reset" not in html


def test_render_account_limits_html_ignores_recent_public_reset_months() -> None:
    data = sample_account_limits_data()
    data["codex_reset"]["events"] = [{
        "event_id": f"month-{month}",
        "time_bjt": f"2026-{month:02d}-02 10:00:00 +0800",
        "date_bjt": f"2026-{month:02d}-02",
        "scope": "Recent reset",
        "source_url": f"https://x.com/example/status/month-{month}",
    } for month in range(4, 9)]

    html = render_account_limits_html(data)

    assert "Codex 官方重置日历" not in html
    assert "2026 年 04 月" not in html
    assert "2026 年 08 月" not in html
    assert "Recent reset" not in html


def test_render_account_limits_html_does_not_render_current_reset_month() -> None:
    html = render_account_limits_html(sample_account_limits_data())
    now = datetime.now(BEIJING_TIMEZONE)

    assert f"{now.year} 年 {now.month:02d} 月" not in html
    assert "codex-calendar" not in html


def test_reset_calendar_puts_reference_month_first_even_without_events() -> None:
    events = [
        {
            "event_id": "aug-1",
            "reset_at": "2026-08-11T08:28:16+08:00",
            "time_bjt": "2026-08-11 08:28:16 +0800",
            "date_bjt": "2026-08-11",
            "scope": "Recent reset",
            "source_url": "https://x.com/example/status/aug-1",
        }
    ]

    html = _render_reset_calendar(events, reference_month=(2026, 9))

    assert html.index("2026 年 09 月") < html.index("2026 年 08 月")
    assert "0 次 reset" in html


def test_reset_calendar_defaults_to_current_bjt_month() -> None:
    events = [
        {
            "event_id": "aug-1",
            "reset_at": "2026-08-11T08:28:16+08:00",
            "time_bjt": "2026-08-11 08:28:16 +0800",
            "date_bjt": "2026-08-11",
            "scope": "Recent reset",
            "source_url": "https://x.com/example/status/aug-1",
        }
    ]

    html = _render_reset_calendar(events)

    now = datetime.now(BEIJING_TIMEZONE)
    assert f"{now.year} 年 {now.month:02d} 月" in html


def test_reset_calendar_marks_today_with_red_circle() -> None:
    events = [
        {
            "event_id": "aug-1",
            "reset_at": "2026-08-11T08:28:16+08:00",
            "time_bjt": "2026-08-11 08:28:16 +0800",
            "date_bjt": "2026-08-11",
            "scope": "Recent reset",
            "source_url": "https://x.com/example/status/aug-1",
        }
    ]

    html = _render_reset_calendar(events, reference_month=(2026, 9), current_date=date(2026, 9, 3))

    assert 'class="codex-reset-day is-today" title="今天"><span class="day-number">3</span>' in html


def test_reset_calendar_keeps_reset_marker_when_today_is_reset_day() -> None:
    events = [
        {
            "event_id": "sep-3",
            "reset_at": "2026-09-03T08:28:16+08:00",
            "time_bjt": "2026-09-03 08:28:16 +0800",
            "date_bjt": "2026-09-03",
            "scope": "Recent reset",
            "label": "Recent reset",
            "source_url": "https://x.com/example/status/sep-3",
        }
    ]

    html = _render_reset_calendar(events, reference_month=(2026, 9), current_date=date(2026, 9, 3))

    assert 'class="codex-reset-day is-reset is-today"' in html
    assert 'title="今天 · Recent reset"' in html


def test_render_account_limits_html_does_not_render_unsafe_reset_source_urls() -> None:
    data = sample_account_limits_data()
    data["codex_reset"]["source"] = "javascript:alert(1)"
    data["codex_reset"]["latest"]["source_url"] = "javascript:alert(2)"

    html = render_account_limits_html(data)

    assert "javascript:alert" not in html


def test_render_account_limits_html_omits_probe_diagnostics_from_cards() -> None:
    data = sample_account_limits_data()
    data["codex"][0]["details"] = [
        "usage_status=200",
        "quota_status=200",
        "quota_headers=yes",
        "refresh_attempted=no",
    ]
    data["codex"][0]["usage_status"] = 200
    data["codex"][0]["quota_status"] = 200
    data["codex"][0]["quota_headers_present"] = True
    data["codex"][0]["refresh_attempted"] = False

    html = render_account_limits_html(data)

    assert "usage_status=200" not in html
    assert "quota_status=200" not in html
    assert "quota_headers=yes" not in html
    assert "refresh_attempted=no" not in html


def test_render_account_limits_html_keeps_reset_data_out_of_account_page() -> None:
    data = sample_account_limits_data()
    data.pop("codex_reset")
    data["codex"][0]["reset_history"] = [{
        "label": "Primary",
        "reset_at": "2026-08-18T09:00:00+08:00",
        "observed_at": "2026-08-12T13:30:00+08:00",
        "used_percent": 3,
    }]

    normalized = normalize_account_limits_data(data)
    html = render_account_limits_html(data)

    assert normalized["counts"]["codex_reset_events"] == 0
    assert "Codex 官方重置日历" not in html
    assert "官方重置记录暂不可用" not in html
    assert "账号窗口采样" not in html
    assert "<span class=\"day-number\">18</span>" not in html
