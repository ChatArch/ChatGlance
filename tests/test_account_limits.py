from __future__ import annotations

import yaml

from chatglance.account_limits import (
    ACCOUNT_LIMITS_PAGE_NAME,
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
                        "label": "Session",
                        "used_percent": 12.5,
                        "reset_at": "2026-08-12T18:30:00+08:00",
                        "window_minutes": 300,
                    },
                    {
                        "label": "Weekly",
                        "used_percent": 3,
                        "reset_at": "2026-08-18T09:00:00+08:00",
                        "window_minutes": 10080,
                    },
                ],
                "details": ["Credits balance: unlimited"],
            }
        ],
        "secrets": {
            "api_key": "sk-should-not-render",
            "access_token": "access-secret",
            "cookie": "session-secret",
        },
    }


def test_normalize_account_limits_dedupes_crs_accounts_and_counts_codex_windows() -> None:
    normalized = normalize_account_limits_data(sample_account_limits_data())

    assert normalized["counts"] == {"accounts": 2, "codex_profiles": 1, "codex_windows": 2}
    wzh = normalized["accounts"][0]
    assert wzh["account_name"] == "wzh"
    assert wzh["profiles"] == ["default", "wzh"]
    assert wzh["models"] == ["gpt-5.5"]


def test_render_account_limits_html_shows_current_usage_and_reset_dates_without_secrets() -> None:
    html = render_account_limits_html(sample_account_limits_data())

    assert "账号额度" in html
    assert "CRS 账号 2 个" in html
    assert "wzh" in html
    assert "default, wzh" in html
    assert "1,786" in html
    assert "64,963" in html
    assert "Codex" in html
    assert "Session" in html
    assert "12.5%" in html
    assert "2026-08-12 18:30" in html
    assert "Weekly" in html
    assert "2026-08-18 09:00" in html
    assert "sk-should-not-render" not in html
    assert "access-secret" not in html
    assert "session-secret" not in html


def test_build_account_limits_page_creates_wide_html_page() -> None:
    page = build_account_limits_page(sample_account_limits_data())

    assert page["name"] == ACCOUNT_LIMITS_PAGE_NAME
    assert page["slug"] == "account-limits"
    assert page["width"] == "wide"
    assert page["columns"][0]["widgets"][0]["type"] == "html"
    assert page["columns"][0]["widgets"][0]["title"] == "账号额度"


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

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目", "服务器", "网站服务", "账号额度"]
    assert updated["pages"][-1]["slug"] == "account-limits"
    assert config["pages"][-1]["old"] is True
    rendered = yaml.safe_dump(updated, allow_unicode=True, sort_keys=False)
    assert "default, wzh" in rendered
    assert "gpt-5.5" in rendered
    assert "sk-should-not-render" not in rendered


def test_render_account_limits_html_is_idempotent_for_normalized_data() -> None:
    normalized = normalize_account_limits_data(sample_account_limits_data())

    html = render_account_limits_html(normalized)

    assert "default, wzh" in html
    assert "gpt-5.5" in html
    assert "2026-08-18 09:00" in html


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

    assert normalized["counts"] == {"accounts": 1, "codex_profiles": 1, "codex_windows": 0}
    assert normalized["accounts"][0]["profiles"] == ["default", "wzh"]
    assert normalized["accounts"][0]["usage"]["total_requests"] == 1786
    assert normalized["accounts"][0]["usage"]["total_all_tokens"] == 200671051
    assert "No Codex credentials stored" in html
    assert "AuthError" in html
