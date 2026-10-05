"""Typed ChatEnv configuration for ChatGlance."""

import re
from urllib.parse import urlsplit

from chatenv import BaseEnvConfig, EnvField


class ChatGlanceConfig(BaseEnvConfig):
    """ChatGlance environment configuration."""

    _title = "ChatGlance Configuration"
    _aliases = ["chatglance", "glance"]
    _storage_dir = "ChatGlance"

    CHATGLANCE_LOGIN_SECRET = EnvField("CHATGLANCE_LOGIN_SECRET", desc="Go login session signing secret.", is_sensitive=True)
    CHATGLANCE_LOGIN_PASSWORD_HASH = EnvField("CHATGLANCE_LOGIN_PASSWORD_HASH", desc="Go login bcrypt password hash (never plaintext).", is_sensitive=True)
    CHATGLANCE_LOGIN_USER = EnvField("CHATGLANCE_LOGIN_USER", desc="Explicit Go login username.")
    CHATGLANCE_PUBLIC_ORIGIN = EnvField("CHATGLANCE_PUBLIC_ORIGIN", desc="Reviewed public origin for optional authenticated controls.")
    CHATGLANCE_WEB_PORT = EnvField("CHATGLANCE_WEB_PORT", default="8080", desc="Loopback Go web port.")
    CHATGLANCE_CONTROL_PORT = EnvField("CHATGLANCE_CONTROL_PORT", default="5679", desc="Optional loopback controls port.")
    CHATGLANCE_PROJECTS_OWNER = EnvField("CHATGLANCE_PROJECTS_OWNER", default="", desc="Optional project inventory owner.")
    CHATGLANCE_REFRESH_PAGES = EnvField("CHATGLANCE_REFRESH_PAGES", default="", desc="Explicit non-consuming scheduled page names.")
    CHATGLANCE_REFRESH_INTERVAL = EnvField("CHATGLANCE_REFRESH_INTERVAL", default="30min", desc="Scheduled refresh interval.")

    CHATGLANCE_GITHUB_TOKEN = EnvField(
        "CHATGLANCE_GITHUB_TOKEN",
        desc="GitHub token used for private repository metadata reads.",
        is_sensitive=True,
    )

    CHATGLANCE_SITES_PUBLIC_DOMAIN = EnvField(
        "CHATGLANCE_SITES_PUBLIC_DOMAIN",
        desc="Public DNS suffix for website services; required unless public_url is explicit.",
    )
    CHATGLANCE_SITES_LOCAL_DOMAIN = EnvField(
        "CHATGLANCE_SITES_LOCAL_DOMAIN",
        desc="Optional internal DNS suffix for website-service probes, never shown on cards.",
    )
    CHATGLANCE_SITES_UPTIME_BASE_URL = EnvField(
        "CHATGLANCE_SITES_UPTIME_BASE_URL",
        desc="Optional HTTP(S) base URL of the website-services Uptime dashboard.",
    )
    CHATGLANCE_ACCOUNT_LIMITS_PROFILES = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_PROFILES", default="",
        desc="Space- or comma-separated Codex profiles for manual refresh; empty uses the current snapshot.",
    )

    CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE", default="",
        desc="Named CRS profile with a dedicated management Key; empty keeps local Codex mode.",
    )
    CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS", default="{}",
        desc="JSON mapping selected display/policy labels to exact CRS account IDs; no OAuth values.",
    )

    CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", default="{}",
        desc="Per-profile reset policy JSON: enabled, threshold_percent, min_remaining_seconds, optional target_window_seconds and skip_if_forecast_24h_above.",
    )
    CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL",
        desc="Optional HTTPS backend base for reset-credit queries and consumption only.",
    )

    CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH", default="",
        desc="Same-origin trailing-slash path of authenticated reset controls; empty hides the entry.",
    )

    @classmethod
    def test(cls) -> None:
        """Validate configured site defaults without making a network request."""

        print(f"Testing {cls._title}...")
        validate_site_settings(site_settings())
        print("Site defaults validated; no network test is required.")


def collection_settings(*, home=None) -> dict:
    """Resolve only non-secret collector settings: process env then ChatEnv."""
    import os
    from chatenv import EnvStore, get_paths
    try:
        values = EnvStore(get_paths(home).envs_dir).load_active(ChatGlanceConfig)
    except (ValueError, OSError):
        values = {}
    def resolve(key, default):
        return os.environ[key] if key in os.environ else values.get(key, default)
    legacy = "CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE"
    if legacy in values or legacy in os.environ:
        raise ValueError("Legacy global execution setting requires per-account migration before scanning")
    return {"profiles": resolve("CHATGLANCE_ACCOUNT_LIMITS_PROFILES", ""),
            "crs_profile": resolve("CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE", ""),
            "crs_accounts": resolve("CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS", "{}"),
            "reset_policies": resolve("CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", "{}"),
            "reset_base_url": resolve("CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL", "") or None,

            "control_path": resolve("CHATGLANCE_ACCOUNT_LIMITS_CONTROL_PATH", "") or ""}


def site_settings(*, home=None) -> dict[str, str]:
    """Resolve site defaults from process env, then the active ChatEnv profile."""
    import os
    from chatenv import EnvStore, get_paths

    values = EnvStore(get_paths(home).envs_dir).load_active(ChatGlanceConfig)
    result = {}
    for field in ("public_domain", "local_domain", "uptime_base_url"):
        key = "CHATGLANCE_SITES_" + field.upper()
        value = os.environ[key] if key in os.environ else values.get(key, "")
        result[field] = str(value or "").strip()
    return result


def validate_site_settings(settings: dict[str, str]) -> None:
    """Reject malformed domain suffixes and unsafe Uptime base URLs."""
    label = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    for key in ("public_domain", "local_domain"):
        domain = settings.get(key, "")
        if domain and (len(domain) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", domain)):
            raise ValueError(f"{key} must be a DNS domain suffix without scheme, port or path")
    url = settings.get("uptime_base_url", "")
    if url:
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                     and parsed.username is None and parsed.password is None
                     and "?" not in url and "#" not in url
                     and not any(char.isspace() for char in url))
            parsed.port  # Validate port syntax/range as well as hostname parsing.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("CHATGLANCE_SITES_UPTIME_BASE_URL must be an HTTP(S) base URL without credentials, query or fragment")


__all__ = ["ChatGlanceConfig", "collection_settings", "site_settings", "validate_site_settings"]
