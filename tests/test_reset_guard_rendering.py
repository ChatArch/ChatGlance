"""The displayed quota must be the same explicit window used by policy."""

import html
import pytest
from chatglance.account_limits import _primary_window, render_account_limits_html
from chatglance.reset_control import render_control_page


def profile():
    return {
        "profile": "example",
        "account_name": "Example",
        "status": "ok",
        "credential_status": "valid",
        "windows": [
            {
                "name": "primary_window",
                "label": "Primary",
                "used_percent": 99,
                "window_seconds": 18000,
                "window_minutes": 300,
                "reset_at": "2027-01-15T14:00:00Z",
            },
            {
                "name": "secondary_window",
                "label": "Secondary",
                "used_percent": 12,
                "window_seconds": 604800,
                "window_minutes": 10080,
                "reset_at": "2027-01-20T14:00:00Z",
            },
        ],
        "reset_credits": {"status": "ok", "available_count": 2},
        "auto_reset": {
            "policy": {
                "enabled": True,
                "threshold_percent": 95,
                "min_remaining_seconds": 129600,
                "target_window_seconds": 604800,
                "skip_if_forecast_24h_above": 70,
            },
            "execute": False,
            "status": "conditions_not_met",
            "reason": "conditions_not_met",
            "forecast": {
                "status": "ok",
                "probability_24h_percent": 28,
                "source_updated_at": "2027-01-15T08:00:00Z",
            },
        },
    }


def render(row):
    return html.unescape(render_account_limits_html({"codex": [row]}))


def popup(row):
    auto = row['auto_reset']
    return render_control_page({
        'profile': row['profile'], 'controls': {'account_enabled': True, 'execute_enabled': False},
        'business_eligible': False, 'automatic_allowed': False, 'checks': [],
        'forecast': auto['forecast'], 'forecast_threshold': auto['policy']['skip_if_forecast_24h_above'],
    }, 'synthetic-nonce', 'synthetic-revision')


def test_explicit_weekly_card_uses_secondary_without_embedding_policy_controls():
    row = profile()
    assert _primary_window(row)["used_percent"] == 12
    text = render(row)
    assert "总额度（7天窗口）" in text
    assert "12%" in text
    assert ">99%" not in text
    assert "自然重置 >36小时" not in text
    assert "未来24小时重置预测" not in text
    assert "实验性概率" in popup(row) and "28%" in popup(row)
    assert "2027-01-20" in text
    assert "准确率" not in text


def test_missing_target_window_is_unknown_not_a_short_window_fallback():
    row = profile()
    row["windows"] = row["windows"][:1]
    row["auto_reset"]["reason"] = "target_window_missing"
    assert _primary_window(row) is None
    text = render(row)
    assert "总额度窗口未知（不用卡）" in text
    assert ">99%" not in text


def test_legacy_snapshot_minutes_can_identify_the_same_weekly_window():
    row = profile()
    for w in row["windows"]:
        w.pop("window_seconds")
    assert _primary_window(row)["used_percent"] == 12


def test_profiles_without_a_target_preserve_primary_display():
    row = profile()
    row["auto_reset"]["policy"].pop("target_window_seconds")
    assert _primary_window(row)["used_percent"] == 99


@pytest.mark.parametrize(
    "reason,label",
    [
        ("forecast_unavailable", "预测缺失或过期（不用卡）"),
        ("forecast_above_threshold", "预测即将重置（不用卡）"),
    ],
)
def test_veto_reason_is_visible_and_does_not_hide_unresolved_receipts(reason, label):
    row = profile()
    row["auto_reset"]["reason"] = reason
    row["auto_reset"]["forecast"]["status"] = "stale"
    assert label not in render(row)
    assert "预测不可用" in popup(row)
    row["auto_reset"]["status"] = "blocked_pending"
    assert "待人工核对（已阻止重试）" in render(row)


def test_ambiguous_weekly_card_does_not_choose_a_different_window_from_policy():
    row = profile()
    row["windows"][0].update(
        window_seconds=604800, window_minutes=10080, used_percent=0
    )
    row["auto_reset"]["reason"] = "target_window_ambiguous"
    assert _primary_window(row) is None
    assert "总额度窗口不明确（不用卡）" in render(row)


def test_prediction_is_a_visible_highlight_not_only_muted_text():
    row = profile()
    output = popup(row)
    assert '<aside class="reset-forecast is-clear"' in output
    assert "28%" in output and "不代表不会重置" in output
    row["auto_reset"]["forecast"]["probability_24h_percent"] = 91
    assert '<aside class="reset-forecast is-veto"' in popup(row)


def test_reset_information_is_collapsed_in_an_account_card():
    output=render_account_limits_html({'codex':[profile()], 'reset_control_path':'/_controls/'})
    assert '<details class="reset-card-panel">' in output
    assert '<summary>重置卡' in output
    assert '<details class="reset-card-panel" open' not in output
    assert 'reset-credit-details' in output and 'popovertarget=' in output


def test_policy_popover_is_explicitly_centered_despite_page_css_resets():
    output = render_account_limits_html({'codex': [profile()]})
    rules = output.split('.reset-policy-popover {', 1)[1].split('}', 1)[0]
    assert 'position:fixed;' in rules and 'inset:0;' in rules
    assert 'margin:auto;' in rules


def test_policy_popover_has_same_origin_frame_and_native_close():
    output = render_account_limits_html(
        {"codex": [profile()], "reset_control_path": "/_controls/"}
    )
    assert "popovertarget=" in output and "popover" in output
    assert 'popovertargetaction="hide"' in output
    assert "<iframe" in output and "/_controls/?profile=example" in output
    assert "自动用卡设置" in output


@pytest.mark.parametrize(
    "path",
    ["https://evil.example.invalid/", "//evil.example.invalid/", "/../", "/x?bad=1"],
)
def test_control_frame_never_points_to_an_external_or_unsafe_path(path):
    output = render_account_limits_html(
        {"codex": [profile()], "reset_control_path": path}
    )
    assert "<iframe" not in output
