"""Explicit CRS account tracking backed by named ChatEnv profiles.

A subscription selects an existing credential profile; it never issues credentials
or discovers accounts. Removed entries retain their binding to fence label reuse.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from typing import Any

from chatenv import EnvStore, get_paths
from chatenv.tokens import normalize_token_profile
from .config import ChatGlanceConfig

SUBSCRIPTIONS = "CHATGLANCE_ACCOUNT_LIMITS_SUBSCRIPTIONS"
POLICIES = "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES"
LEGACY_PROFILES = "CHATGLANCE_ACCOUNT_LIMITS_PROFILES"
LEGACY_CRS = "CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE"
LEGACY_ACCOUNTS = "CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate subscription configuration key")
        result[key] = value
    return result


def _identifier(value):
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Invalid subscription identifier")
    return value


def _profile(value):
    if (not isinstance(value, str) or not value or len(value) > 128
            or value.endswith(".env") or normalize_token_profile(value) != value):
        raise ValueError("Invalid CRS profile reference")
    return value


def parse_subscriptions(text: str | None) -> dict[str, dict[str, Any]] | None:
    """Validate the complete registry before any credential or network operation.

    None means legacy mode. An explicit empty object means no subscriptions.
    """
    if text is None or (isinstance(text, str) and not text.strip()):
        return None
    try:
        raw = json.loads(text, object_pairs_hook=_unique)
        if not isinstance(raw, dict):
            raise ValueError
        result, identities = {}, set()
        for name, row in raw.items():
            _identifier(name)
            if (not isinstance(row, dict) or set(row) - {"crs_profile", "account_id", "enabled", "removed"}
                    or not {"crs_profile", "account_id"} <= row.keys()):
                raise ValueError
            profile, account = _profile(row["crs_profile"]), _identifier(row["account_id"])
            enabled, removed = row.get("enabled", True), row.get("removed", False)
            if type(enabled) is not bool or type(removed) is not bool or (removed and enabled):
                raise ValueError
            identity = (profile, account)
            if identity in identities:
                raise ValueError
            identities.add(identity)
            result[name] = {"crs_profile": profile, "account_id": account, "enabled": enabled}
            if removed:
                result[name]["removed"] = True
        return result
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid CRS subscription registry; verify labels, profiles, IDs and boolean flags") from None


def selected_profiles(settings: dict, explicit=None, fallback=()) -> list[str]:
    """Resolve tracking selection, never allowing an explicit disabled bypass."""
    registry = parse_subscriptions(settings.get("subscriptions"))
    if explicit is not None:
        names = (re.split(r"[\s,]+", explicit.strip()) if isinstance(explicit, str) else list(explicit))
        names = list(dict.fromkeys(name for name in names if name))
    elif registry is not None:
        names = [name for name, row in registry.items() if row["enabled"] and not row.get("removed")]
    else:
        names = list(dict.fromkeys(re.split(r"[\s,]+", str(settings.get("profiles") or "").strip())))
        names = [name for name in names if name] or list(fallback)
    if registry is not None and any(
        name not in registry or not registry[name]["enabled"] or registry[name].get("removed") for name in names
    ):
        raise ValueError("Requested account is not an enabled tracked subscription")
    return names


def _stored_settings(values):
    return {"subscriptions": values.get(SUBSCRIPTIONS), "profiles": values.get(LEGACY_PROFILES, ""),
            "crs_profile": values.get(LEGACY_CRS, ""), "crs_accounts": values.get(LEGACY_ACCOUNTS, "{}")}


def subscription_lock(home=None):
    """One configuration owner across all runtimes using this ChatArch home.

    Reuse the native nonblocking lock primitive in a distinct namespace: a
    collector may already hold its (possibly custom) publication lock.
    """
    from .refresh import _refresh_lock
    return _refresh_lock(get_paths(home).home_dir / "chatglance" / "subscription-settings")


def _registry(values):
    settings = _stored_settings(values)
    current = parse_subscriptions(settings["subscriptions"])
    if current is not None:
        return current
    names = selected_profiles(settings)
    if not names:
        return {}
    try:
        profile = _profile(settings["crs_profile"])
        accounts = json.loads(settings["crs_accounts"], object_pairs_hook=_unique)
        return parse_subscriptions(json.dumps({name: {
            "crs_profile": profile, "account_id": accounts[name], "enabled": True
        } for name in names}))
    except (KeyError, ValueError, TypeError):
        raise ValueError("Legacy accounts need complete explicit CRS mappings before subscription migration") from None


def _load(store, env_profile):
    return (store.load_profile(ChatGlanceConfig, env_profile) if env_profile is not None
            else store.load_active(ChatGlanceConfig))


def list_subscriptions(*, home=None, env_profile=None, include_removed=False) -> dict:
    """List safe tracking references from one profile, without credential reads."""
    values = _load(EnvStore(get_paths(home).envs_dir), env_profile)
    registry = _registry(values)
    rows = [{"name": name, **row} for name, row in registry.items()
            if include_removed or not row.get("removed")]
    return {"source": "registry" if parse_subscriptions(values.get(SUBSCRIPTIONS)) is not None else "legacy",
            "subscriptions": rows, "count": len(rows)}


def _plan(values, action, name, crs_profile, account_id, enabled):
    _identifier(name)
    if action not in {"add", "enable", "disable", "remove"}:
        raise ValueError("Unknown subscription operation")
    registry = _registry(values)
    updated = deepcopy(values)
    old = registry.get(name)
    if action == "add":
        row = {"crs_profile": _profile(crs_profile), "account_id": _identifier(account_id), "enabled": enabled}
        if type(enabled) is not bool:
            raise ValueError("Tracking enabled must be a boolean")
        if old and (old["crs_profile"], old["account_id"]) != (row["crs_profile"], row["account_id"]):
            raise ValueError("Subscription labels cannot be rebound; choose a fresh label")
        registry[name] = row
    else:
        if old is None or old.get("removed"):
            raise ValueError("Subscription is not tracked")
        registry[name] = {**old, "enabled": action == "enable"}
        if action == "remove":
            registry[name]["removed"] = True
    # Revalidate the entire proposed registry, including retained identity fences.
    registry = parse_subscriptions(json.dumps(registry))
    from .codex_resets import parse_policies
    parse_policies(values.get(POLICIES))
    policies = json.loads(values.get(POLICIES) or "{}", object_pairs_hook=_unique)
    if action == "add" and old is None and name in policies:
        raise ValueError("Label already owns historical policy; choose a fresh label")
    if action == "add" and name not in policies:
        policies[name] = {"enabled": False}
        updated[POLICIES] = json.dumps(policies, ensure_ascii=False, separators=(",", ":"))
    updated[SUBSCRIPTIONS] = json.dumps(registry, ensure_ascii=False, separators=(",", ":"))
    return updated, {"action": action, "name": name, "subscription": registry[name], "executed": False}


def change_subscription(action: str, name: str, *, crs_profile=None, account_id=None,
                        enabled=True, execute=False, home=None, env_profile=None) -> dict:
    """Plan or persist one tracking change; never issue/revoke/consume credentials."""
    if type(execute) is not bool:
        raise ValueError("execute must be a boolean")
    store = EnvStore(get_paths(home).envs_dir)
    values = _load(store, env_profile)
    updated, receipt = _plan(values, action, name, crs_profile, account_id, enabled)
    if not execute:
        return receipt
    if env_profile is None and any(key in os.environ for key in (
        SUBSCRIPTIONS, POLICIES, LEGACY_PROFILES, LEGACY_CRS, LEGACY_ACCOUNTS
    )):
        raise ValueError("Active collector environment overrides settings; select an explicit --env-profile")
    # Reload under the configuration owner, independently of runtime placement.
    with subscription_lock(home):
        values = _load(store, env_profile)
        updated, receipt = _plan(values, action, name, crs_profile, account_id, enabled)
        if env_profile is None:
            store.save_active(ChatGlanceConfig, updated)
        else:
            store.save_profile(ChatGlanceConfig, env_profile, updated)
        if _load(store, env_profile) != updated:
            raise ValueError("Subscription settings readback failed")
    return {**receipt, "executed": True}
