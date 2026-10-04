"""Synthetic, offline contracts for the read-only reset explanation API."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import importlib.util
import json

import pytest

from chatglance import codex_resets as resets

NOW = 1800000000.0
WEEK = 604800


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def policy(**updates):
    return resets.ResetPolicy(
        **{
            "enabled": True,
            "threshold_percent": 95,
            "min_remaining_seconds": 129600,
            "target_window_seconds": WEEK,
            "skip_if_forecast_24h_above": 70,
            **updates,
        }
    )


def snapshot():
    return {
        "profile": "example",
        "status": "ok",
        "observed_at": iso(NOW),
        "windows": [
            {
                "name": "secondary_window",
                "label": "Secondary",
                "window_seconds": WEEK,
                "used_percent": 95,
                "reset_at": iso(NOW + 172800),
                "reset_after_seconds": 172800,
            }
        ],
        "reset_credits": {"status": "ok", "available_count": 2, "checked_at": iso(NOW)},
        "auto_reset": {
            "status": "disabled",
            "eligible": False,
            "reason": "disabled",
            "last_action": None,
            "forecast": {
                "source": "https://codexreset.org/",
                "horizon": "24h",
                "status": "ok",
                "probability_24h_percent": 70,
                "source_updated_at": iso(NOW),
            },
        },
    }


def diagnose(account, configured=None, **kwargs):
    # Assert the missing interface as RED without a collection-time import error.
    assert importlib.util.find_spec("chatglance.reset_decisions") is not None, (
        "pure diagnostic API missing"
    )
    module = importlib.import_module("chatglance.reset_decisions")
    return module.diagnose_account(account, configured or policy(), now=NOW, **kwargs)


def checks(result):
    rows = result["checks"]
    assert len({row["key"] for row in rows}) == len(rows)
    for row in rows:
        assert set(row) == {"key", "label", "state", "value", "rule"}
        assert row["state"] in {"pass", "fail", "unknown", "inactive", "guarded"}
        assert row["label"] and row["rule"]
    return {row["key"]: row for row in rows}


@pytest.mark.parametrize(
    "enabled,execute", [(False, False), (False, True), (True, False), (True, True)]
)
def test_switches_are_independent_of_business_eligibility(enabled, execute):
    row = snapshot()
    result = diagnose(row, policy(enabled=enabled), execute_enabled=execute)
    assert set(result) == {
        "profile",
        "observed_at",
        "business_eligible",
        "automatic_allowed",
        "business_reason",
        "controls",
        "checks",
    }
    assert result["profile"] == "example"
    assert datetime.fromisoformat(result["observed_at"]).timestamp() == NOW
    assert result["business_eligible"] is True
    assert result["business_reason"] == "eligible"
    assert result["automatic_allowed"] is (enabled and execute)
    assert result["controls"] == {
        "account_enabled": enabled,
        "execute_enabled": execute,
    }
    assert set(checks(result)) == {
        "snapshot_freshness",
        "target_window",
        "used_percent",
        "remaining_seconds",
        "reset_credits",
        "forecast_freshness",
        "forecast_probability",
        "ledger",
    }
    assert all(check["state"] == "pass" for check in result["checks"])


@pytest.mark.parametrize(
    "change",
    [
        {"observed_at": iso(NOW - 1200.01)},
        {"observed_at": None},
        {"observed_at": "not-a-date"},
        {"observed_at": iso(NOW + 1)},
        {"stale": True},
        {"using_last_known_values": True},
        {"status": "partial"},
    ],
)
def test_stale_or_unusable_snapshot_is_unknown_and_fail_closed(change):
    row = snapshot()
    row.update(change)
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"] and not result["automatic_allowed"]
    assert result["business_reason"] == "query_failed_or_stale"
    states = checks(result)
    for key in (
        "snapshot_freshness",
        "target_window",
        "used_percent",
        "remaining_seconds",
        "reset_credits",
    ):
        assert states[key]["state"] == "unknown"


def test_exact_twenty_minute_boundary_is_usable_and_absolute_reset_is_recomputed():
    row = snapshot()
    row["observed_at"] = iso(NOW - 1200)
    row["windows"][0].update(reset_at=iso(NOW + 129600), reset_after_seconds=999999)
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"]
    assert result["business_reason"] == "conditions_not_met"
    assert checks(result)["snapshot_freshness"]["state"] == "pass"
    assert checks(result)["remaining_seconds"]["value"] == 129600
    assert checks(result)["remaining_seconds"]["state"] == "fail"


@pytest.mark.parametrize(
    "kind,reason",
    [("missing", "target_window_missing"), ("ambiguous", "target_window_ambiguous")],
)
def test_target_must_be_unique_before_usage_is_explained(kind, reason):
    row = snapshot()
    if kind == "missing":
        row["windows"][0]["window_seconds"] = 18000
    else:
        row["windows"].append(
            {**row["windows"][0], "name": "primary_window", "used_percent": 0}
        )
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"] and not result["automatic_allowed"]
    assert result["business_reason"] == reason
    states = checks(result)
    assert states["target_window"]["state"] == "fail"
    assert states["used_percent"]["state"] == "unknown"
    assert states["remaining_seconds"]["state"] == "unknown"


def test_legacy_normalized_minutes_match_the_same_weekly_window():
    row = snapshot()
    for window in row["windows"]:
        window["window_minutes"] = window.pop("window_seconds") / 60
    result = diagnose(row, execute_enabled=True)
    assert checks(result)["target_window"]["state"] == "pass"
    assert result["business_eligible"] is True


def test_duplicate_normalized_target_rows_cannot_be_silently_collapsed():
    row = snapshot()
    row["windows"].append(deepcopy(row["windows"][0]))
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"] and not result["automatic_allowed"]
    assert result["business_reason"] == "target_window_ambiguous"
    assert checks(result)["target_window"]["state"] == "fail"
    assert checks(result)["used_percent"]["state"] == "unknown"


@pytest.mark.parametrize(
    "key,value,check,state",
    [
        ("used_percent", 94.99, "used_percent", "fail"),
        ("used_percent", None, "used_percent", "unknown"),
        ("used_percent", float("nan"), "used_percent", "unknown"),
        ("used_percent", True, "used_percent", "unknown"),
        ("reset_at", None, "remaining_seconds", "unknown"),
    ],
)
def test_missing_or_below_threshold_measurements_are_explained(
    key, value, check, state
):
    row = snapshot()
    row["windows"][0][key] = value
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"] and not result["automatic_allowed"]
    assert checks(result)[check]["state"] == state
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "updates,state",
    [
        ({"available_count": 0}, "fail"),
        ({"available_count": True}, "unknown"),
        ({"available_count": None}, "unknown"),
        ({"status": "count_only"}, "unknown"),
        ({"stale": True}, "unknown"),
        ({"checked_at": iso(NOW - 1201)}, "unknown"),
    ],
)
def test_credit_count_must_be_known_and_fresh(updates, state):
    row = snapshot()
    row["reset_credits"].update(updates)
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"] and not result["automatic_allowed"]
    assert checks(result)["reset_credits"]["state"] == state


@pytest.mark.parametrize(
    "probability,age,state,reason",
    [
        (70, 7200, "pass", "eligible"),
        (70.01, 0, "fail", "forecast_above_threshold"),
        (20, 7200.01, "unknown", "forecast_unavailable"),
        (20, -1, "unknown", "forecast_unavailable"),
    ],
)
def test_forecast_preserves_two_hour_ttl_and_strict_probability_veto(
    probability, age, state, reason
):
    row = snapshot()
    row["auto_reset"]["forecast"].update(
        probability_24h_percent=probability, source_updated_at=iso(NOW - age)
    )
    result = diagnose(row, execute_enabled=True)
    assert result["business_reason"] == reason
    assert result["business_eligible"] is (reason == "eligible")
    states = checks(result)
    assert states["forecast_probability"]["state"] == state
    assert states["forecast_probability"]["value"] == probability
    assert states["forecast_freshness"]["state"] == (
        "unknown" if state == "unknown" else "pass"
    )


def test_unconfigured_forecast_is_inactive_not_a_pass():
    row = snapshot()
    row["auto_reset"]["forecast"] = None
    result = diagnose(row, policy(skip_if_forecast_24h_above=None))
    assert result["business_eligible"]
    assert checks(result)["forecast_freshness"]["state"] == "inactive"
    assert checks(result)["forecast_probability"]["state"] == "inactive"


@pytest.mark.parametrize(
    "status",
    [
        "pending",
        "uncertain",
        "blocked_pending",
        "cooldown",
        "already_processed",
        "state_error",
    ],
)
def test_known_ledger_guard_is_separate_from_business_rules(status):
    row = snapshot()
    row["auto_reset"]["status"] = status
    result = diagnose(row, execute_enabled=True)
    assert result["business_eligible"] and result["business_reason"] == "eligible"
    assert not result["automatic_allowed"]
    assert checks(result)["ledger"]["state"] == "guarded"
    assert status in checks(result)["ledger"]["value"]


@pytest.mark.parametrize(
    "status,age,blocked",
    [
        ("pending", 10000, True),
        ("uncertain", 10000, True),
        ("reset_verified", 3599, True),
        ("nothing_to_reset", 3599, True),
        ("no_credit", 3599, True),
        ("conditions_expired", 3599, True),
        ("reset_verified", 3600, False),
    ],
)
def test_last_action_cannot_hide_unresolved_or_recent_cooldown(status, age, blocked):
    row = snapshot()
    row["auto_reset"]["last_action"] = {"status": status, "at": iso(NOW - age)}
    result = diagnose(row, execute_enabled=True)
    assert result["business_eligible"]
    assert result["automatic_allowed"] is not blocked
    assert checks(result)["ledger"]["state"] == ("guarded" if blocked else "pass")


def test_missing_ledger_evidence_is_unknown_not_permission():
    row = snapshot()
    row["auto_reset"].pop("status")
    result = diagnose(row, execute_enabled=True)
    assert result["business_eligible"]
    assert not result["automatic_allowed"]
    assert checks(result)["ledger"]["state"] == "unknown"


@pytest.mark.parametrize(
    "window_names",
    [("primary_window", "secondary_window"), ("secondary_window", "primary_window")],
)
def test_legacy_window_selection_keeps_any_main_window_semantics(window_names):
    row = snapshot()
    row["windows"] = [
        {**row["windows"][0], "name": window_names[0], "used_percent": 0},
        {**row["windows"][0], "name": window_names[1]},
    ]
    result = diagnose(row, policy(target_window_seconds=None), execute_enabled=True)
    assert result["business_eligible"] and result["automatic_allowed"]
    assert checks(result)["target_window"]["state"] == "inactive"
    assert checks(result)["used_percent"]["value"] == 95


def test_additional_windows_are_not_main_quotas():
    row = snapshot()
    row["windows"][0]["name"] = "review_window"
    result = diagnose(row, execute_enabled=True)
    assert not result["business_eligible"]
    assert result["business_reason"] == "target_window_missing"


def test_normalized_snapshot_matches_core_and_cannot_carry_execution_side_effects(
    monkeypatch,
):
    row = snapshot()
    row["error"] = row["access_token"] = "DO_NOT_RENDER"
    row["auto_reset"]["forecast"]["raw_body"] = "DO_NOT_RENDER"
    row["windows"][0]["label"] = "DO_NOT_RENDER"
    original = deepcopy(row)

    def forbidden(*args, **kwargs):
        pytest.fail("diagnostics must not read/write state, query, or consume")

    for name in (
        "scan_profile",
        "_read_ledger",
        "_reserve",
        "_finish",
        "_consume_and_verify",
        "_ledger_path",
    ):
        monkeypatch.setattr(resets, name, forbidden)
    monkeypatch.setattr(resets.CodexClient, "from_profile", forbidden)
    configured = policy(enabled=False)
    result = diagnose(row, configured, execute_enabled=True)
    expected = resets.evaluate_policy(
        {
            "rate_limit": {
                "secondary_window": {
                    "used_percent": 95,
                    "reset_at": NOW + 172800,
                    "limit_window_seconds": WEEK,
                }
            }
        },
        {"available_count": 2},
        replace(configured, enabled=True),
        now=NOW,
        forecast=row["auto_reset"]["forecast"],
    )
    assert result["business_eligible"] == expected["eligible"]
    assert result["business_reason"] == expected["reason"]
    assert row == original
    assert "DO_NOT_RENDER" not in json.dumps(result, allow_nan=False)


def test_default_execute_is_off_and_default_clock_is_used(monkeypatch):
    diagnose(snapshot())  # Resolve the public API only after its RED assertion.
    module = importlib.import_module("chatglance.reset_decisions")
    monkeypatch.setattr(module.time, "time", lambda: NOW)
    result = module.diagnose_account(snapshot(), policy())
    assert result["business_eligible"]
    assert not result["automatic_allowed"]
    assert result["controls"]["execute_enabled"] is False
