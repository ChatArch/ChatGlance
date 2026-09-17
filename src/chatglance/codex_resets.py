"""Conservative, profile-scoped Codex reset policy and durable reservations.

ChatCRS owns credentials and HTTP. This module never refreshes OAuth, probes a
model, or retries a consume request. Only fresh GET data may authorize a reset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4

from chatenv import get_paths
from chatcrs.reset_credits import CodexResetClient as CodexClient
from chatglance.codex_forecast import forecast_snapshot

BJT = timezone(timedelta(hours=8))
COOLDOWN_SECONDS = 3600
UNRESOLVED = {"pending", "uncertain"}
KNOWN_NO_RESET = {"nothing_to_reset", "no_credit"}


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class ResetPolicy:
    enabled: bool = False
    threshold_percent: float = 95
    min_remaining_seconds: float = 86400
    target_window_seconds: float | None = None
    skip_if_forecast_24h_above: float | None = None

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if not _number(self.threshold_percent) or not 0 <= self.threshold_percent <= 100:
            raise ValueError("threshold_percent must be a finite number between 0 and 100")
        if not _number(self.min_remaining_seconds) or self.min_remaining_seconds < 0:
            raise ValueError("min_remaining_seconds must be a finite nonnegative number")
        if self.target_window_seconds is not None and (
                not _number(self.target_window_seconds) or self.target_window_seconds <= 0):
            raise ValueError("target_window_seconds must be a finite positive number or null")
        if self.skip_if_forecast_24h_above is not None and (
                not _number(self.skip_if_forecast_24h_above) or not 0 <= self.skip_if_forecast_24h_above <= 100):
            raise ValueError("skip_if_forecast_24h_above must be a finite number between 0 and 100 or null")


def parse_policies(text: str | None) -> dict[str, ResetPolicy]:
    """Strict JSON mapping of exact profile names to policies; no global enable."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate reset policy key")
            result[key] = value
        return result

    try:
        raw = json.loads(text or "{}", object_pairs_hook=unique)
        if not isinstance(raw, dict):
            raise ValueError
        result = {}
        for profile, policy in raw.items():
            if not profile.strip() or not isinstance(policy, dict):
                raise ValueError
            result[profile] = ResetPolicy(**policy)
        return result
    except (ValueError, TypeError):
        raise ValueError("Reset policies must map profile names to enabled, threshold_percent, min_remaining_seconds, target_window_seconds and skip_if_forecast_24h_above") from None


def _epoch(value: Any) -> float | None:
    if _number(value):
        try:
            datetime.fromtimestamp(value, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp() if dt.tzinfo is not None else None
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, BJT).isoformat(timespec="seconds") if epoch is not None else None


def _fresh(raw: Any) -> bool:
    return (isinstance(raw, dict) and not raw.get("stale") and not raw.get("using_last_known_values")
            and raw.get("ok") is not False and raw.get("status") in (None, "ok", 200))


def _count(raw: Any) -> int | None:
    value = raw.get("available_count") if _fresh(raw) else None
    return value if type(value) is int and value >= 0 else None


def _windows(raw: Any, now: float) -> list[dict[str, Any]]:
    limit = raw.get("rate_limit") if isinstance(raw, dict) else None
    if not isinstance(limit, dict):
        return []
    windows = []
    for name in ("primary_window", "secondary_window"):
        value = limit.get(name)
        if not isinstance(value, dict):
            continue
        used = value.get("used_percent")
        used = used if _number(used) and 0 <= used <= 100 else None
        reset = _epoch(value.get("reset_at"))
        duration = value.get("limit_window_seconds")
        windows.append({"name": name, "label": name.split("_")[0].title(), "used_percent": used,
                        "reset_at": _iso(reset), "reset_epoch": reset,
                        "reset_after_seconds": reset - now if reset is not None else None,
                        "window_seconds": duration if _number(duration) and duration > 0 else None,
                        "window_minutes": duration / 60 if _number(duration) and duration > 0 else None})
    return windows


def evaluate_policy(rawusage: dict, rawcredits: dict, policy: ResetPolicy, *, now: float,
                    forecast: dict | None = None) -> dict:
    """AND of main-window usage, actual absolute reset time, and available cards.

    Primary is not assumed to be the short window. Unanchored relative countdowns
    and additional/model/review limits are deliberately ineligible.
    """
    result = {"eligible": False, "reason": "disabled", "target": None,
              "forecast": forecast_snapshot(forecast, now=now)}
    if not policy.enabled:
        return result
    if not _number(now) or _epoch(now) is None or not _fresh(rawusage) or not _fresh(rawcredits):
        return {**result, "reason": "query_failed_or_stale"}
    count = _count(rawcredits)
    if count is None:
        return {**result, "reason": "credits_unknown"}
    if count == 0:
        return {**result, "reason": "no_credit"}
    if policy.skip_if_forecast_24h_above is not None:
        if result["forecast"]["status"] != "ok":
            return {**result, "reason": "forecast_unavailable"}
        if result["forecast"]["probability_24h_percent"] > policy.skip_if_forecast_24h_above:
            return {**result, "reason": "forecast_above_threshold"}
    windows = _windows(rawusage, now)
    if policy.target_window_seconds is not None:
        windows = [w for w in windows if w["window_seconds"] == policy.target_window_seconds]
        if not windows:
            return {**result, "reason": "target_window_missing"}
        if len(windows) > 1:
            return {**result, "reason": "target_window_ambiguous"}
    for window in windows:
        if (window["used_percent"] is not None and window["used_percent"] >= policy.threshold_percent
                and window["reset_after_seconds"] is not None
                and window["reset_after_seconds"] > policy.min_remaining_seconds):
            return {**result, "eligible": True, "reason": "eligible", "target": window}
    return {**result, "reason": "conditions_not_met"}


def _credits_summary(raw: Any, usage: Any, now: float) -> dict:
    count = _count(raw)
    status = "ok" if count is not None else "unknown"
    if count is None and isinstance(usage, dict):
        count = _count(usage.get("rate_limit_reset_credits"))
        if count is not None:
            status = "count_only"
    expiry = []
    rows = raw.get("credits") if isinstance(raw, dict) else None
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict) or item.get("status") != "available":
            continue
        timestamp = _epoch(item.get("expires_at"))
        if timestamp is not None and timestamp > now:
            expiry.append(timestamp)
    return {"status": status, "available_count": count,
            "next_expires_at": _iso(min(expiry)) if expiry else None,
            "checked_at": _iso(now)}


def _identity(client: Any) -> str:
    value = client.identity
    if not isinstance(value, str) or not value:
        raise ValueError("Missing account identity")
    # Always hash, including injected identities. Never emit a raw account id.
    return hashlib.sha256(value.encode()).hexdigest()


def _ledger_path(home: str | Path | None, state_dir: str | Path | None) -> Path:
    root = Path(state_dir) if state_dir is not None else get_paths(home).home_dir / "chatglance"
    return root / "codex-reset-ledger.sqlite3"


def _read_ledger(path: Path, identity: str) -> dict | None:
    if not path.exists():
        return None
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=20) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM reset_ledger WHERE identity=?", (identity,)).fetchone()
        return dict(row) if row else None


def _last_action(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {"status": row["status"], "at": _iso(row["updated_at"])}


def _block(row: dict | None, fingerprint: str, now: float) -> str | None:
    if not row:
        return None
    if row["status"] in UNRESOLVED:
        return "blocked_pending"
    if row["status"] not in KNOWN_NO_RESET | {"reset_verified", "conditions_expired"}:
        return "blocked_pending"
    if row["cooldown_until"] > now:
        return "cooldown"
    if row["status"] == "reset_verified" and row["fingerprint"] == fingerprint:
        return "already_processed"
    return None


def _reserve(path: Path, identity: str, fingerprint: str, now: float) -> tuple[str | None, dict]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise OSError("Ledger symlinks are not allowed")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    with sqlite3.connect(path, timeout=20) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS reset_ledger (
            identity TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL,
            fingerprint TEXT NOT NULL, updated_at REAL NOT NULL, cooldown_until REAL NOT NULL)""")
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM reset_ledger WHERE identity=?", (identity,)).fetchone()
        old = dict(old) if old else None
        blocked = _block(old, fingerprint, now)
        if blocked:
            return None, {"status": blocked, "last_action": _last_action(old)}
        request_id = str(uuid4())
        db.execute("INSERT OR REPLACE INTO reset_ledger VALUES (?,?,?,?,?,?)",
                   (identity, request_id, "pending", fingerprint, now, 0))
        # The commit is before POST and releases the DB lock; pending gates all
        # concurrent processes and aliases, even if this worker is then killed.
        db.commit()
        return request_id, {"status": "pending", "last_action": {"status": "pending", "at": _iso(now)}}


def _finish(path: Path, identity: str, request_id: str, status: str, now: float) -> None:
    with sqlite3.connect(path, timeout=20) as db:
        db.execute("PRAGMA synchronous=FULL")
        cursor = db.execute("UPDATE reset_ledger SET status=?,updated_at=?,cooldown_until=? WHERE identity=? AND request_id=?",
                            (status, now, now + COOLDOWN_SECONDS, identity, request_id))
        if cursor.rowcount != 1:
            raise RuntimeError("Missing reservation")


def scan_profile(profile: str, policy: ResetPolicy | None = None, *, execute: bool = False,
                 client: Any = None, home: str | Path | None = None,
                 state_dir: str | Path | None = None, now: float | None = None,
                 reset_base_url: str | None = None, timeout: float = 20,
                 forecast: dict | None = None) -> dict:
    """Return a redacted Glance row; execute requires both opt-in gates.

    Dry runs do not create state. Uncertain POSTs/readbacks stay blocked without
    expiry; there is intentionally no automatic retry or public clear button.
    """
    policy = policy if policy is not None else ResetPolicy()
    if type(execute) is not bool:
        raise ValueError("execute must be a boolean")
    clock = time.time if now is None else (lambda fixed=now: fixed)
    now = clock()
    if not _number(now) or _epoch(now) is None:
        raise ValueError("now must be a valid timestamp")
    auto = {"policy": asdict(policy), "execute": execute, "status": "disabled",
            "eligible": False, "reason": "disabled", "last_action": None,
            "forecast": forecast_snapshot(forecast, now=now)}
    row = {"profile": profile, "account_name": profile, "plan": "Codex", "status": "error",
           "credential_status": "probe_failed", "token_service": "Codex", "refresh_attempted": False,
           "observed_at": _iso(now), "windows": [], "reset_history": [], "auto_reset": auto,
           "reset_credits": _credits_summary(None, None, now)}
    try:
        client = client if client is not None else CodexClient.from_profile(
            profile, home=home, reset_base_url=reset_base_url, timeout=timeout)
        identity = _identity(client)
    except Exception:
        row.update(error_type="CodexProbeError", error="Codex 凭据配置不可用")
        auto.update(status="query_failed", reason="client_unavailable")
        return row
    row["account_id"] = "hash:" + identity[:12]
    rawusage, rawcredits = None, None
    for kind in ("usage", "reset_credits"):
        try:
            data = getattr(client, kind)()
            if kind == "usage":
                rawusage = data
            else:
                rawcredits = data
        except Exception as exc:
            if kind == "usage" and getattr(exc, "status", None) in (401, 403):
                row["credential_status"] = "invalid_or_expired"
    # Network latency must not be counted as remaining natural-reset time.
    now = clock()
    if not _number(now) or _epoch(now) is None:
        raise ValueError("now must be a valid timestamp")
    row["observed_at"] = _iso(now)
    usage_ok = _fresh(rawusage) and bool(_windows(rawusage, now))
    row["windows"] = _windows(rawusage, now)
    row["reset_credits"] = _credits_summary(rawcredits, rawusage, now)
    credits_ok = row["reset_credits"]["status"] == "ok"
    if usage_ok:
        row["credential_status"] = "valid"
    row["status"] = "ok" if usage_ok and credits_ok else "partial" if usage_ok else "error"
    if row["status"] != "ok":
        row.update(error_type="CodexProbeError", error="额度或重置卡详情查询失败 / 数据不完整")
    decision = evaluate_policy(rawusage, rawcredits, policy, now=now, forecast=forecast)
    auto.update(decision)
    auto["status"] = "disabled" if not policy.enabled else "conditions_not_met"
    if policy.enabled and row["status"] != "ok":
        auto["status"] = "query_failed"
    path = _ledger_path(home, state_dir)
    target = decision["target"]
    fingerprint = json.dumps([target["name"], target["reset_epoch"]]) if target else ""
    try:
        previous = _read_ledger(path, identity)
        auto["last_action"] = _last_action(previous)
        blocked = _block(previous, fingerprint, now)
        if blocked:
            auto["status"] = blocked
        elif decision["eligible"] and not execute:
            auto["status"] = "dry_run"
        elif decision["eligible"] and row["status"] == "ok" and execute:
            request_id, reservation = _reserve(path, identity, fingerprint, now)
            auto.update(reservation)
            if request_id:
                # The reservation can wait on another process. Recheck using
                # wall-clock time immediately before the only consuming call.
                post_now = clock()
                post_decision = evaluate_policy(rawusage, rawcredits, policy, now=post_now, forecast=forecast)
                auto.update(post_decision)
                if not post_decision["eligible"]:
                    _finish(path, identity, request_id, "conditions_expired", post_now)
                    auto.update(status="conditions_expired", last_action={"status": "conditions_expired", "at": _iso(post_now)})
                    row["windows"] = _windows(rawusage, post_now)
                else:
                    _consume_and_verify(client, rawusage, rawcredits, post_decision["target"], row, path, identity, request_id, post_now)
    except (OSError, sqlite3.Error, RuntimeError):
        # Never proceed when durable state is unavailable. If a POST happened,
        # its persisted pending row remains a fail-closed barrier.
        auto["status"] = "blocked_pending" if auto["status"] == "pending" else "state_error"
    row["reset_history"] = [{"profile": profile, "label": w["label"], "reset_at": w["reset_at"],
                              "observed_at": _iso(now), "used_percent": w["used_percent"]}
                             for w in row["windows"] if w["reset_at"]]
    return row


def _consume_and_verify(client, before_usage, before_credits, target, row, path, identity, request_id, now):
    status = "uncertain"
    try:
        result = client.consume(request_id, execute=True)
        # GET both after POST, even for non-reset outcomes. HTTP 200 alone
        # never proves consumption; arbitrary result text is never serialized.
        after_usage = client.usage()
        after_credits = client.reset_credits()
        after_windows = _windows(after_usage, now)
        after_count = _count(after_credits)
        if not _fresh(after_usage) or not after_windows or after_count is None:
            raise ValueError("Incomplete readback")
        row["windows"] = after_windows
        row["reset_credits"] = _credits_summary(after_credits, after_usage, now)
        code = result.get("code") if isinstance(result, dict) else None
        windows_reset = result.get("windows_reset") if isinstance(result, dict) else None
        after_target = next((w for w in after_windows if w["name"] == target["name"]), None)
        if (code == "reset" and type(windows_reset) is int and windows_reset > 0
                and after_target and after_target["used_percent"] is not None
                and after_target["used_percent"] < target["used_percent"]
                and after_count < _count(before_credits)):
            status = "reset_verified"
        elif code in KNOWN_NO_RESET:
            status = code
    except Exception:
        # Includes timeout, unknown server outcome, and failure to read back.
        # No retry, no replacement UUID, and no upstream exception text.
        pass
    _finish(path, identity, request_id, status, now)
    row["auto_reset"].update(status=status, last_action={"status": status, "at": _iso(now)})
