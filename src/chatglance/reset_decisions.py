"""Read-only explanations of normalized snapshots, never reset authorization.

Only ``scan_profile`` may execute using fresh GETs and its durable reservation.
This adapter does not query clients, read a ledger, mutate inputs, or predict
future usage. ``automatic_allowed`` describes the observed conditions only.
"""

from __future__ import annotations

from dataclasses import replace
import time

from chatglance.codex_forecast import FORECAST_TTL_SECONDS
from chatglance.codex_resets import (
    COOLDOWN_SECONDS,
    KNOWN_NO_RESET,
    UNRESOLVED,
    ResetPolicy,
    _count,
    _epoch,
    _fresh,
    _iso,
    _number,
    _windows,
    evaluate_policy,
)

SNAPSHOT_TTL_SECONDS = 1200
_MAIN_WINDOWS = ("primary_window", "secondary_window")
_GUARDED = UNRESOLVED | {
    "blocked_pending",
    "cooldown",
    "already_processed",
    "state_error",
    "reset_verified",
}
_CLEAR = KNOWN_NO_RESET | {
    "disabled",
    "conditions_not_met",
    "dry_run",
    "conditions_expired",
}


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _recent(value, now: float) -> bool:
    epoch = _epoch(value)
    return epoch is not None and 0 <= now - epoch <= SNAPSHOT_TTL_SECONDS


def _duration(window: dict):
    value = window.get("window_seconds")
    if value is None:
        minutes = window.get("window_minutes")
        value = minutes * 60 if _number(minutes) and minutes > 0 else None
    return value if _number(value) and value > 0 else None


def _snapshot_usage(account: dict, fresh: bool) -> dict:
    """Adapt only named main quotas; relative countdowns are not evidence."""
    limits = {}
    rows = account.get("windows")
    for window in rows if isinstance(rows, list) else []:
        window = _mapping(window)
        name = window.get("name")
        if name not in _MAIN_WINDOWS:
            continue
        if name in limits:
            # Malformed normalized rows must not silently overwrite a quota.
            fresh = False
        limits[name] = {
            "used_percent": window.get("used_percent"),
            "reset_at": window.get("reset_at"),
            "limit_window_seconds": _duration(window),
        }
    return {"ok": fresh, "rate_limit": limits}


def _ledger_check(auto: dict, *, fresh: bool, now: float) -> tuple[str, str]:
    status = auto.get("status")
    status = status if isinstance(status, str) else None
    if status in _GUARDED:
        return "guarded", status
    last = auto.get("last_action")
    if last is not None:
        last = _mapping(last)
        last_status = last.get("status")
        last_status = last_status if isinstance(last_status, str) else None
        if last_status in UNRESOLVED:
            return "guarded", last_status
        if last_status not in KNOWN_NO_RESET | {"reset_verified", "conditions_expired"}:
            return "unknown", "ledger_unknown"
        at = _epoch(last.get("at"))
        if at is None or at > now:
            return "unknown", "ledger_unknown"
        if now - at < COOLDOWN_SECONDS:
            return "guarded", "cooldown"
    if not fresh or status not in _CLEAR:
        return "unknown", "ledger_unknown"
    return "pass", "no_known_block"


def diagnose_account(
    account: dict,
    policy: ResetPolicy,
    *,
    execute_enabled: bool = False,
    now: float | None = None,
) -> dict:
    """Explain current business rules separately from manual execution switches.

    Checks have stable keys and JSON-safe scalar values (seconds/percent/counts
    are numbers, missing evidence is null). Unknown evidence is fail-closed.
    This result must never be fed into a consuming path or used to clear guards.
    """
    if type(execute_enabled) is not bool:
        raise ValueError("execute_enabled must be a boolean")
    now = time.time() if now is None else now
    if not _number(now) or _epoch(now) is None:
        raise ValueError("now must be a valid timestamp")
    account = _mapping(account)
    observed = _epoch(account.get("observed_at"))
    fresh = (
        account.get("status") == "ok"
        and _fresh(account)
        and _recent(account.get("observed_at"), now)
    )
    usage = _snapshot_usage(account, fresh)
    credits = _mapping(account.get("reset_credits"))
    credits_fresh = (
        fresh
        and credits.get("status") == "ok"
        and _fresh(credits)
        and _recent(credits.get("checked_at", account.get("observed_at")), now)
    )
    rawcredits = {
        "ok": credits_fresh,
        "available_count": credits.get("available_count"),
    }
    auto = _mapping(account.get("auto_reset"))
    business_policy = replace(policy, enabled=True)
    decision = evaluate_policy(
        usage, rawcredits, business_policy, now=now, forecast=auto.get("forecast")
    )
    forecast = decision["forecast"]

    raw_windows = account.get("windows")
    raw_matches = (
        [
            w
            for w in raw_windows
            if isinstance(w, dict)
            and w.get("name") in _MAIN_WINDOWS
            and _duration(w) == policy.target_window_seconds
        ]
        if isinstance(raw_windows, list)
        else []
    )
    ambiguous = policy.target_window_seconds is not None and len(raw_matches) > 1
    if ambiguous:
        decision.update(eligible=False, reason="target_window_ambiguous", target=None)

    windows = _windows(usage, now)
    candidates = (
        windows
        if policy.target_window_seconds is None
        else [
            window
            for window in windows
            if window["window_seconds"] == policy.target_window_seconds
        ]
    )
    selected = candidates[0] if len(candidates) == 1 and not ambiguous else None
    if policy.target_window_seconds is None and candidates:
        # Preserve legacy "any main window" semantics, but explain a single
        # window's conjunction, not usage from one and remaining time from another.
        selected = (
            evaluate_policy(
                usage,
                {"available_count": 1},
                replace(business_policy, skip_if_forecast_24h_above=None),
                now=now,
            )["target"]
            or candidates[0]
        )
    used = selected["used_percent"] if selected else None
    remaining = selected["reset_after_seconds"] if selected else None
    quota_fresh = fresh and usage["ok"]
    ledger_state, ledger_value = _ledger_check(auto, fresh=fresh, now=now)
    rows = []

    def add(key, label, state, value, rule):
        rows.append(
            {"key": key, "label": label, "state": state, "value": value, "rule": rule}
        )

    add(
        "snapshot_freshness",
        "数据新鲜度",
        "pass" if fresh else "unknown",
        now - observed if observed is not None else None,
        f"观察年龄须在 0–{SNAPSHOT_TTL_SECONDS} 秒（20 分钟）；源状态正常且非历史回填",
    )
    target_state = (
        "fail"
        if ambiguous
        else "unknown"
        if not quota_fresh
        else "inactive"
        if policy.target_window_seconds is None
        else "pass"
        if len(candidates) == 1
        else "fail"
    )
    target_rule = (
        "未配置目标时，任一主额度窗口须同时满足使用率与剩余时间条件"
        if policy.target_window_seconds is None
        else f"必须唯一匹配 {policy.target_window_seconds / 86400:g} 天的主额度窗口；不使用模型或审查限额"
    )
    add(
        "target_window",
        "目标额度窗口",
        target_state,
        selected["name"]
        if selected
        else f"matching_windows={len(raw_matches) if ambiguous else len(candidates)}",
        target_rule,
    )
    add(
        "used_percent",
        "当前使用率",
        "unknown"
        if not quota_fresh or used is None
        else "pass"
        if used >= policy.threshold_percent
        else "fail",
        used,
        f"同一目标窗口当前使用率 ≥ {policy.threshold_percent:g}%；不预测未来用量",
    )
    add(
        "remaining_seconds",
        "距自然重置",
        "unknown"
        if not quota_fresh or remaining is None
        else "pass"
        if remaining > policy.min_remaining_seconds
        else "fail",
        remaining,
        f"同一目标窗口距自然重置须 > {policy.min_remaining_seconds / 3600:g} 小时；不采用缓存倒计时",
    )
    count = _count({"available_count": credits.get("available_count")})
    add(
        "reset_credits",
        "可用重置卡",
        "unknown"
        if not credits_fresh or count is None
        else "pass"
        if count > 0
        else "fail",
        count,
        "卡详情查询正常、新鲜且可用卡数为正整数；仅有回退计数不能许可",
    )
    configured_forecast = policy.skip_if_forecast_24h_above is not None
    forecast_state = (
        "inactive"
        if not configured_forecast
        else "pass"
        if forecast["status"] == "ok"
        else "unknown"
    )
    add(
        "forecast_freshness",
        "预测更新时间",
        forecast_state,
        forecast["source_updated_at"],
        f"配置预测规则时来源、24h 周期及概率均须有效；更新时间不得来自未来或超过 {FORECAST_TTL_SECONDS} 秒（2 小时）",
    )
    probability = forecast["probability_24h_percent"]
    probability_state = forecast_state
    if forecast_state == "pass" and probability > policy.skip_if_forecast_24h_above:
        probability_state = "fail"
    add(
        "forecast_probability",
        "未来 24h 公开重置概率",
        probability_state,
        probability,
        "未配置预测否决规则"
        if not configured_forecast
        else f"概率 > {policy.skip_if_forecast_24h_above:g}% 时否决；这是公开预测概率，不是准确率或未来用量预测",
    )
    add(
        "ledger",
        "已有执行保护",
        ledger_state,
        ledger_value,
        f"未决请求、已处理窗口和状态异常均阻断；最近执行冷却 {COOLDOWN_SECONDS} 秒；快照不能解除保护",
    )
    return {
        "profile": account.get("profile")
        if isinstance(account.get("profile"), str)
        else "",
        "observed_at": _iso(observed),
        "business_eligible": decision["eligible"],
        "automatic_allowed": bool(
            decision["eligible"]
            and policy.enabled
            and execute_enabled
            and ledger_state == "pass"
        ),
        "business_reason": decision["reason"],
        "controls": {
            "account_enabled": policy.enabled,
            "execute_enabled": execute_enabled,
        },
        "checks": rows,
    }
