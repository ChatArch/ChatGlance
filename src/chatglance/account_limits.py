"""Build account/quota cards for the ChatArch Glance dashboard."""

from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import html
import json
import calendar
import re
from pathlib import Path
from typing import Any

import yaml

ACCOUNT_LIMITS_PAGE_NAME = "订阅详情"
LEGACY_ACCOUNT_LIMITS_PAGE_NAMES = {"Account Limits", "账号额度", "账号用量", "额度", "Codex 额度"}
DEFAULT_PAGE_SLUG = "account-limits"
DEFAULT_WIDGET_TITLE = "订阅详情"
BEIJING_TIMEZONE = timezone(timedelta(hours=8))

SECRET_KEYS = {
    "api_key",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "cookie",
    "authorization",
    "password",
    "secret",
}
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(access_token|refresh_token|id_token|authorization|cookie|api[_-]?key|proxy|password|secret)\s*[:=]\s*\S+",
    re.I,
)
BEARER_PATTERN = re.compile(r"Bearer\s+\S+", re.I)


def text_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def html_text(value: Any, fallback: str = "—") -> str:
    return html.escape(text_value(value, fallback), quote=True)


def _display_error(value: Any) -> str:
    text = text_value(value)
    text = BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = SECRET_ASSIGNMENT_PATTERN.sub("[redacted secret]", text)
    return text[:220]


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _fmt_number(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return "—"
    if isinstance(number, int):
        return f"{number:,}"
    return f"{number:,.1f}"


def _fmt_percent(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return "—"
    return f"{float(number):.1f}%"


def _fmt_reset(value: Any) -> str:
    text = text_value(value)
    if not text:
        return "—"
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(BEIJING_TIMEZONE)
    return local.strftime("%Y-%m-%d %H:%M").strip()


def _fmt_beijing_iso(value: Any) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        return text_value(value)
    return dt.replace(microsecond=0).isoformat()


def _reset_date(value: Any) -> str:
    formatted = _fmt_reset(value)
    if formatted == "—":
        return "—"
    return formatted.split()[0] if " " in formatted else formatted


def _parse_datetime(value: Any) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    # The public Codex reset tracker keeps Beijing time as
    # ``YYYY-MM-DD HH:MM:SS +0800``. Python 3.10's ``fromisoformat`` is stricter
    # than newer versions, so normalize both the separator and timezone offset.
    if " " in normalized and "T" not in normalized:
        parts = normalized.split()
        if len(parts) == 1:
            normalized = parts[0]
        elif len(parts) == 2:
            normalized = "T".join(parts)
        else:
            normalized = f"{parts[0]}T{parts[1]}{''.join(parts[2:])}"
    if len(normalized) >= 5 and normalized[-5] in "+-" and normalized[-2] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TIMEZONE)


def _list_text(values: Any) -> str:
    if isinstance(values, list):
        return ", ".join(text_value(value) for value in values if text_value(value)) or "—"
    return text_value(values, "—")


def _usage_value(account: dict[str, Any], key: str) -> Any:
    usage = account.get("usage") if isinstance(account.get("usage"), dict) else {}
    if key in usage:
        return usage.get(key)
    if key == "total_requests":
        if "requests_total" in account:
            return account.get("requests_total")
        return (usage.get("total") or {}).get("requests") if isinstance(usage.get("total"), dict) else None
    if key == "daily_requests":
        if "requests_daily" in account:
            return account.get("requests_daily")
        return (usage.get("daily") or {}).get("requests") if isinstance(usage.get("daily"), dict) else None
    if key == "monthly_requests":
        if "requests_monthly" in account:
            return account.get("requests_monthly")
        return (usage.get("monthly") or {}).get("requests") if isinstance(usage.get("monthly"), dict) else None
    if key == "total_all_tokens":
        if "all_tokens_total" in account:
            return account.get("all_tokens_total")
        if "tokens_used" in account:
            return account.get("tokens_used")
        return (usage.get("total") or {}).get("allTokens") if isinstance(usage.get("total"), dict) else None
    return None


def _is_secret_key(key: Any) -> bool:
    lowered = str(key or "").strip().lower().replace("-", "_")
    return lowered in SECRET_KEYS or lowered.endswith("_token") or lowered.endswith("_key") or "cookie" in lowered


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_secrets(item) for key, item in value.items() if not _is_secret_key(key)}
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


def _account_id(account: dict[str, Any]) -> str:
    return text_value(account.get("account_id") or account.get("id"))


def _account_name(account: dict[str, Any]) -> str:
    return text_value(account.get("account_name") or account.get("name"), "unknown")


def _normalize_text_list(value: Any, fallback_value: Any = None) -> list[str]:
    candidates = value if isinstance(value, list) else [fallback_value if value is None else value]
    return [text_value(item) for item in candidates if text_value(item)]


def _normalize_account_entry(account: dict[str, Any]) -> dict[str, Any]:
    usage = {
        "total_requests": _usage_value(account, "total_requests"),
        "daily_requests": _usage_value(account, "daily_requests"),
        "monthly_requests": _usage_value(account, "monthly_requests"),
        "total_all_tokens": _usage_value(account, "total_all_tokens"),
    }
    return {
        "account_id": _account_id(account),
        "account_name": _account_name(account),
        "profiles": _normalize_text_list(account.get("profiles"), account.get("profile")),
        "models": _normalize_text_list(account.get("models"), account.get("model")),
        "permissions": account.get("permissions") if isinstance(account.get("permissions"), list) else [],
        "rate_limit": account.get("rate_limit") if isinstance(account.get("rate_limit"), dict) else {},
        "usage": usage,
        "source": text_value(account.get("source"), "crs-key-info"),
    }


def _merge_unique_list(existing: list[str], values: list[str]) -> list[str]:
    merged = list(existing)
    for value in values:
        if value and value not in merged:
            merged.append(value)
    return merged


def _merge_account(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["profiles"] = _merge_unique_list(existing.get("profiles", []), incoming.get("profiles", []))
    existing["models"] = _merge_unique_list(existing.get("models", []), incoming.get("models", []))
    existing["permissions"] = _merge_unique_list(existing.get("permissions", []), incoming.get("permissions", []))
    existing_usage = existing.setdefault("usage", {})
    for key, value in incoming.get("usage", {}).items():
        current = _safe_number(existing_usage.get(key))
        candidate = _safe_number(value)
        if candidate is not None and (current is None or candidate > current):
            existing_usage[key] = candidate
    if not existing.get("rate_limit") and incoming.get("rate_limit"):
        existing["rate_limit"] = incoming.get("rate_limit")


def _normalize_public_reset_event(event: dict[str, Any]) -> dict[str, Any] | None:
    reset_at = event.get("time_bjt") or event.get("date_bjt") or event.get("time_utc") or event.get("reset_at")
    if not reset_at:
        return None
    return {
        "kind": "official",
        "label": text_value(event.get("scope"), "Official reset"),
        "reset_at": reset_at,
        "date_bjt": text_value(event.get("date_bjt")),
        "time_bjt": text_value(event.get("time_bjt")),
        "event_id": text_value(event.get("event_id")),
        "source_url": text_value(event.get("source_url")),
        "source": text_value(event.get("source"), "codexreset.org"),
    }


def _normalize_account_reset_event(profile: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    reset_at = event.get("reset_at")
    if not reset_at:
        return None
    return {
        "kind": "account-window",
        "profile": text_value(profile.get("profile"), "default"),
        "label": text_value(event.get("label"), "账号窗口采样"),
        "reset_at": reset_at,
        "observed_at": event.get("observed_at"),
        "used_percent": event.get("used_percent"),
        "source": "账号窗口采样",
    }


def _normalize_codex_reset(safe: dict[str, Any], codex_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    raw_reset = safe.get("codex_reset") if isinstance(safe.get("codex_reset"), dict) else {}
    source = text_value(raw_reset.get("source"), "账号窗口采样") if isinstance(raw_reset, dict) else "账号窗口采样"
    status = text_value(raw_reset.get("status"), "ok") if isinstance(raw_reset, dict) else "ok"
    raw_events = raw_reset.get("events") if isinstance(raw_reset, dict) and isinstance(raw_reset.get("events"), list) else []
    events: list[dict[str, Any]] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        event = _normalize_public_reset_event(raw_event)
        if event is not None:
            events.append(event)

    used_fallback = False
    if not events:
        used_fallback = True
        source = "账号窗口采样"
        for profile in codex_profiles:
            history = profile.get("reset_history") if isinstance(profile.get("reset_history"), list) else []
            for raw_event in history:
                if not isinstance(raw_event, dict):
                    continue
                event = _normalize_account_reset_event(profile, raw_event)
                if event is not None:
                    events.append(event)

    events.sort(key=lambda item: text_value(item.get("reset_at")), reverse=True)
    latest = events[0] if events else raw_reset.get("latest") if isinstance(raw_reset, dict) and isinstance(raw_reset.get("latest"), dict) else {}
    return {
        "source": source,
        "status": status,
        "latest": latest,
        "events": events,
        "used_fallback": used_fallback,
        "confirmed_reset_count": raw_reset.get("confirmed_reset_count", len(events)) if isinstance(raw_reset, dict) else len(events),
    }


def _safe_http_url(value: Any) -> str:
    text = text_value(value)
    if text.startswith(("https://", "http://")):
        return text
    return ""


def _progress_percent(value: Any) -> float | None:
    number = _safe_number(value)
    if number is None:
        return None
    return max(0.0, min(100.0, float(number)))


def _profile_probe_status(profile: dict[str, Any]) -> str:
    status = text_value(profile.get("status"), "ok")
    if status == "ok":
        return "valid"
    explicit = text_value(profile.get("credential_status"))
    if explicit:
        return explicit
    error_text = text_value(profile.get("error")).lower()
    if "401" in error_text or "oauth refresh failed" in error_text or "unauthorized" in error_text:
        return "invalid_or_expired"
    if "credential" in error_text:
        return "missing"
    return "probe_failed"


def _status_label(value: str) -> str:
    labels = {
        "valid": "有效",
        "invalid_or_expired": "已失效 / 需重新登录",
        "missing": "缺少凭据",
        "probe_failed": "请求失败",
        "ok": "正常",
        "partial": "部分失败",
        "error": "失败",
    }
    return labels.get(value, value or "未知")


def _refresh_status(safe: dict[str, Any], codex_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    raw = safe.get("refresh_status") if isinstance(safe.get("refresh_status"), dict) else {}
    failed = raw.get("failed_profiles") if isinstance(raw.get("failed_profiles"), list) else []
    ok_profiles = raw.get("ok_profiles") if isinstance(raw.get("ok_profiles"), list) else []
    if not raw:
        failed = [text_value(item.get("profile")) for item in codex_profiles if text_value(item.get("status"), "ok") != "ok"]
        ok_profiles = [text_value(item.get("profile")) for item in codex_profiles if text_value(item.get("status"), "ok") == "ok"]
    failed = [text_value(item) for item in failed if text_value(item)]
    ok_profiles = [text_value(item) for item in ok_profiles if text_value(item)]
    total = int(raw.get("profiles_total") or len(codex_profiles) or len(failed) + len(ok_profiles))
    status = text_value(raw.get("status"), "")
    if not status:
        status = "ok" if not failed else "error" if not ok_profiles else "partial"
    failures: list[dict[str, str]] = []
    by_profile = {text_value(item.get("profile")): item for item in codex_profiles}
    for profile in failed:
        item = by_profile.get(profile, {})
        failures.append(
            {
                "profile": profile,
                "credential_status": _profile_probe_status(item),
                "error_type": text_value(item.get("error_type")),
                "error": _display_error(item.get("error")),
                "last_successful_at": text_value(item.get("last_successful_at")),
                "using_last_known_values": "yes" if item.get("using_last_known_values") else "",
            }
        )
    return {
        "status": status,
        "profiles_total": total,
        "ok_count": int(raw.get("ok_count") or len(ok_profiles)),
        "failed_count": int(raw.get("failed_count") or len(failed)),
        "ok_profiles": ok_profiles,
        "failed_profiles": failed,
        "failures": failures,
    }


def _primary_window(profile: dict[str, Any]) -> dict[str, Any] | None:
    windows = profile.get("windows") if isinstance(profile.get("windows"), list) else []
    candidates = [window for window in windows if isinstance(window, dict)]
    for window in candidates:
        if text_value(window.get("label")).lower() == "primary":
            return window
    return candidates[0] if candidates else None


def _render_reset_calendar(
    reset_events: list[dict[str, Any]],
    reference_month: tuple[int, int] | None = None,
) -> str:
    parsed_events: list[tuple[datetime, dict[str, Any]]] = []
    for event in reset_events:
        dt = _parse_datetime(event.get("reset_at"))
        if dt is not None:
            parsed_events.append((dt, event))
    if not parsed_events:
        return '<div class="codex-calendar-card"><p class="limit-muted">暂无 reset 记录。</p></div>'

    events_by_month_day: dict[tuple[int, int], dict[int, list[tuple[datetime, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
    for dt, event in parsed_events:
        events_by_month_day[(dt.year, dt.month)][dt.day].append((dt, event))

    # Keep the UI as a real Calendar: one visible month at a time, with compact
    # month options for looking back through recent reset history. Always offer
    # the reference (latest refresh) month first so the switcher automatically
    # gains new months as time passes, even before any reset event has been
    # confirmed in them yet.
    if reference_month is None:
        now = datetime.now(BEIJING_TIMEZONE)
        reference_month = (now.year, now.month)
    month_keys = sorted(events_by_month_day.keys(), reverse=True)
    if reference_month not in month_keys:
        month_keys.insert(0, reference_month)
    month_keys = month_keys[:4]
    radios: list[str] = []
    options: list[str] = []
    month_panels: list[str] = []
    switch_rules: list[str] = []
    for index, (year, month) in enumerate(month_keys):
        month_id = f"codex-reset-month-{index}"
        month_class = f"codex-reset-month-panel-{index}"
        active_attr = " checked" if index == 0 else ""
        label = f"{year} 年 {month:02d} 月"
        radios.append(
            f'<input class="codex-calendar-radio" type="radio" name="codex-reset-month" id="{month_id}"{active_attr}>'
        )
        options.append(f'<label class="codex-calendar-option" for="{month_id}">{html_text(label)}</label>')
        switch_rules.append(
            f"#{month_id}:checked ~ .codex-calendar-panels .codex-calendar-month {{ display: none; }}\n"
            f"#{month_id}:checked ~ .codex-calendar-panels .{month_class} {{ display: block; }}\n"
            f"#{month_id}:checked ~ .codex-calendar-month-switcher label {{ background: transparent; color: var(--color-text-subdue); border-color: var(--color-separator); }}\n"
            f"#{month_id}:checked ~ .codex-calendar-month-switcher label[for='{month_id}'] {{ background: var(--color-primary); color: var(--color-widget-background); border-color: var(--color-primary); }}"
        )
        days = events_by_month_day[(year, month)]
        cal = calendar.Calendar(firstweekday=0)
        cells: list[str] = []
        for day in cal.itermonthdays(year, month):
            if day == 0:
                cells.append('<div class="codex-reset-day is-empty"></div>')
                continue
            events = days.get(day, [])
            if events:
                labels = ", ".join(
                    text_value(event.get("label") or event.get("source"), "Reset")
                    for _, event in events[:3]
                )
                title = html_text(labels, "Reset")
                cells.append(
                    f'<div class="codex-reset-day is-reset" title="{title}"><span class="day-number">{day}</span></div>'
                )
            else:
                cells.append(f'<div class="codex-reset-day"><span class="day-number">{day}</span></div>')
        month_panels.append(
            f"""
<article class="codex-calendar-month {month_class}">
  <div class="codex-calendar-heading"><h3>{html_text(label)}</h3><span>{len(days)} 次 reset</span></div>
  <div class="codex-reset-weekdays"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
  <div class="codex-reset-grid">{''.join(cells)}</div>
</article>"""
        )
    return f"""
<div class="codex-calendar-card">
  <style>{''.join(switch_rules)}</style>
  {''.join(radios)}
  <div class="codex-calendar-month-switcher" aria-label="选择 reset 月份">{''.join(options)}</div>
  <div class="codex-calendar-panels">{''.join(month_panels)}</div>
</div>"""


def normalize_account_limits_data(data: dict[str, Any]) -> dict[str, Any]:
    safe = _strip_secrets(deepcopy(data))
    generated_at = _fmt_beijing_iso(safe.get("generated_at"))
    accounts: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    raw_accounts: list[Any] = []
    for key in ("accounts", "rows"):
        values = safe.get(key)
        if isinstance(values, list):
            raw_accounts.extend(values)
    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue
        account = _normalize_account_entry(raw)
        key = account["account_id"] or account["account_name"]
        if key in by_key:
            _merge_account(by_key[key], account)
        else:
            by_key[key] = account
            accounts.append(account)
    codex_profiles = [item for item in safe.get("codex", []) if isinstance(item, dict)]
    codex_windows = sum(len(item.get("windows") or []) for item in codex_profiles if isinstance(item.get("windows"), list))
    codex_reset = _normalize_codex_reset(safe, codex_profiles)
    codex_reset_events = len(codex_reset["events"])
    return {
        "generated_at": generated_at,
        "accounts": accounts,
        "codex": codex_profiles,
        "codex_reset": codex_reset,
        "refresh_status": _refresh_status(safe, codex_profiles),
        "counts": {
            "accounts": len(accounts),
            "codex_profiles": len(codex_profiles),
            "codex_windows": codex_windows,
            "codex_reset_events": codex_reset_events,
        },
    }


def load_account_limits_data(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("account-limits JSON must be an object")
    return normalize_account_limits_data(payload)


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def render_account_limits_html(data: dict[str, Any]) -> str:
    normalized = normalize_account_limits_data(data)
    counts = normalized["counts"]

    codex_cards = []
    for profile in normalized["codex"]:
        primary = _primary_window(profile)
        used_percent = _fmt_percent(primary.get("used_percent")) if primary else "—"
        reset_time = _fmt_reset(primary.get("reset_at")) if primary else "—"
        progress_value = _progress_percent(primary.get("used_percent")) if primary else None
        progress_width = f"{progress_value:.1f}%" if progress_value is not None else "0%"
        status = text_value(profile.get("status"))
        credential = _profile_probe_status(profile)
        error_bits = []
        if status and status != "ok":
            error_bits.append(status)
        if profile.get("error_type"):
            error_bits.append(text_value(profile.get("error_type")))
        error_label = " · ".join(bit for bit in error_bits if bit)
        error_html = ""
        if credential != "valid":
            error_html += f'<p class="limit-status-line">凭据状态：{html_text(_status_label(credential))}</p>'
        if profile.get("using_last_known_values"):
            last_success = _fmt_beijing_iso(profile.get("last_successful_at")) or text_value(profile.get("last_successful_at"))
            if last_success:
                error_html += f'<p class="limit-status-line">保留上次成功值：{html_text(last_success)}</p>'
        if error_label:
            error_html += f'<p class="limit-muted">状态：{html_text(error_label)}</p>'
        if profile.get("error"):
            error_html += f'<p class="limit-muted">{html_text(_display_error(profile.get("error")))}</p>'
        codex_cards.append(
            f"""
<article class="codex-account-card site-style-card">
  <div class="codex-account-card-body">
    <div class="codex-account-card-head"><h3>{html_text(profile.get('account_name') or profile.get('profile'), 'default')}</h3></div>
    <div class="usage-row"><span>使用额度</span><strong>{html_text(used_percent)}</strong></div>
    <div class="limit-progress" aria-label="使用额度 {html_text(used_percent)}"><span style="width: {html_text(progress_width)}"></span></div>
    <div class="reset-row"><span>重置时间</span><strong>{html_text(reset_time)}</strong></div>
    {error_html}
  </div>
</article>"""
        )

    codex_reset = normalized["codex_reset"]
    reset_events = codex_reset["events"]
    reference_dt = _parse_datetime(normalized.get("generated_at"))
    reference_month = (reference_dt.year, reference_dt.month) if reference_dt is not None else None
    reset_calendar = _render_reset_calendar(reset_events, reference_month=reference_month)
    reset_source = text_value(codex_reset.get("source"), "账号窗口采样")
    source_label = "codexreset.org" if "codexreset.org" in reset_source else reset_source
    source_url = _safe_http_url(reset_source)
    source_html = f'<a href="{html_text(source_url)}">{html_text(source_label)}</a>' if source_url else "未知来源"
    latest = codex_reset.get("latest") if isinstance(codex_reset.get("latest"), dict) else {}
    latest_time = text_value(latest.get("time_bjt") or latest.get("date_bjt") or latest.get("time_utc"))
    reset_intro_parts = [f"来源：{source_html}"]
    if latest_time:
        reset_intro_parts.append(f"最新：{html_text(latest_time)}")
    if codex_reset.get("used_fallback"):
        reset_intro_parts.append("账号窗口采样")
    reset_intro = " · ".join(reset_intro_parts)
    refresh_status = normalized["refresh_status"]
    status_class = text_value(refresh_status.get("status"), "ok")
    failure_lines = []
    for failure in refresh_status.get("failures", []):
        if not isinstance(failure, dict):
            continue
        label_bits = [text_value(failure.get("profile")), _status_label(text_value(failure.get("credential_status")))]
        if failure.get("error_type"):
            label_bits.append(text_value(failure.get("error_type")))
        if failure.get("using_last_known_values"):
            last_success = _fmt_beijing_iso(failure.get("last_successful_at")) or text_value(failure.get("last_successful_at"))
            if last_success:
                label_bits.append(f"保留上次成功值 {last_success}")
        if failure.get("error"):
            label_bits.append(text_value(failure.get("error")))
        failure_lines.append(" · ".join(bit for bit in label_bits if bit))
    status_summary = (
        f"采集状态：{_status_label(status_class)} · 成功 {refresh_status.get('ok_count')}/{refresh_status.get('profiles_total')}"
        f" · 失败 {refresh_status.get('failed_count')}"
    )
    status_details = "；".join(failure_lines)
    status_banner = ""
    if status_class != "ok" or status_details:
        status_banner = (
            f'<div class="limit-status-banner is-{html_text(status_class)}">'
            f'<strong>{html_text(status_summary)}</strong>'
            f'{f"<span>{html_text(status_details)}</span>" if status_details else ""}'
            '</div>'
        )

    return f"""
<style>
.limit-summary {{ margin-bottom: 0.8rem; color: var(--color-text-subdue); }}
.limit-muted {{ color: var(--color-text-subdue); font-size: 0.76rem; margin-top: 0.18rem; }}
.limit-status-banner {{ display: flex; flex-direction: column; gap: 0.25rem; border: 1px solid var(--color-separator); border-radius: 14px; padding: 0.62rem 0.75rem; margin-bottom: 0.8rem; background: color-mix(in srgb, var(--color-negative) 9%, var(--color-widget-background)); }}
.limit-status-banner strong {{ font-size: 0.86rem; }}
.limit-status-banner span, .limit-status-line {{ color: var(--color-text-subdue); font-size: 0.76rem; }}
.limit-status-line {{ margin-top: 0.18rem; }}
.account-limits-resource-layout {{ display: grid; grid-template-columns: minmax(250px, 0.86fr) minmax(360px, 1.35fr); gap: 0.9rem; align-items: start; }}
.codex-reset-panel, .codex-accounts-panel {{ border: 1px solid var(--color-separator); border-radius: 18px; padding: 0.85rem; background: var(--color-widget-background); box-shadow: 0 8px 28px rgba(15,23,42,0.08); }}
.codex-reset-panel h2, .codex-accounts-panel h2 {{ margin: 0 0 0.45rem; font-size: 1rem; }}
.codex-calendar-card {{ border: 1px solid var(--color-separator); border-radius: 18px; margin-top: 0.65rem; padding: 0.7rem; background: color-mix(in srgb, var(--color-widget-background) 94%, var(--color-primary) 6%); overflow: hidden; }}
.codex-calendar-radio {{ position: absolute; inline-size: 1px; block-size: 1px; opacity: 0; pointer-events: none; }}
.codex-calendar-month-switcher {{ display: flex; gap: 0.35rem; overflow-x: auto; padding-bottom: 0.45rem; margin-bottom: 0.45rem; }}
.codex-calendar-option {{ flex: 0 0 auto; border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.24rem 0.58rem; font-size: 0.72rem; color: var(--color-text-subdue); cursor: pointer; user-select: none; }}
.codex-calendar-option.is-active {{ background: var(--color-primary); color: var(--color-widget-background); border-color: var(--color-primary); }}
.codex-calendar-month {{ display: none; }}
.codex-calendar-month:first-child {{ display: block; }}
.codex-calendar-heading {{ display: flex; justify-content: space-between; gap: 0.7rem; align-items: center; margin-bottom: 0.45rem; }}
.codex-calendar-heading h3 {{ margin: 0; font-size: 0.92rem; }}
.codex-calendar-heading span {{ color: var(--color-text-subdue); font-size: 0.72rem; }}
.codex-reset-weekdays, .codex-reset-grid {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 0.14rem; }}
.codex-reset-weekdays span {{ color: var(--color-text-subdue); font-size: 0.62rem; text-align: center; }}
.codex-reset-day {{ min-height: 1.55rem; border-radius: 9px; display: grid; place-items: center; color: var(--color-text-subdue); font-size: 0.7rem; }}
.codex-reset-day.is-reset {{ border: 1px solid var(--color-primary); color: var(--color-text-base); font-weight: 700; background: color-mix(in srgb, var(--color-primary) 16%, transparent); }}
.codex-reset-day.is-empty {{ visibility: hidden; }}
.codex-account-card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(235px, 1fr)); gap: 0.85rem; }}
.codex-account-card.site-style-card {{ border: 1px solid var(--color-separator); border-radius: 18px; overflow: hidden; background: var(--color-widget-background); box-shadow: 0 8px 28px rgba(15,23,42,0.08); display: flex; flex-direction: column; }}
.codex-account-card-body {{ padding: 0.82rem; display: flex; flex-direction: column; flex: 1; }}
.codex-account-card-head {{ display: flex; justify-content: space-between; gap: 0.6rem; align-items: flex-start; }}
.codex-account-card h3 {{ margin: 0 0 0.7rem; font-size: 1.05rem; }}
.usage-row, .reset-row {{ display: flex; justify-content: space-between; gap: 0.8rem; align-items: baseline; }}
.usage-row span, .reset-row span {{ color: var(--color-text-subdue); font-size: 0.78rem; }}
.limit-progress {{ height: 0.56rem; border-radius: 999px; overflow: hidden; margin: 0.5rem 0 0.65rem; background: color-mix(in srgb, var(--color-text-subdue) 18%, transparent); }}
.limit-progress span {{ display: block; height: 100%; border-radius: inherit; background: var(--color-primary); }}
@media (max-width: 720px) {{ .account-limits-resource-layout {{ grid-template-columns: 1fr; }} }}
</style>
<div class="limit-summary">订阅详情 · 最新整理：{html_text(normalized.get('generated_at'))} · Codex 账号 {counts['codex_profiles']} 个</div>
{status_banner}
<div class="account-limits-resource-layout">
  <section class="codex-reset-panel"><h2>Codex 官方重置日历</h2><p class="limit-muted">{reset_intro}</p>{reset_calendar}</section>
  <section class="codex-accounts-panel"><h2>账号使用额度</h2><div class="codex-account-card-grid">{''.join(codex_cards) or '<p>暂无 Codex 账号数据。</p>'}</div></section>
</div>
"""


def build_account_limits_page(
    data: dict[str, Any],
    *,
    page_name: str = ACCOUNT_LIMITS_PAGE_NAME,
    page_slug: str = DEFAULT_PAGE_SLUG,
    widget_title: str = DEFAULT_WIDGET_TITLE,
) -> dict[str, Any]:
    return {
        "name": page_name,
        "slug": page_slug,
        "width": "wide",
        "columns": [
            {
                "size": "full",
                "widgets": [
                    {"type": "html", "title": widget_title, "source": render_account_limits_html(data)}
                ],
            }
        ],
    }


def replace_account_limits_page(
    config: dict[str, Any],
    data: dict[str, Any],
    *,
    page_name: str = ACCOUNT_LIMITS_PAGE_NAME,
    page_slug: str = DEFAULT_PAGE_SLUG,
    widget_title: str = DEFAULT_WIDGET_TITLE,
) -> dict[str, Any]:
    updated = deepcopy(config)
    pages = updated.setdefault("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    legacy = set(LEGACY_ACCOUNT_LIMITS_PAGE_NAMES) | {page_name}
    pages[:] = [page for page in pages if not (isinstance(page, dict) and (page.get("name") in legacy or page.get("slug") == page_slug))]
    new_page = build_account_limits_page(data, page_name=page_name, page_slug=page_slug, widget_title=widget_title)
    insert_after = None
    for index, page in enumerate(pages):
        if isinstance(page, dict) and (page.get("slug") == "sites" or page.get("name") == "网站服务"):
            insert_after = index
    if insert_after is None:
        for index, page in enumerate(pages):
            if isinstance(page, dict) and (page.get("slug") == "servers" or page.get("name") == "服务器"):
                insert_after = index
    if insert_after is None:
        pages.append(new_page)
    else:
        pages.insert(insert_after + 1, new_page)
    return updated
