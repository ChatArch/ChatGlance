"""Build account/quota cards for the ChatArch Glance dashboard."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any

import yaml

ACCOUNT_LIMITS_PAGE_NAME = "账号额度"
LEGACY_ACCOUNT_LIMITS_PAGE_NAMES = {"Account Limits", "账号用量", "额度", "Codex 额度"}
DEFAULT_PAGE_SLUG = "account-limits"
DEFAULT_WIDGET_TITLE = "账号额度"

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


def text_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def html_text(value: Any, fallback: str = "—") -> str:
    return html.escape(text_value(value, fallback), quote=True)


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
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M %Z").strip()


def _reset_date(value: Any) -> str:
    formatted = _fmt_reset(value)
    if formatted == "—":
        return "—"
    return formatted.split()[0] if " " in formatted else formatted


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


def normalize_account_limits_data(data: dict[str, Any]) -> dict[str, Any]:
    safe = _strip_secrets(deepcopy(data))
    generated_at = text_value(safe.get("generated_at"))
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
    codex_reset_events = sum(
        len(item.get("reset_history") or []) for item in codex_profiles if isinstance(item.get("reset_history"), list)
    )
    return {
        "generated_at": generated_at,
        "accounts": accounts,
        "codex": codex_profiles,
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
    account_rows = []
    for account in normalized["accounts"]:
        usage = account.get("usage") or {}
        rate = account.get("rate_limit") if isinstance(account.get("rate_limit"), dict) else {}
        rate_text = "—"
        if rate:
            rate_text = f"{_fmt_number(rate.get('requests'))}/{_fmt_number(rate.get('window'))}"
        account_rows.append(
            f"""
<tr>
  <td><strong>{html_text(account.get('account_name'))}</strong><div class="limit-muted">{html_text(account.get('account_id'))}</div></td>
  <td>{html_text(_list_text(account.get('profiles')))}</td>
  <td>{html_text(_list_text(account.get('models')))}</td>
  <td>{html_text(rate_text)}</td>
  <td>{html_text(_fmt_number(usage.get('total_requests')))}</td>
  <td>{html_text(_fmt_number(usage.get('daily_requests')))}</td>
  <td>{html_text(_fmt_number(usage.get('monthly_requests')))}</td>
  <td>{html_text(_fmt_number(usage.get('total_all_tokens')))}</td>
</tr>"""
        )
    codex_cards = []
    reset_events = []
    for profile in normalized["codex"]:
        windows = profile.get("windows") if isinstance(profile.get("windows"), list) else []
        window_rows = []
        for window in windows:
            if not isinstance(window, dict):
                continue
            window_rows.append(
                f"""
<li><span>{html_text(window.get('label'))}</span><strong>{html_text(_fmt_percent(window.get('used_percent')))}</strong><em>重置 {html_text(_fmt_reset(window.get('reset_at')))}</em></li>"""
            )
        details = profile.get("details") if isinstance(profile.get("details"), list) else []
        detail_html = "".join(f"<p class=\"limit-muted\">{html_text(item)}</p>" for item in details)
        status_bits = [text_value(profile.get("status"))]
        if profile.get("error_type"):
            status_bits.append(text_value(profile.get("error_type")))
        status_text = " · ".join(bit for bit in status_bits if bit)
        status_html = f"<p class=\"limit-muted\">状态：{html_text(status_text)}</p>" if status_text else ""
        error_html = f"<p class=\"limit-muted\">{html_text(profile.get('error'))}</p>" if profile.get("error") else ""
        codex_cards.append(
            f"""
<article class="codex-limit-card">
  <h3>Codex · {html_text(profile.get('profile'), 'default')}</h3>
  <p>{html_text(profile.get('account_name') or profile.get('account_id'), '—')} · {html_text(profile.get('plan'), '—')}</p>
  <ul>{''.join(window_rows) or '<li>暂无 Codex window 数据</li>'}</ul>
  {status_html}
  {error_html}
  {detail_html}
</article>"""
        )
        history = profile.get("reset_history") if isinstance(profile.get("reset_history"), list) else []
        for event in history:
            if not isinstance(event, dict):
                continue
            reset_events.append({
                "profile": text_value(profile.get("profile"), "default"),
                "label": text_value(event.get("label"), "Reset"),
                "reset_at": event.get("reset_at"),
                "observed_at": event.get("observed_at"),
                "used_percent": event.get("used_percent"),
            })
    reset_events.sort(key=lambda item: text_value(item.get("reset_at")), reverse=True)
    reset_rows = []
    for event in reset_events[:30]:
        reset_rows.append(
            f"""
<li><time>{html_text(_reset_date(event.get('reset_at')))}</time><strong>{html_text(event.get('label'))}</strong><span>{html_text(event.get('profile'))}</span><em>{html_text(_fmt_percent(event.get('used_percent')))} used · observed {html_text(_fmt_reset(event.get('observed_at')))}</em></li>"""
        )
    return f"""
<style>
.limit-summary {{ margin-bottom: 0.8rem; color: var(--color-text-subdue); }}
.limit-table {{ width: 100%; border-collapse: collapse; font-size: 0.86rem; }}
.limit-table th, .limit-table td {{ border-bottom: 1px solid var(--color-separator); padding: 0.48rem 0.38rem; text-align: left; vertical-align: top; }}
.limit-muted {{ color: var(--color-text-subdue); font-size: 0.76rem; margin-top: 0.18rem; }}
.codex-limit-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0.8rem; margin-top: 1rem; }}
.codex-limit-card {{ border: 1px solid var(--color-separator); border-radius: 16px; padding: 0.8rem; background: var(--color-widget-background); }}
.codex-limit-card h3 {{ margin: 0 0 0.35rem; }}
.codex-limit-card ul {{ list-style: none; padding: 0; margin: 0.55rem 0; }}
.codex-limit-card li {{ display: grid; grid-template-columns: 1fr auto; gap: 0.45rem; border-top: 1px solid var(--color-separator); padding: 0.45rem 0; }}
.codex-limit-card li em {{ grid-column: 1 / -1; color: var(--color-text-subdue); font-style: normal; font-size: 0.78rem; }}
.codex-reset-calendar {{ margin-top: 1rem; }}
.codex-reset-calendar ul {{ list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 0.55rem; }}
.codex-reset-calendar li {{ border: 1px solid var(--color-separator); border-radius: 12px; padding: 0.55rem; display: grid; gap: 0.18rem; }}
.codex-reset-calendar time {{ color: var(--color-text-subdue); font-size: 0.78rem; }}
.codex-reset-calendar em {{ color: var(--color-text-subdue); font-style: normal; font-size: 0.76rem; }}
</style>
<div class="limit-summary">账号额度 · 最新整理：{html_text(normalized.get('generated_at'))} · CRS 账号 {counts['accounts']} 个 · Codex profile {counts['codex_profiles']} 个 · reset window {counts['codex_windows']} 个</div>
<table class="limit-table">
  <thead><tr><th>账号</th><th>Profiles</th><th>Models</th><th>Rate limit</th><th>Total req</th><th>Daily req</th><th>Monthly req</th><th>Total tokens</th></tr></thead>
  <tbody>{''.join(account_rows) or '<tr><td colspan="8">暂无 CRS account 数据。</td></tr>'}</tbody>
</table>
<div class="codex-limit-grid">{''.join(codex_cards) or '<p>暂无 Codex reset 数据。</p>'}</div>
<section class="codex-reset-calendar"><h2>Codex 重置日历</h2><ul>{''.join(reset_rows) or '<li>暂无历史 reset 记录；等待周期刷新脚本采样。</li>'}</ul></section>
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
