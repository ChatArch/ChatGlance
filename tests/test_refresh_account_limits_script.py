from __future__ import annotations

from pathlib import Path


def test_refresh_account_limits_script_lives_in_chatglance_scripts_with_proxy_and_codex_flow() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "refresh-account-limits-page.sh"

    assert script.exists(), "ChatArch-owned refresh script should live in ChatGlance/scripts"
    text = script.read_text(encoding="utf-8")

    assert "CHATGLANCE_ACCOUNT_LIMITS_JSON" in text
    assert "CHATGLANCE_ACCOUNT_LIMITS_PAGE_YML" in text
    assert "CHATGLANCE_ACCOUNT_LIMITS_PROFILES" in text
    assert "CHATGLANCE_CHATCLASH_BIN" in text
    assert "proxy env --no-mask" in text
    assert "set +x" in text
    assert "eval" not in text
    assert "chatcrs" in text
    assert "codex" in text
    assert "usage" in text
    assert "quota" in text
    assert "account-limits render-page" in text
    assert "account-limits update-config" in text
    assert "config:validate" in text
    assert "service_action=external" in text


def test_refresh_account_limits_script_refuses_to_print_secret_values() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "refresh-account-limits-page.sh"

    assert script.exists()
    text = script.read_text(encoding="utf-8")

    forbidden_fragments = [
        "echo $PROXY_EXPORTS",
        "echo \"$PROXY_EXPORTS\"",
        "cat ~/.chatarch/envs/OpenAI",
        "cat ~/.chatarch/tokens/OpenAI",
        "OPENAI_API_KEY=",
        "OPENAI_REFRESH_TOKEN=",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in text


def test_collect_codex_account_limits_script_fetches_public_reset_tracker() -> None:
    collector = Path(__file__).resolve().parents[1] / "scripts" / "collect-codex-account-limits.py"

    assert collector.exists()
    text = collector.read_text(encoding="utf-8")

    assert "codexreset.org" in text
    assert "codex_reset" in text
    assert "source_url" in text
    assert "confirmed_reset_count" in text
    assert "urllib.request" in text
