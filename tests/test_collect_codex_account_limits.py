from __future__ import annotations

import importlib.util
import re
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


def test_timestamp_helpers_emit_explicit_beijing_time() -> None:
    module = load_collector_module()

    now = module.iso_now()

    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$", now)
    assert "Z" not in now
    assert module.iso_from_epoch(0) == "1970-01-01T08:00:00+08:00"


def test_collector_marks_expired_oauth_without_exposing_token_values() -> None:
    module = load_collector_module()

    assert module.credential_status("Error: OpenAI OAuth refresh failed: status=401", ok=False) == "invalid_or_expired"
    assert module.credential_status("", ok=True) == "valid"
    summary = module.refresh_status([
        {"profile": "73-wzh", "status": "error"},
        {"profile": "allis", "status": "ok"},
    ])

    assert summary["status"] == "partial"
    assert summary["failed_profiles"] == ["73-wzh"]
    assert summary["ok_profiles"] == ["allis"]


def test_collector_keeps_last_known_values_for_failed_profile() -> None:
    module = load_collector_module()
    current = [
        {
            "profile": "73-wzh",
            "account_name": "73-wzh",
            "status": "error",
            "windows": [],
            "error": "Error: OpenAI OAuth refresh failed: status=401",
        }
    ]
    previous = {
        "73-wzh": {
            "profile": "73-wzh",
            "status": "ok",
            "account_name": "73-wzh",
            "plan": "Codex",
            "windows": [{"label": "Primary", "used_percent": 12.5, "reset_at": "2026-08-25T10:00:00+08:00"}],
            "_previous_generated_at": "2026-08-23T01:21:19+08:00",
        }
    }

    module.apply_last_known_values(current, previous)

    assert current[0]["status"] == "error"
    assert current[0]["using_last_known_values"] is True
    assert current[0]["last_successful_at"] == "2026-08-23T01:21:19+08:00"
    assert current[0]["windows"][0]["used_percent"] == 12.5
