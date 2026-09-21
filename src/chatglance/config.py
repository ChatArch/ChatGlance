"""Typed ChatEnv configuration for ChatGlance."""

from chatenv import BaseEnvConfig, EnvField


class ChatGlanceConfig(BaseEnvConfig):
    """ChatGlance environment configuration."""

    _title = "ChatGlance Configuration"
    _aliases = ["chatglance", "glance"]
    _storage_dir = "ChatGlance"

    CHATGLANCE_GITHUB_TOKEN = EnvField(
        "CHATGLANCE_GITHUB_TOKEN",
        desc="GitHub token used for private repository metadata reads.",
        is_sensitive=True,
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
        """Validate schema registration without making a network request."""

        print(f"Testing {cls._title}...")
        print("Schema loaded; no network test is required.")


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


__all__ = ["ChatGlanceConfig", "collection_settings"]
