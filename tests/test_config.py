from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

from chatglance.config import ChatGlanceConfig


ROOT = Path(__file__).resolve().parents[1]


def test_chatglance_config_is_typed_and_marks_token_sensitive():
    fields = ChatGlanceConfig.get_fields()
    token = fields["CHATGLANCE_GITHUB_TOKEN"]

    assert ChatGlanceConfig.get_storage_name() == "ChatGlance"
    assert {"chatglance", "glance"}.issubset(set(ChatGlanceConfig._aliases))
    assert token.env_key == "CHATGLANCE_GITHUB_TOKEN"
    assert token.is_sensitive is True
    assert token.desc


def test_manifest_registers_current_chatarch_runtime():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "chatstyle>=0.2.0,<0.3.0" in manifest["project"]["dependencies"]
    assert "chatenv>=0.2.10,<0.3.0" in manifest["project"]["dependencies"]
    assert "ChatCRS>=0.3.0,<0.4.0" in manifest["project"]["dependencies"]
    assert manifest["project"]["entry-points"]["chatenv.configs"]["chatglance"] == "chatglance.config"
