#!/usr/bin/env python3
"""Collect Codex usage and banked reset details for ChatGlance.

Periodic scans use GET only unless both per-profile policy and real-execution
settings are enabled. No model request is made; ChatCRS owns OAuth refresh.
Policy/ledger decisions are made on fresh data before display-only stale fallbacks.
"""
from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from chatglance import __version__
from chatglance.codex_resets import ResetPolicy, parse_policies, scan_profile
from chatglance.codex_forecast import MAX_PUBLIC_BODY_BYTES, parse_public_forecast
from chatglance.config import collection_settings

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
            configured = os.environ.get("CHATGLANCE_ACCOUNT_LIMITS_MODELS", "").strip()
            models = json.loads(configured or "{}")
            if not isinstance(models, dict) or any(not isinstance(value, str) for value in models.values()):
                raise ValueError("CHATGLANCE_ACCOUNT_LIMITS_MODELS must map profile names to model strings")
            model = models.get(profile, "").strip()
            model_options = {"model": model} if model else {}
            payload = codex_direct.inspect_quota(
                profile=profile, refresh=refresh, timeout=timeout, **model_options
            )
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
        r'<div\s+[^>]*data-datetime="(?P<datetime>[^"]+)"[^>]*data-kind="(?P<kind>[^"]+)"[^>]*data-source-url="(?P<source_url>[^"]+)"[^>]*data-testid="reset-timeline-item"(?P<body>.*?)(?=<div\s+[^>]*data-datetime="[^"]+"[^>]*data-kind="[^"]+"[^>]*data-source-url="[^"]+"[^>]*data-testid="reset-timeline-item"|</section>)',
        re.S,
    )
    for match in item_pattern.finditer(page_html):
        body = match.group("body")
        if match.group("kind") != "confirmed":
            continue
        reset_dt = parse_datetime_utc(match.group("datetime"))
        if reset_dt is None:
            continue
        title_match = re.search(r"<h3[^>]*>(?P<title>.*?)</h3>", body, re.S)
        scope = ""
        source_label = ""
        for dt_html, dd_html in re.findall(r"<dt[^>]*>(.*?)</dt><dd[^>]*>(.*?)</dd>", body, re.S):
            label = strip_html(dt_html).lower().rstrip(":")
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
            raw = response.read(MAX_PUBLIC_BODY_BYTES + 1)
            if len(raw) > MAX_PUBLIC_BODY_BYTES:
                raise ValueError("Public source exceeds size limit")
            body = raw.decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return {"source": PUBLIC_RESET_SOURCE, "status": "error", "error": type(exc).__name__,
                "events": [], "forecast": parse_public_forecast("")}
    events = parse_public_reset_events(body)
    return {
        "source": PUBLIC_RESET_SOURCE,
        "status": "ok" if events else "empty",
        "confirmed_reset_count": len(events),
        "latest": events[0] if events else {},
        "events": events,
        "forecast": parse_public_forecast(body),
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


def profile_payload(profile: str, timeout: int, **options) -> dict[str, Any]:
    """Run only the package-owned GET scan and explicitly gated reset policy."""
    return scan_profile(profile, timeout=timeout, **options)


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


def apply_last_known_public_reset(
    current: dict[str, Any], history: Path | None, *, generated_at: str
) -> dict[str, Any]:
    """Retain confirmed public history on failure without making it look fresh."""
    result = deepcopy(current)
    if result.get("status") == "ok" and result.get("events"):
        result["using_last_known_values"] = False
        result["last_successful_at"] = generated_at
        return result
    if result.get("status") == "skipped" or history is None:
        return result
    try:
        snapshot = json.loads(history.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    if not isinstance(snapshot, dict):
        return result
    previous = snapshot.get("codex_reset")
    if not isinstance(previous, dict) or not (
        previous.get("status") == "ok" or previous.get("using_last_known_values") is True
    ):
        return result
    events = previous.get("events")
    if not isinstance(events, list) or not events or not all(isinstance(item, dict) for item in events):
        return result
    result.update(
        source=previous.get("source") or PUBLIC_RESET_SOURCE,
        events=deepcopy(events),
        latest=deepcopy(previous.get("latest") or events[0]),
        confirmed_reset_count=len(events),
        using_last_known_values=True,
        last_successful_at=previous.get("last_successful_at") or (
            snapshot.get("generated_at") if previous.get("status") == "ok" else None
        ),
    )
    return result


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


def _managed_client_options(settings: dict, profiles: list[str]) -> dict:
    """Choose one credential owner for the whole collection, never a fallback."""
    crs_profile = settings.get('crs_profile') or ''
    if not crs_profile:
        return {}
    if not isinstance(crs_profile, str) or not crs_profile.strip() or crs_profile != crs_profile.strip():
        raise ValueError('CRS profile must be an explicit nonempty name')

    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError('Duplicate CRS account mapping')
            values[key] = value
        return values

    try:
        accounts = json.loads(settings.get('crs_accounts') or '{}', object_pairs_hook=unique)
        if not isinstance(accounts, dict) or any(
            not isinstance(label, str) or not label or label != label.strip()
            or not isinstance(account, str) or not account or account != account.strip()
            for label, account in accounts.items()
        ) or any(label not in accounts for label in profiles):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('CRS account mapping must map every selected label to one nonempty account ID') from None

    def factory(label, *, home=None, timeout=20):
        # Import lazily: older released providers must not affect local mode.
        from chatcrs.managed_codex import CrsManagedCodexClient
        return CrsManagedCodexClient.from_profile(
            crs_profile, account_id=accounts[label], home=home, timeout=timeout,
            require_management_key=True,
        )

    return {'client_factory': factory, 'token_service': 'CRS'}


def collect_account_limits(*, profiles, output_path: str | Path, history_path: str | Path | None = None,
                           timeout: float = 20, reset_timeout: float = 20, no_public_reset: bool = False,
                           reset_policies: str | None = None, reset_base_url: str | None = None,
                           execute_resets: bool | None = None, home: str | Path | None = None) -> dict:
    """Collect fresh usage/credits and apply policy, then write the safe snapshot.

    This importable API is also used by the published CLI. No model smoke or
    package-local token refresh is performed; ChatCRS uses its standard token
    lifecycle. Last-known values are display-only.
    """
    settings = collection_settings(home=home)
    reset_policies = settings['reset_policies'] if reset_policies is None else reset_policies
    reset_base_url = settings['reset_base_url'] if reset_base_url is None else reset_base_url
    # A configured account's enabled flag is its only persistent permission.
    # Explicit False is a per-call inspection mode, not another account setting.
    execute_resets = True if execute_resets is None else execute_resets
    if type(execute_resets) is not bool:
        raise ValueError('execute_resets must be boolean')
    policies = parse_policies(reset_policies)
    profiles = parse_profiles(profiles if isinstance(profiles, str) else ' '.join(profiles))
    if not profiles:
        raise ValueError('At least one explicit Codex profile is required')
    client_options = _managed_client_options(settings, profiles)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    history = Path(history_path) if history_path is not None else None
    previous_profiles = load_previous_profiles(history)
    # Fetch fresh forecast before any account may authorize a consuming request.
    # History cache is still applied only after decisions and never supplies it.
    public_reset = ({'source': PUBLIC_RESET_SOURCE, 'status': 'skipped', 'events': [], 'forecast': None}
                    if no_public_reset else fetch_public_codex_reset(reset_timeout))
    payloads = [profile_payload(profile, timeout, policy=policies.get(profile, ResetPolicy()),
                execute=execute_resets, reset_base_url=reset_base_url or None, home=home,
                forecast=public_reset.get('forecast'), **client_options) for profile in profiles]
    apply_last_known_values(payloads, previous_profiles)
    merged_history = merge_history([event for item in payloads for event in item.get('reset_history', [])], load_history(history))
    for payload in payloads:
        payload['reset_history'] = [event for event in merged_history if event.get('profile') == payload['profile']]
    generated_at = iso_now()
    public_reset = apply_last_known_public_reset(public_reset, history, generated_at=generated_at)
    result = {'generated_at': generated_at, 'collector_version': __version__, 'refresh_status': refresh_status(payloads),
              'accounts': [], 'codex': payloads,
              'codex_reset': public_reset,
              'reset_control_path': settings.get('control_path', ''),
              'resources': [{'kind': 'codex', 'title': 'Codex account usage', 'profiles': profiles, 'sections': ['usage_cards','reset_calendar']}]}
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Collect Codex usage/reset cards without model requests.')
    parser.add_argument('--profiles', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--history', type=Path)
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('--reset-timeout', type=float, default=20)
    parser.add_argument('--no-public-reset', action='store_true')
    parser.add_argument('--fail-on-profile-error', action='store_true')
    parser.add_argument('--reset-policies')
    parser.add_argument('--reset-base-url')
    parser.add_argument('--execute-resets', action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args(argv)
    result = collect_account_limits(profiles=args.profiles, output_path=args.output, history_path=args.history,
              timeout=args.timeout, reset_timeout=args.reset_timeout, no_public_reset=args.no_public_reset,
              reset_policies=args.reset_policies, reset_base_url=args.reset_base_url, execute_resets=args.execute_resets)
    print(f"wrote {args.output} profiles={len(result['codex'])} version={__version__}")
    return 1 if args.fail_on_profile_error and result['refresh_status']['failed_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
