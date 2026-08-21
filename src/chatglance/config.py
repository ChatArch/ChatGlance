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

    @classmethod
    def test(cls) -> None:
        """Validate schema registration without making a network request."""

        print(f"Testing {cls._title}...")
        print("Schema loaded; no network test is required.")


__all__ = ["ChatGlanceConfig"]
