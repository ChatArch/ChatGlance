#!/usr/bin/env python3
"""Collect Codex account usage data for ChatGlance account-limits pages.

This helper is intentionally conservative:
- Uses ChatCRS' importable Python API rather than reading token files directly
  or shelling back into a CLI.
- First tries stored access tokens with --no-refresh.
- If usage/quota fails or quota headers are missing, refreshes once through
  ChatCRS/ChatEnv and retries.
- Emits only Glance-ready JSON without raw access tokens, refresh tokens, id
  tokens, emails, user ids, or account ids.
"""
from __future__ import annotations

import argparse
import html
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EXPECTED_QUOTA_KEYS = {
    "primary_used_percent",
    "primary_reset_after_seconds",
    "primary_window_minutes",
    "secondary_used_percent",
    "secondary_reset_after_seconds",
    "secondary_window_minutes",
    "primary_over_secondary_percent",
}

PUBLIC_RESET_SOURCE = "https://codexreset.org/"
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


def short_hash(value: Any) -> str:
    if value in (None, ""):
        return ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def call_chatcrs_api(
    operation: str,
    *,
    profile: str,
    refresh: bool,
    timeout: int,
    codex_direct: Any | None = None,
) -> dict[str, Any]:
    """Call the ChatCRS Python API and normalize it to collector result shape."""

    try:
        if codex_direct is None:
            from chatcrs import codex_direct as codex_direct_module

            codex_direct = codex_direct_module
        if operation == "usage":
            payload = codex_direct.inspect_usage(profile=profile, refresh=refresh, timeout=timeout)
        elif operation == "quota":
            payload = codex_direct.inspect_quota(profile=profile, refresh=refresh, timeout=timeout)
        else:
            raise ValueError(f"unsupported ChatCRS Codex operation: {operation}")
    except Exception as exc:  # noqa: BLE001 - collector must publish redacted failure status.
        return {
            "ok": False,
            "exit_code": 1,
            "json": {},
            "stderr": f"{type(exc).__name__}: {redact_text(str(exc))}",
        }
    ok = bool(isinstance(payload, dict) and payload.get("ok"))
    return {
        "ok": ok,
        "exit_code": 0 if ok else 1,
        "json": payload if isinstance(payload, dict) else {},
        "stderr": "" if ok else f"ChatCRS {operation} failed: status={payload.get('status') if isinstance(payload, dict) else 'unknown'}",
    }


def rate_limits(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get("rate_limits") or payload.get("quota_headers")
    return value if isinstance(value, dict) else {}


def headers_present(payload: Any) -> bool:
    limits = rate_limits(payload)
    return any(limits.get(key) is not None for key in EXPECTED_QUOTA_KEYS)


def needs_refresh(usage: dict[str, Any], quota: dict[str, Any]) -> bool:
    usage_json = usage.get("json")
    quota_json = quota.get("json")
    if not usage.get("ok") or not quota.get("ok"):
        return True
    if isinstance(usage_json, dict) and usage_json.get("status") not in (None, 200):
        return True
    if isinstance(quota_json, dict) and quota_json.get("status") not in (None, 200):
        return True
    return not headers_present(quota_json)


def request_bundle(profile: str, refresh: bool, timeout: int) -> tuple[dict[str, Any], dict[str, Any]]:
    usage = call_chatcrs_api("usage", profile=profile, refresh=refresh, timeout=timeout)
    quota = call_chatcrs_api("quota", profile=profile, refresh=refresh, timeout=timeout)
    return usage, quota


def iso_from_epoch(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(BEIJING_TIMEZONE).replace(microsecond=0).isoformat()


def iso_now() -> str:
    return datetime.now(BEIJING_TIMEZONE).replace(microsecond=0).isoformat()


def parse_datetime_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def extract_attr(fragment: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}="([^"]*)"', fragment)
    return html.unescape(match.group(1)) if match else ""


def parse_public_reset_events(page_html: str) -> list[dict[str, Any]]:
    """Parse confirmed Codex reset events from codexreset.org static HTML."""

    events: list[dict[str, Any]] = []
    item_pattern = re.compile(
        r'<div class="w-72[^>]*data-datetime="(?P<datetime>[^"]+)"[^>]*data-kind="(?P<kind>[^"]+)"[^>]*data-source-url="(?P<source_url>[^"]+)"[^>]*data-testid="reset-timeline-item"(?P<body>.*?)(?=<div class="w-72[^>]*data-datetime=|</div></div></div></div></section>)',
        re.S,
    )
    for match in item_pattern.finditer(page_html):
        body = match.group("body")
        if match.group("kind") != "confirmed" or "Confirmed reset" not in body:
            continue
        reset_dt = parse_datetime_utc(match.group("datetime"))
        if reset_dt is None:
            continue
        title_match = re.search(r"<h3[^>]*>(?P<title>.*?)</h3>", body, re.S)
        scope = ""
        source_label = ""
        for dt_html, dd_html in re.findall(r"<dt[^>]*>(.*?)</dt><dd[^>]*>(.*?)</dd>", body, re.S):
            label = strip_html(dt_html).lower()
            if label == "scope":
                scope = strip_html(dd_html)
            elif label == "source":
                source_label = strip_html(dd_html)
        bjt = reset_dt.astimezone(timezone(timedelta(hours=8)))
        source_url = safe_url(html.unescape(match.group("source_url")))
        status_id = ""
        status_match = re.search(r"/status/(\d+)", source_url)
        if status_match:
            status_id = status_match.group(1)
        events.append(
            {
                "event_id": status_id or short_hash(source_url + reset_dt.isoformat()),
                "title": strip_html(title_match.group("title")) if title_match else "Confirmed Codex reset",
                "scope": scope,
                "source": source_label or "codexreset.org",
                "source_url": source_url,
                "time_utc": reset_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "time_bjt": bjt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S +0800"),
                "date_bjt": bjt.strftime("%Y-%m-%d"),
            }
        )
    events.sort(key=lambda item: str(item.get("time_utc") or ""), reverse=True)
    return events


def fetch_public_codex_reset(timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        PUBLIC_RESET_SOURCE,
        headers={
            "User-Agent": "Mozilla/5.0 ChatGlance codex reset refresh",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(1_000_000).decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as exc:
        return {"source": PUBLIC_RESET_SOURCE, "status": "error", "error": type(exc).__name__, "events": []}
    events = parse_public_reset_events(body)
    return {
        "source": PUBLIC_RESET_SOURCE,
        "status": "ok" if events else "empty",
        "confirmed_reset_count": len(events),
        "latest": events[0] if events else {},
        "events": events,
    }


SECRET_PATTERN = re.compile(
    r"(access_token|refresh_token|id_token|authorization|cookie|api[_-]?key|proxy|password|secret)"
    r"(\s*[:=]\s*)([^\s]+)",
    re.I,
)
BEARER_PATTERN = re.compile(r"Bearer\s+[^\s]+", re.I)
PROXY_AUTH_PATTERN = re.compile(r"(https?://)[^\s/@:]+:[^\s/@]+@", re.I)


def safe_url(value: Any) -> str:
    text = str(value or "").strip()
    return text if text.startswith(("https://", "http://")) else ""


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = PROXY_AUTH_PATTERN.sub(r"\1[REDACTED]@", text)
    text = BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    return text


def safe_error(result: dict[str, Any]) -> str:
    text = redact_text(result.get("stderr") or "").strip()
    if not text:
        return ""
    return text[:300]


def credential_status(error_text: str, *, ok: bool) -> str:
    """Return a non-secret credential/probe status for dashboard display."""

    if ok:
        return "valid"
    lowered = error_text.lower()
    if "401" in lowered or "oauth refresh failed" in lowered or "unauthorized" in lowered:
        return "invalid_or_expired"
    if "no codex credentials" in lowered or "credentials" in lowered:
        return "missing"
    return "probe_failed"


def usage_window(profile: str, usage_payload: Any, quota_payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    windows: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    usage_limit = usage_payload.get("rate_limit") if isinstance(usage_payload, dict) else {}
    primary = usage_limit.get("primary_window") if isinstance(usage_limit, dict) else None
    secondary = usage_limit.get("secondary_window") if isinstance(usage_limit, dict) else None
    quota_limits = rate_limits(quota_payload)
    observed_at = iso_now()

    def add_window(label: str, window: dict[str, Any] | None, fallback_prefix: str) -> None:
        if not isinstance(window, dict):
            used = quota_limits.get(f"{fallback_prefix}_used_percent")
            reset_after = quota_limits.get(f"{fallback_prefix}_reset_after_seconds")
            window_minutes = quota_limits.get(f"{fallback_prefix}_window_minutes")
            if used is None and reset_after is None and window_minutes in (None, 0, 0.0):
                return
            reset_at = ""
            if reset_after not in (None, ""):
                try:
                    reset_at = datetime.fromtimestamp(
                        datetime.now(timezone.utc).timestamp() + float(reset_after),
                        tz=timezone.utc,
                    ).astimezone(BEIJING_TIMEZONE).replace(microsecond=0).isoformat()
                except (TypeError, ValueError):
                    reset_at = ""
            entry = {
                "label": label,
                "used_percent": used,
                "reset_at": reset_at,
                "reset_after_seconds": reset_after,
                "window_minutes": window_minutes,
            }
        else:
            entry = {
                "label": label,
                "used_percent": window.get("used_percent"),
                "reset_at": iso_from_epoch(window.get("reset_at")),
                "reset_after_seconds": window.get("reset_after_seconds"),
                "window_minutes": (window.get("limit_window_seconds") / 60 if isinstance(window.get("limit_window_seconds"), (int, float)) else None),
            }
        windows.append(entry)
        if entry.get("reset_at"):
            history.append({
                "profile": profile,
                "label": label,
                "reset_at": entry.get("reset_at"),
                "observed_at": observed_at,
                "used_percent": entry.get("used_percent"),
            })

    add_window("Primary", primary, "primary")
    add_window("Secondary", secondary, "secondary")
    return windows, history


def profile_payload(profile: str, timeout: int) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    usage, quota = request_bundle(profile, refresh=False, timeout=timeout)
    attempts.append({"mode": "no_refresh", "usage_ok": usage.get("ok"), "quota_ok": quota.get("ok")})
    refreshed = False
    if needs_refresh(usage, quota):
        refreshed = True
        usage, quota = request_bundle(profile, refresh=True, timeout=timeout)
        attempts.append({"mode": "refresh_once", "usage_ok": usage.get("ok"), "quota_ok": quota.get("ok")})

    usage_json = usage.get("json") if isinstance(usage.get("json"), dict) else {}
    quota_json = quota.get("json") if isinstance(quota.get("json"), dict) else {}
    ok = bool(usage.get("ok") and quota.get("ok") and usage_json.get("status") == 200 and quota_json.get("status") == 200)
    limits = rate_limits(quota_json) or rate_limits(usage_json)
    windows, history = usage_window(profile, usage_json, quota_json)
    details = [
        f"usage_status={usage_json.get('status', '—')}",
        f"quota_status={quota_json.get('status', '—')}",
        f"quota_headers={'yes' if headers_present(quota_json) else 'no'}",
        f"refresh_attempted={'yes' if refreshed else 'no'}",
    ]
    error_text = ""
    if not ok:
        error_text = safe_error(usage) or safe_error(quota) or "Codex usage/quota probe failed"
    payload = {
        "profile": profile,
        "account_id": f"hash:{short_hash(usage_json.get('account_id') or quota_json.get('account_id') or profile)}",
        "account_name": profile,
        "plan": usage_json.get("plan") or usage_json.get("account_plan") or "Codex",
        "status": "ok" if ok else "error",
        "credential_status": credential_status(error_text, ok=ok),
        "token_service": usage_json.get("token_service") or quota_json.get("token_service") or "Codex",
        "windows": windows,
        "reset_history": history,
        "details": details,
        "usage_status": usage_json.get("status"),
        "quota_status": quota_json.get("status"),
        "quota_headers_present": headers_present(quota_json),
        "refresh_attempted": refreshed,
        "rate_limits": limits,
    }
    if not ok:
        payload["error_type"] = "CodexProbeError"
        payload["error"] = error_text
    return payload


def refresh_status(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize profile probe results without exposing credential values."""

    failed = [str(item.get("profile")) for item in payloads if item.get("status") != "ok"]
    ok_profiles = [str(item.get("profile")) for item in payloads if item.get("status") == "ok"]
    status = "ok" if not failed else "error" if not ok_profiles else "partial"
    return {
        "status": status,
        "profiles_total": len(payloads),
        "ok_count": len(ok_profiles),
        "failed_count": len(failed),
        "ok_profiles": ok_profiles,
        "failed_profiles": failed,
        "message": "all profiles refreshed" if status == "ok" else f"failed_profiles={','.join(failed)}",
    }


def parse_profiles(text: str) -> list[str]:
    values = [item.strip() for item in text.replace(",", " ").split() if item.strip()]
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def load_history(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    history: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for profile in payload.get("codex", []):
            if isinstance(profile, dict) and isinstance(profile.get("reset_history"), list):
                history.extend(item for item in profile["reset_history"] if isinstance(item, dict))
    return history


def load_previous_profiles(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    generated_at = payload.get("generated_at")
    profiles: dict[str, dict[str, Any]] = {}
    for item in payload.get("codex", []):
        if not isinstance(item, dict):
            continue
        profile = str(item.get("profile") or "").strip()
        if not profile:
            continue
        previous = dict(item)
        previous["_previous_generated_at"] = generated_at
        profiles[profile] = previous
    return profiles


def apply_last_known_values(current: list[dict[str, Any]], previous: dict[str, dict[str, Any]]) -> None:
    """Keep last successful values visible while marking current failure."""

    for payload in current:
        if payload.get("status") == "ok":
            continue
        profile = str(payload.get("profile") or "")
        previous_payload = previous.get(profile)
        if not previous_payload:
            continue
        windows = previous_payload.get("windows") if isinstance(previous_payload.get("windows"), list) else []
        if windows and not payload.get("windows"):
            payload["windows"] = windows
        for key in ("account_id", "account_name", "plan", "rate_limits"):
            if previous_payload.get(key) not in (None, "", [], {}) and payload.get(key) in (None, "", [], {}):
                payload[key] = previous_payload.get(key)
        last_successful_at = previous_payload.get("last_successful_at")
        if not last_successful_at and previous_payload.get("status") == "ok":
            last_successful_at = previous_payload.get("_previous_generated_at")
        if windows or last_successful_at:
            payload["using_last_known_values"] = True
        if last_successful_at:
            payload["last_successful_at"] = last_successful_at


def merge_history(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in [*current, *previous]:
        key = (str(item.get("profile", "")), str(item.get("label", "")), str(item.get("reset_at", "")))
        if key in seen or not key[2]:
            continue
        seen.add(key)
        merged.append(item)
    merged.sort(key=lambda item: str(item.get("reset_at", "")), reverse=True)
    return merged[:120]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default="73-wzh allis lookeng yifei", help="Space/comma-separated ChatEnv Codex profile names")
    parser.add_argument("--output", type=Path, required=True, help="Glance account-limits JSON output path")
    parser.add_argument("--history", type=Path, help="Previous account-limits JSON whose reset history should be merged")
    parser.add_argument("--timeout", type=int, default=60, help="Per ChatCRS command timeout in seconds")
    parser.add_argument("--reset-timeout", type=int, default=25, help="Public codexreset.org fetch timeout in seconds")
    parser.add_argument("--no-public-reset", action="store_true", help="Skip public codexreset.org reset timeline fetch")
    parser.add_argument("--fail-on-profile-error", action="store_true", help="Exit non-zero when any profile probe fails after writing JSON.")
    args = parser.parse_args(argv)

    profiles = parse_profiles(args.profiles)
    previous_history = load_history(args.history)
    previous_profiles = load_previous_profiles(args.history)
    current_payloads = [profile_payload(profile, args.timeout) for profile in profiles]
    apply_last_known_values(current_payloads, previous_profiles)
    current_history: list[dict[str, Any]] = []
    for payload in current_payloads:
        history = payload.get("reset_history") if isinstance(payload.get("reset_history"), list) else []
        current_history.extend(item for item in history if isinstance(item, dict))
    merged_history = merge_history(current_history, previous_history)
    by_profile = {profile: [] for profile in profiles}
    for event in merged_history:
        profile = str(event.get("profile", ""))
        if profile in by_profile:
            by_profile[profile].append(event)
    for payload in current_payloads:
        payload["reset_history"] = by_profile.get(str(payload.get("profile")), [])

    result = {
        "generated_at": iso_now(),
        "refresh_status": refresh_status(current_payloads),
        "accounts": [],
        "codex": current_payloads,
        "codex_reset": {"source": PUBLIC_RESET_SOURCE, "status": "skipped", "events": []}
        if args.no_public_reset
        else fetch_public_codex_reset(args.reset_timeout),
        "resources": [
            {
                "kind": "codex",
                "title": "Codex account usage",
                "profiles": profiles,
                "sections": ["usage_cards", "reset_calendar"],
            }
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output} profiles={len(profiles)} codex={len(current_payloads)}")
    failures = [item.get("profile") for item in current_payloads if item.get("status") != "ok"]
    if failures:
        print("failed_profiles=" + ",".join(str(item) for item in failures), file=sys.stderr)
        return 1 if args.fail_on_profile_error else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
