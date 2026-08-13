from __future__ import annotations

import importlib.util
from pathlib import Path


def load_collector_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "collect-codex-account-limits.py"
    spec = importlib.util.spec_from_file_location("collect_codex_account_limits", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_safe_error_redacts_tokens_and_proxy_credentials_from_stderr() -> None:
    module = load_collector_module()

    message = (
        "failed with access_token=abc123secret refresh_token=r123secret "
        "Authorization: Bearer sk-testsecret123456 "
        "proxy http://user:pass@example.com:7890"
    )
    safe = module.safe_error({"stderr": message})

    assert "abc123secret" not in safe
    assert "r123secret" not in safe
    assert "sk-testsecret" not in safe
    assert "user:pass@" not in safe
    assert "[REDACTED]" in safe
