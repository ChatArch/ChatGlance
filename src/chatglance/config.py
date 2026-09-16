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

    CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", default="{}",
        desc="Per-profile reset policy JSON: enabled, threshold_percent and min_remaining_seconds.",
    )
    CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL",
        desc="Optional HTTPS backend base for reset-credit queries and consumption only.",
    )
    CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE = EnvField(
        "CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE", default="false",
        desc="Explicitly enable real policy-driven consumption; false is monitor-only.",
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
    raw = resolve("CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE", "false")
    if isinstance(raw, bool):
        execute = raw
    elif isinstance(raw, str) and raw.lower() in ("1", "true", "yes", "on", "0", "false", "no", "off", ""):
        execute = raw.lower() in ("1", "true", "yes", "on")
    else:
        raise ValueError("CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE must be an explicit boolean")
    return {"profiles": resolve("CHATGLANCE_ACCOUNT_LIMITS_PROFILES", ""),
            "reset_policies": resolve("CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES", "{}"),
            "reset_base_url": resolve("CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL", "") or None,
            "execute_resets": execute}


__all__ = ["ChatGlanceConfig", "collection_settings"]
