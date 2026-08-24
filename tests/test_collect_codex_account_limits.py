from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace


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


def test_public_reset_parser_handles_current_timeline_item_markup() -> None:
    module = load_collector_module()
    html = '''
    <section>
      <div class="relative flex" data-datetime="2026-08-13T00:00:00.000Z" data-kind="confirmed" data-source-url="https://x.com/thsottiaux/status/2087423996115681767" data-testid="reset-timeline-item">
        <span>Confirmed reset</span><h3>Old reset</h3><dl><dt>Scope:</dt><dd>Shared/global Codex usage quota</dd><dt>Source:</dt><dd>Tibo on X</dd></dl>
      </div>
      <div class="relative flex" data-datetime="2026-08-24T00:46:51.000Z" data-kind="confirmed" data-source-url="https://x.com/thsottiaux/status/2091400000000000000" data-testid="reset-timeline-item">
        <span>Confirmed reset</span><h3>Global Codex quota reset</h3><dl><dt>Scope:</dt><dd>Paid Codex users</dd><dt>Source:</dt><dd>Tibo on X</dd></dl>
      </div>
    </section>
    '''

    events = module.parse_public_reset_events(html)

    assert len(events) == 2
    assert events[0]["time_utc"] == "2026-08-24T00:46:51Z"
    assert events[0]["time_bjt"] == "2026-08-24 08:46:51 +0800"
    assert events[0]["scope"] == "Paid Codex users"
    assert events[0]["event_id"] == "2091400000000000000"


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


def test_collector_calls_chatcrs_python_api_without_shelling_to_cli() -> None:
    module = load_collector_module()
    calls = []

    fake_api = SimpleNamespace(
        inspect_usage=lambda **kwargs: calls.append(("usage", kwargs)) or {"ok": True, "status": 200, "token_service": "Codex", "rate_limits": {}},
        inspect_quota=lambda **kwargs: calls.append(("quota", kwargs))
        or {"ok": True, "status": 200, "token_service": "Codex", "rate_limits": {"primary_used_percent": 1.0}},
    )

    usage = module.call_chatcrs_api("usage", profile="allis", refresh=False, timeout=7, codex_direct=fake_api)
    quota = module.call_chatcrs_api("quota", profile="allis", refresh=True, timeout=9, codex_direct=fake_api)

    assert usage["ok"] is True
    assert quota["ok"] is True
    assert calls == [
        ("usage", {"profile": "allis", "refresh": False, "timeout": 7}),
        ("quota", {"profile": "allis", "refresh": True, "timeout": 9}),
    ]


def test_profile_payload_records_chatcrs_token_service(monkeypatch) -> None:
    module = load_collector_module()

    def fake_bundle(profile: str, refresh: bool, timeout: int):
        assert profile == "allis"
        assert refresh is False
        assert timeout == 7
        return (
            {"ok": True, "json": {"ok": True, "status": 200, "token_service": "Codex", "rate_limits": {}}},
            {
                "ok": True,
                "json": {
                    "ok": True,
                    "status": 200,
                    "token_service": "Codex",
                    "rate_limits": {"primary_used_percent": 1.0, "primary_reset_after_seconds": 60, "primary_window_minutes": 300},
                },
            },
        )

    monkeypatch.setattr(module, "request_bundle", fake_bundle)

    payload = module.profile_payload("allis", 7)

    assert payload["status"] == "ok"
    assert payload["token_service"] == "Codex"


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
