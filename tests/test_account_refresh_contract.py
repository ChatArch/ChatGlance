"""Consumer contracts for ChatCRS 0.3.4; no real OAuth requests."""
import json

import pytest

from chatglance import codex_resets as m
from chatglance.account_limits import render_account_limits_html
from test_codex_resets import FakeClient, NOW


@pytest.mark.parametrize("base", [None, "https://relay.example/backend-api"])
def test_account_scan_requests_standard_refresh_and_inherits_backend(tmp_path, monkeypatch, base):
    calls = []
    def factory(profile, **kwargs):
        calls.append((profile, kwargs))
        return FakeClient()
    monkeypatch.setattr(m.CodexClient, "from_profile", factory)
    row = m.scan_profile("work", home=tmp_path, now=NOW, reset_base_url=base)
    assert row["status"] == "ok"
    assert calls == [("work", {"home": tmp_path, "reset_base_url": base, "timeout": 20, "refresh": True})]
    assert "chatgpt.com" not in json.dumps(calls, default=str)
    assert row["refresh_requested"] is True
    assert row["refresh_attempted"] is None  # requested != actually refreshed
    assert row["last_successful_at"] == row["observed_at"]
    assert row["credential_status"] == "valid"


@pytest.mark.parametrize("status, expected", [(401, "invalid_or_expired"), (403, "invalid_or_expired"), (None, "probe_failed")])
def test_provider_refresh_failure_is_truthful_safe_status(tmp_path, monkeypatch, status, expected):
    class ProviderError(RuntimeError):
        pass
    error = ProviderError("access_token=NEVER_RENDER refresh_token=NEVER_RENDER")
    error.status = status
    def factory(*a, **kw):
        raise error
    monkeypatch.setattr(m.CodexClient, "from_profile", factory)
    row = m.scan_profile("work", home=tmp_path, now=NOW)
    assert row["refresh_requested"] is True
    assert row["credential_status"] == expected
    assert row["status"] == "error"
    assert "last_successful_at" not in row
    assert "NEVER_RENDER" not in json.dumps(row) + render_account_limits_html({"codex": [row]})


def test_consumer_declares_refresh_capable_chatcrs_floor():
    from pathlib import Path
    from packaging.requirements import Requirement
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    deps = tomllib.loads((Path(__file__).parents[1]/"pyproject.toml").read_text())["project"]["dependencies"]
    spec = next(Requirement(dep).specifier for dep in deps if dep.lower().startswith("chatcrs"))
    assert "0.3.3" not in spec and "0.3.4" in spec and "0.4.0" not in spec
